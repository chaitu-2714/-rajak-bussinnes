"""Deterministic inventory analysis used by the Inventory Agent."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from app.ai.schemas.agent_schema import Evidence, Finding, Recommendation
from app.core.constants import FindingSeverity


@dataclass
class ReorderPolicy:
    """Configurable replenishment policy.

    Reorder point = average daily demand × (lead time + safety days).
    Suggested quantity = reorder point + review-period demand − stock on hand.
    """

    lead_time_days: int = 7
    safety_days: int = 7
    review_days: int = 30
    overstock_days: int = 60
    dead_stock_days: int = 90

    def as_dict(self) -> dict:
        return {
            "lead_time_days": self.lead_time_days,
            "safety_days": self.safety_days,
            "review_days": self.review_days,
            "overstock_days": self.overstock_days,
            "dead_stock_days": self.dead_stock_days,
        }


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):,.2f}"


def detect_low_stock(*, stock_rows: list[dict], period_label: str) -> tuple[list[Finding], dict]:
    """Products at or below their configured minimum."""
    low = [row for row in stock_rows if row.get("low") or row.get("available", 0) <= row.get("minimum", 0)]
    metrics = {"low_stock_count": len(low), "products_checked": len(stock_rows)}
    findings: list[Finding] = []
    if not low:
        return findings, metrics

    worst = min(low, key=lambda row: int(row.get("available", 0)))
    findings.append(
        Finding(
            finding_id="inv-low-stock",
            finding_type="LOW_STOCK",
            description=(
                f"{len(low)} product(s) are at or below minimum stock; the lowest is "
                f"{worst.get('product')} with {worst.get('available')} "
                f"{worst.get('unit', 'units')} (minimum {worst.get('minimum')})."
            ),
            severity=FindingSeverity.HIGH
            if any(int(row.get("available", 0)) == 0 for row in low)
            else FindingSeverity.MEDIUM,
            evidence=[
                Evidence(source="get_low_stock_products", metric="products below minimum", value=str(len(low)), period=period_label, record_count=len(low)),
                Evidence(source="get_product_stock", metric="lowest available quantity", value=str(worst.get("available")), period=period_label),
            ],
            reporting_period=period_label,
            metric_value=float(len(low)),
            agent_id="inventory_agent",
        )
    )
    return findings, metrics


def calculate_reorder(
    *,
    available: int,
    minimum: int,
    units_per_day: float | None,
    policy: ReorderPolicy,
    lead_time_days: int | None = None,
) -> dict:
    """Demand-aware reorder point and suggested quantity."""
    lead = lead_time_days if lead_time_days is not None else policy.lead_time_days
    missing: list[str] = []
    if units_per_day is None:
        missing.append("historical sales velocity (no completed sales for this product)")
    if lead_time_days is None:
        missing.append("supplier lead time (not recorded in Phase 4)")

    demand = units_per_day or 0.0
    safety = demand * policy.safety_days
    reorder_point = demand * lead + safety
    review_demand = demand * policy.review_days
    target = reorder_point + review_demand
    suggested = max(0, round(target - available))
    days_cover = round(available / demand, 1) if demand > 0 else None

    return {
        "available": available,
        "minimum": minimum,
        "units_per_day": round(demand, 3),
        "lead_time_days": lead,
        "safety_stock": round(safety, 1),
        "reorder_point": round(reorder_point, 1),
        "suggested_quantity": suggested,
        "days_of_cover": days_cover,
        "missing_inputs": missing,
        "policy": policy.as_dict(),
    }


def detect_overstock(
    *, stock_rows: list[dict], velocity_by_product: dict[str, float], policy: ReorderPolicy
) -> tuple[list[Finding], list[dict]]:
    """Stock cover far beyond the review window."""
    overstocked: list[dict] = []
    for row in stock_rows:
        available = int(row.get("available", 0) or 0)
        if available <= 0:
            continue
        rate = velocity_by_product.get(str(row.get("sku")))
        if rate is None or rate <= 0:
            continue
        days_cover = available / rate
        if days_cover >= policy.overstock_days:
            overstocked.append(
                {
                    "product": row.get("product"),
                    "sku": row.get("sku"),
                    "available": available,
                    "units_per_day": round(rate, 3),
                    "days_of_cover": round(days_cover, 1),
                    "stock_value": row.get("stock_value"),
                }
            )
    overstocked.sort(key=lambda item: item["days_of_cover"], reverse=True)

    findings: list[Finding] = []
    if overstocked:
        worst = overstocked[0]
        findings.append(
            Finding(
                finding_id="inv-overstock",
                finding_type="OVERSTOCK",
                description=(
                    f"{len(overstocked)} product(s) hold more than {policy.overstock_days} "
                    f"days of cover; {worst['product']} holds {worst['available']} units "
                    f"({worst['days_of_cover']} days at current demand)."
                ),
                severity=FindingSeverity.LOW,
                evidence=[
                    Evidence(source="get_product_velocity", metric="days of cover", value=str(worst["days_of_cover"]), period=f"policy {policy.overstock_days} days"),
                    Evidence(source="get_product_stock", metric="available quantity", value=str(worst["available"]), period=None),
                ],
                metric_value=worst["days_of_cover"],
                agent_id="inventory_agent",
            )
        )
    return findings, overstocked


def detect_dead_stock(
    *,
    stock_rows: list[dict],
    last_sold: dict[str, str | None],
    policy: ReorderPolicy,
) -> tuple[list[Finding], list[dict]]:
    """Products holding stock with no recent sales (not assumed obsolete)."""
    dead: list[dict] = []
    for row in stock_rows:
        available = int(row.get("available", 0) or 0)
        if available <= 0:
            continue
        sku = str(row.get("sku"))
        if sku not in last_sold:
            continue
        last = last_sold.get(sku)
        if last is None:
            dead.append(
                {
                    "product": row.get("product"),
                    "sku": sku,
                    "available": available,
                    "last_sold": "no recorded sales",
                    "stock_value": row.get("stock_value"),
                }
            )
    findings: list[Finding] = []
    if dead:
        findings.append(
            Finding(
                finding_id="inv-dead-stock",
                finding_type="DEAD_STOCK",
                description=(
                    f"{len(dead)} product(s) hold stock but have no sales in the last "
                    f"{policy.dead_stock_days} days. No sales does not by itself mean the "
                    "stock is obsolete."
                ),
                severity=FindingSeverity.LOW,
                evidence=[
                    Evidence(source="get_product_velocity", metric="products with no recent sales", value=str(len(dead)), period=f"last {policy.dead_stock_days} days")
                ],
                metric_value=float(len(dead)),
                agent_id="inventory_agent",
            )
        )
    return findings, dead


def build_purchase_recommendations(
    *,
    reorder_rows: list[dict],
    stock_rows: list[dict],
    policy: ReorderPolicy,
    supplier_name: str | None,
) -> list[Recommendation]:
    """Turn reorder calculations into approval-ready suggestions."""
    by_sku = {str(row.get("sku")): row for row in stock_rows}
    recommendations: list[Recommendation] = []
    for row in reorder_rows:
        if row["suggested_quantity"] <= 0:
            continue
        stock = by_sku.get(str(row.get("sku")), {})
        cost = _dec(stock.get("cost_price", 0)) * row["suggested_quantity"]
        recommendations.append(
            Recommendation(
                recommendation_id=f"inv-rec-{row.get('sku')}",
                recommendation=(
                    f"Order {row['suggested_quantity']} unit(s) of {row.get('product')} "
                    f"from {supplier_name or 'a supplier'}."
                ),
                reason=(
                    f"Stock {row['available']} against a reorder point of "
                    f"{row['reorder_point']} at {row['units_per_day']} units/day"
                    + (
                        f"; missing inputs: {', '.join(row['missing_inputs'])}."
                        if row["missing_inputs"]
                        else "."
                    )
                ),
                priority="HIGH" if row["available"] <= row["minimum"] else "MEDIUM",
                supporting_figures={
                    "available": str(row["available"]),
                    "suggested_quantity": str(row["suggested_quantity"]),
                    "estimated_cost": _money(cost),
                    "supplier": supplier_name or "not recorded",
                },
                agent_id="inventory_agent",
            )
        )
    return recommendations[:5]
