"""Data access for the business profile."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database.models.business import Business


class BusinessRepository:
    """The workspace holds exactly one business profile in Phase 1."""

    def get_primary(self, db: Session) -> Business | None:
        return db.scalars(select(Business).order_by(Business.id.asc())).first()

    def count(self, db: Session) -> int:
        return len(list(db.scalars(select(Business.id)).all()))

    def add(self, db: Session, business: Business) -> Business:
        db.add(business)
        db.flush()
        return business
