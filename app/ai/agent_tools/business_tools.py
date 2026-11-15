"""Cross-functional analysis used by the Business Intelligence Agent."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from app.ai.schemas.agent_schema import AgentResult, Evidence, Finding, Recommendation
from app.core.constants import FindingSeverity


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):,.2f}"


def dedupe_findings(results: list[AgentResult]) -> list[Finding]:
    """Merge findings from several agents, removing duplicates.

    Two findings are duplicates when they share a type and a normalised
    description; the highest severity wins.
    """
    best: dict[tuple[str, str], Finding] = {}
    for result in results:
        for finding in result.findings:
            key = (finding.finding_type, finding.description.strip().lower()[:120])
            existing = best.get(key)
            if existing is None or FindingSeverity.ORDER.get(
                finding.severity, 0
            ) > FindingSeverity.ORDER.get(existing.severity, 0):
                best[key] = finding
    return list(best.values())


def combine_metrics(results: list[AgentResult]) -> dict:
    """Flatten agent metrics under their agent id."""
    combined: dict = {}
    for result in results:
        combined[result.agent_id] = {
            "summary": result.summary,
            "confidence": result.confidence,
            "metrics": result.metrics,
            "findings": len(result.findings),
            "recommendations": len(result.recommendations),
            "status": result.status,
        }
    return combined


def analyse_sales_and_inventory(
    *, sales_result: AgentResult, inventory_result: AgentResult, period_label: str
) -> tuple[list[Finding], list[Recommendation]]:
    """Compare demand with stock cover to expose stockout risk."""
    sales_metrics = sales_result.metrics or {}
    inventory_metrics = inventory_result.metrics or {}
    findings: list[Finding] = []
    recommendations: list[Recommendation] = []

    low_stock = int(inventory_metrics.get("low_stock_count", 0) or 0)
    products_checked = int(inventory_metrics.get("products_checked", 0) or 0)
    sales_value = _dec(sales_metrics.get("sales_value", 0))
    completed = int(sales_metrics.get("completed_orders", 0) or 0)

    if low_stock and completed:
        findings.append(
            Finding(
                finding_id="bi-stockout-risk",
                finding_type="STOCKOUT_RISK",
                description=(
                    f"{low_stock} of {products_checked} product(s) are at or below minimum "
                    f"while {completed} order(s) worth {_money(sales_value)} were completed "
                    f"in {period_label} — demand is outrunning stock cover."
                ),
                severity=FindingSeverity.HIGH,
                evidence=[
                    Evidence(source="run_inventory_agent", metric="low stock products", value=str(low_stock), period=period_label),
                    Evidence(source="run_sales_agent", metric="completed orders", value=str(completed), period=period_label),
                    Evidence(source="run_sales_agent", metric="sales value", value=_money(sales_value), period=period_label),
                ],
                reporting_period=period_label,
                metric_value=float(low_stock),
                agent_id="business_intelligence_agent",
            )
        )
        recommendations.append(
            Recommendation(
                recommendation_id="bi-rec-restock",
                recommendation=(
                    "Raise purchase orders for the products at or below minimum stock "
                    "before the next sales cycle."
                ),
                reason=(
                    f"{low_stock} product(s) at minimum stock while sales are active "
                    f"({completed} completed orders)."
                ),
                priority="HIGH",
                supporting_figures={
                    "low_stock": str(low_stock),
                    "sales_value": _money(sales_value),
                },
                agent_id="business_intelligence_agent",
            )
        )
    return findings, recommendations


def analyse_revenue_and_expenses(
    *, finance_result: AgentResult, period_label: str
) -> tuple[list[Finding], list[Recommendation]]:
    """Revenue versus cost structure, from the Finance Agent's own metrics."""
    metrics = finance_result.metrics or {}
    revenue = _dec(metrics.get("revenue", 0))
    opex = _dec(metrics.get("operating_expenses", 0))
    net = _dec(metrics.get("net_profit", 0))

    findings: list[Finding] = []
    recommendations: list[Recommendation] = []
    if revenue <= 0:
        return findings, recommendations

    share = float(opex / revenue)
    if share >= 0.5:
        findings.append(
            Finding(
                finding_id="bi-cost-structure",
                finding_type="COST_STRUCTURE",
                description=(
                    f"Operating expenses are {share * 100:.1f}% of revenue "
                    f"({_money(opex)} of {_money(revenue)}), leaving net profit {_money(net)}."
                ),
                severity=FindingSeverity.MEDIUM,
                evidence=[
                    Evidence(source="run_finance_agent", metric="revenue", value=_money(revenue), period=period_label),
                    Evidence(source="run_finance_agent", metric="operating expenses", value=_money(opex), period=period_label),
                ],
                reporting_period=period_label,
                metric_value=round(share * 100, 2),
                agent_id="business_intelligence_agent",
            )
        )
        recommendations.append(
            Recommendation(
                recommendation_id="bi-rec-costs",
                recommendation="Set a monthly cap on the two largest expense categories.",
                reason=f"Operating expenses consume {share * 100:.1f}% of revenue.",
                priority="MEDIUM",
                supporting_figures={"opex_share_pct": f"{share * 100:.1f}"},
                agent_id="business_intelligence_agent",
            )
        )
    return findings, recommendations


def identify_risks(*, results: list[AgentResult], period_label: str) -> list[Finding]:
    """Collect high-severity findings from every agent as business risks."""
    risks: list[Finding] = []
    for result in results:
        for finding in result.findings:
            if FindingSeverity.ORDER.get(finding.severity, 0) < FindingSeverity.ORDER["MEDIUM"]:
                continue
            risks.append(
                Finding(
                    finding_id=f"bi-risk-{result.agent_id}-{finding.finding_id}",
                    finding_type="BUSINESS_RISK",
                    description=f"[{result.agent_id}] {finding.description}",
                    severity=finding.severity,
                    evidence=finding.evidence,
                    reporting_period=finding.reporting_period or period_label,
                    metric_value=finding.metric_value,
                    agent_id="business_intelligence_agent",
                )
            )
    return risks


def compare_periods(
    *, current: dict, previous: dict, period_label: str, label_current: str, label_previous: str
) -> tuple[list[Finding], dict]:
    """Compare two business snapshots on revenue, sales and expenses."""
    findings: list[Finding] = []
    metrics: dict = {}
    pairs = (
        ("revenue", "Revenue", "get_business_snapshot"),
        ("sales_value", "Sales value", "get_business_snapshot"),
        ("operating_expenses", "Operating expenses", "get_business_snapshot"),
    )
    for key, label, source in pairs:
        now_value = _dec(current.get(key, 0))
        before_value = _dec(previous.get(key, 0))
        if before_value == 0 and now_value == 0:
            continue
        change = (
            float((now_value - before_value) / before_value) if before_value else None
        )
        metrics[key] = {
            "current": _money(now_value),
            "previous": _money(before_value),
            "change_pct": round(change * 100, 2) if change is not None else None,
        }
        if change is None:
            continue
        if abs(change) >= 0.10:
            findings.append(
                Finding(
                    finding_id=f"bi-compare-{key}",
                    finding_type="PERIOD_COMPARISON",
                    description=(
                        f"{label} moved {change * 100:+.1f}% from {label_previous} "
                        f"({_money(before_value)}) to {label_current} ({_money(now_value)})."
                    ),
                    severity=FindingSeverity.MEDIUM
                    if key == "operating_expenses" and change > 0
                    else FindingSeverity.INFO,
                    evidence=[
                        Evidence(source=source, metric=f"{label} {label_previous}", value=_money(before_value), period=label_previous),
                        Evidence(source=source, metric=f"{label} {label_current}", value=_money(now_value), period=label_current),
                    ],
                    reporting_period=f"{label_previous} vs {label_current}",
                    metric_value=round(change * 100, 2),
                    agent_id="business_intelligence_agent",
                )
            )
    return findings, metrics


def simulate_price_change(*, products: list[dict], change_pct: float) -> dict:
    """What-if analysis: revenue effect of a price change at current volumes.

    The result is explicitly hypothetical: it holds volume constant and ignores
    demand elasticity.
    """
    rows: list[dict] = []
    current_total = Decimal("0")
    simulated_total = Decimal("0")
    for item in products:
        revenue = _dec(item.get("revenue", 0))
        quantity = int(item.get("quantity", 0) or 0)
        if revenue <= 0 or quantity <= 0:
            continue
        simulated = revenue * (Decimal("1") + Decimal(str(change_pct)) / Decimal("100"))
        current_total += revenue
        simulated_total += simulated
        rows.append(
            {
                "product": item.get("product"),
                "current_revenue": _money(revenue),
                "simulated_revenue": _money(simulated),
                "difference": _money(simulated - revenue),
            }
        )
    return {
        "assumption": (
            "Hypothetical: unit volume is held constant and demand elasticity is ignored. "
            "These are simulated values, not actual results."
        ),
        "change_pct": change_pct,
        "current_revenue": _money(current_total),
        "simulated_revenue": _money(simulated_total),
        "difference": _money(simulated_total - current_total),
        "products": rows,
    }
