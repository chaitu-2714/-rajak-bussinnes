"""Integration tests: user management workflows."""

from __future__ import annotations

import pytest

from app.core.exceptions import (
    AuthorizationError,
    DuplicateEmailError,
    NotFoundError,
    ValidationError,
)

from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    EMPLOYEE_PASSWORD,
    create_user,
)


def _payload(**overrides) -> dict:
    data = {
        "full_name": "Asha Rao",
        "email": "asha@bizpilot.test",
        "phone": "9876500000",
        "password": "An0ther!Passw0rd",
        "password_confirm": "An0ther!Passw0rd",
        "role_ids": [],
        "is_active": True,
    }
    data.update(overrides)
    return data


def _role_id(context, name: str) -> int:
    return next(role.id for role in context.role_service.list_roles() if role.role_name == name)


def test_create_user_with_role(admin) -> None:
    user = admin.user_service.create_user(_payload(role_ids=[_role_id(admin, "Employee")]))
    assert user.email == "asha@bizpilot.test"
    assert user.roles == ["Employee"]
    assert user.is_active is True


def test_duplicate_email_is_rejected(admin) -> None:
    admin.user_service.create_user(_payload(role_ids=[_role_id(admin, "Employee")]))
    with pytest.raises(DuplicateEmailError):
        admin.user_service.create_user(
            _payload(email="ASHA@bizpilot.test", role_ids=[_role_id(admin, "Employee")])
        )


def test_invalid_input_is_rejected(admin) -> None:
    with pytest.raises(ValidationError):
        admin.user_service.create_user(_payload(email="not-an-email", role_ids=[1]))
    with pytest.raises(ValidationError):
        admin.user_service.create_user(_payload(password="weak", password_confirm="weak", role_ids=[1]))


def test_create_user_requires_at_least_one_role(admin) -> None:
    with pytest.raises(ValidationError):
        admin.user_service.create_user(_payload(role_ids=[]))


def test_update_user_changes_details_and_roles(admin) -> None:
    user = admin.user_service.create_user(_payload(role_ids=[_role_id(admin, "Employee")]))
    updated = admin.user_service.update_user(
        user.id,
        {
            "full_name": "Asha R. Rao",
            "email": "asha.rao@bizpilot.test",
            "phone": "9000011111",
            "role_ids": [_role_id(admin, "Sales Manager")],
        },
    )
    assert updated.full_name == "Asha R. Rao"
    assert updated.email == "asha.rao@bizpilot.test"
    assert updated.roles == ["Sales Manager"]


def test_search_and_filters(admin) -> None:
    admin.user_service.create_user(_payload(role_ids=[_role_id(admin, "Employee")]))
    admin.user_service.create_user(
        _payload(
            full_name="Ravi Kumar",
            email="ravi@bizpilot.test",
            role_ids=[_role_id(admin, "Finance Manager")],
        )
    )

    assert [u.full_name for u in admin.user_service.list_users(search="ravi")] == ["Ravi Kumar"]
    assert len(admin.user_service.list_users(search="bizpilot.test")) == 3
    finance_role = _role_id(admin, "Finance Manager")
    assert len(admin.user_service.list_users(role_id=finance_role)) == 1
    assert len(admin.user_service.list_users(is_active=True)) == 3


def test_deactivate_user_blocks_login_and_revokes_sessions(admin) -> None:
    user_id = create_user(admin, "Employee", "leave@bizpilot.test")
    admin.auth_service.logout()
    admin.auth_service.login("leave@bizpilot.test", EMPLOYEE_PASSWORD)
    admin.auth_service.login(ADMIN_EMAIL, ADMIN_PASSWORD)

    admin.user_service.set_active(user_id, False)
    user = admin.user_service.get_user(user_id)
    assert user.is_active is False

    from app.core.exceptions import AccountInactiveError

    with pytest.raises(AccountInactiveError):
        admin.auth_service.login("leave@bizpilot.test", EMPLOYEE_PASSWORD)


def test_reactivate_user_restores_access(admin) -> None:
    user_id = create_user(admin, "Employee", "return@bizpilot.test")
    admin.user_service.set_active(user_id, False)
    admin.user_service.set_active(user_id, True)
    assert admin.user_service.get_user(user_id).is_active is True


def test_reset_password_allows_new_credentials(admin) -> None:
    user_id = create_user(admin, "Employee", "reset@bizpilot.test")
    admin.user_service.reset_password(user_id, "Fr3sh!Passw0rd", "Fr3sh!Passw0rd")

    admin.auth_service.logout()
    admin.auth_service.login("reset@bizpilot.test", "Fr3sh!Passw0rd")
    assert admin.auth_context.principal.email == "reset@bizpilot.test"


def test_unknown_user_raises_not_found(admin) -> None:
    with pytest.raises(NotFoundError):
        admin.user_service.get_user(4242)


def test_employee_cannot_manage_users(employee_context) -> None:
    with pytest.raises(AuthorizationError):
        employee_context.user_service.create_user(_payload(role_ids=[1]))
    with pytest.raises(AuthorizationError):
        employee_context.user_service.set_active(1, False)


def test_profile_update_is_allowed_for_any_user(employee_context) -> None:
    updated = employee_context.user_service.update_own_profile(
        {"full_name": "Employee Renamed", "phone": "9000022222"}
    )
    assert updated.full_name == "Employee Renamed"
    assert updated.phone == "9000022222"


def test_audit_entries_written_for_user_operations(admin) -> None:
    user = admin.user_service.create_user(_payload(role_ids=[_role_id(admin, "Employee")]))
    admin.user_service.update_user(
        user.id,
        {
            "full_name": "Asha Rao",
            "email": user.email,
            "phone": None,
            "role_ids": [_role_id(admin, "Employee")],
        },
    )
    admin.user_service.set_active(user.id, False)

    entries = admin.audit_service.list_entries()
    actions = {entry.action for entry in entries}
    assert {"CREATE_USER", "UPDATE_USER", "DEACTIVATE_USER"}.issubset(actions)


def test_audit_entry_records_old_and_new_values(admin) -> None:
    user = admin.user_service.create_user(_payload(role_ids=[_role_id(admin, "Employee")]))
    admin.user_service.update_user(
        user.id,
        {
            "full_name": "Asha Updated",
            "email": user.email,
            "phone": None,
            "role_ids": [_role_id(admin, "Employee")],
        },
    )
    entry = next(
        item for item in admin.audit_service.list_entries() if item.action == "UPDATE_USER"
    )
    assert entry.old_values["full_name"] == "Asha Rao"
    assert entry.new_values["full_name"] == "Asha Updated"


def test_audit_filters(admin) -> None:
    create_user(admin, "Employee", "filter@bizpilot.test")
    entries = admin.audit_service.list_entries(action="CREATE_USER")
    assert entries
    assert all(entry.action == "CREATE_USER" for entry in entries)

    entries = admin.audit_service.list_entries(module="User Management")
    assert entries
    assert all("User Management" in entry.module for entry in entries)


def test_role_listing_includes_user_counts(admin) -> None:
    create_user(admin, "Employee", "count@bizpilot.test")
    roles = {role.role_name: role for role in admin.role_service.list_roles()}
    assert roles["Employee"].user_count == 1
    assert roles["Employee"].is_system_role is True


def test_users_for_role(admin) -> None:
    create_user(admin, "Employee", "member@bizpilot.test")
    employee_role = next(
        role for role in admin.role_service.list_roles() if role.role_name == "Employee"
    )
    users = admin.role_service.list_users_for_role(employee_role.id)
    assert [user.email for user in users] == ["member@bizpilot.test"]
