"""Pydantic schemas for customers, segmentation and follow-ups."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import CustomerType
from app.utils.validators import is_valid_email, is_valid_phone, normalise_email


class CustomerCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_code: str | None = Field(default=None, max_length=30)
    full_name: str = Field(min_length=2, max_length=160)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=80)
    customer_type: str = Field(default=CustomerType.INDIVIDUAL)
    notes: str | None = Field(default=None, max_length=1000)
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

    @field_validator("customer_type")
    @classmethod
    def _type_valid(cls, value: str) -> str:
        if value not in CustomerType.ALL:
            raise ValueError(f"Customer type must be one of {', '.join(CustomerType.ALL)}.")
        return value


class CustomerUpdateRequest(CustomerCreateRequest):
    pass


class CustomerSummary(BaseModel):
    id: int
    customer_code: str
    full_name: str
    email: str | None = None
    phone: str | None = None
    city: str | None = None
    customer_type: str
    is_active: bool
    created_at: datetime
    order_count: int = 0
    total_purchase: Decimal = Decimal("0.00")
    last_purchase_at: datetime | None = None
    segment: str = "New"


class FollowUpCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    customer_id: int
    title: str = Field(min_length=3, max_length=160)
    notes: str | None = Field(default=None, max_length=1000)
    due_date: datetime
    assigned_to: int | None = None


class FollowUpView(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    title: str
    notes: str | None = None
    due_date: datetime
    status: str
    assigned_to: int | None = None
    assignee_name: str | None = None
    is_overdue: bool = False

    @classmethod
    def from_follow_up(cls, follow_up, *, now: datetime | None = None) -> "FollowUpView":
        from app.utils.date_utils import utcnow

        reference = now or utcnow()
        return cls(
            id=follow_up.id,
            customer_id=follow_up.customer_id,
            customer_name=follow_up.customer.full_name if follow_up.customer else "—",
            title=follow_up.title,
            notes=follow_up.notes,
            due_date=follow_up.due_date,
            status=follow_up.status,
            assigned_to=follow_up.assigned_to,
            assignee_name=getattr(follow_up.assignee, "full_name", None)
            if follow_up.assignee
            else None,
            is_overdue=follow_up.status == "PENDING" and follow_up.due_date < reference,
        )


class CustomerInvoiceRow(BaseModel):
    invoice_number: str
    invoice_date: datetime
    total_amount: Decimal
    paid_amount: Decimal
    outstanding: Decimal
    status: str


class CustomerPaymentRow(BaseModel):
    payment_date: datetime
    amount: Decimal
    payment_method: str
    reference: str | None = None
    invoice_number: str


class CustomerProfile(BaseModel):
    summary: CustomerSummary
    address: str | None = None
    notes: str | None = None
    outstanding_amount: Decimal = Decimal("0.00")
    invoices: list[CustomerInvoiceRow] = Field(default_factory=list)
    payments: list[CustomerPaymentRow] = Field(default_factory=list)
    follow_ups: list[FollowUpView] = Field(default_factory=list)
    segment_reason: str = ""


class CrmDashboard(BaseModel):
    total_customers: int
    active_customers: int
    new_customers_30d: int
    inactive_customers: int
    total_purchase_value: Decimal
    top_customers: list[CustomerSummary] = Field(default_factory=list)
    segments: dict[str, int] = Field(default_factory=dict)
    segmentation_rules: list[str] = Field(default_factory=list)
