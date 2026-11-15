"""Transactional outbox for business events."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.constants import EventStatus
from app.database.base import Base
from app.utils.date_utils import utcnow


class BusinessEvent(Base):
    """An event written in the same transaction as the business change.

    Rows are dispatched after the transaction commits, which makes delivery
    reliable and retryable — the foundation for Phase 3 automation.
    """

    __tablename__ = "business_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    aggregate_type: Mapped[str | None] = mapped_column(String(60))
    aggregate_id: Mapped[str | None] = mapped_column(String(60))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=EventStatus.PENDING, index=True,
        server_default=text("'PENDING'"),
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BusinessEvent {self.event_type} {self.status}>"
