"""Pydantic schemas for expenses and financial reporting."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import ExpenseCategory, PaymentMethod


class ExpenseCreateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    expense_category: str
    description: str = Field(min_length=3, max_length=255)
    vendor_name: str | None = Field(default=None, max_length=160)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    payment_method: str = Field(default=PaymentMethod.CASH)
    expense_date: datetime

    @field_validator("expense_category")
    @classmethod
    def _category_valid(cls, value: str) -> str:
        if value not in ExpenseCategory.ALL:
            raise ValueError(f"Category must be one of {', '.join(ExpenseCategory.ALL)}.")
        return value

    @field_validator("payment_method")
    @classmethod
    def _method_valid(cls, value: str) -> str:
        if value not in PaymentMethod.ALL:
            raise ValueError(f"Payment method must be one of {', '.join(PaymentMethod.ALL)}.")
        return value


class ExpenseUpdateRequest(ExpenseCreateRequest):
    pass


class ExpenseSummary(BaseModel):
    id: int
    expense_number: str
    expense_category: str
    description: str
    vendor_name: str | None = None
    amount: Decimal
    payment_method: str
    expense_date: datetime
    status: str
    created_by_name: str | None = None
    created_at: datetime

    @classmethod
    def from_expense(cls, expense) -> "ExpenseSummary":
        return cls(
            id=expense.id,
            expense_number=expense.expense_number,
            expense_category=expense.expense_category,
            description=expense.description,
            vendor_name=expense.vendor_name,
            amount=expense.amount,
            payment_method=expense.payment_method,
            expense_date=expense.expense_date,
            status=expense.status,
            created_by_name=getattr(expense.creator, "full_name", None) if expense.creator else None,
            created_at=expense.created_at,
        )


class TransactionRow(BaseModel):
    id: int
    transaction_number: str
    transaction_type: str
    category: str
    amount: Decimal
    reference_type: str
    reference_id: str
    description: str | None = None
    transaction_date: datetime

    @classmethod
    def from_transaction(cls, transaction) -> "TransactionRow":
        return cls(
            id=transaction.id,
            transaction_number=transaction.transaction_number,
            transaction_type=transaction.transaction_type,
            category=transaction.category,
            amount=transaction.amount,
            reference_type=transaction.reference_type,
            reference_id=transaction.reference_id,
            description=transaction.description,
            transaction_date=transaction.transaction_date,
        )


class FinanceSummary(BaseModel):
    """Every figure is computed from recorded transactions (see ``basis``)."""

    revenue: Decimal
    cogs: Decimal
    gross_profit: Decimal
    operating_expenses: Decimal
    net_profit: Decimal
    total_expenses: Decimal
    cash_received: Decimal
    refunds_paid: Decimal
    outstanding_receivables: Decimal
    monthly_income: Decimal
    monthly_expenses: Decimal
    transaction_count: int
    basis: str = ""


class PnlLine(BaseModel):
    label: str
    amount: Decimal
    is_total: bool = False


class ReportTable(BaseModel):
    title: str
    subtitle: str = ""
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    totals: list[str] = Field(default_factory=list)
    basis: str = ""
    generated_at: datetime | None = None
