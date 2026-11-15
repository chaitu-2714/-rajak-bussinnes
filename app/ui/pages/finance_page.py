"""Finance page: summary, expenses, ledger and reports."""

from __future__ import annotations

from datetime import datetime, time

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import ExpenseCategory
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.confirmation_dialog import confirm
from app.ui.components.stat_card import StatCard
from app.ui.components.tables import DataTable
from app.ui.dialogs.finance_dialogs import ExpenseDialog
from app.ui.dialogs.sales_dialogs import ReasonDialog
from app.ui.pages.dashboard_page import ChartCard
from app.ui.ui_utils import muted_label, primary_button, secondary_button, show_info
from app.utils.date_utils import format_datetime, local_to_utc

logger = get_logger("ui.finance")

REPORT_LABELS = (
    ("Income report", "income"),
    ("Expense report", "expense"),
    ("Profit and loss", "profit_and_loss"),
    ("Cash flow", "cash_flow"),
    ("Outstanding payments", "outstanding"),
    ("Monthly summary", "monthly_summary"),
)


class FinancePage(QWidget):
    """Financial overview, expense management and reports."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._expenses = []
        self.setObjectName("PageSurface")
        self._build()
        self.refresh()

    def _can(self, permission: str) -> bool:
        return bool(self._principal and self._principal.has(permission))

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)

        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)
        self.range_check = QCheckBox("Date range")
        self.range_check.toggled.connect(self._toggle_range)
        filter_bar.addWidget(self.range_check)

        self.from_date = QDateEdit(QDate.currentDate().addMonths(-1))
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("dd MMM yyyy")
        self.from_date.setButtonSymbols(QDateEdit.NoButtons)
        self.from_date.setMinimumWidth(122)
        self.from_date.setEnabled(False)
        filter_bar.addWidget(self.from_date)

        self.to_date = QDateEdit(QDate.currentDate())
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("dd MMM yyyy")
        self.to_date.setButtonSymbols(QDateEdit.NoButtons)
        self.to_date.setMinimumWidth(122)
        self.to_date.setEnabled(False)
        filter_bar.addWidget(self.to_date)

        apply_button = secondary_button("Apply")
        apply_button.clicked.connect(self.refresh)
        filter_bar.addWidget(apply_button)
        filter_bar.addStretch(1)
        layout.addLayout(filter_bar)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._overview_tab(), "Overview")
        self.tabs.addTab(self._expenses_tab(), "Expenses")
        self.tabs.addTab(self._transactions_tab(), "Transactions")
        self.tabs.addTab(self._reports_tab(), "Reports")
        layout.addWidget(self.tabs, 1)

    def _overview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        cards_one = QHBoxLayout()
        cards_one.setSpacing(10)
        self.card_revenue = StatCard("Revenue", "—", "Net of refunds")
        self.card_expenses = StatCard("Total expenses", "—", "COGS + operating")
        self.card_gross = StatCard("Gross profit", "—", "Revenue − COGS")
        self.card_net = StatCard("Net profit", "—", "After operating expenses")
        for card in (self.card_revenue, self.card_expenses, self.card_gross, self.card_net):
            cards_one.addWidget(card)
        layout.addLayout(cards_one)

        cards_two = QHBoxLayout()
        cards_two.setSpacing(10)
        self.card_cash = StatCard("Cash received", "—", "Payments recorded")
        self.card_outstanding = StatCard("Outstanding", "—", "Receivables")
        self.card_month_income = StatCard("This month income", "—", "Current month")
        self.card_month_expense = StatCard("This month expenses", "—", "Current month")
        for card in (self.card_cash, self.card_outstanding, self.card_month_income, self.card_month_expense):
            cards_two.addWidget(card)
        layout.addLayout(cards_two)

        charts = QHBoxLayout()
        charts.setSpacing(10)
        self.revenue_chart = ChartCard(
            "Monthly revenue", "Revenue appears once a sale is completed."
        )
        self.expense_chart = ChartCard(
            "Monthly expenses", "Expenses appear once you record them."
        )
        charts.addWidget(self.revenue_chart)
        charts.addWidget(self.expense_chart)
        layout.addLayout(charts, 1)

        self.basis_label = QLabel("")
        self.basis_label.setObjectName("Hint")
        self.basis_label.setWordWrap(True)
        layout.addWidget(self.basis_label)
        return page

    def _expenses_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.expense_search = QLineEdit()
        self.expense_search.setPlaceholderText("Search description, vendor or number…")
        self.expense_search.setClearButtonEnabled(True)
        self.expense_search.textChanged.connect(lambda _: self._load_expenses())
        bar.addWidget(self.expense_search, 2)

        self.category_filter = QComboBox()
        self.category_filter.addItem("All categories", None)
        for category in ExpenseCategory.ALL:
            self.category_filter.addItem(category.title(), category)
        self.category_filter.currentIndexChanged.connect(lambda _: self._load_expenses())
        bar.addWidget(self.category_filter)

        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", None)
        self.status_filter.addItem("Recorded", "RECORDED")
        self.status_filter.addItem("Reversed", "REVERSED")
        self.status_filter.currentIndexChanged.connect(lambda _: self._load_expenses())
        bar.addWidget(self.status_filter)
        bar.addStretch(1)

        self.add_expense_button = primary_button("Record expense")
        self.add_expense_button.setEnabled(self._can("finance.create"))
        self.add_expense_button.clicked.connect(self._add_expense)
        bar.addWidget(self.add_expense_button)

        self.edit_expense_button = secondary_button("Edit")
        self.edit_expense_button.setEnabled(self._can("finance.update"))
        self.edit_expense_button.clicked.connect(self._edit_expense)
        bar.addWidget(self.edit_expense_button)

        self.reverse_button = secondary_button("Reverse")
        self.reverse_button.setEnabled(self._can("finance.approve"))
        self.reverse_button.clicked.connect(self._reverse_expense)
        bar.addWidget(self.reverse_button)

        self.export_button = secondary_button("Export CSV")
        self.export_button.setEnabled(self._can("finance.export"))
        self.export_button.clicked.connect(lambda: self._export("expense", "csv"))
        bar.addWidget(self.export_button)
        layout.addLayout(bar)

        self.expense_table = DataTable(
            ["Date", "Number", "Category", "Description", "Vendor", "Method", "Amount", "Status"],
            stretch_columns=(3,),
            empty_title="No expenses recorded",
            empty_body="Record rent, salaries, utilities and other costs here.",
        )
        self.expense_table.table.doubleClicked.connect(lambda _: self._edit_expense())
        layout.addWidget(self.expense_table, 1)
        return page

    def _transactions_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(
            muted_label(
                "The ledger records revenue, cash receipts, expenses and refunds. "
                "Each business event posts exactly one entry."
            )
        )
        self.transaction_table = DataTable(
            ["Date", "Number", "Type", "Category", "Reference", "Amount"],
            empty_title="No transactions yet",
            empty_body="Completing a sale or recording an expense creates ledger entries.",
        )
        layout.addWidget(self.transaction_table, 1)
        return page

    def _reports_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.report_combo = QComboBox()
        for label, value in REPORT_LABELS:
            self.report_combo.addItem(label, value)
        self.report_combo.currentIndexChanged.connect(lambda _: self._generate_report())
        bar.addWidget(self.report_combo)
        bar.addStretch(1)

        self.report_export_csv = secondary_button("Export CSV")
        self.report_export_csv.setEnabled(self._can("finance.export"))
        self.report_export_csv.clicked.connect(
            lambda: self._export(self.report_combo.currentData(), "csv")
        )
        bar.addWidget(self.report_export_csv)

        self.report_export_pdf = secondary_button("Export PDF")
        self.report_export_pdf.setEnabled(self._can("finance.export"))
        self.report_export_pdf.clicked.connect(
            lambda: self._export(self.report_combo.currentData(), "pdf")
        )
        bar.addWidget(self.report_export_pdf)
        layout.addLayout(bar)

        self.report_table = DataTable(
            ["Report"],
            empty_title="No report generated",
            empty_body="Choose a report above.",
        )
        layout.addWidget(self.report_table, 1)

        self.report_basis = QLabel("")
        self.report_basis.setObjectName("Hint")
        self.report_basis.setWordWrap(True)
        layout.addWidget(self.report_basis)
        return page

    # -- data --------------------------------------------------------------
    def _date_range(self) -> tuple[datetime | None, datetime | None]:
        if not self.range_check.isChecked():
            return None, None
        start = local_to_utc(datetime.combine(self.from_date.date().toPython(), time.min))
        end = local_to_utc(datetime.combine(self.to_date.date().toPython(), time.max))
        return start, end

    def _toggle_range(self, enabled: bool) -> None:
        self.from_date.setEnabled(enabled)
        self.to_date.setEnabled(enabled)
        self.refresh()

    def refresh(self) -> None:
        self._error.setVisible(False)
        date_from, date_to = self._date_range()
        try:
            summary = self._context.finance_service.summary(date_from=date_from, date_to=date_to)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.card_revenue.set_value(f"{summary.revenue:,.2f}", True, "Net of refunds")
        self.card_expenses.set_value(
            f"{summary.total_expenses:,.2f}", True, f"COGS {summary.cogs:,.2f} + opex {summary.operating_expenses:,.2f}"
        )
        self.card_gross.set_value(f"{summary.gross_profit:,.2f}", True, "Revenue − COGS")
        self.card_net.set_value(f"{summary.net_profit:,.2f}", True, "After operating expenses")
        self.card_cash.set_value(f"{summary.cash_received:,.2f}", True, f"Refunded {summary.refunds_paid:,.2f}")
        self.card_outstanding.set_value(f"{summary.outstanding_receivables:,.2f}", True, "Unpaid invoices")
        self.card_month_income.set_value(f"{summary.monthly_income:,.2f}", True, "Current month")
        self.card_month_expense.set_value(f"{summary.monthly_expenses:,.2f}", True, "Current month")
        self.basis_label.setText(f"Accounting basis: {summary.basis}")

        self._load_charts()
        self._load_expenses()
        self._load_transactions()
        self._generate_report()

    def _load_charts(self) -> None:
        try:
            series = self._context.finance_service.monthly_series()
        except BizPilotError:
            return
        labels = series["labels"]
        self.revenue_chart.set_series(
            list(range(len(labels))), [float(v) for v in series["income"]], labels
        )
        self.expense_chart.set_series(
            list(range(len(labels))), [float(v) for v in series["expenses"]], labels
        )

    def _load_expenses(self) -> None:
        date_from, date_to = self._date_range()
        try:
            self._expenses = self._context.finance_service.list_expenses(
                search=self.expense_search.text().strip() or None,
                category=self.category_filter.currentData(),
                status=self.status_filter.currentData(),
                date_from=date_from,
                date_to=date_to,
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.expense_table.set_rows(
            [
                [
                    format_datetime(expense.expense_date, "%d %b %Y"),
                    expense.expense_number,
                    expense.expense_category.title(),
                    expense.description,
                    expense.vendor_name or "—",
                    expense.payment_method.replace("_", " ").title(),
                    f"{expense.amount:,.2f}",
                    expense.status.title(),
                ]
                for expense in self._expenses
            ],
            row_ids=[expense.id for expense in self._expenses],
            sort_keys={0: [expense.expense_date for expense in self._expenses],
                       6: [float(expense.amount) for expense in self._expenses]},
        )

    def _load_transactions(self) -> None:
        date_from, date_to = self._date_range()
        try:
            transactions = self._context.finance_service.list_transactions(
                date_from=date_from, date_to=date_to
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.transaction_table.set_rows(
            [
                [
                    format_datetime(transaction.transaction_date, "%d %b %Y"),
                    transaction.transaction_number,
                    transaction.transaction_type.title(),
                    transaction.category.replace("_", " ").title(),
                    f"{transaction.reference_type} {transaction.reference_id}",
                    f"{transaction.amount:,.2f}",
                ]
                for transaction in transactions
            ],
            sort_keys={0: [transaction.transaction_date for transaction in transactions],
                       5: [float(transaction.amount) for transaction in transactions]},
        )

    def _generate_report(self) -> None:
        report_type = self.report_combo.currentData()
        if not report_type:
            return
        date_from, date_to = self._date_range()
        try:
            report = self._context.finance_service.build_report(
                report_type, date_from=date_from, date_to=date_to
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.report_table.table.setColumnCount(len(report.headers))
        self.report_table.table.setHorizontalHeaderLabels(report.headers)
        self.report_table.set_rows([list(row) for row in report.rows])
        self.report_basis.setText(
            f"{report.subtitle} · Basis: {report.basis}"
            if report.basis
            else report.subtitle
        )

    # -- actions -----------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _selected_expense(self):
        expense_id = self.expense_table.selected_id()
        return next((expense for expense in self._expenses if expense.id == expense_id), None)

    def _add_expense(self) -> None:
        dialog = ExpenseDialog(self._context, None, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The expense was recorded.", "Expense saved")

    def _edit_expense(self) -> None:
        expense = self._selected_expense()
        if expense is None:
            self._show_error("Select an expense to edit.")
            return
        dialog = ExpenseDialog(self._context, expense, self)
        if dialog.exec():
            self.refresh()

    def _reverse_expense(self) -> None:
        expense = self._selected_expense()
        if expense is None:
            self._show_error("Select an expense to reverse.")
            return
        if expense.status == "REVERSED":
            self._show_error("This expense is already reversed.")
            return
        if not confirm(
            self,
            title="Reverse expense",
            message=(
                f"Reverse {expense.expense_number} ({expense.amount:,.2f})? A counter entry is "
                "posted and the original record is preserved."
            ),
            confirm_text="Reverse expense",
            destructive=True,
        ):
            return
        dialog = ReasonDialog("Reverse expense", "Why is this expense being reversed?", self)
        if not dialog.exec():
            return
        try:
            self._context.finance_service.reverse_expense(expense.id, dialog.reason())
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()

    def _export(self, report_type: str, file_format: str) -> None:
        date_from, date_to = self._date_range()
        try:
            path = self._context.finance_service.export_report(
                report_type, file_format=file_format, date_from=date_from, date_to=date_to
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        show_info(self, f"Report exported to:\n{path}", "Export complete")
