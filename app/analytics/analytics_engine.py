"""The Business Analytics Engine: one entry point for every analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.analytics.anomaly.anomaly_detection import BusinessAnomalyDetectionEngine
from app.analytics.customers.customer_analytics import AdvancedCustomerAnalytics
from app.analytics.data_collector import BusinessDataCollector, BusinessDataset
from app.analytics.data_validator import AnalyticsDataValidator, clean_dataset
from app.analytics.dataset_builder import AnalyticsDatasetBuilder
from app.analytics.finance.financial_analytics import AdvancedFinancialAnalytics
from app.analytics.forecasting.forecasting_engine import PredictiveAnalyticsEngine
from app.analytics.inventory.inventory_analytics import AdvancedInventoryAnalytics
from app.analytics.kpi.kpi_engine import BusinessKPIEngine
from app.analytics.periods import AnalyticsPeriod, previous_period, resolve_period
from app.analytics.risk.business_risk_engine import BusinessRiskAssessmentEngine
from app.analytics.sales.sales_analytics import AdvancedSalesAnalytics
from app.analytics.schemas import (
    AnomalyFinding,
    CustomerAnalytics,
    DataQuality,
    FinancialAnalytics,
    InventoryAnalytics,
    KPIItem,
    RiskItem,
    SalesAnalytics,
    SupplierAnalytics,
    money,
)
from app.analytics.simulation.business_simulation import BusinessSimulationEngine
from app.analytics.suppliers.supplier_analytics import AdvancedSupplierAnalytics
from app.core.logging_config import get_logger

logger = get_logger("analytics.engine")

ZERO = Decimal("0.00")


@dataclass
class AnalyticsBundle:
    """Everything one period's analysis produced."""

    period: AnalyticsPeriod
    comparison: AnalyticsPeriod | None
    quality: DataQuality
    financial: FinancialAnalytics
    sales: SalesAnalytics
    customers: CustomerAnalytics
    inventory: InventoryAnalytics
    suppliers: SupplierAnalytics
    anomalies: list[AnomalyFinding] = field(default_factory=list)
    risks: list[RiskItem] = field(default_factory=list)
    kpis: list[KPIItem] = field(default_factory=list)
    dataset: BusinessDataset | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period.label,
            "granularity": self.period.granularity,
            "period_start": self.period.start.isoformat(),
            "period_end": self.period.end.isoformat(),
            "comparison_period": self.comparison.label if self.comparison else None,
            "quality": self.quality.model_dump(mode="json"),
            "financial": self.financial.model_dump(mode="json"),
            "sales": self.sales.model_dump(mode="json"),
            "customers": self.customers.model_dump(mode="json"),
            "inventory": self.inventory.model_dump(mode="json"),
            "suppliers": self.suppliers.model_dump(mode="json"),
            "anomalies": [item.model_dump(mode="json") for item in self.anomalies],
            "risks": [item.model_dump(mode="json") for item in self.risks],
            "kpis": [item.model_dump(mode="json") for item in self.kpis],
        }


class BusinessAnalyticsEngine:
    """Collects, validates and analyses real business records."""

    def __init__(self, services: Any) -> None:
        self._services = services
        self.collector = BusinessDataCollector(services)
        self.validator = AnalyticsDataValidator()
        self.builder = AnalyticsDatasetBuilder()
        self.financial = AdvancedFinancialAnalytics(self.builder)
        self.sales = AdvancedSalesAnalytics(self.builder)
        self.customers = AdvancedCustomerAnalytics(self.builder)
        self.inventory = AdvancedInventoryAnalytics()
        self.suppliers = AdvancedSupplierAnalytics()
        self.anomalies = BusinessAnomalyDetectionEngine()
        self.forecasting = PredictiveAnalyticsEngine(self.collector)
        self.risk = BusinessRiskAssessmentEngine()
        self.simulation = BusinessSimulationEngine()
        self.kpis = BusinessKPIEngine()

    # -- data --------------------------------------------------------------
    def collect_business_data(
        self, period: AnalyticsPeriod, *, with_comparison: bool = True
    ) -> BusinessDataset:
        comparison = previous_period(period) if with_comparison else None
        return self.collector.collect_business_data(period, comparison=comparison)

    def validate_analytics_data(self, dataset: BusinessDataset) -> DataQuality:
        return self.validator.validate_analytics_data(dataset)

    def prepare_analytics_dataset(self, dataset: BusinessDataset) -> dict[str, Any]:
        return self.builder.prepare_analytics_dataset(dataset)

    # -- analysis ----------------------------------------------------------
    def analyze_business_performance(
        self,
        granularity: str = "MONTHLY",
        *,
        reference: datetime | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        include_anomalies: bool = True,
        include_risks: bool = True,
        include_kpis: bool = True,
    ) -> AnalyticsBundle:
        period = resolve_period(granularity, reference=reference, start=start, end=end)
        dataset = self.collect_business_data(period)
        clean_dataset(dataset)
        quality = self.validate_analytics_data(dataset)

        financial = self.financial.analyze(dataset, quality=quality)
        sales = self.sales.analyze(dataset, quality=quality)
        customers = self.customers.analyze(dataset, quality=quality)
        inventory = self.inventory.analyze(dataset, quality=quality)
        suppliers = self.suppliers.analyze(dataset, quality=quality)

        anomalies = self.anomalies.detect(dataset) if include_anomalies else []
        risks = (
            self.risk.assess(
                financial=financial,
                sales=sales,
                customers=customers,
                inventory=inventory,
                suppliers=suppliers,
            )
            if include_risks
            else []
        )
        kpis = (
            self.kpis.calculate_business_kpis(
                financial=financial,
                sales=sales,
                customers=customers,
                inventory=inventory,
                suppliers=suppliers,
                quality=quality,
            )
            if include_kpis
            else []
        )
        return AnalyticsBundle(
            period=period,
            comparison=dataset.comparison,
            quality=quality,
            financial=financial,
            sales=sales,
            customers=customers,
            inventory=inventory,
            suppliers=suppliers,
            anomalies=anomalies,
            risks=risks,
            kpis=kpis,
            dataset=dataset,
        )

    def compare_reporting_periods(self, granularity: str = "MONTHLY", **kwargs) -> dict[str, Any]:
        bundle = self.analyze_business_performance(granularity, **kwargs)
        return {
            "period": bundle.period.label,
            "comparison_period": bundle.comparison.label if bundle.comparison else None,
            "financial": [row.model_dump(mode="json") for row in bundle.financial.comparisons],
            "growth": {key: str(value) if value is not None else None
                       for key, value in self.financial.calculate_growth_metrics(
                           bundle.dataset
                       ).items()},
        }

    def calculate_growth_metrics(self, granularity: str = "MONTHLY", **kwargs) -> dict[str, Any]:
        bundle = self.analyze_business_performance(granularity, **kwargs)
        return {
            key: str(value) if value is not None else None
            for key, value in self.financial.calculate_growth_metrics(bundle.dataset).items()
        }

    def calculate_business_kpis(self, granularity: str = "MONTHLY", **kwargs) -> list[KPIItem]:
        bundle = self.analyze_business_performance(granularity, **kwargs)
        return bundle.kpis

    # -- narrative ---------------------------------------------------------
    def generate_business_insights(self, bundle: AnalyticsBundle) -> list[str]:
        """Plain-language findings, each traceable to the figures above it."""
        insights: list[str] = []
        financial = bundle.financial
        sales = bundle.sales
        insights.append(
            f"Revenue for {bundle.period.label} was {financial.revenue:,.2f} from "
            f"{sales.order_count} completed order(s); cash actually collected was "
            f"{financial.cash_received:,.2f}."
        )
        if sales.growth_percent is not None:
            direction = "up" if sales.growth_percent >= 0 else "down"
            insights.append(
                f"Revenue is {direction} {abs(sales.growth_percent)}% versus the previous period."
            )
        else:
            insights.append("There is no previous period with revenue, so growth cannot be measured.")
        if financial.net_profit is not None:
            insights.append(
                f"Net profit is {financial.net_profit:,.2f} "
                f"({financial.net_margin_percent}% margin) after "
                f"{financial.operating_expenses:,.2f} of operating expenses."
            )
        else:
            insights.append(
                "Net profit is not reported: cost of goods sold is incomplete for this period."
            )
        if financial.outstanding_receivables > ZERO:
            insights.append(
                f"{financial.outstanding_receivables:,.2f} remains outstanding across open invoices."
            )
        if bundle.customers.inactive_customers:
            insights.append(
                f"{bundle.customers.inactive_customers} customer(s) have not purchased in over "
                "90 days and "
                f"{bundle.customers.at_risk_customers} more are at risk."
            )
        if bundle.inventory.low_stock_count:
            insights.append(
                f"{bundle.inventory.low_stock_count} SKU(s) are at or below minimum stock."
            )
        if bundle.anomalies:
            by_severity: dict[str, int] = {}
            for finding in bundle.anomalies:
                by_severity[finding.severity] = by_severity.get(finding.severity, 0) + 1
            summary = ", ".join(f"{count} {severity}" for severity, count in sorted(by_severity.items()))
            insights.append(f"{len(bundle.anomalies)} anomaly review item(s) were raised ({summary}).")
        if bundle.risks:
            worst = max(bundle.risks, key=lambda risk: risk.score)
            insights.append(
                f"The highest-scoring business risk is {worst.category} "
                f"(score {worst.score}, {worst.severity})."
            )
        return insights

    def identify_performance_gaps(self, bundle: AnalyticsBundle) -> list[dict[str, Any]]:
        gaps: list[dict[str, Any]] = []
        if bundle.financial.outstanding_receivables > ZERO:
            gaps.append(
                {
                    "area": "Cash collection",
                    "gap": f"{bundle.financial.outstanding_receivables:,.2f} invoiced but not collected",
                    "evidence": "sales_invoices with an outstanding balance",
                }
            )
        if bundle.inventory.low_stock_count:
            gaps.append(
                {
                    "area": "Stock availability",
                    "gap": f"{bundle.inventory.low_stock_count} SKU(s) at or below minimum stock",
                    "evidence": "inventory_stock",
                }
            )
        if bundle.customers.inactive_customers:
            gaps.append(
                {
                    "area": "Customer retention",
                    "gap": f"{bundle.customers.inactive_customers} inactive customer(s)",
                    "evidence": "customers.last_purchase_at",
                }
            )
        for product in bundle.sales.declining_products[:5]:
            gaps.append(
                {
                    "area": "Product performance",
                    "gap": f"{product.product} is declining ({product.reason})",
                    "evidence": "sales_order_lines",
                }
            )
        if bundle.suppliers.on_time_delivery_percent is None:
            gaps.append(
                {
                    "area": "Supplier measurement",
                    "gap": "On-time delivery cannot be measured: expected delivery dates are missing",
                    "evidence": "purchase_orders.expected_delivery_date",
                }
            )
        if bundle.inventory.turnover_ratio is None:
            gaps.append(
                {
                    "area": "Inventory measurement",
                    "gap": bundle.inventory.turnover_basis,
                    "evidence": "finance cogs + inventory valuation",
                }
            )
        return gaps

    def generate_analytics_report(self, report_type: str, granularity: str = "MONTHLY", **kwargs):
        from app.analytics.reports.analytics_report_service import AnalyticsReportService

        bundle = self.analyze_business_performance(granularity, **kwargs)
        service = AnalyticsReportService(self._services)
        return service.build_report(report_type, bundle)
