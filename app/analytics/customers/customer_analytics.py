"""Customer analytics: acquisition, retention, segmentation, cohorts."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.analytics.data_collector import BusinessDataset
from app.analytics.dataset_builder import AnalyticsDatasetBuilder
from app.analytics.periods import AnalyticsPeriod
from app.analytics.schemas import (
    CustomerAnalytics,
    CustomerSegmentRow,
    DataQuality,
    MetricRow,
    money,
)
from app.utils.date_utils import to_local, utcnow

ZERO = Decimal("0.00")

# Documented segmentation rules (days since last purchase, order count, value).
INACTIVE_DAYS = 90
AT_RISK_DAYS = 60
HIGH_VALUE_ORDERS = 3
HIGH_VALUE_SPEND = Decimal("10000.00")
REGULAR_ORDERS = 2

SEGMENT_RULES = {
    "New": "first purchase within the last 30 days",
    "Regular": f"{REGULAR_ORDERS}+ orders, purchased within {AT_RISK_DAYS} days",
    "High-value": f"{HIGH_VALUE_ORDERS}+ orders or lifetime spend >= {HIGH_VALUE_SPEND:,.2f}",
    "Occasional": "fewer than 2 orders and a low lifetime value",
    "At-risk": f"last purchase {AT_RISK_DAYS}–{INACTIVE_DAYS} days ago",
    "Inactive": f"no purchase for more than {INACTIVE_DAYS} days",
}


class AdvancedCustomerAnalytics:
    """Customer behaviour from real orders, with transparent segment rules."""

    def __init__(self, builder: AnalyticsDatasetBuilder | None = None) -> None:
        self._builder = builder or AnalyticsDatasetBuilder()

    def analyze(self, dataset: BusinessDataset, *, quality: DataQuality | None = None) -> CustomerAnalytics:
        period = dataset.period
        now = utcnow()
        customers = dataset.customers
        active = [customer for customer in customers if customer["active"]]

        new_customers = [
            customer
            for customer in customers
            if customer["created_at"] and period.start <= customer["created_at"] <= period.end
        ]
        repeat = [customer for customer in customers if (customer["orders"] or 0) >= 2]
        inactive = [
            customer
            for customer in customers
            if customer["last_purchase"] and (now - customer["last_purchase"]).days > INACTIVE_DAYS
        ]
        at_risk = [
            customer
            for customer in customers
            if customer["last_purchase"]
            and AT_RISK_DAYS < (now - customer["last_purchase"]).days <= INACTIVE_DAYS
        ]

        orders_by_customer: dict[int, list[dict]] = {}
        for order in dataset.orders:
            orders_by_customer.setdefault(order["customer_id"], []).append(order)

        order_count = len(dataset.orders)
        revenue = money(sum(order["total"] for order in dataset.orders))
        aov = (revenue / order_count).quantize(Decimal("0.01")) if order_count else ZERO

        purchasing_customers = len(orders_by_customer)
        frequency = (
            (Decimal(order_count) / Decimal(purchasing_customers)).quantize(Decimal("0.01"))
            if purchasing_customers
            else None
        )
        repeat_rate = (
            (Decimal(len(repeat)) / Decimal(len(customers)) * 100).quantize(Decimal("0.01"))
            if customers
            else None
        )

        return CustomerAnalytics(
            period_label=period.label,
            total_customers=len(customers),
            active_customers=len(active),
            new_customers=len(new_customers),
            repeat_customers=len(repeat),
            repeat_rate_percent=repeat_rate,
            inactive_customers=len(inactive),
            at_risk_customers=len(at_risk),
            average_order_value=aov,
            average_purchase_frequency=frequency,
            concentration_top5_percent=self._concentration(orders_by_customer),
            segments=self.segment_customers(customers, now),
            top_customers=[
                MetricRow(
                    label=customer["name"],
                    value=money(customer["total_purchase"]),
                    unit="₹",
                    source="customers",
                    note=f"{customer['orders']} order(s)",
                )
                for customer in sorted(
                    customers, key=lambda item: item["total_purchase"], reverse=True
                )[:10]
            ],
            acquisition_series=self._acquisition_series(customers, period),
            cohorts=self.cohort_analysis(dataset, orders_by_customer),
            quality=quality or DataQuality(),
        )

    # -- segmentation ------------------------------------------------------
    def segment_customers(self, customers: list[dict], now: datetime | None = None) -> list[CustomerSegmentRow]:
        now = now or utcnow()
        buckets: dict[str, dict] = {
            name: {"count": 0, "revenue": ZERO} for name in SEGMENT_RULES
        }
        for customer in customers:
            segment = self.segment_of(customer, now)
            buckets[segment]["count"] += 1
            buckets[segment]["revenue"] += Decimal(str(customer["total_purchase"]))
        return [
            CustomerSegmentRow(
                segment=name,
                count=buckets[name]["count"],
                revenue=money(buckets[name]["revenue"]),
                rule=SEGMENT_RULES[name],
            )
            for name in SEGMENT_RULES
        ]

    def segment_of(self, customer: dict, now: datetime | None = None) -> str:
        """Apply the documented rules in order (most specific first)."""
        now = now or utcnow()
        orders = customer["orders"] or 0
        spend = Decimal(str(customer["total_purchase"]))
        last = customer["last_purchase"]
        days = (now - last).days if last else None

        if days is None and orders == 0:
            return "New" if customer["created_at"] and (now - customer["created_at"]).days <= 30 else "Inactive"
        if days is not None and days > INACTIVE_DAYS:
            return "Inactive"
        if days is not None and days > AT_RISK_DAYS:
            return "At-risk"
        if orders >= HIGH_VALUE_ORDERS or spend >= HIGH_VALUE_SPEND:
            return "High-value"
        if orders >= REGULAR_ORDERS:
            return "Regular"
        if customer["created_at"] and (now - customer["created_at"]).days <= 30:
            return "New"
        return "Occasional"

    # -- cohorts -----------------------------------------------------------
    def cohort_analysis(
        self, dataset: BusinessDataset, orders_by_customer: dict[int, list[dict]]
    ) -> list[dict]:
        """Group customers by the month of their first order and show repeat behaviour."""
        first_order: dict[int, datetime] = {}
        for customer_id, orders in orders_by_customer.items():
            earliest = min(order["created_at"] for order in orders)
            first_order[customer_id] = earliest
        cohorts: dict[str, dict] = {}
        for customer_id, first in first_order.items():
            local = to_local(first)
            label = local.strftime("%b %Y") if local else "Unknown"
            entry = cohorts.setdefault(label, {"customers": 0, "repeat": 0, "revenue": ZERO})
            entry["customers"] += 1
            orders = orders_by_customer[customer_id]
            if len(orders) >= 2:
                entry["repeat"] += 1
            entry["revenue"] += sum((Decimal(str(order["total"])) for order in orders), ZERO)
        rows = []
        for label, entry in sorted(cohorts.items()):
            retention = (
                (Decimal(entry["repeat"]) / Decimal(entry["customers"]) * 100).quantize(Decimal("0.01"))
                if entry["customers"]
                else ZERO
            )
            rows.append(
                {
                    "cohort": label,
                    "customers": entry["customers"],
                    "repeat_customers": entry["repeat"],
                    "retention_percent": str(retention),
                    "revenue": str(money(entry["revenue"])),
                }
            )
        return rows

    # -- helpers -----------------------------------------------------------
    def _concentration(self, orders_by_customer: dict[int, list[dict]]) -> Decimal:
        totals = {
            customer_id: sum((Decimal(str(order["total"])) for order in orders), ZERO)
            for customer_id, orders in orders_by_customer.items()
        }
        grand = sum(totals.values(), ZERO)
        if grand <= ZERO:
            return ZERO
        top = sum(sorted(totals.values(), reverse=True)[:5], ZERO)
        return (top / grand * 100).quantize(Decimal("0.01"))

    def _acquisition_series(self, customers: list[dict], period: AnalyticsPeriod):
        buckets = {}
        from app.analytics.periods import buckets_for

        for label, start, end in buckets_for(period):
            buckets[label] = ZERO
        for customer in customers:
            created = to_local(customer["created_at"]) if customer["created_at"] else None
            if created is None:
                continue
            for label, start, end in buckets_for(period):
                if start <= created <= end:
                    buckets[label] += Decimal("1")
                    break
        from app.analytics.schemas import SeriesPoint

        return [
            SeriesPoint(label=label, period_start=start, value=buckets.get(label, ZERO))
            for label, start, _ in buckets_for(period)
        ]
