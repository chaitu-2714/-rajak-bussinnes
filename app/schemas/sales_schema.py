"""Pydantic schemas for sales orders, invoices and payments."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import PaymentMethod


class OrderItemInput(BaseModel):
    """One requested line. Prices default to the product's current selling price."""

    product_id: int
    quantity: int = Field(gt=0, le=1_000_000)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2)
    tax_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2)


class SalesOrderCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: int
    items: list[OrderItemInput] = Field(min_length=1)
    discount_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=14, decimal_places=2)
    notes: str | None = Field(default=None, max_length=1000)


class PaymentCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    invoice_id: int
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    payment_method: str = Field(default=PaymentMethod.CASH)
    payment_reference: str | None = Field(default=None, max_length=80)

    @field_validator("payment_method")
    @classmethod
    def _method_valid(cls, value: str) -> str:
        if value not in PaymentMethod.ALL:
            raise ValueError(f"Payment method must be one of {', '.join(PaymentMethod.ALL)}.")
        return value


class SalesOrderLine(BaseModel):
    product_id: int
    product_name: str
    sku: str
    quantity: int
    unit_price: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    line_total: Decimal

    @classmethod
    def from_item(cls, item) -> "SalesOrderLine":
        return cls(
            product_id=item.product_id,
            product_name=item.product.product_name if item.product else "—",
            sku=item.product.sku if item.product else "—",
            quantity=item.quantity,
            unit_price=item.unit_price,
            discount_amount=item.discount_amount,
            tax_amount=item.tax_amount,
            line_total=item.line_total,
        )


class SalesOrderSummary(BaseModel):
    id: int
    order_number: str
    customer_id: int
    customer_name: str
    order_status: str
    payment_status: str
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    item_count: int
    invoice_number: str | None = None
    invoice_id: int | None = None
    created_at: datetime
    notes: str | None = None
    lines: list[SalesOrderLine] = Field(default_factory=list)

    @classmethod
    def from_order(cls, order) -> "SalesOrderSummary":
        invoice = order.invoice
        return cls(
            id=order.id,
            order_number=order.order_number,
            customer_id=order.customer_id,
            customer_name=order.customer.full_name if order.customer else "—",
            order_status=order.order_status,
            payment_status=order.payment_status,
            subtotal=order.subtotal,
            discount_amount=order.discount_amount,
            tax_amount=order.tax_amount,
            total_amount=order.total_amount,
            paid_amount=order.paid_amount,
            outstanding_amount=order.outstanding_amount,
            item_count=len(order.items),
            invoice_number=invoice.invoice_number if invoice else None,
            invoice_id=invoice.id if invoice else None,
            created_at=order.created_at,
            notes=order.notes,
            lines=[SalesOrderLine.from_item(item) for item in order.items],
        )


class InvoiceView(BaseModel):
    id: int
    invoice_number: str
    order_number: str
    customer_name: str
    customer_email: str | None = None
    customer_phone: str | None = None
    customer_address: str | None = None
    invoice_date: datetime
    due_date: datetime | None = None
    subtotal: Decimal
    discount_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    paid_amount: Decimal
    outstanding_amount: Decimal
    status: str
    lines: list[SalesOrderLine] = Field(default_factory=list)
    payments: list[dict] = Field(default_factory=list)

    @classmethod
    def from_invoice(cls, invoice) -> "InvoiceView":
        order = invoice.order
        customer = invoice.customer
        return cls(
            id=invoice.id,
            invoice_number=invoice.invoice_number,
            order_number=order.order_number if order else "—",
            customer_name=customer.full_name if customer else "—",
            customer_email=customer.email if customer else None,
            customer_phone=customer.phone if customer else None,
            customer_address=customer.address if customer else None,
            invoice_date=invoice.invoice_date,
            due_date=invoice.due_date,
            subtotal=invoice.subtotal,
            discount_amount=invoice.discount_amount,
            tax_amount=invoice.tax_amount,
            total_amount=invoice.total_amount,
            paid_amount=invoice.paid_amount,
            outstanding_amount=invoice.outstanding_amount,
            status=invoice.status,
            lines=[SalesOrderLine.from_item(item) for item in (order.items if order else [])],
            payments=[
                {
                    "date": payment.payment_date,
                    "amount": payment.amount,
                    "method": payment.payment_method,
                    "reference": payment.payment_reference,
                    "status": payment.payment_status,
                }
                for payment in invoice.payments
            ],
        )


class SalesDashboard(BaseModel):
    total_orders: int
    completed_orders: int
    pending_orders: int
    cancelled_orders: int
    total_sales_value: Decimal
    average_order_value: Decimal
    paid_total: Decimal
    outstanding_total: Decimal
    top_products: list[dict] = Field(default_factory=list)
    monthly_sales: list[tuple[str, Decimal]] = Field(default_factory=list)
    daily_sales: list[tuple[str, Decimal]] = Field(default_factory=list)
