"""Advanced sales analytics: trends, contribution, concentration, decline."""

from __future__ import annotations

from decimal import Decimal

from app.analytics.data_collector import BusinessDataset
from app.analytics.dataset_builder import AnalyticsDatasetBuilder
from app.analytics.schemas import (
    DataQuality,
    MetricRow,
    ProductPerformance,
    SalesAnalytics,
    money,
)

ZERO = Decimal("0.00")

# Documented, configurable classification thresholds (share of units sold and
# growth versus the previous period).
HIGH_PERFORMER_SHARE = Decimal("15.0")   # >= 15% of units and not declining
DECLINING_GROWTH = Decimal("-20.0")      # <= -20% versus the previous period
LOW_VOLUME_UNITS = 2                     # <= 2 units in the period


class AdvancedSalesAnalytics:
    """Sales performance calculated from completed orders only."""

    def __init__(self, builder: AnalyticsDatasetBuilder | None = None) -> None:
        self._builder = builder or AnalyticsDatasetBuilder()

    def analyze(self, dataset: BusinessDataset, *, quality: DataQuality | None = None) -> SalesAnalytics:
        period = dataset.period
        revenue = money(sum(order["total"] for order in dataset.orders))
        units = sum(int(line["quantity"]) for line in dataset.lines)
        order_count = len(dataset.orders)
        aov = (revenue / order_count).quantize(Decimal("0.01")) if order_count else ZERO

        previous_revenue = money(sum(order["total"] for order in dataset.previous_orders))
        growth = (
            ((revenue - previous_revenue) / previous_revenue * 100).quantize(Decimal("0.01"))
            if previous_revenue > ZERO
            else None
        )

        by_product = self.product_performance(dataset)
        total_product_revenue = sum((row.revenue for row in by_product), ZERO)
        customer_totals = self._customer_totals(dataset.orders)

        return SalesAnalytics(
            period_label=period.label,
            total_revenue=revenue,
            order_count=order_count,
            units_sold=units,
            average_order_value=aov,
            growth_percent=growth,
            series=self._builder.series_from_orders(dataset.orders, period),
            by_product=by_product,
            by_category=self._category_totals(dataset, total_product_revenue),
            by_customer=[
                MetricRow(label=name, value=money(total), unit="₹", source="sales_orders")
                for name, total in sorted(customer_totals.items(), key=lambda item: item[1], reverse=True)[:10]
            ],
            concentration_top5_percent=self._concentration(customer_totals),
            declining_products=[row for row in by_product if row.classification == "DECLINING"],
            quality=quality or DataQuality(),
        )

    # -- product performance ----------------------------------------------
    def product_performance(self, dataset: BusinessDataset) -> list[ProductPerformance]:
        totals: dict[int, dict] = {}
        for line in dataset.lines:
            key = line["product_id"]
            entry = totals.setdefault(
                key,
                {
                    "product": line["product"],
                    "sku": line["sku"],
                    "revenue": ZERO,
                    "quantity": 0,
                },
            )
            entry["revenue"] += Decimal(str(line["line_total"]))
            entry["quantity"] += int(line["quantity"])

        previous_units = self._previous_units(dataset)
        total_units = sum(entry["quantity"] for entry in totals.values())
        costs = {product["id"]: Decimal(str(product["cost_price"])) for product in dataset.products}

        rows: list[ProductPerformance] = []
        for product_id, entry in totals.items():
            share = (
                (Decimal(entry["quantity"]) / Decimal(total_units) * 100).quantize(Decimal("0.01"))
                if total_units
                else ZERO
            )
            before = previous_units.get(product_id, 0)
            growth = (
                ((entry["quantity"] - before) / before * 100).quantize(Decimal("0.01"))
                if before > 0
                else None
            )
            classification, reason = self._classify(entry["quantity"], share, growth)
            rows.append(
                ProductPerformance(
                    product_id=product_id,
                    product=entry["product"],
                    sku=entry["sku"],
                    revenue=money(entry["revenue"]),
                    quantity=entry["quantity"],
                    share_percent=share,
                    classification=classification,
                    reason=reason,
                    cost_available=costs.get(product_id, ZERO) > ZERO,
                )
            )
        return sorted(rows, key=lambda row: row.revenue, reverse=True)

    def _classify(self, quantity: int, share: Decimal, growth: Decimal | None) -> tuple[str, str]:
        if growth is not None and growth <= DECLINING_GROWTH:
            return "DECLINING", f"units fell {growth}% versus the previous period"
        if quantity <= LOW_VOLUME_UNITS:
            return "LOW_VOLUME", f"only {quantity} unit(s) sold in this period"
        if share >= HIGH_PERFORMER_SHARE:
            return "HIGH_PERFORMER", f"{share}% of units sold, not declining"
        return "STABLE", f"{share}% of units sold with no significant decline"

    def _previous_units(self, dataset: BusinessDataset) -> dict[int, int]:
        if dataset.comparison is None:
            return {}
        from app.utils.date_utils import to_local

        units: dict[int, int] = {}
        for order in dataset.previous_orders:
            created = to_local(order["created_at"])
            if created is None or not (
                dataset.comparison.local_start <= created <= dataset.comparison.local_end
            ):
                continue
            for line in dataset.lines:
                if line["order_id"] == order["id"]:
                    units[line["product_id"]] = units.get(line["product_id"], 0) + int(line["quantity"])
        return units

    def _customer_totals(self, orders: list[dict]) -> dict[str, Decimal]:
        totals: dict[str, Decimal] = {}
        for order in orders:
            name = order["customer"] or "Walk-in"
            totals[name] = totals.get(name, ZERO) + Decimal(str(order["total"]))
        return totals

    def _concentration(self, totals: dict[str, Decimal]) -> Decimal:
        if not totals:
            return ZERO
        grand = sum(totals.values(), ZERO)
        if grand <= ZERO:
            return ZERO
        top = sum(sorted(totals.values(), reverse=True)[:5], ZERO)
        return (top / grand * 100).quantize(Decimal("0.01"))

    def _category_totals(
        self, dataset: BusinessDataset, total_revenue: Decimal
    ) -> list[MetricRow]:
        categories = {product["id"]: product["category"] for product in dataset.products}
        totals: dict[str, Decimal] = {}
        for line in dataset.lines:
            category = categories.get(line["product_id"], "Uncategorised")
            totals[category] = totals.get(category, ZERO) + Decimal(str(line["line_total"]))
        rows = []
        for category, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True):
            share = (
                (amount / total_revenue * 100).quantize(Decimal("0.01"))
                if total_revenue > ZERO
                else ZERO
            )
            rows.append(
                MetricRow(
                    label=category,
                    value=money(amount),
                    unit="₹",
                    source="sales_order_lines",
                    note=f"{share}% of product revenue",
                )
            )
        return rows

    # -- decline investigation --------------------------------------------
    def investigate_decline(self, dataset: BusinessDataset) -> list[dict]:
        """Explain a sales decline using the records that show it."""
        findings: list[dict] = []
        current = money(sum(order["total"] for order in dataset.orders))
        previous = money(sum(order["total"] for order in dataset.previous_orders))
        if previous <= ZERO:
            return [
                {
                    "finding": "No comparable previous period",
                    "detail": "A decline cannot be assessed without a previous period of data.",
                }
            ]
        change = ((current - previous) / previous * 100).quantize(Decimal("0.01"))
        findings.append(
            {
                "finding": "Revenue change",
                "detail": f"{current:,.2f} versus {previous:,.2f} previously ({change}%).",
            }
        )
        for row in self.product_performance(dataset):
            if row.classification == "DECLINING":
                findings.append(
                    {
                        "finding": f"{row.product} is declining",
                        "detail": row.reason,
                    }
                )
        orders_now = len(dataset.orders)
        orders_before = len(dataset.previous_orders)
        if orders_before and orders_now < orders_before:
            findings.append(
                {
                    "finding": "Fewer orders",
                    "detail": f"{orders_now} completed order(s) versus {orders_before} previously.",
                }
            )
        return findings
