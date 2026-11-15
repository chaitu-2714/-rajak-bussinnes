"""Input schemas for the registered tools."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PeriodName = Literal[
    "today",
    "this_week",
    "this_month",
    "last_month",
    "this_year",
    "last_30_days",
    "all_time",
]


class PeriodArgs(BaseModel):
    """Common date filter. ``period`` wins over explicit dates when supplied."""

    model_config = ConfigDict(extra="forbid")

    period: PeriodName | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None


class EmptyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductRef(BaseModel):
    """Reference a product by id, SKU or (partial) name."""

    model_config = ConfigDict(extra="forbid")

    product_id: int | None = None
    sku: str | None = Field(default=None, max_length=40)
    product_name: str | None = Field(default=None, max_length=160)


class CustomerRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: int | None = None
    customer_name: str | None = Field(default=None, max_length=160)


class SupplierRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    supplier_id: int | None = None
    supplier_name: str | None = Field(default=None, max_length=160)


class LimitArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=10, ge=1, le=100)


class TopProductsArgs(LimitArgs):
    pass


class TrendArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    months: int = Field(default=6, ge=1, le=24)


class HistoryArgs(PeriodArgs):
    limit: int = Field(default=20, ge=1, le=100)


class MovementsArgs(PeriodArgs):
    product_id: int | None = None
    product_name: str | None = Field(default=None, max_length=160)
    limit: int = Field(default=20, ge=1, le=100)


class InactiveCustomersArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=90, ge=7, le=3650)
    limit: int = Field(default=20, ge=1, le=100)


class ReportArgs(PeriodArgs):
    report_type: Literal[
        "income", "expense", "profit_and_loss", "cash_flow", "outstanding", "monthly_summary"
    ] = "profit_and_loss"
    file_format: Literal["csv", "pdf"] = "pdf"


class PurchaseOrderStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal[
        "DRAFT", "APPROVED", "ORDERED", "PARTIALLY_RECEIVED", "RECEIVED", "CANCELLED"
    ] | None = None
    supplier_id: int | None = None


class SalesOrderLineArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str | None = Field(default=None, max_length=160)
    product_id: int | None = None
    quantity: int = Field(gt=0, le=100_000)


class PrepareSalesOrderArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_name: str | None = Field(default=None, max_length=160)
    customer_id: int | None = None
    items: list[SalesOrderLineArgs] = Field(default_factory=list)
    notes: str | None = Field(default=None, max_length=500)


class PrepareExpenseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expense_category: Literal[
        "RENT", "SALARY", "UTILITIES", "TRANSPORT", "PURCHASE", "MARKETING", "MAINTENANCE", "OTHER"
    ] = "OTHER"
    description: str = Field(min_length=3, max_length=255)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    vendor_name: str | None = Field(default=None, max_length=160)
    payment_method: Literal["CASH", "CARD", "UPI", "BANK_TRANSFER", "OTHER"] = "CASH"


class PurchaseRecommendationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_name: str | None = Field(default=None, max_length=160)
    product_id: int | None = None
    requested_quantity: int | None = Field(default=None, gt=0, le=1_000_000)


# ---------------------------------------------------------------------------
# Phase 4 agent inputs
# ---------------------------------------------------------------------------
class MonthsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    months: int = Field(default=6, ge=1, le=24)


class VelocityArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    window_days: int = Field(default=30, ge=7, le=180)


class FollowUpArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: int | None = None
    customer_name: str | None = Field(default=None, max_length=160)
    title: str = Field(default="Follow up with customer", min_length=3, max_length=120)
    due_in_days: int = Field(default=7, ge=0, le=365)


class AgentRunArgs(BaseModel):
    """Arguments for a ``run_*_agent`` tool."""

    model_config = ConfigDict(extra="forbid")

    period: PeriodName | None = None
    task_type: str | None = Field(default=None, max_length=60)
    parameters: dict = Field(default_factory=dict)
