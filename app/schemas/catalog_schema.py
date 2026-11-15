"""Pydantic schemas for categories and products."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import DEFAULT_UNIT


class CategoryCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    category_name: str = Field(min_length=2, max_length=120)
    description: str | None = Field(default=None, max_length=255)
    is_active: bool = True


class CategoryUpdateRequest(CategoryCreateRequest):
    pass


class CategorySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_name: str
    description: str | None = None
    is_active: bool
    product_count: int = 0

    @classmethod
    def from_category(cls, category) -> "CategorySummary":
        return cls(
            id=category.id,
            category_name=category.category_name,
            description=category.description,
            is_active=category.is_active,
            product_count=len(category.products),
        )


class ProductCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    sku: str | None = Field(default=None, max_length=40)
    product_name: str = Field(min_length=2, max_length=160)
    category_id: int | None = None
    description: str | None = None
    unit: str = Field(default=DEFAULT_UNIT, max_length=16)
    cost_price: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2)
    selling_price: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2)
    minimum_stock: int = Field(default=0, ge=0)
    barcode: str | None = Field(default=None, max_length=64)
    is_active: bool = True

    @field_validator("unit")
    @classmethod
    def _unit_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Unit is required.")
        return value.strip()


class ProductUpdateRequest(ProductCreateRequest):
    sku: str = Field(min_length=1, max_length=40)


class ProductSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    product_name: str
    category_id: int | None = None
    category_name: str
    unit: str
    cost_price: Decimal
    selling_price: Decimal
    minimum_stock: int
    barcode: str | None = None
    is_active: bool
    created_at: datetime

    @classmethod
    def from_product(cls, product) -> "ProductSummary":
        return cls(
            id=product.id,
            sku=product.sku,
            product_name=product.product_name,
            category_id=product.category_id,
            category_name=product.category_name,
            unit=product.unit,
            cost_price=product.cost_price,
            selling_price=product.selling_price,
            minimum_stock=product.minimum_stock,
            barcode=product.barcode,
            is_active=product.is_active,
            created_at=product.created_at,
        )
