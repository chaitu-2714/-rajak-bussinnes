"""Pydantic schemas for inventory operations."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import MovementType


class StockAdjustmentRequest(BaseModel):
    """Manual stock change (opening stock, addition, reduction, damage)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    product_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    movement_type: str = Field(default=MovementType.ADJUSTMENT)
    reason: str = Field(min_length=3, max_length=255)
    direction: int | None = Field(
        default=None, description="+1 adds stock, -1 removes stock; defaults by movement type"
    )

    @field_validator("movement_type")
    @classmethod
    def _valid_type(cls, value: str) -> str:
        allowed = {
            MovementType.OPENING_STOCK,
            MovementType.ADJUSTMENT,
            MovementType.DAMAGE,
            MovementType.RETURN,
            MovementType.PURCHASE,
        }
        if value not in allowed:
            raise ValueError(f"Movement type must be one of {', '.join(sorted(allowed))}.")
        return value


class StockRow(BaseModel):
    """One product's stock position."""

    product_id: int
    sku: str
    product_name: str
    category_name: str
    unit: str
    available_quantity: int
    reserved_quantity: int
    minimum_stock: int
    cost_price: Decimal
    selling_price: Decimal
    stock_value: Decimal
    is_active: bool
    is_low: bool
    is_out_of_stock: bool

    @classmethod
    def from_record(cls, record) -> "StockRow":
        from app.database.types import to_money

        product = record.product
        available = int(record.available_quantity or 0)
        return cls(
            product_id=product.id,
            sku=product.sku,
            product_name=product.product_name,
            category_name=product.category_name,
            unit=product.unit,
            available_quantity=available,
            reserved_quantity=int(record.reserved_quantity or 0),
            minimum_stock=int(product.minimum_stock or 0),
            cost_price=product.cost_price,
            selling_price=product.selling_price,
            stock_value=to_money(product.cost_price) * available,
            is_active=product.is_active,
            is_low=available <= int(product.minimum_stock or 0),
            is_out_of_stock=available == 0,
        )


class StockMovementView(BaseModel):
    id: int
    created_at: datetime
    product_id: int
    product_name: str
    sku: str
    movement_type: str
    quantity: int
    previous_quantity: int
    new_quantity: int
    reference_type: str | None = None
    reference_id: str | None = None
    notes: str | None = None
    user_name: str | None = None

    @classmethod
    def from_movement(cls, movement) -> "StockMovementView":
        return cls(
            id=movement.id,
            created_at=movement.created_at,
            product_id=movement.product_id,
            product_name=movement.product.product_name if movement.product else "—",
            sku=movement.product.sku if movement.product else "—",
            movement_type=movement.movement_type,
            quantity=movement.quantity,
            previous_quantity=movement.previous_quantity,
            new_quantity=movement.new_quantity,
            reference_type=movement.reference_type,
            reference_id=movement.reference_id,
            notes=movement.notes,
            user_name=getattr(movement.user, "full_name", None) if movement.user else None,
        )


class LowStockAlert(BaseModel):
    product_id: int
    product_name: str
    sku: str
    available_quantity: int
    minimum_stock: int
    suggested_reorder_quantity: int


class InventoryDashboard(BaseModel):
    total_products: int
    active_products: int
    total_stock_quantity: int
    low_stock_count: int
    out_of_stock_count: int
    stock_value: Decimal
    recent_movement_count: int
    valuation_method: str = (
        "Weighted cost basis: quantity on hand × product cost price (never selling price)"
    )
