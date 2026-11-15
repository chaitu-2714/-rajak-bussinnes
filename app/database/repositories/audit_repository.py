"""Data access for the audit trail.

There is deliberately no ``update`` or ``delete`` method: audit entries are
append-only.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.models.audit_log import AuditLog


class AuditRepository:
    """Append and query audit entries."""

    def add(self, db: Session, entry: AuditLog) -> AuditLog:
        db.add(entry)
        db.flush()
        return entry

    def list_entries(
        self,
        db: Session,
        *,
        user_id: int | None = None,
        action: str | None = None,
        module: str | None = None,
        search: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> list[AuditLog]:
        stmt = select(AuditLog).options(selectinload(AuditLog.user))
        if user_id is not None:
            stmt = stmt.where(AuditLog.user_id == user_id)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if module:
            pattern = f"%{module.strip().lower()}%"
            stmt = stmt.where(func.lower(AuditLog.module).like(pattern))
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(AuditLog.action).like(pattern),
                    func.lower(AuditLog.module).like(pattern),
                    func.lower(func.coalesce(AuditLog.entity_type, "")).like(pattern),
                    func.lower(func.coalesce(AuditLog.entity_id, "")).like(pattern),
                )
            )
        if date_from is not None:
            stmt = stmt.where(AuditLog.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(AuditLog.created_at <= date_to)
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        stmt = stmt.offset(offset).limit(limit)
        return list(db.scalars(stmt).unique().all())

    def recent(self, db: Session, limit: int = 8) -> list[AuditLog]:
        return self.list_entries(db, limit=limit)

    def count(self, db: Session) -> int:
        return int(db.scalar(select(func.count(AuditLog.id))) or 0)

    def distinct_actions(self, db: Session) -> list[str]:
        return sorted(
            {action for action in db.scalars(select(AuditLog.action)).all() if action}
        )
