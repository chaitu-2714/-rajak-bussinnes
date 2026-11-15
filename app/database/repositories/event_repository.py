"""Data access for the business event outbox."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.constants import EventStatus
from app.database.models.events import BusinessEvent


class EventRepository:
    """Append and read outbox rows."""

    def add(self, db: Session, event: BusinessEvent) -> BusinessEvent:
        db.add(event)
        db.flush()
        return event

    def list_pending(self, db: Session, limit: int = 100) -> list[BusinessEvent]:
        return list(
            db.scalars(
                select(BusinessEvent)
                .where(BusinessEvent.status.in_((EventStatus.PENDING, EventStatus.FAILED)))
                .where(BusinessEvent.attempts < 5)
                .order_by(BusinessEvent.id)
                .limit(limit)
            ).all()
        )

    def list_events(
        self, db: Session, *, status: str | None = None, limit: int = 200
    ) -> list[BusinessEvent]:
        stmt = select(BusinessEvent)
        if status:
            stmt = stmt.where(BusinessEvent.status == status)
        stmt = stmt.order_by(BusinessEvent.id.desc()).limit(limit)
        return list(db.scalars(stmt).all())

    def count(self, db: Session, *, status: str | None = None) -> int:
        stmt = select(func.count(BusinessEvent.id))
        if status:
            stmt = stmt.where(BusinessEvent.status == status)
        return int(db.scalar(stmt) or 0)
