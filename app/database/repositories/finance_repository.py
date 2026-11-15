"""Data access for expenses and the financial transaction ledger."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database.models.finance import Expense, FinancialTransaction
from app.database.types import ZERO, to_money


class FinanceRepository:
    """Expense and ledger queries."""

    # -- expenses ----------------------------------------------------------
    def add_expense(self, db: Session, expense: Expense) -> Expense:
        db.add(expense)
        db.flush()
        return expense

    def get_expense(self, db: Session, expense_id: int) -> Expense | None:
        return db.get(Expense, expense_id)

    def list_expenses(
        self,
        db: Session,
        *,
        search: str | None = None,
        category: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 500,
    ) -> list[Expense]:
        stmt = select(Expense)
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Expense.description).like(pattern),
                    func.lower(func.coalesce(Expense.vendor_name, "")).like(pattern),
                    func.lower(Expense.expense_number).like(pattern),
                )
            )
        if category:
            stmt = stmt.where(Expense.expense_category == category)
        if status:
            stmt = stmt.where(Expense.status == status)
        if date_from is not None:
            stmt = stmt.where(Expense.expense_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Expense.expense_date <= date_to)
        stmt = stmt.order_by(Expense.expense_date.desc(), Expense.id.desc()).limit(limit)
        return list(db.scalars(stmt).all())

    def expense_total(
        self,
        db: Session,
        *,
        categories: tuple[str, ...] | None = None,
        exclude_categories: tuple[str, ...] = (),
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Decimal:
        stmt = select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.status == "RECORDED")
        if categories:
            stmt = stmt.where(Expense.expense_category.in_(categories))
        if exclude_categories:
            stmt = stmt.where(Expense.expense_category.notin_(exclude_categories))
        if date_from is not None:
            stmt = stmt.where(Expense.expense_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Expense.expense_date <= date_to)
        return to_money(db.scalar(stmt) or 0)

    # -- ledger ------------------------------------------------------------
    def add_transaction(self, db: Session, transaction: FinancialTransaction) -> FinancialTransaction:
        db.add(transaction)
        db.flush()
        return transaction

    def get_transaction(
        self, db: Session, *, reference_type: str, reference_id: str, category: str
    ) -> FinancialTransaction | None:
        return db.scalars(
            select(FinancialTransaction).where(
                FinancialTransaction.reference_type == reference_type,
                FinancialTransaction.reference_id == reference_id,
                FinancialTransaction.category == category,
            )
        ).first()

    def list_transactions(
        self,
        db: Session,
        *,
        transaction_types: tuple[str, ...] | None = None,
        categories: tuple[str, ...] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 500,
    ) -> list[FinancialTransaction]:
        stmt = select(FinancialTransaction)
        if transaction_types:
            stmt = stmt.where(FinancialTransaction.transaction_type.in_(transaction_types))
        if categories:
            stmt = stmt.where(FinancialTransaction.category.in_(categories))
        if date_from is not None:
            stmt = stmt.where(FinancialTransaction.transaction_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(FinancialTransaction.transaction_date <= date_to)
        stmt = stmt.order_by(
            FinancialTransaction.transaction_date.desc(), FinancialTransaction.id.desc()
        ).limit(limit)
        return list(db.scalars(stmt).all())

    def sum_transactions(
        self,
        db: Session,
        *,
        categories: tuple[str, ...],
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Decimal:
        stmt = select(func.coalesce(func.sum(FinancialTransaction.amount), 0)).where(
            FinancialTransaction.category.in_(categories)
        )
        if date_from is not None:
            stmt = stmt.where(FinancialTransaction.transaction_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(FinancialTransaction.transaction_date <= date_to)
        return to_money(db.scalar(stmt) or 0)

    def monthly_totals(self, db: Session, months: int = 6) -> dict[str, dict[str, Decimal]]:
        rows = db.execute(
            select(
                func.strftime("%Y-%m", FinancialTransaction.transaction_date).label("month"),
                FinancialTransaction.category,
                func.coalesce(func.sum(FinancialTransaction.amount), 0),
            )
            .group_by("month", FinancialTransaction.category)
            .order_by("month")
        ).all()

        result: dict[str, dict[str, Decimal]] = {}
        for month, category, total in rows:
            bucket = result.setdefault(str(month), {})
            bucket[str(category)] = to_money(total or 0)
        ordered = dict(sorted(result.items()))
        return dict(list(ordered.items())[-months:])

    def count(self, db: Session) -> int:
        return int(db.scalar(select(func.count(FinancialTransaction.id))) or 0)

    def opening_balance(self, db: Session) -> Decimal:
        """Phase 2 starts from a zero cash balance (documented accounting basis)."""
        return ZERO
