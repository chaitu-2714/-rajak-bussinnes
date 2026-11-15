"""Data access for authentication sessions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.database.models.session import UserSession
from app.utils.date_utils import utcnow


class SessionRepository:
    """Persist and query hashed session tokens."""

    def add(self, db: Session, session: UserSession) -> UserSession:
        db.add(session)
        db.flush()
        return session

    def get_by_token_hash(self, db: Session, token_hash: str) -> UserSession | None:
        return db.scalars(
            select(UserSession).where(UserSession.session_token_hash == token_hash)
        ).first()

    def get(self, db: Session, session_id: int) -> UserSession | None:
        return db.get(UserSession, session_id)

    def list_active_for_user(self, db: Session, user_id: int) -> list[UserSession]:
        return list(
            db.scalars(
                select(UserSession)
                .where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > utcnow(),
                )
                .order_by(UserSession.created_at.desc())
            ).all()
        )

    def revoke_all_for_user(self, db: Session, user_id: int, *, except_id: int | None = None) -> int:
        """Revoke every live session of a user; returns how many were revoked."""
        now = utcnow()
        sessions = list(
            db.scalars(
                select(UserSession).where(
                    UserSession.user_id == user_id,
                    UserSession.revoked_at.is_(None),
                    UserSession.expires_at > now,
                )
            ).all()
        )
        revoked = 0
        for session in sessions:
            if except_id is not None and session.id == except_id:
                continue
            session.revoked_at = now
            revoked += 1
        db.flush()
        return revoked

    def purge_expired(self, db: Session, *, older_than: datetime | None = None) -> int:
        """Delete sessions that expired before ``older_than`` (default: now)."""
        cutoff = older_than or utcnow()
        result = db.execute(
            delete(UserSession).where(UserSession.expires_at < cutoff)
        )
        db.flush()
        return int(result.rowcount or 0)
