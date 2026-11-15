"""Finance models: expenses and the financial transaction ledger."""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import ExpenseStatus
from app.database.base import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.database.models.user import User
from app.database.types import Money, ZERO
from app.utils.date_utils import utcnow


class Expense(Base):
    """An operating expense."""

    __tablename__ = "expenses"
    __table_args__ = (CheckConstraint("amount > 0", name="expense_amount_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    expense_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    expense_category: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor_name: Mapped[str | None] = mapped_column(String(160))
    amount: Mapped[object] = mapped_column(Money, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False, default="CASH")
    expense_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ExpenseStatus.RECORDED, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Expense {self.expense_number} {self.amount} {self.status}>"


class FinancialTransaction(Base):
    """Double-entry-friendly ledger of money movements.

    ``amount`` is signed: income and refunds that reduce revenue are negative,
    expenses are positive. A uniqueness constraint on
    ``(reference_type, reference_id, category)`` prevents the same business
    event from being posted twice.
    """

    __tablename__ = "financial_transactions"
    __table_args__ = (
        UniqueConstraint(
            "reference_type",
            "reference_id",
            "category",
            name="uq_financial_transactions_reference_category",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transaction_number: Mapped[str] = mapped_column(
        String(30), nullable=False, unique=True, index=True
    )
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    reference_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    reference_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    transaction_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<FinancialTransaction {self.transaction_number} {self.transaction_type} {self.amount}>"
