"""Analytics report generation (PDF and CSV) with provenance and limitations."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.analytics.analytics_engine import AnalyticsBundle
from app.analytics.schemas import money
from app.schemas.finance_schema import ReportTable
from app.utils.date_utils import format_datetime, utcnow

ZERO = Decimal("0.00")

REPORT_TYPES = (
    "EXECUTIVE_PERFORMANCE",
    "FINANCIAL_ANALYTICS",
    "SALES_PERFORMANCE",
    "CUSTOMER_ANALYTICS",
    "INVENTORY_HEALTH",
    "SUPPLIER_PERFORMANCE",
    "ANOMALY_INVESTIGATION",
    "FORECAST",
    "BUSINESS_RISK",
    "SIMULATION",
)

REPORT_TITLES = {
    "EXECUTIVE_PERFORMANCE": "Executive Business Performance Report",
    "FINANCIAL_ANALYTICS": "Financial Analytics Report",
    "SALES_PERFORMANCE": "Sales Performance Report",
    "CUSTOMER_ANALYTICS": "Customer Analytics Report",
    "INVENTORY_HEALTH": "Inventory Health Report",
    "SUPPLIER_PERFORMANCE": "Supplier Performance Report",
    "ANOMALY_INVESTIGATION": "Anomaly Investigation Report",
    "FORECAST": "Forecast Report",
    "BUSINESS_RISK": "Business Risk Report",
    "SIMULATION": "What-if Simulation Report",
}


class AnalyticsReportService:
    """Builds report tables from a real analytics bundle."""

    def __init__(self, services: Any) -> None:
        self._services = services

    def build_report(self, report_type: str, bundle: AnalyticsBundle, *, extra: dict | None = None) -> ReportTable:
        report_type = (report_type or "EXECUTIVE_PERFORMANCE").upper()
        if report_type not in REPORT_TYPES:
            raise ValueError(
                f"Unknown report type '{report_type}'. Supported: {', '.join(REPORT_TYPES)}"
            )
        builder = {
            "EXECUTIVE_PERFORMANCE": self._executive,
            "FINANCIAL_ANALYTICS": self._financial,
            "SALES_PERFORMANCE": self._sales,
            "CUSTOMER_ANALYTICS": self._customers,
            "INVENTORY_HEALTH": self._inventory,
            "SUPPLIER_PERFORMANCE": self._suppliers,
            "ANOMALY_INVESTIGATION": self._anomalies,
            "FORECAST": self._forecast,
            "BUSINESS_RISK": self._risk,
            "SIMULATION": self._simulation,
        }[report_type]
        table = builder(bundle, extra or {})
        table.generated_at = utcnow()
        return table

    # -- sections ----------------------------------------------------------
    def _header(self, title: str, bundle: AnalyticsBundle) -> tuple[list[str], list[str]]:
        business = getattr(self._services, "business_settings", None)
        name = getattr(business, "business_name", "Business") if business else "Business"
        subtitle = (
            f"{name} · {bundle.period.label} "
            f"({bundle.period.local_start:%d %b %Y} – {bundle.period.local_end:%d %b %Y})"
        )
        return [title, subtitle], [name]

    def _basis(self, bundle: AnalyticsBundle, extra: str = "") -> str:
        lines = [
            "All figures come from records in this workspace for the stated period.",
            "Revenue is invoiced value of completed sales; cash is money actually received.",
            "Cancelled orders and reversed expenses are excluded.",
        ]
        if bundle.quality.limitations:
            lines.extend(f"Limitation: {item}" for item in bundle.quality.limitations)
        if extra:
            lines.append(extra)
        return " ".join(lines)

    def _executive(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        financial, sales, customers = bundle.financial, bundle.sales, bundle.customers
        rows = [
            ["Revenue", f"{financial.revenue:,.2f}"],
            ["Cash collected", f"{financial.cash_received:,.2f}"],
            ["Operating expenses", f"{financial.operating_expenses:,.2f}"],
            [
                "Net profit",
                f"{financial.net_profit:,.2f}" if financial.net_profit is not None else "not reported",
            ],
            ["Outstanding receivables", f"{financial.outstanding_receivables:,.2f}"],
            ["Completed orders", str(sales.order_count)],
            [
                "Revenue growth",
                f"{sales.growth_percent}%" if sales.growth_percent is not None else "not measurable",
            ],
            ["New customers", str(customers.new_customers)],
            ["Inactive customers", str(customers.inactive_customers)],
            ["Low-stock SKUs", str(bundle.inventory.low_stock_count)],
            ["Anomaly review items", str(len(bundle.anomalies))],
            [
                "Highest risk",
                f"{max(bundle.risks, key=lambda r: r.score).category} "
                f"({max(bundle.risks, key=lambda r: r.score).severity})"
                if bundle.risks
                else "none assessed",
            ],
        ]
        meta, _ = self._header("Executive Business Performance Report", bundle)
        return ReportTable(
            title=meta[0],
            subtitle=meta[1],
            headers=["Metric", "Value"],
            rows=rows,
            basis=self._basis(bundle),
        )

    def _financial(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        financial = bundle.financial
        rows = [
            ["Revenue", f"{financial.revenue:,.2f}"],
            ["Cost of goods sold", f"{financial.cogs:,.2f}"],
            ["Gross profit", f"{financial.gross_profit:,.2f}"],
            ["Gross margin", f"{financial.gross_margin_percent}%"
             if financial.gross_margin_percent is not None else "not calculable"],
            ["Operating expenses", f"{financial.operating_expenses:,.2f}"],
            ["Net profit", f"{financial.net_profit:,.2f}" if financial.net_profit is not None else "not reported"],
            ["Cash received", f"{financial.cash_received:,.2f}"],
            ["Cash paid out", f"{financial.cash_paid_out:,.2f}"],
            ["Net cash flow", f"{financial.net_cash_flow:,.2f}"],
            ["Outstanding receivables", f"{financial.outstanding_receivables:,.2f}"],
        ]
        for row in financial.expense_categories:
            rows.append([f"Expense · {row.label}", f"{row.value:,.2f}"])
        for row in financial.receivables_aging:
            rows.append([f"Receivables · {row.label}", f"{row.value:,.2f}"])
        meta, _ = self._header("Financial Analytics Report", bundle)
        return ReportTable(
            title=meta[0],
            subtitle=meta[1],
            headers=["Metric", "Value"],
            rows=rows,
            basis=self._basis(bundle, " ".join(financial.profit_components)),
        )

    def _sales(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        sales = bundle.sales
        rows = [
            ["Total revenue", f"{sales.total_revenue:,.2f}"],
            ["Completed orders", str(sales.order_count)],
            ["Units sold", str(sales.units_sold)],
            ["Average order value", f"{sales.average_order_value:,.2f}"],
            ["Revenue growth", f"{sales.growth_percent}%" if sales.growth_percent is not None else "not measurable"],
            ["Top-5 customer concentration", f"{sales.concentration_top5_percent}%"],
        ]
        for product in sales.by_product[:10]:
            rows.append(
                [f"Product · {product.product}", f"{product.revenue:,.2f} ({product.quantity} units, {product.classification})"]
            )
        for category in sales.by_category[:8]:
            rows.append([f"Category · {category.label}", f"{category.value:,.2f}"])
        meta, _ = self._header("Sales Performance Report", bundle)
        return ReportTable(
            title=meta[0], subtitle=meta[1], headers=["Metric", "Value"], rows=rows,
            basis=self._basis(bundle),
        )

    def _customers(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        customers = bundle.customers
        rows = [
            ["Total customers", str(customers.total_customers)],
            ["Active customers", str(customers.active_customers)],
            ["New customers", str(customers.new_customers)],
            ["Repeat customers", str(customers.repeat_customers)],
            ["Repeat rate", f"{customers.repeat_rate_percent}%" if customers.repeat_rate_percent is not None else "not calculable"],
            ["Inactive customers", str(customers.inactive_customers)],
            ["At-risk customers", str(customers.at_risk_customers)],
            ["Average order value", f"{customers.average_order_value:,.2f}"],
            ["Top-5 concentration", f"{customers.concentration_top5_percent}%"],
        ]
        for segment in customers.segments:
            rows.append([f"Segment · {segment.segment}", f"{segment.count} customer(s), {segment.revenue:,.2f}"])
        for cohort in customers.cohorts[:8]:
            rows.append(
                [f"Cohort · {cohort['cohort']}", f"{cohort['customers']} customer(s), retention {cohort['retention_percent']}%"]
            )
        meta, _ = self._header("Customer Analytics Report", bundle)
        return ReportTable(
            title=meta[0], subtitle=meta[1], headers=["Metric", "Value"], rows=rows,
            basis=self._basis(bundle, "Historical customer value is not a guaranteed future value."),
        )

    def _inventory(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        inventory = bundle.inventory
        rows = [
            ["SKUs", str(inventory.sku_count)],
            ["Units on hand", str(inventory.units_on_hand)],
            ["Inventory value", f"{inventory.inventory_value:,.2f}"],
            ["Low-stock SKUs", str(inventory.low_stock_count)],
            ["Out of stock", str(inventory.stockout_products)],
            ["Stock turnover", str(inventory.turnover_ratio) if inventory.turnover_ratio is not None else "not calculated"],
            ["Turnover basis", inventory.turnover_basis],
            ["Slow-moving SKUs", str(len(inventory.slow_moving))],
            ["Non-moving SKUs", str(len(inventory.non_moving))],
            ["Overstocked SKUs", str(len(inventory.overstock))],
        ]
        for row in inventory.demand[:10]:
            rows.append([f"Demand · {row['product']}", f"{row['sold']} units, {row['units_per_day']}/day, cover {row['days_of_cover']}"])
        meta, _ = self._header("Inventory Health Report", bundle)
        return ReportTable(
            title=meta[0], subtitle=meta[1], headers=["Metric", "Value"], rows=rows,
            basis=self._basis(bundle, "Slow-moving stock is not the same as obsolete stock."),
        )

    def _suppliers(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        suppliers = bundle.suppliers
        rows = [
            ["Suppliers", str(suppliers.supplier_count)],
            ["Purchase orders", str(suppliers.purchase_order_count)],
            ["Purchase value", f"{suppliers.purchase_value:,.2f}"],
            ["Goods receipts", str(suppliers.receipt_count)],
            [
                "On-time delivery",
                f"{suppliers.on_time_delivery_percent}%"
                if suppliers.on_time_delivery_percent is not None
                else "not measurable (no expected dates)",
            ],
            [
                "Average lead time",
                f"{suppliers.average_lead_time_days} days"
                if suppliers.average_lead_time_days is not None
                else "not measurable",
            ],
            ["Delayed orders", str(suppliers.delayed_orders)],
            ["Top-3 concentration", f"{suppliers.concentration_top3_percent}%"],
        ]
        for row in suppliers.supplier_rows[:10]:
            rows.append([f"Supplier · {row['supplier']}", f"{row['orders']} order(s), {row['value']}, lead {row['average_lead_time_days']}"])
        meta, _ = self._header("Supplier Performance Report", bundle)
        return ReportTable(
            title=meta[0], subtitle=meta[1], headers=["Metric", "Value"], rows=rows,
            basis=self._basis(bundle),
        )

    def _anomalies(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        rows = [
            [
                finding.category,
                finding.anomaly_type,
                finding.affected_record,
                finding.detection_method,
                f"{finding.observed_value:,.2f}" if finding.observed_value is not None else "—",
                f"{finding.expected_value:,.2f}" if finding.expected_value is not None else "—",
                finding.severity,
            ]
            for finding in bundle.anomalies
        ]
        meta, _ = self._header("Anomaly Investigation Report", bundle)
        return ReportTable(
            title=meta[0],
            subtitle=meta[1],
            headers=["Category", "Type", "Record", "Method", "Observed", "Expected", "Severity"],
            rows=rows or [["—", "No anomalies detected", "—", "—", "—", "—", "—"]],
            basis=self._basis(
                bundle,
                "Anomalies are review items. They are never labelled fraud and never modify "
                "business records.",
            ),
        )

    def _forecast(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        rows: list[list[str]] = []
        outcomes = extra.get("forecasts") or []
        for outcome in outcomes:
            if outcome.status != "COMPLETED":
                rows.append([outcome.target, "INSUFFICIENT_HISTORICAL_DATA", outcome.insufficient_reason or "", "—", "—"])
                continue
            for point in outcome.forecast:
                rows.append(
                    [
                        outcome.target,
                        point.label,
                        f"{point.value:,.2f}",
                        f"{point.lower:,.2f} – {point.upper:,.2f}"
                        if point.lower is not None
                        else "—",
                        outcome.method,
                    ]
                )
            metrics = outcome.metrics
            rows.append(
                [
                    f"{outcome.target} validation",
                    outcome.validation_period,
                    f"MAE {metrics.mae}",
                    f"RMSE {metrics.rmse}",
                    outcome.method,
                ]
            )
        meta, _ = self._header("Forecast Report", bundle)
        return ReportTable(
            title=meta[0],
            subtitle=meta[1],
            headers=["Target", "Period", "Forecast value", "Interval", "Method"],
            rows=rows or [["—", "No forecast requested", "—", "—", "—"]],
            basis=self._basis(
                bundle,
                "Forecast values are estimates, validated chronologically; they are never "
                "actual results.",
            ),
        )

    def _risk(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        rows = [
            [
                risk.category,
                risk.description,
                risk.likelihood,
                risk.impact,
                risk.severity,
                str(risk.score),
                risk.mitigation,
            ]
            for risk in bundle.risks
        ]
        meta, _ = self._header("Business Risk Report", bundle)
        return ReportTable(
            title=meta[0],
            subtitle=meta[1],
            headers=["Risk", "Description", "Likelihood", "Impact", "Severity", "Score", "Mitigation"],
            rows=rows or [["—", "No risks assessed", "—", "—", "—", "—", "—"]],
            basis=self._basis(
                bundle,
                "Risk scores are transparent likelihood × impact weights, not statistical "
                "probabilities.",
            ),
        )

    def _simulation(self, bundle: AnalyticsBundle, extra: dict) -> ReportTable:
        rows: list[list[str]] = []
        simulation = extra.get("simulation")
        if simulation is not None:
            for line in simulation.lines:
                rows.append(
                    [
                        line.metric,
                        f"{line.baseline:,.2f}" if line.baseline is not None else "—",
                        f"{line.simulated:,.2f}" if line.simulated is not None else "—",
                        f"{line.delta:,.2f}" if line.delta is not None else "—",
                        f"{line.delta_percent}%" if line.delta_percent is not None else "—",
                    ]
                )
        meta, _ = self._header("What-if Simulation Report", bundle)
        return ReportTable(
            title=meta[0],
            subtitle=f"{meta[1]} · HYPOTHETICAL SCENARIO — NOT AN ACTUAL BUSINESS RESULT",
            headers=["Metric", "Baseline", "Simulated", "Change", "Change %"],
            rows=rows or [["—", "No simulation run", "—", "—", "—"]],
            basis=self._basis(
                bundle,
                "Simulations read real baselines and write nothing to business records. "
                "Every assumption is listed with the scenario.",
            ),
        )

    # -- exports -----------------------------------------------------------
    def export_pdf(self, table: ReportTable, filename: str):
        return self._services.export_service.write_pdf_report(table, filename)

    def export_csv(self, table: ReportTable, filename: str):
        return self._services.export_service.write_report_csv(table, filename)
