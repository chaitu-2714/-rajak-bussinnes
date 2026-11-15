"""Session token creation, validation and revocation.

Raw tokens are returned to the caller once (held in memory by the UI) and are
never persisted: only their SHA-256 digest is written to the database.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import SecuritySettings
from app.core.exceptions import SessionExpiredError
from app.database.models.session import UserSession
from app.database.models.user import User
from app.database.repositories.session_repository import SessionRepository
from app.utils.date_utils import utcnow

_TOKEN_BYTES = 48


def hash_token(token: str) -> str:
    """SHA-256 digest of a high-entropy token (not a password hash)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionManager:
    """Create and validate authenticated sessions."""

    def __init__(
        self, session_repository: SessionRepository, settings: SecuritySettings
    ) -> None:
        self._repository = session_repository
        self._settings = settings

    @property
    def lifetime(self) -> timedelta:
        return timedelta(hours=self._settings.session_hours)

    def create_session(self, db: Session, user: User) -> tuple[str, UserSession]:
        """Create a session and return ``(raw_token, session_row)``."""
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        now = utcnow()
        session = UserSession(
            user_id=user.id,
            session_token_hash=hash_token(token),
            created_at=now,
            expires_at=now + self.lifetime,
            last_activity_at=now,
        )
        self._repository.add(db, session)
        return token, session

    def resolve_session(self, db: Session, token: str) -> UserSession:
        """Return the session for ``token`` or raise :class:`SessionExpiredError`."""
        if not token:
            raise SessionExpiredError("No session token supplied")
        session = self._repository.get_by_token_hash(db, hash_token(token))
        if session is None:
            raise SessionExpiredError("Session not recognised")
        if session.revoked_at is not None:
            raise SessionExpiredError("Session was revoked")
        if session.expires_at <= utcnow():
            raise SessionExpiredError("Session expired")
        idle_limit = timedelta(minutes=self._settings.idle_timeout_minutes)
        if session.last_activity_at + idle_limit <= utcnow():
            session.revoked_at = utcnow()
            db.flush()
            raise SessionExpiredError("Session timed out after inactivity")
        return session

    def touch(self, db: Session, session: UserSession) -> None:
        """Record activity without extending the absolute expiry."""
        session.last_activity_at = utcnow()
        db.flush()

    def revoke(self, db: Session, session: UserSession) -> None:
        if session.revoked_at is None:
            session.revoked_at = utcnow()
            db.flush()

    def revoke_all_for_user(self, db: Session, user_id: int, *, except_id: int | None = None) -> int:
        return self._repository.revoke_all_for_user(db, user_id, except_id=except_id)

    def purge_expired(self, db: Session) -> int:
        return self._repository.purge_expired(db)
