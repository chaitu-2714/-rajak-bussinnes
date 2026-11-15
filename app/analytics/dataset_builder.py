"""Dataset builder: turn records into time series with explicit gaps."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Iterable

from app.analytics.periods import AnalyticsPeriod, buckets_for
from app.analytics.schemas import SeriesPoint

ZERO = Decimal("0.00")

CASH_IN_CATEGORIES = ("CASH_SALE", "PAYMENT_RECEIVED", "SALES_REVENUE")
CASH_OUT_CATEGORIES = ("EXPENSE_PAYMENT", "CASH_REFUND", "SUPPLIER_PAYMENT")


def _to_local(value: datetime) -> datetime:
    from app.utils.date_utils import to_local

    return to_local(value) or value


class AnalyticsDatasetBuilder:
    """Builds period series from real rows, marking empty buckets as gaps."""

    def prepare_analytics_dataset(self, dataset: Any) -> dict[str, Any]:
        period = dataset.period
        return {
            "period": period.label,
            "granularity": period.granularity,
            "order_count": len(dataset.orders),
            "line_count": len(dataset.lines),
            "expense_count": len(dataset.expenses),
            "transaction_count": len(dataset.transactions),
            "customer_count": len(dataset.customers),
            "product_count": len(dataset.products),
        }

    # -- series ------------------------------------------------------------
    def series_from_orders(
        self, orders: Iterable[dict[str, Any]], period: AnalyticsPeriod, *, granularity: str | None = None
    ) -> list[SeriesPoint]:
        buckets = buckets_for(period, granularity)
        totals = {label: ZERO for label, _, _ in buckets}
        counts = {label: 0 for label, _, _ in buckets}
        for order in orders:
            label = self._bucket_label(order["created_at"], buckets)
            if label is None:
                continue
            totals[label] += Decimal(str(order["total"]))
            counts[label] += 1
        return [
            SeriesPoint(
                label=label,
                period_start=start,
                value=totals[label],
                is_gap=counts[label] == 0,
            )
            for label, start, _ in buckets
        ]

    def series_from_expenses(
        self, expenses: Iterable[dict[str, Any]], period: AnalyticsPeriod, *, granularity: str | None = None
    ) -> list[SeriesPoint]:
        buckets = buckets_for(period, granularity)
        totals = {label: ZERO for label, _, _ in buckets}
        counts = {label: 0 for label, _, _ in buckets}
        for expense in expenses:
            label = self._bucket_label(expense["date"], buckets)
            if label is None:
                continue
            totals[label] += Decimal(str(expense["amount"]))
            counts[label] += 1
        return [
            SeriesPoint(label=label, period_start=start, value=totals[label], is_gap=counts[label] == 0)
            for label, start, _ in buckets
        ]

    def series_from_transactions(
        self,
        transactions: Iterable[dict[str, Any]],
        period: AnalyticsPeriod,
        *,
        categories: tuple[str, ...],
        granularity: str | None = None,
    ) -> list[SeriesPoint]:
        buckets = buckets_for(period, granularity)
        totals = {label: ZERO for label, _, _ in buckets}
        counts = {label: 0 for label, _, _ in buckets}
        for row in transactions:
            if row["category"] not in categories:
                continue
            label = self._bucket_label(row["date"], buckets)
            if label is None:
                continue
            totals[label] += Decimal(str(row["amount"]))
            counts[label] += 1
        return [
            SeriesPoint(label=label, period_start=start, value=totals[label], is_gap=counts[label] == 0)
            for label, start, _ in buckets
        ]

    # -- helpers -----------------------------------------------------------
    def _bucket_label(
        self, value: datetime, buckets: list[tuple[str, datetime, datetime]]
    ) -> str | None:
        local = _to_local(value)
        for label, start, end in buckets:
            if start <= local <= end:
                return label
        return None
