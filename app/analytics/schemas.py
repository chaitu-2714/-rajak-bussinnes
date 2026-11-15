"""Shared result contracts for the analytics package."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ZERO = Decimal("0.00")


def money(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


class AnalyticsPeriod(BaseModel):
    """A resolved reporting period in local calendar terms."""

    model_config = ConfigDict(frozen=True)

    label: str
    granularity: str
    start: datetime
    end: datetime
    local_start: datetime
    local_end: datetime
    days: int


class DataIssue(BaseModel):
    """One data-quality problem found while preparing analytics."""

    code: str
    severity: str = "INFO"
    message: str
    affected: str | None = None
    count: int = 0


class MetricRow(BaseModel):
    """A single labelled figure with its provenance."""

    label: str
    value: Decimal = ZERO
    unit: str = "₹"
    source: str = ""
    note: str | None = None


class SeriesPoint(BaseModel):
    label: str
    period_start: datetime
    value: Decimal = ZERO
    is_gap: bool = False


class DataQuality(BaseModel):
    completeness: str = "COMPLETE"  # COMPLETE | PARTIAL | INSUFFICIENT
    issues: list[DataIssue] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @property
    def has_blocking_issues(self) -> bool:
        return any(issue.severity == "BLOCKING" for issue in self.issues)


class FinancialAnalytics(BaseModel):
    period_label: str
    revenue: Decimal = ZERO
    cogs: Decimal = ZERO
    gross_profit: Decimal = ZERO
    operating_expenses: Decimal = ZERO
    net_profit: Decimal | None = None
    gross_margin_percent: Decimal | None = None
    net_margin_percent: Decimal | None = None
    cash_received: Decimal = ZERO
    cash_paid_out: Decimal = ZERO
    net_cash_flow: Decimal = ZERO
    outstanding_receivables: Decimal = ZERO
    outstanding_payables: Decimal | None = None
    refunds_paid: Decimal = ZERO
    profit_components: list[str] = Field(default_factory=list)
    receivables_aging: list[MetricRow] = Field(default_factory=list)
    expense_categories: list[MetricRow] = Field(default_factory=list)
    revenue_series: list[SeriesPoint] = Field(default_factory=list)
    expense_series: list[SeriesPoint] = Field(default_factory=list)
    cash_in_series: list[SeriesPoint] = Field(default_factory=list)
    cash_out_series: list[SeriesPoint] = Field(default_factory=list)
    comparisons: list[MetricRow] = Field(default_factory=list)
    quality: DataQuality = Field(default_factory=DataQuality)


class ProductPerformance(BaseModel):
    product_id: int
    product: str
    sku: str
    revenue: Decimal = ZERO
    quantity: int = 0
    share_percent: Decimal = ZERO
    classification: str = "STABLE"
    reason: str = ""
    cost_available: bool = True


class SalesAnalytics(BaseModel):
    period_label: str
    total_revenue: Decimal = ZERO
    order_count: int = 0
    units_sold: int = 0
    average_order_value: Decimal = ZERO
    growth_percent: Decimal | None = None
    series: list[SeriesPoint] = Field(default_factory=list)
    by_product: list[ProductPerformance] = Field(default_factory=list)
    by_category: list[MetricRow] = Field(default_factory=list)
    by_customer: list[MetricRow] = Field(default_factory=list)
    concentration_top5_percent: Decimal = ZERO
    declining_products: list[ProductPerformance] = Field(default_factory=list)
    quality: DataQuality = Field(default_factory=DataQuality)


class CustomerSegmentRow(BaseModel):
    segment: str
    count: int
    revenue: Decimal = ZERO
    rule: str = ""


class CustomerAnalytics(BaseModel):
    period_label: str
    total_customers: int = 0
    active_customers: int = 0
    new_customers: int = 0
    repeat_customers: int = 0
    repeat_rate_percent: Decimal | None = None
    inactive_customers: int = 0
    at_risk_customers: int = 0
    average_order_value: Decimal = ZERO
    average_purchase_frequency: Decimal | None = None
    concentration_top5_percent: Decimal = ZERO
    segments: list[CustomerSegmentRow] = Field(default_factory=list)
    top_customers: list[MetricRow] = Field(default_factory=list)
    acquisition_series: list[SeriesPoint] = Field(default_factory=list)
    cohorts: list[dict[str, Any]] = Field(default_factory=list)
    quality: DataQuality = Field(default_factory=DataQuality)


class InventoryAnalytics(BaseModel):
    period_label: str
    sku_count: int = 0
    units_on_hand: int = 0
    inventory_value: Decimal = ZERO
    low_stock_count: int = 0
    stockout_products: int = 0
    slow_moving: list[dict[str, Any]] = Field(default_factory=list)
    non_moving: list[dict[str, Any]] = Field(default_factory=list)
    overstock: list[dict[str, Any]] = Field(default_factory=list)
    turnover_ratio: Decimal | None = None
    turnover_basis: str = ""
    average_days_of_cover: Decimal | None = None
    valuation_series: list[SeriesPoint] = Field(default_factory=list)
    demand: list[dict[str, Any]] = Field(default_factory=list)
    quality: DataQuality = Field(default_factory=DataQuality)


class SupplierAnalytics(BaseModel):
    period_label: str
    supplier_count: int = 0
    purchase_order_count: int = 0
    purchase_value: Decimal = ZERO
    receipt_count: int = 0
    on_time_delivery_percent: Decimal | None = None
    average_lead_time_days: Decimal | None = None
    delayed_orders: int = 0
    fulfilment_percent: Decimal | None = None
    concentration_top3_percent: Decimal = ZERO
    supplier_rows: list[dict[str, Any]] = Field(default_factory=list)
    price_trends: list[dict[str, Any]] = Field(default_factory=list)
    quality: DataQuality = Field(default_factory=DataQuality)


class AnomalyFinding(BaseModel):
    anomaly_id: str
    category: str
    anomaly_type: str
    affected_record: str
    affected_record_id: int | None = None
    detection_method: str
    observed_value: Decimal | None = None
    expected_value: Decimal | None = None
    deviation: Decimal | None = None
    severity: str = "LOW"
    evidence: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""
    detected_at: datetime | None = None


class ForecastPoint(BaseModel):
    label: str
    period_start: datetime
    value: Decimal
    lower: Decimal | None = None
    upper: Decimal | None = None
    is_forecast: bool = True


class ModelMetrics(BaseModel):
    mae: Decimal | None = None
    rmse: Decimal | None = None
    mape: Decimal | None = None
    smape: Decimal | None = None
    bias: Decimal | None = None
    validation_points: int = 0


class ForecastOutcome(BaseModel):
    run_ref: str | None = None
    target: str
    metric: str
    status: str = "COMPLETED"  # COMPLETED | INSUFFICIENT_HISTORICAL_DATA
    method: str = ""
    method_note: str = ""
    data_points: int = 0
    horizon: int = 0
    train_period: str = ""
    validation_period: str = ""
    metrics: ModelMetrics = Field(default_factory=ModelMetrics)
    baseline_metrics: ModelMetrics | None = None
    actuals: list[ForecastPoint] = Field(default_factory=list)
    forecast: list[ForecastPoint] = Field(default_factory=list)
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    insufficient_reason: str | None = None
    model_version: str = "1.0"


class RiskItem(BaseModel):
    risk_key: str
    category: str
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    likelihood: str = "MEDIUM"
    impact: str = "MEDIUM"
    severity: str = "MEDIUM"
    score: Decimal = ZERO
    formula: str = ""
    mitigation: str = ""
    data_limitations: str | None = None


class SimulationLine(BaseModel):
    metric: str
    baseline: Decimal | None = None
    simulated: Decimal | None = None
    delta: Decimal | None = None
    delta_percent: Decimal | None = None
    unit: str = "₹"


class SimulationOutcome(BaseModel):
    simulation_ref: str | None = None
    scenario_type: str
    label: str = "HYPOTHETICAL SCENARIO — NOT AN ACTUAL BUSINESS RESULT"
    parameters: dict[str, Any] = Field(default_factory=dict)
    lines: list[SimulationLine] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    narrative: str = ""


class KPIItem(BaseModel):
    kpi_key: str
    kpi_name: str
    category: str
    formula: str
    period_label: str
    actual: Decimal | None = None
    comparison: Decimal | None = None
    unit: str = ""
    completeness: str = "COMPLETE"
    source_records: dict[str, Any] = Field(default_factory=dict)
    limitation: str | None = None
    updated_at: datetime | None = None
