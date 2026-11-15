"""Audit logging service.

Application logs (files) and business audit records (SQLite) stay separate.
Audit rows are append-only: there is no update or delete path in this service.
"""

from __future__ import annotations

import platform
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import STATUS_SUCCESS
from app.database.models.audit_log import AuditLog
from app.database.repositories.audit_repository import AuditRepository
from app.core.logging_config import get_logger
from app.database.repositories.user_repository import UserRepository
from app.services.base_service import AuthContext, BaseService
from app.utils.date_utils import utcnow

logger = get_logger("services.audit")

_SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "password_confirm",
    "new_password",
    "confirm_password",
    "current_password",
    "token",
    "session_token",
    "session_token_hash",
}


def _sanitise(values: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove secrets before an audit row is written."""
    if not values:
        return None
    cleaned: dict[str, Any] = {}
    for key, value in values.items():
        if key.lower() in _SENSITIVE_KEYS:
            cleaned[key] = "***redacted***"
        elif isinstance(value, datetime):
            cleaned[key] = value.isoformat()
        elif isinstance(value, dict):
            cleaned[key] = _sanitise(value)
        elif isinstance(value, (list, tuple, set)):
            cleaned[key] = list(value)
        else:
            cleaned[key] = value
    return cleaned


def device_info() -> str:
    """Local device description stored with each audit entry."""
    return f"{platform.system()} {platform.release()} ({platform.node() or 'local'})"


@dataclass(frozen=True)
class AuditEntryView:
    """UI-facing audit row."""

    id: int
    user_id: int | None
    user_name: str
    action: str
    module: str
    entity_type: str | None
    entity_id: str | None
    status: str
    created_at: datetime
    old_values: dict[str, Any] | None
    new_values: dict[str, Any] | None
    device: str | None

    @classmethod
    def from_row(cls, row: AuditLog) -> "AuditEntryView":
        return cls(
            id=row.id,
            user_id=row.user_id,
            user_name=row.user.full_name if row.user else "System",
            action=row.action,
            module=row.module,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            status=row.status,
            created_at=row.created_at,
            old_values=row.old_values,
            new_values=row.new_values,
            device=row.ip_or_device_info,
        )


class AuditService(BaseService):
    """Writes and reads the audit trail."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        audit_repository: AuditRepository,
        user_repository: UserRepository,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._audit = audit_repository
        self._users = user_repository

    # -- internal write path (no permission check) -------------------------
    def record(
        self,
        db: Session,
        *,
        actor_id: int | None,
        action: str,
        module: str,
        entity_type: str | None = None,
        entity_id: str | int | None = None,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
        status: str = STATUS_SUCCESS,
        info: str | None = None,
    ) -> AuditLog:
        """Append one audit entry inside the caller's transaction."""
        entry = AuditLog(
            user_id=actor_id,
            action=action,
            module=module,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            old_values=_sanitise(old_values),
            new_values=_sanitise(new_values),
            ip_or_device_info=info or device_info(),
            status=status,
            created_at=utcnow(),
        )
        written = self._audit.add(db, entry)
        self._chain(db, written)
        return written

    def attach_integrity(self, integrity: Any) -> None:
        """Enable the Phase 9 hash chain for every audit record."""
        self._integrity = integrity

    def _chain(self, db: Session, entry: AuditLog) -> None:
        integrity = getattr(self, "_integrity", None)
        if integrity is None:
            return
        try:
            integrity.append(db, entry)
        except Exception:  # noqa: BLE001 - auditing must never break the operation
            logger.exception("Could not chain an audit record")

    # -- read paths --------------------------------------------------------
    def record_event(
        self,
        *,
        actor_id: int | None,
        action: str,
        module: str,
        entity_type: str | None = None,
        entity_id: str | None = None,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
        status: str = STATUS_SUCCESS,
    ) -> None:
        """Record an audit entry in its own transaction.

        Used by components (such as the collaboration manager) that do not hold
        a database session of their own.
        """
        with self.unit_of_work() as db:
            self.record(
                db,
                actor_id=actor_id,
                action=action,
                module=module,
                entity_type=entity_type,
                entity_id=entity_id,
                old_values=old_values,
                new_values=new_values,
                status=status,
            )

    def recent_activity(self, limit: int = 8) -> list[AuditEntryView]:
        """Small recent-activity feed for the dashboard (any signed-in user)."""
        with self.unit_of_work(write=False) as db:
            self._current_user(db)
            rows = self._audit.recent(db, limit=limit)
            return [AuditEntryView.from_row(row) for row in rows]

    def list_entries(
        self,
        *,
        user_id: int | None = None,
        action: str | None = None,
        module: str | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AuditEntryView]:
        """Filtered audit history; requires ``audit.view``."""
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "audit.view")
            rows = self._audit.list_entries(
                db,
                user_id=user_id,
                action=action,
                module=module,
                search=search,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
                offset=offset,
            )
            return [AuditEntryView.from_row(row) for row in rows]

    def available_actions(self) -> list[str]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "audit.view")
            return self._audit.distinct_actions(db)

    def total_entries(self) -> int:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "audit.view")
            return self._audit.count(db)

    def filter_users(self) -> list[tuple[int, str]]:
        """(id, name) pairs for the audit filter combo."""
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "audit.view")
            return [(user.id, user.full_name) for user in self._users.list(db)]
