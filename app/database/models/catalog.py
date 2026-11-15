"""Catalogue models: product categories and products."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.types import Money, ZERO
from app.utils.date_utils import utcnow


class Category(Base):
    """Product category (e.g. Beverages, Stationery)."""

    __tablename__ = "categories"
    __table_args__ = (CheckConstraint("length(trim(category_name)) > 0", name="category_name_not_blank"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category_name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    products: Mapped[list["Product"]] = relationship(back_populates="category")

    @property
    def product_count(self) -> int:
        return len(self.products)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Category id={self.id} name={self.category_name!r}>"


class Product(Base):
    """A sellable / stockable item."""

    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("cost_price >= 0", name="cost_price_non_negative"),
        CheckConstraint("selling_price >= 0", name="selling_price_non_negative"),
        CheckConstraint("minimum_stock >= 0", name="minimum_stock_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    product_name: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="pcs")
    cost_price: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    selling_price: Mapped[object] = mapped_column(Money, nullable=False, default=ZERO)
    minimum_stock: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    barcode: Mapped[str | None] = mapped_column(String(64), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    category: Mapped["Category | None"] = relationship(back_populates="products")
    inventory_records: Mapped[list["Inventory"]] = relationship(  # noqa: F821
        back_populates="product", cascade="all, delete-orphan"
    )
    stock_movements: Mapped[list["StockMovement"]] = relationship(  # noqa: F821
        back_populates="product"
    )

    @property
    def category_name(self) -> str:
        return self.category.category_name if self.category else "Uncategorised"

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Product id={self.id} sku={self.sku!r}>"
