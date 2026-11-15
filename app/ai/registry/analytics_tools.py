"""Phase 7 analytics tools: how the orchestrator reaches the BI layer.

Every tool is permission-checked, read-only (nothing here modifies a business
record) and returns the deterministic figures the analytics engine calculated —
the language model narrates them, it never computes them.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas.tool_schema import ToolContext, ToolDefinition
from app.core.constants import AIRiskLevel
from app.core.exceptions import NotFoundError

Granularity = Literal["DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY"]
Section = Literal["ALL", "FINANCIAL", "SALES", "CUSTOMERS", "INVENTORY", "SUPPLIERS"]


class AnalyticsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granularity: Granularity = "MONTHLY"
    section: Section = "ALL"


class KPIArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granularity: Granularity = "MONTHLY"
    category: str | None = Field(default=None, max_length=40)


class ForecastArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["SALES", "REVENUE", "EXPENSES", "CASH_FLOW", "DEMAND"] = "SALES"
    horizon: int = Field(default=1, ge=1, le=12)
    product_id: int | None = None


class AnomalyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granularity: Granularity = "MONTHLY"
    severity: Literal["ALL", "LOW", "MEDIUM", "HIGH", "CRITICAL"] = "ALL"


class RiskArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    granularity: Granularity = "MONTHLY"


class SimulationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: Literal[
        "PRICE_INCREASE",
        "SALES_DECLINE",
        "SUPPLIER_PRICE_INCREASE",
        "HIRE_EMPLOYEES",
        "PURCHASE_UNITS",
    ]
    percent: float | None = Field(default=None, ge=-100, le=100)
    count: int | None = Field(default=None, ge=1, le=100)
    units: int | None = Field(default=None, ge=1, le=100000)
    unit_cost: float | None = Field(default=None, ge=0)


def _service(context: ToolContext):
    service = getattr(context.services, "analytics_service", None)
    if service is None:
        raise NotFoundError("The analytics service is not available")
    return service


def _run_analytics(context: ToolContext, args: AnalyticsArgs) -> dict:
    service = _service(context)
    bundle = service.analyze(args.granularity)
    financial, sales = bundle.financial, bundle.sales
    payload = {
        "period": bundle.period.label,
        "granularity": bundle.period.granularity,
        "comparison_period": bundle.comparison.label if bundle.comparison else None,
        "data_quality": bundle.quality.completeness,
        "limitations": bundle.quality.limitations,
        "insights": service._engine.generate_business_insights(bundle),
        "gaps": service._engine.identify_performance_gaps(bundle),
    }
    if args.section in ("ALL", "FINANCIAL"):
        payload["financial"] = {
            "revenue": str(financial.revenue),
            "cash_received": str(financial.cash_received),
            "cost_of_goods_sold": str(financial.cogs),
            "gross_profit": str(financial.gross_profit),
            "operating_expenses": str(financial.operating_expenses),
            "net_profit": str(financial.net_profit) if financial.net_profit is not None else "not reported",
            "gross_margin_percent": str(financial.gross_margin_percent)
            if financial.gross_margin_percent is not None
            else None,
            "net_cash_flow": str(financial.net_cash_flow),
            "outstanding_receivables": str(financial.outstanding_receivables),
            "profit_components": financial.profit_components,
            "receivables_aging": [row.model_dump(mode="json") for row in financial.receivables_aging],
        }
    if args.section in ("ALL", "SALES"):
        payload["sales"] = {
            "revenue": str(sales.total_revenue),
            "orders": sales.order_count,
            "units_sold": sales.units_sold,
            "average_order_value": str(sales.average_order_value),
            "growth_percent": str(sales.growth_percent) if sales.growth_percent is not None else None,
            "top_products": [
                {
                    "product": row.product,
                    "revenue": str(row.revenue),
                    "units": row.quantity,
                    "classification": row.classification,
                    "reason": row.reason,
                }
                for row in sales.by_product[:8]
            ],
            "declining_products": [row.product for row in sales.declining_products],
        }
    if args.section in ("ALL", "CUSTOMERS"):
        customers = bundle.customers
        payload["customers"] = {
            "total": customers.total_customers,
            "new": customers.new_customers,
            "repeat_rate_percent": str(customers.repeat_rate_percent)
            if customers.repeat_rate_percent is not None
            else None,
            "inactive": customers.inactive_customers,
            "at_risk": customers.at_risk_customers,
            "concentration_top5_percent": str(customers.concentration_top5_percent),
            "segments": [row.model_dump(mode="json") for row in customers.segments],
        }
    if args.section in ("ALL", "INVENTORY"):
        inventory = bundle.inventory
        payload["inventory"] = {
            "skus": inventory.sku_count,
            "inventory_value": str(inventory.inventory_value),
            "low_stock": inventory.low_stock_count,
            "out_of_stock": inventory.stockout_products,
            "turnover": str(inventory.turnover_ratio) if inventory.turnover_ratio is not None else None,
            "turnover_basis": inventory.turnover_basis,
            "slow_moving": len(inventory.slow_moving),
            "non_moving": len(inventory.non_moving),
        }
    if args.section in ("ALL", "SUPPLIERS"):
        suppliers = bundle.suppliers
        payload["suppliers"] = {
            "purchase_orders": suppliers.purchase_order_count,
            "purchase_value": str(suppliers.purchase_value),
            "on_time_percent": str(suppliers.on_time_delivery_percent)
            if suppliers.on_time_delivery_percent is not None
            else None,
            "average_lead_time_days": str(suppliers.average_lead_time_days)
            if suppliers.average_lead_time_days is not None
            else None,
            "concentration_top3_percent": str(suppliers.concentration_top3_percent),
        }
    return payload


def _run_kpis(context: ToolContext, args: KPIArgs) -> dict:
    service = _service(context)
    kpis = service.kpis(args.granularity)
    if args.category:
        wanted = args.category.lower()
        kpis = [kpi for kpi in kpis if kpi.category.lower() == wanted]
    return {
        "period": kpis[0].period_label if kpis else args.granularity,
        "count": len(kpis),
        "kpis": [
            {
                "name": kpi.kpi_name,
                "category": kpi.category,
                "value": str(kpi.actual) if kpi.actual is not None else "not calculable",
                "unit": kpi.unit,
                "formula": kpi.formula,
                "completeness": kpi.completeness,
                "limitation": kpi.limitation,
            }
            for kpi in kpis
        ],
    }


def _run_forecast(context: ToolContext, args: ForecastArgs) -> dict:
    service = _service(context)
    outcome = service.forecast(args.target, horizon=args.horizon, product_id=args.product_id)
    if outcome.status != "COMPLETED":
        return {
            "target": outcome.target,
            "status": outcome.status,
            "reason": outcome.insufficient_reason,
            "summary": outcome.insufficient_reason,
        }
    return {
        "target": outcome.target,
        "metric": outcome.metric,
        "status": outcome.status,
        "method": outcome.method,
        "method_note": outcome.method_note,
        "data_points": outcome.data_points,
        "train_period": outcome.train_period,
        "validation_period": outcome.validation_period,
        "metrics": outcome.metrics.model_dump(mode="json"),
        "baseline_metrics": outcome.baseline_metrics.model_dump(mode="json")
        if outcome.baseline_metrics
        else None,
        "forecast": [
            {
                "period": point.label,
                "value": str(point.value),
                "lower": str(point.lower) if point.lower is not None else None,
                "upper": str(point.upper) if point.upper is not None else None,
            }
            for point in outcome.forecast
        ],
        "actuals": [
            {"period": point.label, "value": str(point.value)} for point in outcome.actuals[-6:]
        ],
        "assumptions": outcome.assumptions,
        "limitations": outcome.limitations,
        "summary": (
            f"{outcome.metric}: {outcome.forecast[0].value:,.2f} expected for "
            f"{outcome.forecast[0].label} using {outcome.method} "
            f"(validated MAE {outcome.metrics.mae}). This is a forecast, not an actual result."
        ),
    }


def _run_anomalies(context: ToolContext, args: AnomalyArgs) -> dict:
    service = _service(context)
    findings = service.anomalies(args.granularity)
    if args.severity != "ALL":
        findings = [finding for finding in findings if finding.severity == args.severity]
    return {
        "count": len(findings),
        "summary": (
            f"{len(findings)} anomaly review item(s) were detected. These are review flags, "
            "not findings of fraud."
        ),
        "anomalies": [
            {
                "category": finding.category,
                "type": finding.anomaly_type,
                "record": finding.affected_record,
                "method": finding.detection_method,
                "observed": str(finding.observed_value) if finding.observed_value is not None else None,
                "expected": str(finding.expected_value) if finding.expected_value is not None else None,
                "severity": finding.severity,
                "explanation": finding.explanation,
            }
            for finding in findings[:15]
        ],
    }


def _run_risks(context: ToolContext, args: RiskArgs) -> dict:
    service = _service(context)
    risks = service.risks(args.granularity)
    return {
        "count": len(risks),
        "summary": (
            "Risks are scored by likelihood × impact weights (1–9); the scores are transparent "
            "rules, not statistical probabilities."
        ),
        "risks": [
            {
                "category": risk.category,
                "description": risk.description,
                "likelihood": risk.likelihood,
                "impact": risk.impact,
                "severity": risk.severity,
                "score": str(risk.score),
                "mitigation": risk.mitigation,
                "limitations": risk.data_limitations,
            }
            for risk in sorted(risks, key=lambda item: item.score, reverse=True)
        ],
    }


def _run_simulation(context: ToolContext, args: SimulationArgs) -> dict:
    service = _service(context)
    parameters: dict = {}
    if args.percent is not None:
        parameters["percent"] = args.percent
    if args.count is not None:
        parameters["count"] = args.count
    if args.units is not None:
        parameters["units"] = args.units
    if args.unit_cost is not None:
        parameters["unit_cost"] = args.unit_cost
    outcome = service.simulate(args.scenario, parameters=parameters)
    return {
        "scenario": outcome.scenario_type,
        "label": outcome.label,
        "parameters": outcome.parameters,
        "results": [
            {
                "metric": line.metric,
                "baseline": str(line.baseline) if line.baseline is not None else None,
                "simulated": str(line.simulated) if line.simulated is not None else None,
                "delta": str(line.delta) if line.delta is not None else None,
                "delta_percent": str(line.delta_percent) if line.delta_percent is not None else None,
            }
            for line in outcome.lines
        ],
        "assumptions": outcome.assumptions,
        "limitations": outcome.limitations,
        "summary": f"{outcome.label}. {outcome.narrative}",
    }


def build_analytics_tools() -> list[ToolDefinition]:
    """Register the Phase 7 analytics tools."""
    return [
        ToolDefinition(
            name="get_business_analytics",
            description=(
                "Business performance for a period: financial, sales, customer, inventory and "
                "supplier analytics calculated from recorded data"
            ),
            category="analytics",
            input_model=AnalyticsArgs,
            required_permission="analytics.view",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=120.0,
            handler=_run_analytics,
        ),
        ToolDefinition(
            name="get_business_kpis",
            description="The KPI board with formulas, values, completeness and limitations",
            category="analytics",
            input_model=KPIArgs,
            required_permission="analytics.view",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=120.0,
            handler=_run_kpis,
        ),
        ToolDefinition(
            name="forecast_business_metric",
            description=(
                "Forecast sales, revenue, expenses, cash flow or product demand with "
                "chronological validation and measured error metrics"
            ),
            category="analytics",
            input_model=ForecastArgs,
            required_permission="analytics.view",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=180.0,
            handler=_run_forecast,
        ),
        ToolDefinition(
            name="detect_business_anomalies",
            description="Detected business anomalies with method, evidence and severity",
            category="analytics",
            input_model=AnomalyArgs,
            required_permission="analytics.view",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=120.0,
            handler=_run_anomalies,
        ),
        ToolDefinition(
            name="assess_business_risks",
            description="Business risk assessment with documented scoring formulas",
            category="analytics",
            input_model=RiskArgs,
            required_permission="analytics.view",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=120.0,
            handler=_run_risks,
        ),
        ToolDefinition(
            name="simulate_business_scenario",
            description=(
                "Run a what-if simulation (price change, sales decline, supplier price rise, "
                "hiring, stock purchase). Never modifies business records"
            ),
            category="analytics",
            input_model=SimulationArgs,
            required_permission="analytics.manage",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=120.0,
            handler=_run_simulation,
        ),
    ]
