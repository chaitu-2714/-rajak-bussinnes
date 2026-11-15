"""CRM models: customers and follow-up reminders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import CustomerType, FollowUpStatus
from app.database.base import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.database.models.user import User
from app.utils.date_utils import utcnow


class Customer(Base):
    """A buying customer."""

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(32), index=True)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(80), index=True)
    customer_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CustomerType.INDIVIDUAL
    )
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    sales_orders: Mapped[list["SalesOrder"]] = relationship(  # noqa: F821
        back_populates="customer"
    )
    follow_ups: Mapped[list["CustomerFollowUp"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Customer id={self.id} code={self.customer_code!r}>"


class CustomerFollowUp(Base):
    """Local reminder to follow up with a customer (no email in Phase 2)."""

    __tablename__ = "customer_follow_ups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=FollowUpStatus.PENDING, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    customer: Mapped["Customer"] = relationship(back_populates="follow_ups")
    assignee: Mapped["User | None"] = relationship(  # noqa: F821
        foreign_keys=[assigned_to]
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CustomerFollowUp id={self.id} status={self.status}>"
