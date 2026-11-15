"""Business Intelligence dashboard: every figure comes from the analytics service."""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.confirmation_dialog import confirm
from app.ui.components.stat_card import StatCard
from app.ui.components.tables import DataTable
from app.ui.ui_utils import (
    muted_label,
    primary_button,
    secondary_button,
    show_error,
    show_info,
)
from app.ui.workers.orchestration_worker import ActionWorker
from app.utils.date_utils import format_datetime

logger = get_logger("ui.business_intelligence")

GRANULARITIES = (
    ("This month", "MONTHLY"),
    ("This week", "WEEKLY"),
    ("Today", "DAILY"),
    ("This quarter", "QUARTERLY"),
    ("This year", "YEARLY"),
)

SCENARIOS = (
    ("Price increase", "PRICE_INCREASE", "percent", "5"),
    ("Sales decline", "SALES_DECLINE", "percent", "10"),
    ("Supplier price increase", "SUPPLIER_PRICE_INCREASE", "percent", "8"),
    ("Hire employees", "HIRE_EMPLOYEES", "count", "2"),
    ("Purchase additional units", "PURCHASE_UNITS", "units", "100"),
)

FORECAST_TARGETS = (
    ("Sales", "SALES"),
    ("Revenue", "REVENUE"),
    ("Expenses", "EXPENSES"),
    ("Cash flow", "CASH_FLOW"),
)


class BusinessIntelligencePage(QWidget):
    """Executive overview plus one tab per analytics domain."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._workers: list[Any] = []
        self._bundle: Any | None = None
        self._build()
        self.refresh()

    # -- permissions -------------------------------------------------------
    def _can(self, permission: str) -> bool:
        return bool(self._principal and permission in self._principal.permissions)

    # -- UI ----------------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Period"))
        self.period_combo = QComboBox()
        for label, value in GRANULARITIES:
            self.period_combo.addItem(label, value)
        self.period_combo.currentIndexChanged.connect(lambda _: self.refresh())
        controls.addWidget(self.period_combo)
        self.refresh_button = secondary_button("Refresh analytics")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        self.quality_label = muted_label("")
        controls.addWidget(self.quality_label)
        layout.addLayout(controls)

        cards = QGridLayout()
        cards.setSpacing(10)
        self.card_revenue = StatCard("Revenue", "—", "invoiced this period")
        self.card_cash = StatCard("Cash collected", "—", "money actually received")
        self.card_expenses = StatCard("Operating expenses", "—", "recorded expenses")
        self.card_profit = StatCard("Net profit", "—", "after COGS and expenses")
        self.card_growth = StatCard("Revenue growth", "—", "vs previous period")
        self.card_receivables = StatCard("Receivables", "—", "outstanding invoices")
        for index, card in enumerate(
            (
                self.card_revenue,
                self.card_cash,
                self.card_expenses,
                self.card_profit,
                self.card_growth,
                self.card_receivables,
            )
        ):
            cards.addWidget(card, 0, index)
        layout.addLayout(cards)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_executive_tab(), "Executive")
        self.tabs.addTab(self._build_financial_tab(), "Financial")
        self.tabs.addTab(self._build_sales_tab(), "Sales")
        self.tabs.addTab(self._build_customer_tab(), "Customers")
        self.tabs.addTab(self._build_inventory_tab(), "Inventory")
        self.tabs.addTab(self._build_supplier_tab(), "Suppliers")
        self.tabs.addTab(self._build_anomaly_tab(), "Anomalies")
        self.tabs.addTab(self._build_forecast_tab(), "Forecast")
        self.tabs.addTab(self._build_risk_tab(), "Risk")
        self.tabs.addTab(self._build_simulation_tab(), "What-if")
        layout.addWidget(self.tabs, 1)

    def _table_tab(self, headers: list[str], stretch: tuple[int, ...] = (0,)) -> tuple[QWidget, DataTable]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        table = DataTable(headers, stretch_columns=stretch)
        layout.addWidget(table)
        return page, table

    def _build_executive_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Business KPIs"))
        self.kpi_table = DataTable(
            ["KPI", "Value", "Unit", "Completeness", "Formula"], stretch_columns=(4,)
        )
        left_layout.addWidget(self.kpi_table, 1)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Insights"))
        self.insights_text = QPlainTextEdit()
        self.insights_text.setReadOnly(True)
        right_layout.addWidget(self.insights_text, 2)
        right_layout.addWidget(QLabel("Performance gaps and data limitations"))
        self.gaps_text = QPlainTextEdit()
        self.gaps_text.setReadOnly(True)
        right_layout.addWidget(self.gaps_text, 1)
        splitter.addWidget(right)
        splitter.setSizes([700, 700])
        layout.addWidget(splitter, 1)
        return page

    def _build_financial_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.revenue_plot = pg.PlotWidget()
        self.revenue_plot.setBackground("w")
        self.revenue_plot.showGrid(x=True, y=True, alpha=0.12)
        self.revenue_plot.setMenuEnabled(False)
        self.revenue_plot.setMouseEnabled(x=False, y=False)
        self.revenue_plot.hideButtons()
        self.revenue_plot.setMinimumHeight(220)
        layout.addWidget(self.revenue_plot, 1)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Financial summary"))
        self.financial_table = DataTable(["Metric", "Value", "Basis"], stretch_columns=(2,))
        left_layout.addWidget(self.financial_table)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Expense categories and receivables aging"))
        self.expense_table = DataTable(["Category", "Amount", "Share"], stretch_columns=(0,))
        right_layout.addWidget(self.expense_table)
        splitter.addWidget(right)
        layout.addWidget(splitter, 1)
        return page

    def _build_sales_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Product performance"))
        self.product_table = DataTable(
            ["Product", "Revenue", "Units", "Share %", "Class", "Reason"], stretch_columns=(5,)
        )
        left_layout.addWidget(self.product_table)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Sales summary"))
        self.sales_table = DataTable(["Metric", "Value"], stretch_columns=(0,))
        right_layout.addWidget(self.sales_table, 1)
        right_layout.addWidget(QLabel("Category contribution"))
        self.category_table = DataTable(["Category", "Revenue", "Share"], stretch_columns=(0,))
        right_layout.addWidget(self.category_table, 1)
        splitter.addWidget(right)
        splitter.setSizes([700, 600])
        layout.addWidget(splitter, 1)
        return page

    def _build_customer_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Segments (rules shown)"))
        self.segment_table = DataTable(
            ["Segment", "Customers", "Revenue", "Rule"], stretch_columns=(3,)
        )
        left_layout.addWidget(self.segment_table)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Customer metrics"))
        self.customer_table = DataTable(["Metric", "Value"], stretch_columns=(0,))
        right_layout.addWidget(self.customer_table, 1)
        right_layout.addWidget(QLabel("Cohorts (first purchase month)"))
        self.cohort_table = DataTable(
            ["Cohort", "Customers", "Repeat", "Retention %", "Revenue"], stretch_columns=(0,)
        )
        right_layout.addWidget(self.cohort_table, 1)
        splitter.addWidget(right)
        layout.addWidget(splitter, 1)
        return page

    def _build_inventory_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Demand and cover"))
        self.demand_table = DataTable(
            ["Product", "Available", "Sold", "Per day", "Days of cover"], stretch_columns=(0,)
        )
        left_layout.addWidget(self.demand_table, 1)
        left_layout.addWidget(QLabel("Slow-moving and non-moving stock"))
        self.slow_table = DataTable(
            ["Product", "Available", "Value", "Status", "Note"], stretch_columns=(4,)
        )
        left_layout.addWidget(self.slow_table, 1)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Inventory metrics"))
        self.inventory_table = DataTable(["Metric", "Value"], stretch_columns=(0,))
        right_layout.addWidget(self.inventory_table, 1)
        right_layout.addWidget(QLabel("Overstock"))
        self.overstock_table = DataTable(
            ["Product", "Available", "Days of cover", "Note"], stretch_columns=(3,)
        )
        right_layout.addWidget(self.overstock_table, 1)
        splitter.addWidget(right)
        layout.addWidget(splitter, 1)
        return page

    def _build_supplier_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Supplier performance"))
        self.supplier_table = DataTable(
            ["Supplier", "Orders", "Received", "Value", "Lead time", "On time"],
            stretch_columns=(0,),
        )
        left_layout.addWidget(self.supplier_table)
        splitter.addWidget(left)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Purchase price trends"))
        self.price_table = DataTable(
            ["Product", "First cost", "Latest cost", "Change %", "Observations"],
            stretch_columns=(0,),
        )
        right_layout.addWidget(self.price_table, 1)
        right_layout.addWidget(QLabel("Supplier metrics"))
        self.supplier_metrics = DataTable(["Metric", "Value"], stretch_columns=(0,))
        right_layout.addWidget(self.supplier_metrics, 1)
        splitter.addWidget(right)
        layout.addWidget(splitter, 1)
        return page

    def _build_anomaly_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(
            muted_label(
                "Anomalies are review items, never fraud findings. Nothing here changes a "
                "business record."
            )
        )
        self.anomaly_table = DataTable(
            ["Category", "Type", "Record", "Method", "Observed", "Expected", "Severity", "Status"],
            stretch_columns=(2,),
        )
        self.anomaly_table.table.itemSelectionChanged.connect(self._show_anomaly_detail)
        layout.addWidget(self.anomaly_table, 2)
        self.anomaly_detail = QPlainTextEdit()
        self.anomaly_detail.setReadOnly(True)
        layout.addWidget(self.anomaly_detail, 1)
        row = QHBoxLayout()
        self.anomaly_note = QLineEdit()
        self.anomaly_note.setPlaceholderText("Review note (optional)…")
        row.addWidget(self.anomaly_note, 1)
        self.ack_button = secondary_button("Acknowledge")
        self.ack_button.clicked.connect(lambda: self._review_anomaly("ACKNOWLEDGED"))
        self.dismiss_button = secondary_button("Dismiss")
        self.dismiss_button.clicked.connect(lambda: self._review_anomaly("DISMISSED"))
        for button in (self.ack_button, self.dismiss_button):
            button.setEnabled(self._can("analytics.manage"))
            row.addWidget(button)
        layout.addLayout(row)
        return page

    def _build_forecast_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Forecast"))
        self.forecast_target = QComboBox()
        for label, value in FORECAST_TARGETS:
            self.forecast_target.addItem(label, value)
        controls.addWidget(self.forecast_target)
        controls.addWidget(QLabel("Horizon (months)"))
        self.forecast_horizon = QLineEdit("3")
        self.forecast_horizon.setMaximumWidth(60)
        controls.addWidget(self.forecast_horizon)
        self.forecast_button = primary_button("Run forecast")
        self.forecast_button.clicked.connect(self._run_forecast)
        self.forecast_button.setEnabled(self._can("analytics.view"))
        controls.addWidget(self.forecast_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.forecast_plot = pg.PlotWidget()
        self.forecast_plot.setBackground("w")
        self.forecast_plot.showGrid(x=True, y=True, alpha=0.12)
        self.forecast_plot.setMenuEnabled(False)
        self.forecast_plot.setMouseEnabled(x=False, y=False)
        self.forecast_plot.hideButtons()
        self.forecast_plot.setMinimumHeight(220)
        layout.addWidget(self.forecast_plot, 1)
        self.forecast_text = QPlainTextEdit()
        self.forecast_text.setReadOnly(True)
        layout.addWidget(self.forecast_text, 1)
        return page

    def _build_risk_tab(self) -> QWidget:
        page, table = self._table_tab(
            ["Risk", "Description", "Likelihood", "Impact", "Severity", "Score", "Mitigation"],
            stretch=(1, 6),
        )
        self.risk_table = table
        return page

    def _build_simulation_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(
            muted_label(
                "HYPOTHETICAL SCENARIO — NOT AN ACTUAL BUSINESS RESULT. Simulations read the "
                "real baseline and write nothing to business records."
            )
        )
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Scenario"))
        self.scenario_combo = QComboBox()
        for label, value, _, _ in SCENARIOS:
            self.scenario_combo.addItem(label, value)
        self.scenario_combo.currentIndexChanged.connect(self._scenario_changed)
        controls.addWidget(self.scenario_combo)
        self.scenario_param_label = QLabel("Change %")
        controls.addWidget(self.scenario_param_label)
        self.scenario_param = QLineEdit("10")
        self.scenario_param.setMaximumWidth(80)
        controls.addWidget(self.scenario_param)
        self.simulate_button = primary_button("Run simulation")
        self.simulate_button.clicked.connect(self._run_simulation)
        self.simulate_button.setEnabled(self._can("analytics.manage"))
        controls.addWidget(self.simulate_button)
        controls.addStretch(1)
        layout.addLayout(controls)
        self.simulation_table = DataTable(
            ["Metric", "Baseline", "Simulated", "Change", "Change %"], stretch_columns=(0,)
        )
        layout.addWidget(self.simulation_table, 2)
        self.simulation_text = QPlainTextEdit()
        self.simulation_text.setReadOnly(True)
        layout.addWidget(self.simulation_text, 1)
        return page

    # -- data --------------------------------------------------------------
    def _granularity(self) -> str:
        return self.period_combo.currentData() or "MONTHLY"

    def refresh(self) -> None:
        granularity = self._granularity()
        service = self._context.analytics_service
        self.refresh_button.setEnabled(False)
        self._run_worker(
            lambda: service.analyze(granularity),
            "Analytics",
            self._on_bundle,
            on_failure=self._on_refresh_failed,
        )

    def _on_bundle(self, bundle: Any) -> None:
        self.refresh_button.setEnabled(True)
        self._bundle = bundle
        financial = bundle.financial
        self.card_revenue.set_value(f"{financial.revenue:,.2f}", True)
        self.card_cash.set_value(f"{financial.cash_received:,.2f}", True)
        self.card_expenses.set_value(f"{financial.operating_expenses:,.2f}", True)
        self.card_profit.set_value(
            f"{financial.net_profit:,.2f}" if financial.net_profit is not None else "not reported",
            financial.net_profit is not None,
        )
        self.card_growth.set_value(
            f"{bundle.sales.growth_percent}%"
            if bundle.sales.growth_percent is not None
            else "not measurable",
            bundle.sales.growth_percent is not None,
        )
        self.card_receivables.set_value(f"{financial.outstanding_receivables:,.2f}", True)
        self.quality_label.setText(
            f"{bundle.period.label} · data {bundle.quality.completeness.lower()}"
            + (f" · {len(bundle.quality.issues)} data note(s)" if bundle.quality.issues else "")
        )

        self._fill_executive(bundle)
        self._fill_financial(bundle)
        self._fill_sales(bundle)
        self._fill_customers(bundle)
        self._fill_inventory(bundle)
        self._fill_suppliers(bundle)
        self._fill_risks(bundle)
        self._load_anomalies()

    def _fill_executive(self, bundle: Any) -> None:
        self.kpi_table.set_rows(
            [
                [
                    kpi.kpi_name,
                    f"{kpi.actual:,.2f}" if kpi.actual is not None else "not calculable",
                    kpi.unit,
                    kpi.completeness,
                    kpi.formula,
                ]
                for kpi in bundle.kpis
            ]
        )
        insights = self._context.analytics_engine.generate_business_insights(bundle)
        gaps = self._context.analytics_engine.identify_performance_gaps(bundle)
        self.insights_text.setPlainText(
            "\n\n".join(f"• {line}" for line in insights) or "No insights for this period."
        )
        gap_lines = [f"• {gap['area']}: {gap['gap']}" for gap in gaps]
        gap_lines.extend(f"• Limitation: {item}" for item in bundle.quality.limitations)
        gap_lines.extend(f"• Data note: {issue.message}" for issue in bundle.quality.issues)
        self.gaps_text.setPlainText("\n".join(gap_lines) or "No gaps identified.")

    def _fill_financial(self, bundle: Any) -> None:
        financial = bundle.financial
        rows = [
            ["Revenue (invoiced)", f"{financial.revenue:,.2f}", "completed sales"],
            ["Cash collected", f"{financial.cash_received:,.2f}", "payments received"],
            ["Cost of goods sold", f"{financial.cogs:,.2f}", "quantity × recorded cost price"],
            ["Gross profit", f"{financial.gross_profit:,.2f}", "revenue − COGS"],
            ["Operating expenses", f"{financial.operating_expenses:,.2f}", "recorded expenses"],
            [
                "Net profit",
                f"{financial.net_profit:,.2f}" if financial.net_profit is not None else "not reported",
                "gross profit − operating expenses",
            ],
            ["Cash paid out", f"{financial.cash_paid_out:,.2f}", "expenses and refunds"],
            ["Net cash flow", f"{financial.net_cash_flow:,.2f}", "cash in − cash out"],
            ["Outstanding receivables", f"{financial.outstanding_receivables:,.2f}", "unpaid invoices"],
        ]
        self.financial_table.set_rows(rows)

        rows = []
        for row in financial.expense_categories:
            rows.append([row.label, f"{row.value:,.2f}", row.note or ""])
        for row in financial.receivables_aging:
            rows.append([f"Receivables · {row.label}", f"{row.value:,.2f}", row.note or ""])
        self.expense_table.set_rows(rows)

        self.revenue_plot.clear()
        try:
            trend = self._context.analytics_service.trend_series(6)
        except BizPilotError:
            trend = {"labels": [], "revenue": [], "expenses": []}
        labels = trend.get("labels") or []
        if labels:
            xs = list(range(len(labels)))
            self.revenue_plot.plot(
                xs,
                [float(value) for value in trend["revenue"]],
                pen=pg.mkPen("#2563EB", width=2),
                symbol="o",
                symbolSize=5,
                name="Revenue",
            )
            self.revenue_plot.plot(
                xs,
                [float(value) for value in trend["expenses"]],
                pen=pg.mkPen("#DC2626", width=2),
                symbol="t",
                symbolSize=5,
                name="Expenses",
            )
            self.revenue_plot.getAxis("bottom").setTicks(
                [[(index, label) for index, label in enumerate(labels)]]
            )

    def _fill_sales(self, bundle: Any) -> None:
        sales = bundle.sales
        self.product_table.set_rows(
            [
                [
                    row.product,
                    f"{row.revenue:,.2f}",
                    str(row.quantity),
                    str(row.share_percent),
                    row.classification,
                    row.reason,
                ]
                for row in sales.by_product
            ]
        )
        self.sales_table.set_rows(
            [
                ["Revenue", f"{sales.total_revenue:,.2f}"],
                ["Completed orders", str(sales.order_count)],
                ["Units sold", str(sales.units_sold)],
                ["Average order value", f"{sales.average_order_value:,.2f}"],
                [
                    "Revenue growth",
                    f"{sales.growth_percent}%" if sales.growth_percent is not None else "not measurable",
                ],
                ["Top-5 customer concentration", f"{sales.concentration_top5_percent}%"],
                ["Declining products", str(len(sales.declining_products))],
            ]
        )
        self.category_table.set_rows(
            [[row.label, f"{row.value:,.2f}", row.note or ""] for row in sales.by_category]
        )

    def _fill_customers(self, bundle: Any) -> None:
        customers = bundle.customers
        self.segment_table.set_rows(
            [
                [row.segment, str(row.count), f"{row.revenue:,.2f}", row.rule]
                for row in customers.segments
            ]
        )
        self.customer_table.set_rows(
            [
                ["Total customers", str(customers.total_customers)],
                ["Active", str(customers.active_customers)],
                ["New this period", str(customers.new_customers)],
                ["Repeat customers", str(customers.repeat_customers)],
                [
                    "Repeat rate",
                    f"{customers.repeat_rate_percent}%"
                    if customers.repeat_rate_percent is not None
                    else "not calculable",
                ],
                ["Inactive (>90 days)", str(customers.inactive_customers)],
                ["At risk", str(customers.at_risk_customers)],
                ["Top-5 concentration", f"{customers.concentration_top5_percent}%"],
            ]
        )
        self.cohort_table.set_rows(
            [
                [
                    row["cohort"],
                    str(row["customers"]),
                    str(row["repeat_customers"]),
                    row["retention_percent"],
                    row["revenue"],
                ]
                for row in customers.cohorts
            ]
        )

    def _fill_inventory(self, bundle: Any) -> None:
        inventory = bundle.inventory
        self.demand_table.set_rows(
            [
                [row["product"], str(row["available"]), str(row["sold"]), row["units_per_day"], row["days_of_cover"]]
                for row in inventory.demand
            ]
        )
        self.slow_table.set_rows(
            [
                [row["product"], str(row["available"]), row["value"], row["status"], row["note"]]
                for row in inventory.slow_moving + inventory.non_moving
            ]
        )
        self.inventory_table.set_rows(
            [
                ["SKUs", str(inventory.sku_count)],
                ["Units on hand", str(inventory.units_on_hand)],
                ["Inventory value", f"{inventory.inventory_value:,.2f}"],
                ["Low-stock SKUs", str(inventory.low_stock_count)],
                ["Out of stock", str(inventory.stockout_products)],
                [
                    "Stock turnover",
                    str(inventory.turnover_ratio)
                    if inventory.turnover_ratio is not None
                    else "not calculated",
                ],
                ["Turnover basis", inventory.turnover_basis],
            ]
        )
        self.overstock_table.set_rows(
            [
                [row["product"], str(row["available"]), row["days_of_cover"], row["note"]]
                for row in inventory.overstock
            ]
        )

    def _fill_suppliers(self, bundle: Any) -> None:
        suppliers = bundle.suppliers
        self.supplier_table.set_rows(
            [
                [
                    row["supplier"],
                    str(row["orders"]),
                    str(row["received_orders"]),
                    row["value"],
                    row["average_lead_time_days"],
                    row["on_time_percent"],
                ]
                for row in suppliers.supplier_rows
            ]
        )
        self.price_table.set_rows(
            [
                [
                    row["product"],
                    row["first_unit_cost"],
                    row["latest_unit_cost"],
                    row["change_percent"],
                    str(row["observations"]),
                ]
                for row in suppliers.price_trends
            ]
        )
        self.supplier_metrics.set_rows(
            [
                ["Suppliers", str(suppliers.supplier_count)],
                ["Purchase orders", str(suppliers.purchase_order_count)],
                ["Purchase value", f"{suppliers.purchase_value:,.2f}"],
                ["Goods receipts", str(suppliers.receipt_count)],
                [
                    "On-time delivery",
                    f"{suppliers.on_time_delivery_percent}%"
                    if suppliers.on_time_delivery_percent is not None
                    else "not measurable",
                ],
                [
                    "Average lead time",
                    f"{suppliers.average_lead_time_days} days"
                    if suppliers.average_lead_time_days is not None
                    else "not measurable",
                ],
                ["Delayed orders", str(suppliers.delayed_orders)],
                ["Top-3 concentration", f"{suppliers.top3 if hasattr(suppliers, 'top3') else suppliers.concentration_top3_percent}%"],
            ]
        )

    def _fill_risks(self, bundle: Any) -> None:
        self.risk_table.set_rows(
            [
                [
                    risk.category,
                    risk.description,
                    risk.likelihood,
                    risk.impact,
                    risk.severity,
                    str(risk.score),
                    risk.mitigation,
                ]
                for risk in sorted(bundle.risks, key=lambda item: item.score, reverse=True)
            ]
        )

    # -- anomalies ---------------------------------------------------------
    def _load_anomalies(self) -> None:
        service = self._context.analytics_service
        try:
            rows = service.list_anomalies(limit=200)
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self._anomalies = {row["anomaly_id"]: row for row in rows}
        self.anomaly_table.set_rows(
            [
                [
                    row["category"],
                    row["anomaly_type"].replace("_", " ").title(),
                    row["affected_record"],
                    row["detection_method"],
                    row["observed_value"] or "—",
                    row["expected_value"] or "—",
                    row["severity"],
                    row["review_status"],
                ]
                for row in rows
            ],
            row_ids=[row["anomaly_id"] for row in rows],
        )

    def _show_anomaly_detail(self) -> None:
        row = self.anomaly_table.table.currentRow()
        if row < 0:
            return
        item = self.anomaly_table.table.item(row, 0)
        anomaly = self._anomalies.get(str(item.data(Qt.UserRole))) if item else None
        if anomaly is None:
            return
        lines = [
            f"{anomaly['anomaly_type']} · {anomaly['severity']}",
            f"Record: {anomaly['affected_record']}",
            f"Method: {anomaly['detection_method']}",
            f"Observed: {anomaly['observed_value']}   Expected: {anomaly['expected_value']}",
            f"Detected: {format_datetime(anomaly['detected_at'])}",
            f"Review status: {anomaly['review_status']}",
            "",
            anomaly["explanation"],
            "",
            "Evidence:",
            *[f"  {key}: {value}" for key, value in (anomaly["evidence"] or {}).items()],
        ]
        self.anomaly_detail.setPlainText("\n".join(lines))

    def _review_anomaly(self, decision: str) -> None:
        row = self.anomaly_table.table.currentRow()
        if row < 0:
            show_info(self, "Select an anomaly first.")
            return
        item = self.anomaly_table.table.item(row, 0)
        anomaly_id = str(item.data(Qt.UserRole)) if item else ""
        note = self.anomaly_note.text().strip() or None
        service = self._context.analytics_service
        self._run_worker(
            lambda: service.review_anomaly(anomaly_id, decision=decision, note=note),
            "Review",
            lambda _: (self._load_anomalies(), show_info(self, f"Anomaly {decision.lower()}")),
        )

    # -- forecast ----------------------------------------------------------
    def _run_forecast(self) -> None:
        target = self.forecast_target.currentData() or "SALES"
        try:
            horizon = int(self.forecast_horizon.text().strip() or "3")
        except ValueError:
            show_info(self, "The horizon must be a number of months.")
            return
        service = self._context.analytics_service
        self.forecast_button.setEnabled(False)
        self._run_worker(
            lambda: service.forecast(target, horizon=horizon),
            "Forecast",
            self._on_forecast,
        )

    def _on_forecast(self, outcome: Any) -> None:
        self.forecast_button.setEnabled(True)
        self.forecast_plot.clear()
        if outcome.status != "COMPLETED":
            self.forecast_text.setPlainText(
                f"INSUFFICIENT_HISTORICAL_DATA\n\n{outcome.insufficient_reason}"
            )
            return
        actual = outcome.actuals
        forecast = outcome.forecast
        xs_actual = list(range(len(actual)))
        self.forecast_plot.plot(
            xs_actual,
            [float(point.value) for point in actual],
            pen=pg.mkPen("#2563EB", width=2),
            name="Actual",
        )
        offset = len(actual) - 1
        xs_forecast = [offset + index + 1 for index in range(len(forecast))]
        self.forecast_plot.plot(
            xs_forecast,
            [float(point.value) for point in forecast],
            pen=pg.mkPen("#7C3AED", width=2, style=Qt.DashLine),
            symbol="t",
            symbolSize=6,
            name="Forecast",
        )
        labels = [(index, point.label) for index, point in enumerate(actual)]
        labels += [
            (offset + index + 1, point.label) for index, point in enumerate(forecast)
        ]
        self.forecast_plot.getAxis("bottom").setTicks([labels])

        metrics = outcome.metrics
        lines = [
            f"Target: {outcome.metric}",
            f"Status: {outcome.status}   Method: {outcome.method} ({outcome.method_note})",
            f"Observations: {outcome.data_points}   Horizon: {outcome.horizon} month(s)",
            f"Train: {outcome.train_period}",
            f"Validation: {outcome.validation_period}",
            "",
            f"Measured error on validation: MAE {metrics.mae} · RMSE {metrics.rmse} · "
            f"MAPE {metrics.mape if metrics.mape is not None else 'not applicable'} · "
            f"sMAPE {metrics.smape} · bias {metrics.bias}",
            f"Naive baseline MAE: {outcome.baseline_metrics.mae if outcome.baseline_metrics else '—'}",
            "",
            "Forecast (estimates, not actual results):",
            *[
                f"  {point.label}: {point.value:,.2f}"
                + (f" (range {point.lower:,.2f} – {point.upper:,.2f})" if point.lower is not None else "")
                for point in forecast
            ],
            "",
            "Assumptions:",
            *[f"  • {item}" for item in outcome.assumptions],
            "Limitations:",
            *[f"  • {item}" for item in outcome.limitations],
        ]
        self.forecast_text.setPlainText("\n".join(lines))

    # -- simulation --------------------------------------------------------
    def _scenario_changed(self) -> None:
        scenario = self.scenario_combo.currentData()
        entry = next((row for row in SCENARIOS if row[1] == scenario), None)
        if entry is None:
            return
        labels = {"percent": "Change %", "count": "Employees", "units": "Units"}
        self.scenario_param_label.setText(labels.get(entry[2], "Value"))
        self.scenario_param.setText(entry[3])

    def _run_simulation(self) -> None:
        scenario = self.scenario_combo.currentData() or "SALES_DECLINE"
        entry = next((row for row in SCENARIOS if row[1] == scenario), None)
        key = entry[2] if entry else "percent"
        try:
            value = float(self.scenario_param.text().strip() or "0")
        except ValueError:
            show_info(self, "The scenario value must be a number.")
            return
        parameters = {key: value}
        service = self._context.analytics_service
        self.simulate_button.setEnabled(False)
        self._run_worker(
            lambda: service.simulate(scenario, parameters=parameters),
            "Simulation",
            self._on_simulation,
        )

    def _on_simulation(self, outcome: Any) -> None:
        self.simulate_button.setEnabled(True)
        self.simulation_table.set_rows(
            [
                [
                    line.metric,
                    f"{line.baseline:,.2f}" if line.baseline is not None else "—",
                    f"{line.simulated:,.2f}" if line.simulated is not None else "—",
                    f"{line.delta:,.2f}" if line.delta is not None else "—",
                    f"{line.delta_percent}%" if line.delta_percent is not None else "—",
                ]
                for line in outcome.lines
            ]
        )
        lines = [
            outcome.label,
            "",
            outcome.narrative,
            "",
            "Assumptions:",
            *[f"  • {item}" for item in outcome.assumptions],
            "Limitations:",
            *[f"  • {item}" for item in outcome.limitations],
        ]
        self.simulation_text.setPlainText("\n".join(lines))

    # -- workers -----------------------------------------------------------
    def _on_refresh_failed(self, message: str) -> None:
        """Show the reason inline instead of a blocking dialog."""
        self.refresh_button.setEnabled(True)
        self.quality_label.setText(f"Analytics unavailable: {message}")
        self.insights_text.setPlainText(
            f"Analytics could not be calculated.\n\n{message}\n\n"
            "Analytics aggregates the finance, sales, customer, inventory and supplier "
            "modules, so it needs read access to each of them."
        )

    def _run_worker(self, callable_, label: str, on_success, on_failure=None) -> None:
        worker = ActionWorker(callable_, label)
        worker.finished_ok.connect(on_success)
        if on_failure is not None:
            worker.failed.connect(on_failure)
        else:
            worker.failed.connect(lambda message: show_error(self, BizPilotError(message)))
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def wait_for_idle(self, timeout_ms: int = 120000) -> bool:
        """Wait for running background workers (used by tests and shutdown)."""
        from PySide6.QtWidgets import QApplication

        idle = True
        for worker in list(self._workers):
            try:
                if not worker.wait(timeout_ms):
                    idle = False
            except RuntimeError:
                continue
            QApplication.processEvents()
        QApplication.processEvents()
        return idle

    def shutdown(self) -> None:
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(5000)
            except RuntimeError:
                pass
