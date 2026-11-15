"""Finance service: expenses, the transaction ledger, reports and exports.

Accounting basis (also returned with every summary and report)
-------------------------------------------------------------
* **Revenue** = recognised sales revenue (``SALES_REVENUE``) less sales refunds.
  It is recognised when a sales order is completed, not when cash arrives.
* **COGS** = cost price snapshot × quantity for completed orders.
* **Gross profit** = revenue − COGS.
* **Operating expenses** = recorded expenses excluding the ``PURCHASE``
  category, because stock purchases are capitalised into inventory and hit the
  P&L through COGS instead (avoids double counting).
* **Net profit** = gross profit − operating expenses.
* **Cash received** = payments recorded against invoices; **outstanding
  receivables** = unpaid invoice balances. Neither is mixed into revenue.
* **Cash flow** = payments received − (expenses paid + refunds paid), starting
  from a zero opening balance for the Phase 2 reporting window.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    MODULE_FINANCE,
    ExpenseCategory,
    ExpenseStatus,
    TransactionCategory,
    TransactionType,
    AuditAction,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.finance import Expense, FinancialTransaction
from app.database.repositories.finance_repository import FinanceRepository
from app.database.repositories.sales_repository import SalesRepository
from app.database.types import ZERO, to_money
from app.schemas.finance_schema import (
    ExpenseCreateRequest,
    ExpenseSummary,
    ExpenseUpdateRequest,
    FinanceSummary,
    ReportTable,
    TransactionRow,
)
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload
from app.services.event_service import EventService
from app.services.export_service import ExportService
from app.services.numbering import next_document_number
from app.utils.date_utils import end_of_day, start_of_day, utcnow

logger = get_logger("services.finance")

BASIS = (
    "Revenue is recognised when a sales order completes; cash is recognised only "
    "when a payment is recorded. COGS uses the cost snapshot captured on each sale. "
    "Operating expenses exclude the PURCHASE category because stock purchases are "
    "capitalised into inventory and expensed through COGS."
)

def _month_label(month: str) -> str:
    try:
        return datetime.strptime(month, "%Y-%m").strftime("%b %y")
    except ValueError:
        return month


REPORT_TYPES = (
    "income",
    "expense",
    "profit_and_loss",
    "cash_flow",
    "outstanding",
    "monthly_summary",
)


class FinanceService(BaseService):
    """Expenses, ledger posting, financial summaries and reports."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        finance_repository: FinanceRepository,
        sales_repository: SalesRepository,
        audit_service: AuditService,
        event_service: EventService,
        export_service: ExportService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._finance = finance_repository
        self._sales = sales_repository
        self._audit = audit_service
        self._events = event_service
        self._export = export_service

    # -- ledger posting (used by sales) ------------------------------------
    def post_transaction(
        self,
        db: Session,
        *,
        transaction_type: str,
        category: str,
        amount: Decimal,
        reference_type: str,
        reference_id: str | int,
        description: str | None = None,
        actor_id: int | None = None,
        transaction_date: datetime | None = None,
    ) -> FinancialTransaction:
        """Post one ledger entry, refusing duplicates for the same reference."""
        reference = str(reference_id)
        existing = self._finance.get_transaction(
            db, reference_type=reference_type, reference_id=reference, category=category
        )
        if existing is not None:
            raise ConflictError(
                f"A {category} entry already exists for {reference_type} {reference}"
            )

        transaction = FinancialTransaction(
            transaction_number=next_document_number(
                db, FinancialTransaction, "transaction_number", "TXN"
            ),
            transaction_type=transaction_type,
            category=category,
            amount=to_money(amount),
            reference_type=reference_type,
            reference_id=reference,
            description=description,
            transaction_date=transaction_date or utcnow(),
            created_by=actor_id,
        )
        self._finance.add_transaction(db, transaction)
        return transaction

    # -- summary -----------------------------------------------------------
    def summary(
        self, *, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> FinanceSummary:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "finance.view")

            revenue = self._finance.sum_transactions(
                db,
                categories=(TransactionCategory.SALES_REVENUE, TransactionCategory.SALES_REFUND),
                date_from=date_from,
                date_to=date_to,
            )
            cogs = self._sales.cogs(db, date_from=date_from, date_to=date_to)
            gross_profit = to_money(revenue - cogs)
            operating_expenses = self._finance.expense_total(
                db,
                exclude_categories=ExpenseCategory.CAPITALISED,
                date_from=date_from,
                date_to=date_to,
            )
            net_profit = to_money(gross_profit - operating_expenses)
            cash_received = self._sales.payments_received(db, date_from=date_from, date_to=date_to)
            refunds = self._finance.sum_transactions(
                db,
                categories=(TransactionCategory.CASH_REFUND,),
                date_from=date_from,
                date_to=date_to,
            )

            month_start = start_of_day(utcnow().replace(day=1))
            month_end = end_of_day(utcnow())
            monthly_income = self._finance.sum_transactions(
                db,
                categories=(TransactionCategory.SALES_REVENUE, TransactionCategory.SALES_REFUND),
                date_from=month_start,
                date_to=month_end,
            )
            monthly_expenses = self._finance.expense_total(
                db,
                exclude_categories=ExpenseCategory.CAPITALISED,
                date_from=month_start,
                date_to=month_end,
            )

            return FinanceSummary(
                revenue=to_money(revenue),
                cogs=to_money(cogs),
                gross_profit=gross_profit,
                operating_expenses=to_money(operating_expenses),
                net_profit=net_profit,
                total_expenses=to_money(cogs + operating_expenses),
                cash_received=to_money(cash_received),
                refunds_paid=to_money(-refunds),
                outstanding_receivables=self._sales.outstanding_total(db),
                monthly_income=to_money(monthly_income),
                monthly_expenses=to_money(monthly_expenses),
                transaction_count=self._finance.count(db),
                basis=BASIS,
            )

    # -- expenses ----------------------------------------------------------
    def list_expenses(
        self,
        *,
        search: str | None = None,
        category: str | None = None,
        status: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[ExpenseSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "finance.view")
            expenses = self._finance.list_expenses(
                db,
                search=search,
                category=category,
                status=status,
                date_from=date_from,
                date_to=date_to,
            )
            return [ExpenseSummary.from_expense(expense) for expense in expenses]

    def create_expense(self, payload: dict | ExpenseCreateRequest) -> ExpenseSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "finance.create")
            data = validate_payload(ExpenseCreateRequest, payload)

            expense = Expense(
                expense_number=next_document_number(db, Expense, "expense_number", "EXP"),
                expense_category=data.expense_category,
                description=data.description,
                vendor_name=data.vendor_name,
                amount=to_money(data.amount),
                payment_method=data.payment_method,
                expense_date=data.expense_date,
                status=ExpenseStatus.RECORDED,
                created_by=actor.id,
            )
            self._finance.add_expense(db, expense)
            db.flush()

            category = (
                TransactionCategory.CAPITAL_PURCHASE
                if data.expense_category in ExpenseCategory.CAPITALISED
                else TransactionCategory.OPERATING_EXPENSE
            )
            self.post_transaction(
                db,
                transaction_type=TransactionType.EXPENSE,
                category=category,
                amount=expense.amount,
                reference_type="EXPENSE",
                reference_id=expense.id,
                description=f"{expense.expense_category}: {expense.description}",
                actor_id=actor.id,
                transaction_date=expense.expense_date,
            )

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.RECORD_EXPENSE,
                module=MODULE_FINANCE,
                entity_type="Expense",
                entity_id=expense.id,
                new_values={
                    "expense_number": expense.expense_number,
                    "category": expense.expense_category,
                    "amount": str(expense.amount),
                    "vendor": expense.vendor_name,
                },
            )
            self._events.publish(
                db,
                "ExpenseRecorded",
                aggregate_type="Expense",
                aggregate_id=expense.id,
                payload={
                    "expense_id": expense.id,
                    "category": expense.expense_category,
                    "amount": str(expense.amount),
                },
            )
            summary = ExpenseSummary.from_expense(expense)
        self._events.dispatch_pending()
        return summary

    def update_expense(self, expense_id: int, payload: dict | ExpenseUpdateRequest) -> ExpenseSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "finance.update")
            data = validate_payload(ExpenseUpdateRequest, payload)
            expense = self._finance.get_expense(db, expense_id)
            if expense is None:
                raise NotFoundError(f"Expense {expense_id} was not found")
            if expense.status == ExpenseStatus.REVERSED:
                raise ConflictError("A reversed expense cannot be edited")

            old_values = {
                "category": expense.expense_category,
                "description": expense.description,
                "vendor": expense.vendor_name,
                "amount": str(expense.amount),
                "method": expense.payment_method,
            }
            expense.expense_category = data.expense_category
            expense.description = data.description
            expense.vendor_name = data.vendor_name
            expense.amount = to_money(data.amount)
            expense.payment_method = data.payment_method
            expense.expense_date = data.expense_date
            expense.updated_at = utcnow()

            # Keep the ledger in step with the edited amount.
            transaction = self._finance.get_transaction(
                db, reference_type="EXPENSE", reference_id=str(expense.id), category=TransactionCategory.OPERATING_EXPENSE
            ) or self._finance.get_transaction(
                db, reference_type="EXPENSE", reference_id=str(expense.id), category=TransactionCategory.CAPITAL_PURCHASE
            )
            if transaction is not None:
                transaction.amount = expense.amount
                transaction.transaction_date = expense.expense_date
                transaction.category = (
                    TransactionCategory.CAPITAL_PURCHASE
                    if expense.expense_category in ExpenseCategory.CAPITALISED
                    else TransactionCategory.OPERATING_EXPENSE
                )

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_EXPENSE,
                module=MODULE_FINANCE,
                entity_type="Expense",
                entity_id=expense.id,
                old_values=old_values,
                new_values={
                    "category": expense.expense_category,
                    "description": expense.description,
                    "vendor": expense.vendor_name,
                    "amount": str(expense.amount),
                    "method": expense.payment_method,
                },
            )
            return ExpenseSummary.from_expense(expense)

    def reverse_expense(self, expense_id: int, reason: str) -> ExpenseSummary:
        """Reverse an expense (kept in history, excluded from totals)."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "finance.approve")
            if not reason or len(reason.strip()) < 3:
                raise ValidationError("Provide a reason for the reversal.", fields={"reason": "Required"})

            expense = self._finance.get_expense(db, expense_id)
            if expense is None:
                raise NotFoundError(f"Expense {expense_id} was not found")
            if expense.status == ExpenseStatus.REVERSED:
                raise ConflictError("This expense is already reversed")

            expense.status = ExpenseStatus.REVERSED
            expense.updated_at = utcnow()

            # Post the counter entry rather than deleting the original.
            self.post_transaction(
                db,
                transaction_type=TransactionType.REFUND,
                category="EXPENSE_REVERSAL",
                amount=-to_money(expense.amount),
                reference_type="EXPENSE_REVERSAL",
                reference_id=expense.id,
                description=f"Reversal of {expense.expense_number}: {reason.strip()}",
                actor_id=actor.id,
            )

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.REVERSE_EXPENSE,
                module=MODULE_FINANCE,
                entity_type="Expense",
                entity_id=expense.id,
                old_values={"status": ExpenseStatus.RECORDED},
                new_values={"status": ExpenseStatus.REVERSED, "reason": reason.strip()},
            )
            return ExpenseSummary.from_expense(expense)

    def list_transactions(
        self,
        *,
        transaction_types: tuple[str, ...] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 500,
    ) -> list[TransactionRow]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "finance.view")
            return [
                TransactionRow.from_transaction(transaction)
                for transaction in self._finance.list_transactions(
                    db,
                    transaction_types=transaction_types,
                    date_from=date_from,
                    date_to=date_to,
                    limit=limit,
                )
            ]

    def monthly_series(self, months: int = 6) -> dict[str, list]:
        """Income and expense totals per month for the finance charts."""
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "finance.view")
            monthly = self._finance.monthly_totals(db, months=months)
            labels: list[str] = []
            income: list[Decimal] = []
            expenses: list[Decimal] = []
            for month, buckets in monthly.items():
                labels.append(_month_label(month))
                income.append(
                    to_money(
                        buckets.get(TransactionCategory.SALES_REVENUE, ZERO)
                        + buckets.get(TransactionCategory.SALES_REFUND, ZERO)
                    )
                )
                expenses.append(
                    to_money(
                        buckets.get(TransactionCategory.OPERATING_EXPENSE, ZERO)
                        + buckets.get(TransactionCategory.CAPITAL_PURCHASE, ZERO)
                        + buckets.get("EXPENSE_REVERSAL", ZERO)
                    )
                )
            return {"labels": labels, "income": income, "expenses": expenses}

    # -- reports -----------------------------------------------------------
    def build_report(
        self,
        report_type: str,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> ReportTable:
        if report_type not in REPORT_TYPES:
            raise ValidationError(f"Unknown report type '{report_type}'.")

        with self.unit_of_work(write=False) as db:
            self._authorize(db, "finance.view")
            generated = utcnow()
            period = self._period_label(date_from, date_to)

            if report_type == "income":
                rows = [
                    [
                        transaction.transaction_date.strftime("%d-%m-%Y"),
                        transaction.transaction_number,
                        transaction.transaction_type,
                        transaction.category,
                        transaction.reference_type,
                        f"{transaction.amount:.2f}",
                    ]
                    for transaction in self._finance.list_transactions(
                        db,
                        transaction_types=(TransactionType.INCOME, TransactionType.REFUND),
                        date_from=date_from,
                        date_to=date_to,
                    )
                ]
                total = self._finance.sum_transactions(
                    db,
                    categories=(
                        TransactionCategory.SALES_REVENUE,
                        TransactionCategory.PAYMENT_RECEIVED,
                        TransactionCategory.SALES_REFUND,
                        TransactionCategory.CASH_REFUND,
                    ),
                    date_from=date_from,
                    date_to=date_to,
                )
                return ReportTable(
                    title="Income report",
                    subtitle=period,
                    headers=["Date", "Reference", "Type", "Category", "Source", "Amount"],
                    rows=rows,
                    totals=["", "", "", "", "Net income", f"{total:.2f}"],
                    basis=BASIS,
                    generated_at=generated,
                )

            if report_type == "expense":
                expenses = self._finance.list_expenses(db, date_from=date_from, date_to=date_to)
                rows = [
                    [
                        expense.expense_date.strftime("%d-%m-%Y"),
                        expense.expense_number,
                        expense.expense_category,
                        expense.description,
                        expense.vendor_name or "",
                        expense.status,
                        f"{expense.amount:.2f}",
                    ]
                    for expense in expenses
                ]
                total = self._finance.expense_total(db, date_from=date_from, date_to=date_to)
                return ReportTable(
                    title="Expense report",
                    subtitle=period,
                    headers=["Date", "Number", "Category", "Description", "Vendor", "Status", "Amount"],
                    rows=rows,
                    totals=["", "", "", "", "", "Total", f"{total:.2f}"],
                    basis=BASIS,
                    generated_at=generated,
                )

            if report_type == "profit_and_loss":
                revenue = self._finance.sum_transactions(
                    db,
                    categories=(TransactionCategory.SALES_REVENUE, TransactionCategory.SALES_REFUND),
                    date_from=date_from,
                    date_to=date_to,
                )
                cogs = self._sales.cogs(db, date_from=date_from, date_to=date_to)
                opex = self._finance.expense_total(
                    db, exclude_categories=ExpenseCategory.CAPITALISED, date_from=date_from, date_to=date_to
                )
                rows = [
                    ["Revenue (net of refunds)", f"{revenue:.2f}"],
                    ["Cost of goods sold", f"({cogs:.2f})"],
                    ["Gross profit", f"{to_money(revenue - cogs):.2f}"],
                    ["Operating expenses", f"({opex:.2f})"],
                    ["Net profit", f"{to_money(revenue - cogs - opex):.2f}"],
                ]
                return ReportTable(
                    title="Profit and loss summary",
                    subtitle=period,
                    headers=["Line", "Amount"],
                    rows=rows,
                    totals=["", ""],
                    basis=BASIS,
                    generated_at=generated,
                )

            if report_type == "cash_flow":
                received = self._sales.payments_received(db, date_from=date_from, date_to=date_to)
                refunds = -self._finance.sum_transactions(
                    db, categories=(TransactionCategory.CASH_REFUND,), date_from=date_from, date_to=date_to
                )
                expenses_paid = self._finance.expense_total(db, date_from=date_from, date_to=date_to)
                net = to_money(received - refunds - expenses_paid)
                rows = [
                    ["Opening cash balance", "0.00"],
                    ["Cash received from customers", f"{received:.2f}"],
                    ["Refunds paid to customers", f"({refunds:.2f})"],
                    ["Expenses paid", f"({expenses_paid:.2f})"],
                    ["Net cash movement", f"{net:.2f}"],
                    ["Closing cash balance", f"{net:.2f}"],
                ]
                return ReportTable(
                    title="Cash flow summary",
                    subtitle=period,
                    headers=["Item", "Amount"],
                    rows=rows,
                    totals=["", ""],
                    basis=BASIS + " Opening balance is zero for this reporting window.",
                    generated_at=generated,
                )

            if report_type == "outstanding":
                invoices = self._sales.list_invoices(db, status="UNPAID") + self._sales.list_invoices(
                    db, status="PARTIALLY_PAID"
                )
                rows = [
                    [
                        invoice.invoice_number,
                        invoice.invoice_date.strftime("%d-%m-%Y"),
                        invoice.customer.full_name if invoice.customer else "—",
                        f"{invoice.total_amount:.2f}",
                        f"{invoice.paid_amount:.2f}",
                        f"{invoice.outstanding_amount:.2f}",
                        invoice.due_date.strftime("%d-%m-%Y") if invoice.due_date else "",
                    ]
                    for invoice in invoices
                ]
                total = sum((invoice.outstanding_amount for invoice in invoices), ZERO)
                return ReportTable(
                    title="Outstanding payments",
                    subtitle=period,
                    headers=["Invoice", "Date", "Customer", "Total", "Paid", "Outstanding", "Due"],
                    rows=rows,
                    totals=["", "", "", "", "", "Outstanding", f"{to_money(total):.2f}"],
                    basis=BASIS,
                    generated_at=generated,
                )

            # monthly_summary
            monthly = self._finance.monthly_totals(db)
            rows = []
            for month, buckets in monthly.items():
                income = buckets.get(TransactionCategory.SALES_REVENUE, ZERO) + buckets.get(
                    TransactionCategory.SALES_REFUND, ZERO
                )
                expense = buckets.get(TransactionCategory.OPERATING_EXPENSE, ZERO) + buckets.get(
                    TransactionCategory.CAPITAL_PURCHASE, ZERO
                ) + buckets.get("EXPENSE_REVERSAL", ZERO)
                rows.append([month, f"{income:.2f}", f"{expense:.2f}", f"{to_money(income - expense):.2f}"])
            return ReportTable(
                title="Monthly financial summary",
                subtitle="Last 6 months",
                headers=["Month", "Income", "Expenses", "Net"],
                rows=rows,
                totals=["", "", "", ""],
                basis=BASIS,
                generated_at=generated,
            )

    # -- exports -----------------------------------------------------------
    def export_report(
        self,
        report_type: str,
        *,
        file_format: str = "csv",
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> str:
        """Write a report to the exports folder and return the path."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "finance.export")
            report = self.build_report(report_type, date_from=date_from, date_to=date_to)
            stamp = utcnow().strftime("%Y%m%d_%H%M%S")
            if file_format == "pdf":
                path = self._export.write_pdf_report(
                    report, f"{report_type}_{stamp}.pdf"
                )
            else:
                path = self._export.write_report_csv(report, f"{report_type}_{stamp}.csv")

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.EXPORT_REPORT,
                module=MODULE_FINANCE,
                entity_type="Report",
                entity_id=report_type,
                new_values={"format": file_format, "path": str(path)},
            )
            return str(path)

    def export_expenses_csv(self, *, date_from: datetime | None = None, date_to: datetime | None = None) -> str:
        return self.export_report("expense", file_format="csv", date_from=date_from, date_to=date_to)

    @staticmethod
    def _period_label(date_from: datetime | None, date_to: datetime | None) -> str:
        if date_from and date_to:
            return f"{date_from:%d %b %Y} – {date_to:%d %b %Y}"
        if date_from:
            return f"From {date_from:%d %b %Y}"
        if date_to:
            return f"Up to {date_to:%d %b %Y}"
        return "All recorded transactions"
