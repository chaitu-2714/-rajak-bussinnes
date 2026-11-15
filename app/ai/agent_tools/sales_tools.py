"""Deterministic sales analysis used by the Sales Agent."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import mean, pstdev

from app.ai.schemas.agent_schema import Evidence, Finding, Recommendation
from app.core.constants import FindingSeverity


@dataclass
class SalesThresholds:
    decline_warning: float = 0.10  # 10% period-over-period drop
    decline_critical: float = 0.25
    low_performer_share: float = 0.05  # <5% of revenue


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):,.2f}"


def analyse_sales_performance(
    *, summary: dict, trends: dict, period_label: str
) -> tuple[list[Finding], dict]:
    completed = int(summary.get("completed_orders", 0) or 0)
    value = _dec(summary.get("sales_value", 0))
    average = _dec(summary.get("average_order_value", 0))
    pending = int(summary.get("pending_orders", 0) or 0)

    metrics = {
        "completed_orders": completed,
        "sales_value": _money(value),
        "average_order_value": _money(average),
        "pending_orders": pending,
        "total_orders": int(summary.get("total_orders", 0) or 0),
    }
    findings: list[Finding] = [
        Finding(
            finding_id="sales-volume",
            finding_type="SALES_VOLUME",
            description=(
                f"{completed} completed order(s) worth {_money(value)} for {period_label}; "
                f"average order value {_money(average)}."
            ),
            severity=FindingSeverity.INFO,
            evidence=[
                Evidence(source="get_sales_summary", metric="completed orders", value=str(completed), period=period_label),
                Evidence(source="get_sales_summary", metric="sales value", value=_money(value), period=period_label),
                Evidence(source="get_sales_summary", metric="average order value", value=_money(average), period=period_label),
            ],
            reporting_period=period_label,
            metric_value=float(value),
            agent_id="sales_agent",
        )
    ]

    monthly = trends.get("monthly", []) or []
    if len(monthly) >= 2:
        latest = _dec(monthly[-1]["sales"])
        previous = _dec(monthly[-2]["sales"])
        metrics["latest_month"] = monthly[-1]["month"]
        metrics["previous_month"] = monthly[-2]["month"]
        if previous > 0:
            change = float((latest - previous) / previous)
            metrics["month_over_month_pct"] = round(change * 100, 2)
            if change <= -SalesThresholds.decline_warning:
                findings.append(
                    Finding(
                        finding_id="sales-mom-decline",
                        finding_type="SALES_DECLINE",
                        description=(
                            f"Sales fell {abs(change) * 100:.1f}% from {monthly[-2]['month']} "
                            f"({_money(previous)}) to {monthly[-1]['month']} ({_money(latest)})."
                        ),
                        severity=FindingSeverity.HIGH
                        if change <= -SalesThresholds.decline_critical
                        else FindingSeverity.MEDIUM,
                        evidence=[
                            Evidence(source="get_sales_trends", metric="previous month sales", value=_money(previous), period=monthly[-2]["month"]),
                            Evidence(source="get_sales_trends", metric="latest month sales", value=_money(latest), period=monthly[-1]["month"]),
                        ],
                        reporting_period=period_label,
                        metric_value=round(change * 100, 2),
                        agent_id="sales_agent",
                    )
                )

    if pending > 0:
        findings.append(
            Finding(
                finding_id="sales-pending-orders",
                finding_type="PENDING_ORDERS",
                description=f"{pending} order(s) are still open (draft or confirmed).",
                severity=FindingSeverity.LOW,
                evidence=[
                    Evidence(source="get_sales_summary", metric="pending orders", value=str(pending), period=period_label)
                ],
                reporting_period=period_label,
                metric_value=float(pending),
                agent_id="sales_agent",
            )
        )
    return findings, metrics


def analyse_products(*, products: list[dict], period_label: str) -> tuple[list[Finding], dict]:
    """Top and low performers, keeping quantity and revenue distinct."""
    if not products:
        return [], {"products_analysed": 0}

    total_revenue = sum((_dec(item.get("revenue", 0)) for item in products), Decimal("0"))
    ranked = sorted(products, key=lambda item: _dec(item.get("revenue", 0)), reverse=True)
    top = ranked[0]
    metrics = {
        "products_analysed": len(products),
        "total_revenue": _money(total_revenue),
        "top_product": top.get("product"),
        "top_product_revenue": top.get("revenue"),
        "top_product_quantity": top.get("quantity"),
    }
    findings: list[Finding] = [
        Finding(
            finding_id="sales-top-product",
            finding_type="TOP_PRODUCT",
            description=(
                f"{top.get('product')} is the highest revenue product with "
                f"{top.get('revenue')} from {top.get('quantity')} unit(s)."
            ),
            severity=FindingSeverity.INFO,
            evidence=[
                Evidence(source="get_top_products", metric="product revenue", value=str(top.get("revenue")), period=period_label),
                Evidence(source="get_top_products", metric="quantity sold", value=str(top.get("quantity")), period=period_label),
            ],
            reporting_period=period_label,
            agent_id="sales_agent",
        )
    ]

    if total_revenue > 0:
        weakest = ranked[-1]
        share = float(_dec(weakest.get("revenue", 0)) / total_revenue)
        metrics["weakest_product"] = weakest.get("product")
        metrics["weakest_share_pct"] = round(share * 100, 2)
        if share < SalesThresholds.low_performer_share and len(ranked) > 1:
            findings.append(
                Finding(
                    finding_id="sales-low-performer",
                    finding_type="LOW_PERFORMER",
                    description=(
                        f"{weakest.get('product')} contributes only {share * 100:.1f}% of "
                        f"product revenue ({weakest.get('revenue')})."
                    ),
                    severity=FindingSeverity.LOW,
                    evidence=[
                        Evidence(source="get_top_products", metric="product revenue", value=str(weakest.get("revenue")), period=period_label),
                        Evidence(source="get_top_products", metric="total product revenue", value=_money(total_revenue), period=period_label),
                    ],
                    reporting_period=period_label,
                    metric_value=round(share * 100, 2),
                    agent_id="sales_agent",
                )
            )
    return findings, metrics


def analyse_demand(*, velocity_rows: list[dict], period_label: str) -> tuple[list[Finding], dict]:
    """Average daily demand and its variability, from real completed sales."""
    rows = [row for row in velocity_rows if int(row.get("quantity_sold", 0) or 0) > 0]
    if not rows:
        return [], {"products_with_sales": 0}

    rates = [float(row.get("units_per_day", 0) or 0) for row in rows]
    metrics = {
        "products_with_sales": len(rows),
        "average_units_per_day": round(mean(rates), 3),
        "demand_variability": round(pstdev(rates), 3) if len(rates) > 1 else 0.0,
        "window_days": rows[0].get("window_days"),
    }
    fastest = max(rows, key=lambda row: float(row.get("units_per_day", 0) or 0))
    findings = [
        Finding(
            finding_id="sales-demand",
            finding_type="DEMAND_LEVEL",
            description=(
                f"Across {len(rows)} product(s) with recent sales, demand averages "
                f"{metrics['average_units_per_day']} units/day; the fastest mover is "
                f"{fastest.get('product')} at {fastest.get('units_per_day')} units/day."
            ),
            severity=FindingSeverity.INFO,
            evidence=[
                Evidence(source="get_product_velocity", metric="units per day", value=str(fastest.get("units_per_day")), period=f"last {rows[0].get('window_days')} days"),
                Evidence(source="get_product_velocity", metric="products with sales", value=str(len(rows)), period=period_label),
            ],
            reporting_period=period_label,
            metric_value=metrics["average_units_per_day"],
            agent_id="sales_agent",
        )
    ]
    return findings, metrics


def build_sales_recommendations(
    *, findings: list[Finding], metrics: dict, period_label: str
) -> list[Recommendation]:
    by_type = {finding.finding_type: finding for finding in findings}
    recommendations: list[Recommendation] = []

    if "SALES_DECLINE" in by_type:
        recommendations.append(
            Recommendation(
                recommendation_id="sales-rec-decline",
                recommendation=(
                    "Review the products and categories behind the latest decline before "
                    "changing pricing."
                ),
                reason=by_type["SALES_DECLINE"].description,
                priority="HIGH",
                supporting_figures={
                    "month_over_month_pct": str(metrics.get("month_over_month_pct", "")),
                    "period": period_label,
                },
                agent_id="sales_agent",
            )
        )
    if "TOP_PRODUCT" in by_type:
        recommendations.append(
            Recommendation(
                recommendation_id="sales-rec-top",
                recommendation=(
                    "Keep stock cover for the top revenue product so momentum is not lost."
                ),
                reason=by_type["TOP_PRODUCT"].description,
                priority="MEDIUM",
                supporting_figures={
                    "product": str(metrics.get("top_product", "")),
                    "revenue": str(metrics.get("top_product_revenue", "")),
                },
                agent_id="sales_agent",
            )
        )
    if "PENDING_ORDERS" in by_type:
        recommendations.append(
            Recommendation(
                recommendation_id="sales-rec-pending",
                recommendation="Complete or cancel open orders so revenue is recognised.",
                reason=by_type["PENDING_ORDERS"].description,
                priority="MEDIUM",
                supporting_figures={"pending_orders": str(metrics.get("pending_orders", ""))},
                agent_id="sales_agent",
            )
        )
    if "LOW_PERFORMER" in by_type:
        recommendations.append(
            Recommendation(
                recommendation_id="sales-rec-low",
                recommendation=(
                    "Review pricing and promotion for the weakest product, or reduce its stock."
                ),
                reason=by_type["LOW_PERFORMER"].description,
                priority="LOW",
                supporting_figures={"share_pct": str(metrics.get("weakest_share_pct", ""))},
                agent_id="sales_agent",
            )
        )
    return recommendations
