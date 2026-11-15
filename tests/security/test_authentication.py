"""Security tests: local authentication, lockout, sessions, password change."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.exceptions import (
    AccountInactiveError,
    AccountLockedError,
    ConflictError,
    InvalidCredentialsError,
    SessionExpiredError,
    ValidationError,
)
from app.database.models.audit_log import AuditLog
from app.database.models.session import UserSession
from app.database.models.user import User
from app.utils.date_utils import utcnow

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, ADMIN_PAYLOAD, create_user


def test_initial_setup_creates_business_admin_and_session(context) -> None:
    assert context.auth_service.needs_initial_setup() is True
    result = context.auth_service.run_initial_setup(ADMIN_PAYLOAD)

    assert result.principal.email == ADMIN_EMAIL
    assert result.principal.is_superuser is True
    assert "Super Admin" in result.principal.roles
    assert result.principal.business_name == "Test Traders"
    assert context.auth_service.needs_initial_setup() is False

    business = context.business_service.get_business()
    assert business.business_name == "Test Traders"
    assert business.currency == "INR"


def test_setup_creates_six_roles_and_permission_catalogue(admin) -> None:
    roles = {role.role_name for role in admin.role_service.list_roles()}
    assert roles == {
        "Super Admin",
        "Business Admin",
        "Finance Manager",
        "Sales Manager",
        "Inventory Manager",
        "Employee",
    }
    permissions = admin.permission_service.list_all()
    assert len(permissions) >= 30
    assert "users.create" in {permission.key for permission in permissions}


def test_setup_cannot_run_twice(admin) -> None:
    with pytest.raises(ConflictError):
        admin.auth_service.run_initial_setup(ADMIN_PAYLOAD)


def test_setup_rejects_weak_password(context) -> None:
    payload = dict(ADMIN_PAYLOAD, password="weakpass", password_confirm="weakpass")
    with pytest.raises(ValidationError):
        context.auth_service.run_initial_setup(payload)
    assert context.auth_service.needs_initial_setup() is True


def test_password_is_hashed_with_argon2id(admin) -> None:
    with admin.database.session_factory() as db:
        user = db.scalars(select(User).where(User.email == ADMIN_EMAIL)).first()
        assert user is not None
        assert user.password_hash.startswith("$argon2id$")
        assert ADMIN_PASSWORD not in user.password_hash


def test_login_success_records_last_login_and_audit(admin) -> None:
    admin.auth_service.logout()
    result = admin.auth_service.login(ADMIN_EMAIL, ADMIN_PASSWORD)
    assert result.principal.email == ADMIN_EMAIL

    with admin.database.session_factory() as db:
        user = db.scalars(select(User).where(User.email == ADMIN_EMAIL)).first()
        assert user.last_login_at is not None
        actions = [row.action for row in db.scalars(select(AuditLog)).all()]
    assert "LOGIN_SUCCESS" in actions
    assert "LOGOUT" in actions


def test_login_with_wrong_password_is_generic(admin) -> None:
    with pytest.raises(InvalidCredentialsError) as excinfo:
        admin.auth_service.login(ADMIN_EMAIL, "Wrong!Passw0rd")
    assert excinfo.value.user_message == "Invalid email or password."


def test_login_with_unknown_email_is_generic(admin) -> None:
    with pytest.raises(InvalidCredentialsError) as excinfo:
        admin.auth_service.login("nobody@bizpilot.test", "Wrong!Passw0rd")
    assert excinfo.value.user_message == "Invalid email or password."


def test_account_locks_after_repeated_failures(admin) -> None:
    max_attempts = admin.config.security.max_failed_attempts
    for _ in range(max_attempts):
        with pytest.raises(InvalidCredentialsError):
            admin.auth_service.login(ADMIN_EMAIL, "Wrong!Passw0rd")

    with pytest.raises(AccountLockedError):
        admin.auth_service.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    with admin.database.session_factory() as db:
        user = db.scalars(select(User).where(User.email == ADMIN_EMAIL)).first()
        assert user.locked_until is not None
        assert user.locked_until > utcnow()


def test_inactive_account_cannot_sign_in(admin) -> None:
    user_id = create_user(admin, "Employee", "inactive@bizpilot.test")
    admin.user_service.set_active(user_id, False)
    with pytest.raises(AccountInactiveError):
        admin.auth_service.login("inactive@bizpilot.test", "Empl0yee!Passw0rd")


def test_logout_revokes_the_session(admin) -> None:
    token = admin.auth_context.token
    admin.auth_service.logout()
    assert admin.auth_context.principal is None

    with admin.database.session_factory() as db:
        from app.security.session_manager import hash_token

        session = db.scalars(
            select(UserSession).where(UserSession.session_token_hash == hash_token(token))
        ).first()
        assert session is not None
        assert session.revoked_at is not None


def test_expired_session_invalidates_context(admin) -> None:
    token = admin.auth_context.token
    with admin.database.session_factory() as db:
        from app.security.session_manager import hash_token

        session = db.scalars(
            select(UserSession).where(UserSession.session_token_hash == hash_token(token))
        ).first()
        session.expires_at = utcnow() - timedelta(minutes=5)
        db.commit()

    assert admin.auth_service.validate_active_session() is False
    assert admin.auth_context.principal is None


def test_change_password_invalidates_old_password(admin) -> None:
    admin.auth_service.change_password(ADMIN_PASSWORD, "N3w!Passw0rd99", "N3w!Passw0rd99")
    admin.auth_service.logout()

    with pytest.raises(InvalidCredentialsError):
        admin.auth_service.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    result = admin.auth_service.login(ADMIN_EMAIL, "N3w!Passw0rd99")
    assert result.principal.email == ADMIN_EMAIL


def test_change_password_requires_correct_current_password(admin) -> None:
    with pytest.raises(ValidationError):
        admin.auth_service.change_password("Wrong!Passw0rd", "N3w!Passw0rd99", "N3w!Passw0rd99")


def test_change_password_revokes_other_sessions(admin) -> None:
    # A second session for the same account (e.g. another window).
    first_token = admin.auth_context.token
    second = admin.auth_service.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    admin.auth_service.change_password(ADMIN_PASSWORD, "N3w!Passw0rd99", "N3w!Passw0rd99")

    with admin.database.session_factory() as db:
        from app.security.session_manager import hash_token

        first = db.scalars(
            select(UserSession).where(
                UserSession.session_token_hash == hash_token(first_token)
            )
        ).first()
        other = db.scalars(
            select(UserSession).where(
                UserSession.session_token_hash == hash_token(second.token)
            )
        ).first()
    assert first.revoked_at is not None  # the older session is revoked
    assert other.revoked_at is None  # the active session survives


def test_session_token_is_not_stored_in_plain_text(admin) -> None:
    token = admin.auth_context.token
    with admin.database.session_factory() as db:
        hashes = [row.session_token_hash for row in db.scalars(select(UserSession)).all()]
    assert token not in hashes


def test_login_failure_is_audited_without_secrets(admin) -> None:
    with pytest.raises(InvalidCredentialsError):
        admin.auth_service.login(ADMIN_EMAIL, "Wrong!Passw0rd")

    with admin.database.session_factory() as db:
        entry = db.scalars(
            select(AuditLog).where(AuditLog.action == "LOGIN_FAILURE")
        ).first()
        assert entry is not None
        assert entry.status == "FAILURE"
        assert "Wrong!Passw0rd" not in str(entry.new_values)


def test_audit_never_contains_password_material(admin) -> None:
    admin.auth_service.change_password(ADMIN_PASSWORD, "N3w!Passw0rd99", "N3w!Passw0rd99")
    with admin.database.session_factory() as db:
        rows = db.scalars(select(AuditLog)).all()
        for row in rows:
            payload = f"{row.old_values}{row.new_values}"
            assert "N3w!Passw0rd99" not in payload
            assert ADMIN_PASSWORD not in payload
            assert "$argon2id$" not in payload


def test_unauthenticated_service_call_is_rejected(admin) -> None:
    admin.auth_service.logout()
    with pytest.raises(Exception):
        admin.user_service.list_users()
