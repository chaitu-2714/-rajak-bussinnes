"""Inventory models: branches, stock levels and the movement ledger."""

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
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import MovementType
from app.database.base import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.database.models.user import User
from app.utils.date_utils import utcnow


class Branch(Base):
    """Business location. Phase 2 ships a single default branch."""

    __tablename__ = "branches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    branch_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    inventory_records: Mapped[list["Inventory"]] = relationship(back_populates="branch")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Branch id={self.id} name={self.branch_name!r}>"


class Inventory(Base):
    """Stock held for one product at one branch."""

    __tablename__ = "inventory"
    __table_args__ = (
        UniqueConstraint("product_id", "branch_id", name="uq_inventory_product_id_branch_id"),
        CheckConstraint("available_quantity >= 0", name="available_quantity_non_negative"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_quantity_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    available_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    reserved_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    product: Mapped["Product"] = relationship(back_populates="inventory_records")  # noqa: F821
    branch: Mapped["Branch"] = relationship(back_populates="inventory_records")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Inventory product={self.product_id} qty={self.available_quantity}>"


class StockMovement(Base):
    """Append-only ledger entry for every stock change."""

    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    branch_id: Mapped[int] = mapped_column(
        ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    new_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(40))
    reference_id: Mapped[str | None] = mapped_column(String(40))
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    product: Mapped["Product"] = relationship(back_populates="stock_movements")  # noqa: F821
    branch: Mapped["Branch"] = relationship()
    user: Mapped["User | None"] = relationship(foreign_keys=[created_by])  # noqa: F821

    @property
    def is_inbound(self) -> bool:
        return self.new_quantity >= self.previous_quantity

    @property
    def signed_quantity(self) -> int:
        return self.quantity if self.is_inbound else -self.quantity

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<StockMovement {self.movement_type} product={self.product_id} "
            f"{self.previous_quantity}->{self.new_quantity}>"
        )


INBOUND_MOVEMENTS = (MovementType.PURCHASE, MovementType.RETURN, MovementType.OPENING_STOCK)
