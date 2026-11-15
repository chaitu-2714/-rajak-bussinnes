"""Pydantic schemas for suppliers, purchase orders and goods receipts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.utils.validators import is_valid_email, is_valid_phone, normalise_email


class SupplierCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    supplier_code: str | None = Field(default=None, max_length=30)
    supplier_name: str = Field(min_length=2, max_length=160)
    contact_person: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    tax_identifier: str | None = Field(default=None, max_length=40)
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str | None) -> str | None:
        if value and not is_valid_email(value):
            raise ValueError("Enter a valid email address.")
        return normalise_email(value) if value else None

    @field_validator("phone")
    @classmethod
    def _phone_shape(cls, value: str | None) -> str | None:
        if value and not is_valid_phone(value):
            raise ValueError("Enter a valid phone number.")
        return value or None


class SupplierUpdateRequest(SupplierCreateRequest):
    pass


class SupplierSummary(BaseModel):
    id: int
    supplier_code: str
    supplier_name: str
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    address: str | None = None
    tax_identifier: str | None = None
    is_active: bool
    created_at: datetime
    order_count: int = 0
    total_order_value: Decimal = Decimal("0.00")
    received_value: Decimal = Decimal("0.00")
    last_order_at: datetime | None = None


class PurchaseOrderItemInput(BaseModel):
    product_id: int
    ordered_quantity: int = Field(gt=0, le=1_000_000)
    unit_cost: Decimal = Field(ge=0, max_digits=14, decimal_places=2)


class PurchaseOrderCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    supplier_id: int
    items: list[PurchaseOrderItemInput] = Field(min_length=1)
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2)
    expected_delivery_date: datetime | None = None
    notes: str | None = Field(default=None, max_length=1000)


class PurchaseOrderLine(BaseModel):
    id: int
    product_id: int
    product_name: str
    sku: str
    ordered_quantity: int
    received_quantity: int
    outstanding_quantity: int
    unit_cost: Decimal
    line_total: Decimal


class PurchaseOrderSummary(BaseModel):
    id: int
    purchase_order_number: str
    supplier_id: int
    supplier_name: str
    status: str
    subtotal: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    expected_delivery_date: datetime | None = None
    created_at: datetime
    ordered_quantity: int
    received_quantity: int
    receipt_count: int
    lines: list[PurchaseOrderLine] = Field(default_factory=list)

    @classmethod
    def from_order(cls, order) -> "PurchaseOrderSummary":
        return cls(
            id=order.id,
            purchase_order_number=order.purchase_order_number,
            supplier_id=order.supplier_id,
            supplier_name=order.supplier.supplier_name if order.supplier else "—",
            status=order.status,
            subtotal=order.subtotal,
            tax_amount=order.tax_amount,
            total_amount=order.total_amount,
            expected_delivery_date=order.expected_delivery_date,
            created_at=order.created_at,
            ordered_quantity=order.ordered_quantity,
            received_quantity=order.received_quantity,
            receipt_count=len(order.receipts),
            lines=[
                PurchaseOrderLine(
                    id=item.id,
                    product_id=item.product_id,
                    product_name=item.product.product_name if item.product else "—",
                    sku=item.product.sku if item.product else "—",
                    ordered_quantity=item.ordered_quantity,
                    received_quantity=item.received_quantity,
                    outstanding_quantity=item.outstanding_quantity,
                    unit_cost=item.unit_cost,
                    line_total=item.line_total,
                )
                for item in order.items
            ],
        )


class ReceiptItemInput(BaseModel):
    purchase_order_item_id: int
    quantity: int = Field(gt=0, le=1_000_000)


class GoodsReceiptRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    purchase_order_id: int
    items: list[ReceiptItemInput] = Field(min_length=1)
    notes: str | None = Field(default=None, max_length=1000)


class GoodsReceiptView(BaseModel):
    id: int
    receipt_number: str
    purchase_order_number: str
    received_at: datetime
    notes: str | None = None
    total_quantity: int
    items: list[dict] = Field(default_factory=list)

    @classmethod
    def from_receipt(cls, receipt) -> "GoodsReceiptView":
        return cls(
            id=receipt.id,
            receipt_number=receipt.receipt_number,
            purchase_order_number=receipt.order.purchase_order_number if receipt.order else "—",
            received_at=receipt.received_at,
            notes=receipt.notes,
            total_quantity=receipt.total_quantity,
            items=[
                {
                    "product": item.product.product_name if item.product else "—",
                    "sku": item.product.sku if item.product else "—",
                    "quantity": item.quantity,
                }
                for item in receipt.items
            ],
        )
