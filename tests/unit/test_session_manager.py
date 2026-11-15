"""Unit tests: session token handling."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.core.exceptions import SessionExpiredError
from app.database.models.user import User
from app.security.session_manager import SessionManager, hash_token
from app.utils.date_utils import utcnow


def _create_user(context, email: str = "session@bizpilot.test") -> int:
    roles = {role.role_name: role for role in context.role_service.list_roles()}
    user = context.user_service.create_user(
        {
            "full_name": "Session User",
            "email": email,
            "password": "Sess1on!Passw0rd",
            "password_confirm": "Sess1on!Passw0rd",
            "role_ids": [roles["Employee"].id],
        }
    )
    return user.id


def test_raw_token_is_never_stored(admin) -> None:
    manager: SessionManager = admin.session_manager
    with admin.database.session_factory() as db:
        user = db.get(User, _create_user(admin))
        token, session = manager.create_session(db, user)
        db.commit()
        stored_hash = session.session_token_hash

    assert token != stored_hash
    assert stored_hash == hash_token(token)
    assert len(stored_hash) == 64


def test_resolve_session_accepts_live_token(admin) -> None:
    manager: SessionManager = admin.session_manager
    with admin.database.session_factory() as db:
        user = db.get(User, _create_user(admin, "live@bizpilot.test"))
        token, session = manager.create_session(db, user)
        db.commit()
        resolved = manager.resolve_session(db, token)
        assert resolved.id == session.id


def test_revoked_session_is_rejected(admin) -> None:
    manager: SessionManager = admin.session_manager
    with admin.database.session_factory() as db:
        user = db.get(User, _create_user(admin, "revoked@bizpilot.test"))
        token, session = manager.create_session(db, user)
        manager.revoke(db, session)
        db.commit()
        with pytest.raises(SessionExpiredError):
            manager.resolve_session(db, token)


def test_expired_session_is_rejected(admin) -> None:
    manager: SessionManager = admin.session_manager
    with admin.database.session_factory() as db:
        user = db.get(User, _create_user(admin, "expired@bizpilot.test"))
        token, session = manager.create_session(db, user)
        session.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
        with pytest.raises(SessionExpiredError):
            manager.resolve_session(db, token)


def test_unknown_token_is_rejected(admin) -> None:
    manager: SessionManager = admin.session_manager
    with admin.database.session_factory() as db:
        with pytest.raises(SessionExpiredError):
            manager.resolve_session(db, "not-a-real-token")


def test_hash_token_is_deterministic() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert hash_token("abc") != hash_token("abd")
