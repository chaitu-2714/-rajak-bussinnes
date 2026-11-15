"""Supplier and purchasing models."""

from __future__ import annotations

from typing import TYPE_CHECKING

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import PurchaseOrderStatus
from app.database.base import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.database.models.user import User
from app.database.types import Money, ZERO
from app.utils.date_utils import utcnow


class Supplier(Base):
    """A supplier we buy stock from."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    contact_person: Mapped[str | None] = mapped_column(String(120))
    email: Mapped[str | None] = mapped_column(String(255), index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)
    tax_identifier: Mapped[str | None] = mapped_column(String(40))
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    purchase_orders: Mapped[list["PurchaseOrder"]] = relationship(back_populates="supplier")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Supplier id={self.id} code={self.supplier_code!r}>"


class PurchaseOrder(Base):
    """Purchase order raised against a supplier."""

    __tablename__ = "purchase_orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="po_total_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_order_number: Mapped[str] = mapped_column(
        String(30), nullable=False, unique=True, index=True
    )
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    subtotal: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    tax_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    total_amount: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PurchaseOrderStatus.DRAFT, index=True
    )
    expected_delivery_date: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    supplier: Mapped["Supplier"] = relationship(back_populates="purchase_orders")
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    receipts: Mapped[list["GoodsReceipt"]] = relationship(back_populates="order")
    creator: Mapped["User | None"] = relationship(foreign_keys=[created_by])  # noqa: F821

    @property
    def ordered_quantity(self) -> int:
        return sum(item.ordered_quantity for item in self.items)

    @property
    def received_quantity(self) -> int:
        return sum(item.received_quantity for item in self.items)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PurchaseOrder {self.purchase_order_number} {self.status}>"


class PurchaseOrderItem(Base):
    """A product line on a purchase order, with received quantity."""

    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("ordered_quantity > 0", name="po_item_quantity_positive"),
        CheckConstraint("received_quantity >= 0", name="po_item_received_non_negative"),
        CheckConstraint(
            "received_quantity <= ordered_quantity", name="po_item_received_within_ordered"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    ordered_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    received_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    unit_cost: Mapped[object] = mapped_column(Money, nullable=False)
    line_total: Mapped[object] = mapped_column(Money, nullable=False)

    order: Mapped["PurchaseOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship()  # noqa: F821

    @property
    def outstanding_quantity(self) -> int:
        return self.ordered_quantity - self.received_quantity

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PurchaseOrderItem product={self.product_id} qty={self.ordered_quantity}>"


class GoodsReceipt(Base):
    """A recorded delivery against a purchase order."""

    __tablename__ = "goods_receipts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    receipt_number: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    notes: Mapped[str | None] = mapped_column(Text)
    received_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    order: Mapped["PurchaseOrder"] = relationship(back_populates="receipts")
    items: Mapped[list["GoodsReceiptItem"]] = relationship(
        back_populates="receipt", cascade="all, delete-orphan"
    )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GoodsReceipt {self.receipt_number} qty={self.total_quantity}>"


class GoodsReceiptItem(Base):
    """Quantity received for one purchase order line."""

    __tablename__ = "goods_receipt_items"
    __table_args__ = (CheckConstraint("quantity > 0", name="receipt_quantity_positive"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goods_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("goods_receipts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    purchase_order_item_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_order_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    receipt: Mapped["GoodsReceipt"] = relationship(back_populates="items")
    purchase_order_item: Mapped["PurchaseOrderItem"] = relationship()
    product: Mapped["Product"] = relationship()  # noqa: F821

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GoodsReceiptItem product={self.product_id} qty={self.quantity}>"
