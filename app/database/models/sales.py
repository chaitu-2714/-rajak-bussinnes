"""Sales models: orders, order lines, invoices and payments."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import InvoiceStatus, OrderStatus, PaymentStatus
from app.database.base import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.database.models.user import User
from app.database.types import Money, ZERO
from app.utils.date_utils import utcnow


class SalesOrder(Base):
    """A customer order and its lifecycle."""

    __tablename__ = "sales_orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="total_amount_non_negative"),
        CheckConstraint("paid_amount >= 0", name="paid_amount_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subtotal: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    discount_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    tax_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    total_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    paid_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=PaymentStatus.UNPAID, index=True
    )
    order_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=OrderStatus.DRAFT, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    customer: Mapped["Customer"] = relationship(back_populates="sales_orders")  # noqa: F821
    items: Mapped[list["SalesOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    invoice: Mapped["Invoice | None"] = relationship(
        back_populates="order", uselist=False
    )
    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])  # noqa: F821

    @property
    def outstanding_amount(self):
        from app.database.types import to_money

        return to_money(self.total_amount) - to_money(self.paid_amount)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SalesOrder {self.order_number} {self.order_status} total={self.total_amount}>"


class SalesOrderItem(Base):
    """One product line on an order, with historical price snapshots."""

    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("line_total >= 0", name="line_total_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[object] = mapped_column(Money, nullable=False)
    cost_price_snapshot: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    discount_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    tax_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    line_total: Mapped[object] = mapped_column(Money, nullable=False)

    order: Mapped["SalesOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<SalesOrderItem product={self.product_id} qty={self.quantity}>"


class Invoice(Base):
    """Invoice generated from a completed sales order."""

    __tablename__ = "invoices"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="invoice_total_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    invoice_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    due_date: Mapped[datetime | None] = mapped_column(DateTime)
    subtotal: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    discount_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    tax_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    total_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=InvoiceStatus.UNPAID, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    order: Mapped["SalesOrder"] = relationship(back_populates="invoice")
    customer: Mapped["Customer"] = relationship()  # noqa: F821
    payments: Mapped[list["Payment"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )

    @property
    def paid_amount(self):
        from app.database.types import money_sum

        return money_sum(payment.amount for payment in self.payments if payment.payment_status == "COMPLETED")

    @property
    def outstanding_amount(self):
        from app.database.types import to_money

        return to_money(self.total_amount) - self.paid_amount

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Invoice {self.invoice_number} {self.status}>"


class Payment(Base):
    """A payment received against an invoice (partial payments supported)."""

    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount > 0", name="payment_amount_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount: Mapped[object] = mapped_column(Money, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(20), nullable=False, default="CASH")
    payment_reference: Mapped[str | None] = mapped_column(String(80))
    payment_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    payment_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="COMPLETED", index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    invoice: Mapped["Invoice"] = relationship(back_populates="payments")
    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment id={self.id} amount={self.amount} status={self.payment_status}>"
