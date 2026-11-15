"""Deterministic customer analysis used by the Customer Agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.ai.schemas.agent_schema import Evidence, Finding, Recommendation
from app.core.constants import FindingSeverity, CustomerSegment
from app.utils.date_utils import utcnow


@dataclass
class SegmentationRules:
    """Transparent, configurable segmentation thresholds."""

    new_days: int = 30
    regular_min_orders: int = 3
    high_value_amount: float = 50000.0
    inactive_days: int = 90
    occasional_max_orders: int = 2

    def as_dict(self) -> dict:
        return {
            "new_days": self.new_days,
            "regular_min_orders": self.regular_min_orders,
            "high_value_amount": self.high_value_amount,
            "inactive_days": self.inactive_days,
            "occasional_max_orders": self.occasional_max_orders,
        }


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):,.2f}"


def _parse_date(value) -> datetime | None:
    if not value or value in ("never", "None"):
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%d %b %Y", "%Y-%m-%d", "%d %b %Y, %I:%M %p"):
        try:
            return datetime.strptime(str(value), fmt)
        except ValueError:
            continue
    return None


def classify_customer(row: dict, rules: SegmentationRules, now: datetime | None = None) -> str:
    """Assign one transparent segment to a customer row."""
    now = now or utcnow()
    orders = int(row.get("order_count", 0) or 0)
    value = _dec(row.get("total_purchase", 0))
    last = _parse_date(row.get("last_purchase_at"))
    created = _parse_date(row.get("created_at"))

    days_inactive = (now - last).days if last else None
    days_since_created = (now - created).days if created else None

    if orders > 0 and days_inactive is not None and days_inactive > rules.inactive_days:
        return CustomerSegment.INACTIVE
    if value >= Decimal(str(rules.high_value_amount)):
        return CustomerSegment.HIGH_VALUE
    if (
        orders == 0
        and days_since_created is not None
        and days_since_created <= rules.new_days
    ) or (days_since_created is not None and days_since_created <= rules.new_days and orders <= 1):
        return CustomerSegment.NEW
    if orders >= rules.regular_min_orders:
        return CustomerSegment.REGULAR
    if 0 < orders <= rules.occasional_max_orders:
        return CustomerSegment.OCCASIONAL
    return CustomerSegment.NEW


def segment_customers(
    *, customers: list[dict], rules: SegmentationRules, period_label: str
) -> tuple[list[Finding], dict]:
    """Segment the whole customer base with explicit rules."""
    if not customers:
        return [], {"total_customers": 0, "segments": {}}

    now = utcnow()
    counts: dict[str, int] = {}
    values: dict[str, Decimal] = {}
    for row in customers:
        segment = classify_customer(row, rules, now)
        counts[segment] = counts.get(segment, 0) + 1
        values[segment] = values.get(segment, Decimal("0")) + _dec(row.get("total_purchase", 0))

    metrics = {
        "total_customers": len(customers),
        "segments": counts,
        "segment_values": {key: _money(value) for key, value in values.items()},
        "rules": rules.as_dict(),
    }
    findings = [
        Finding(
            finding_id="crm-segmentation",
            finding_type="SEGMENTATION",
            description=(
                f"{len(customers)} customer(s) segmented: "
                + ", ".join(f"{key} {count}" for key, count in sorted(counts.items()))
                + "."
            ),
            severity=FindingSeverity.INFO,
            evidence=[
                Evidence(source="get_customer_portfolio", metric=f"segment {key}", value=str(count), period=period_label)
                for key, count in sorted(counts.items())
            ],
            reporting_period=period_label,
            metric_value=float(len(customers)),
            agent_id="customer_agent",
        )
    ]
    return findings, metrics


def find_inactive_customers(
    *, customers: list[dict], days: int, period_label: str
) -> tuple[list[Finding], list[dict]]:
    """Customers with no completed purchase inside the inactivity window."""
    now = utcnow()
    cutoff = now - timedelta(days=days)
    inactive: list[dict] = []

    for row in customers:
        last = _parse_date(row.get("last_purchase_at"))
        orders = int(row.get("order_count", 0) or 0)
        if orders == 0 and not last:
            continue
        if last is None or last < cutoff:
            inactive.append(
                {
                    "customer": row.get("full_name"),
                    "customer_code": row.get("customer_code"),
                    "last_purchase": row.get("last_purchase_at") or "never",
                    "days_inactive": (now - last).days if last else None,
                    "total_purchase": row.get("total_purchase", "0.00"),
                    "order_count": orders,
                }
            )

    inactive.sort(key=lambda item: _dec(item.get("total_purchase", 0)), reverse=True)
    findings: list[Finding] = []
    if inactive:
        worst = inactive[0]
        findings.append(
            Finding(
                finding_id="crm-inactive",
                finding_type="INACTIVE_CUSTOMERS",
                description=(
                    f"{len(inactive)} customer(s) have not purchased in {days} days; "
                    f"the highest historical value among them is {worst['customer']} "
                    f"({worst['total_purchase']})."
                ),
                severity=FindingSeverity.HIGH if len(inactive) >= 5 else FindingSeverity.MEDIUM,
                evidence=[
                    Evidence(source="get_customer_portfolio", metric="customers inactive", value=str(len(inactive)), period=f"no purchase in {days} days"),
                    Evidence(source="get_customer_portfolio", metric="largest inactive value", value=str(worst["total_purchase"]), period=str(worst.get("last_purchase"))),
                ],
                reporting_period=period_label,
                metric_value=float(len(inactive)),
                agent_id="customer_agent",
            )
        )
    return findings, inactive


def analyse_customer_value(
    *, customers: list[dict], period_label: str
) -> tuple[list[Finding], dict]:
    """Historical customer value (never a prediction)."""
    with_orders = [row for row in customers if int(row.get("order_count", 0) or 0) > 0]
    if not with_orders:
        return [], {"customers_with_purchases": 0}

    total = sum((_dec(row.get("total_purchase", 0)) for row in with_orders), Decimal("0"))
    ranked = sorted(with_orders, key=lambda row: _dec(row.get("total_purchase", 0)), reverse=True)
    top = ranked[0]
    average = total / len(with_orders)
    share = float(_dec(top.get("total_purchase", 0)) / total) if total > 0 else 0.0

    metrics = {
        "customers_with_purchases": len(with_orders),
        "total_historical_value": _money(total),
        "average_customer_value": _money(average),
        "top_customer": top.get("full_name"),
        "top_customer_value": _money(_dec(top.get("total_purchase", 0))),
        "top_customer_share_pct": round(share * 100, 2),
    }
    findings = [
        Finding(
            finding_id="crm-value",
            finding_type="CUSTOMER_VALUE",
            description=(
                f"Historical customer value totals {_money(total)} across {len(with_orders)} "
                f"buying customer(s); {top.get('full_name')} contributes {share * 100:.1f}%."
            ),
            severity=FindingSeverity.MEDIUM if share >= 0.4 else FindingSeverity.INFO,
            evidence=[
                Evidence(source="get_customer_portfolio", metric="total historical value", value=_money(total), period=period_label),
                Evidence(source="get_customer_portfolio", metric="top customer value", value=_money(_dec(top.get("total_purchase", 0))), period=period_label),
            ],
            reporting_period=period_label,
            metric_value=round(share * 100, 2),
            agent_id="customer_agent",
        )
    ]
    if share >= 0.4 and len(with_orders) > 1:
        findings.append(
            Finding(
                finding_id="crm-concentration",
                finding_type="CUSTOMER_CONCENTRATION",
                description=(
                    f"{top.get('full_name')} accounts for {share * 100:.1f}% of historical "
                    "customer value — concentration risk if that customer leaves."
                ),
                severity=FindingSeverity.MEDIUM,
                evidence=[
                    Evidence(source="get_customer_portfolio", metric="top customer share", value=f"{share * 100:.1f}%", period=period_label)
                ],
                reporting_period=period_label,
                metric_value=round(share * 100, 2),
                agent_id="customer_agent",
            )
        )
    return findings, metrics


def prioritise_followups(
    *, inactive: list[dict], rules: SegmentationRules, limit: int = 5
) -> tuple[list[Recommendation], list[dict]]:
    """Rank lapsed customers by value, recency and order history."""
    scored: list[dict] = []
    for row in inactive:
        value = float(_dec(row.get("total_purchase", 0)))
        days = row.get("days_inactive") or rules.inactive_days
        orders = int(row.get("order_count", 0) or 0)
        score = value * 0.001 + days * 0.5 + orders * 5
        scored.append({**row, "priority_score": round(score, 2)})
    scored.sort(key=lambda item: item["priority_score"], reverse=True)

    recommendations = [
        Recommendation(
            recommendation_id=f"crm-rec-followup-{index + 1}",
            recommendation=f"Contact {row['customer']} about a repeat order.",
            reason=(
                f"No purchase for {row.get('days_inactive') or 'over ' + str(rules.inactive_days)} "
                f"day(s); historical value {row.get('total_purchase')} across "
                f"{row.get('order_count')} order(s)."
            ),
            priority="HIGH" if index == 0 else "MEDIUM",
            supporting_figures={
                "customer": str(row.get("customer")),
                "historical_value": str(row.get("total_purchase")),
                "last_purchase": str(row.get("last_purchase")),
            },
            agent_id="customer_agent",
        )
        for index, row in enumerate(scored[:limit])
    ]
    return recommendations, scored[:limit]
