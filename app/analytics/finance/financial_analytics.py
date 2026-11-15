"""Advanced financial analytics.

Every figure is deterministic and states its basis. Revenue is invoiced value of
completed sales; cash is money actually received. They are never mixed.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.analytics.data_collector import BusinessDataset
from app.analytics.dataset_builder import CASH_IN_CATEGORIES, CASH_OUT_CATEGORIES, AnalyticsDatasetBuilder
from app.analytics.periods import AnalyticsPeriod, previous_period, year_ago
from app.analytics.schemas import (
    DataQuality,
    FinancialAnalytics,
    MetricRow,
    money,
)
from app.utils.date_utils import to_local, utcnow

ZERO = Decimal("0.00")

AGING_BUCKETS = (
    ("Current (not yet due)", 0, 0),
    ("1–30 days", 1, 30),
    ("31–60 days", 31, 60),
    ("61–90 days", 61, 90),
    ("Over 90 days", 91, 100000),
)


class AdvancedFinancialAnalytics:
    """Financial analysis with an explicit statement of what is included."""

    def __init__(self, builder: AnalyticsDatasetBuilder | None = None) -> None:
        self._builder = builder or AnalyticsDatasetBuilder()

    def analyze(self, dataset: BusinessDataset, *, quality: DataQuality | None = None) -> FinancialAnalytics:
        period = dataset.period
        summary = dataset.finance_summary
        revenue = money(summary.get("revenue"))
        cogs = money(summary.get("cogs"))
        expenses = money(summary.get("operating_expenses"))
        gross_profit = money(revenue - cogs)
        cash_received = money(summary.get("cash_received"))
        refunds = money(summary.get("refunds_paid"))
        receivables = money(summary.get("outstanding_receivables"))

        missing_cost = [p for p in dataset.products if Decimal(str(p["cost_price"])) <= ZERO]
        cost_reliable = bool(revenue > ZERO) and not missing_cost

        net_profit: Decimal | None
        profit_components: list[str] = []
        limitations: list[str] = []
        if revenue <= ZERO:
            net_profit = None
            limitations.append("No revenue was recorded, so profit is not meaningful.")
        elif cost_reliable:
            net_profit = money(gross_profit - expenses)
            profit_components = [
                "Revenue: invoiced value of completed sales in the period.",
                "Cost of goods sold: quantity sold × recorded product cost price.",
                "Gross profit = revenue − cost of goods sold.",
                "Net profit = gross profit − operating expenses (capitalised purchases excluded).",
            ]
        else:
            net_profit = None
            profit_components = [
                "Revenue: invoiced value of completed sales in the period.",
                "Cost of goods sold is incomplete: some products have no recorded cost price.",
                "Net profit is therefore not reported — only gross margin on known costs.",
            ]
            limitations.append(
                f"{len(missing_cost)} product(s) have no cost price, so cost of goods sold and "
                "net profit are not reliable."
            )

        gross_margin = (
            (gross_profit / revenue * 100).quantize(Decimal("0.01")) if revenue > ZERO else None
        )
        net_margin = (
            (net_profit / revenue * 100).quantize(Decimal("0.01"))
            if net_profit is not None and revenue > ZERO
            else None
        )

        cash_out = self._cash_out(dataset)
        net_cash = money(cash_received - cash_out)

        result = FinancialAnalytics(
            period_label=period.label,
            revenue=revenue,
            cogs=cogs,
            gross_profit=gross_profit,
            operating_expenses=expenses,
            net_profit=net_profit,
            gross_margin_percent=gross_margin,
            net_margin_percent=net_margin,
            cash_received=cash_received,
            cash_paid_out=cash_out,
            net_cash_flow=net_cash,
            outstanding_receivables=receivables,
            outstanding_payables=None,
            refunds_paid=refunds,
            profit_components=profit_components,
            receivables_aging=self.receivables_aging(dataset.invoices),
            expense_categories=self.expense_categories(dataset.expenses),
            revenue_series=self._builder.series_from_orders(dataset.orders, period),
            expense_series=self._builder.series_from_expenses(dataset.expenses, period),
            cash_in_series=self._builder.series_from_transactions(
                dataset.transactions, period, categories=CASH_IN_CATEGORIES
            ),
            cash_out_series=self._builder.series_from_transactions(
                dataset.transactions, period, categories=CASH_OUT_CATEGORIES
            ),
            comparisons=self.compare_reporting_periods(dataset),
            quality=quality or DataQuality(),
        )
        if limitations:
            result.quality.limitations = list(result.quality.limitations) + limitations
        return result

    # -- components --------------------------------------------------------
    def _cash_out(self, dataset: BusinessDataset) -> Decimal:
        total = ZERO
        for row in dataset.transactions:
            if row["category"] in CASH_OUT_CATEGORIES:
                total += Decimal(str(row["amount"]))
        return money(total)

    def expense_categories(self, expenses: list[dict]) -> list[MetricRow]:
        totals: dict[str, Decimal] = {}
        for expense in expenses:
            category = expense["category"] or "UNCATEGORISED"
            totals[category] = totals.get(category, ZERO) + Decimal(str(expense["amount"]))
        grand = sum(totals.values(), ZERO)
        rows = []
        for category, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True):
            share = (amount / grand * 100).quantize(Decimal("0.01")) if grand > ZERO else ZERO
            rows.append(
                MetricRow(
                    label=category.replace("_", " ").title(),
                    value=money(amount),
                    unit="₹",
                    source="finance_expenses",
                    note=f"{share}% of expenses",
                )
            )
        return rows

    def receivables_aging(self, invoices: list[dict]) -> list[MetricRow]:
        """Aging of open invoices by days past due (from the invoice due date)."""
        today = utcnow()
        buckets: dict[str, Decimal] = {label: ZERO for label, _, _ in AGING_BUCKETS}
        counts: dict[str, int] = {label: 0 for label, _, _ in AGING_BUCKETS}
        for invoice in invoices:
            outstanding = Decimal(str(invoice["outstanding"]))
            if outstanding <= ZERO:
                continue
            due = invoice.get("due_date")
            if due is None:
                days_overdue = 0
            else:
                days_overdue = max(0, (today - due).days)
            for label, low, high in AGING_BUCKETS:
                if low <= days_overdue <= high:
                    buckets[label] += outstanding
                    counts[label] += 1
                    break
        return [
            MetricRow(
                label=label,
                value=money(buckets[label]),
                unit="₹",
                source="sales_invoices",
                note=f"{counts[label]} invoice(s)",
            )
            for label, _, _ in AGING_BUCKETS
        ]

    def compare_reporting_periods(self, dataset: BusinessDataset) -> list[MetricRow]:
        """Month-over-month style comparison against the previous period."""
        current = dataset.finance_summary
        previous = dataset.previous_finance_summary
        if not previous:
            return []
        rows: list[MetricRow] = []
        for key, label in (
            ("revenue", "Revenue"),
            ("operating_expenses", "Operating expenses"),
            ("cash_received", "Cash received"),
            ("outstanding_receivables", "Outstanding receivables"),
        ):
            now_value = money(current.get(key))
            before = money(previous.get(key))
            change = self._change(now_value, before)
            rows.append(
                MetricRow(
                    label=label,
                    value=now_value,
                    unit="₹",
                    source="finance_transactions",
                    note=f"previous period {before:,.2f} ({change})",
                )
            )
        return rows

    def calculate_growth_metrics(self, dataset: BusinessDataset) -> dict[str, Decimal | None]:
        current = dataset.finance_summary
        previous = dataset.previous_finance_summary
        revenue_now = money(current.get("revenue"))
        revenue_before = money(previous.get("revenue")) if previous else ZERO
        expense_now = money(current.get("operating_expenses"))
        expense_before = money(previous.get("operating_expenses")) if previous else ZERO
        return {
            "revenue_growth_percent": self._percent_change(revenue_now, revenue_before),
            "expense_growth_percent": self._percent_change(expense_now, expense_before),
            "cash_growth_percent": self._percent_change(
                money(current.get("cash_received")),
                money(previous.get("cash_received")) if previous else ZERO,
            ),
        }

    def year_over_year(self, dataset: BusinessDataset, analytics_service=None) -> MetricRow | None:
        """Year-over-year comparison, only when a year of history exists."""
        if analytics_service is None:
            return None
        prior = year_ago(dataset.period)
        if prior is None:
            return None
        summary = analytics_service.finance_service.summary(
            date_from=prior.start, date_to=prior.end
        )
        if money(summary.revenue) <= ZERO:
            return None
        change = self._change(money(dataset.finance_summary.get("revenue")), money(summary.revenue))
        return MetricRow(
            label="Revenue vs same period last year",
            value=money(dataset.finance_summary.get("revenue")),
            unit="₹",
            source="finance_transactions",
            note=f"last year {money(summary.revenue):,.2f} ({change})",
        )

    def budget_variance(self, dataset: BusinessDataset) -> list[MetricRow]:
        """Budget comparison. No budget table exists, so this is stated plainly."""
        return [
            MetricRow(
                label="Budget variance",
                value=ZERO,
                unit="₹",
                source="none",
                note="No budgets are configured in this workspace, so budget variance "
                "cannot be calculated.",
            )
        ]

    # -- helpers -----------------------------------------------------------
    def _change(self, now_value: Decimal, before: Decimal) -> str:
        if before <= ZERO:
            return "no prior value"
        change = ((now_value - before) / before * 100).quantize(Decimal("0.01"))
        return f"{'+' if change >= 0 else ''}{change}%"

    def _percent_change(self, now_value: Decimal, before: Decimal) -> Decimal | None:
        if before <= ZERO:
            return None
        return ((now_value - before) / before * 100).quantize(Decimal("0.01"))
