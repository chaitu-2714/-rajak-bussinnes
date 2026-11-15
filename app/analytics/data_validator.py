"""Data validation and cleaning before any analytics is calculated."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal

from app.analytics.data_collector import BusinessDataset
from app.analytics.schemas import DataIssue, DataQuality
from app.utils.date_utils import utcnow

ZERO = Decimal("0.00")


class AnalyticsDataValidator:
    """Reports what the data can and cannot support. Never invents values."""

    def validate_analytics_data(self, dataset: BusinessDataset) -> DataQuality:
        issues: list[DataIssue] = []
        limitations: list[str] = []

        if not dataset.orders:
            issues.append(
                DataIssue(
                    code="NO_SALES",
                    severity="BLOCKING",
                    message="No completed sales were recorded in this period.",
                    count=0,
                )
            )
            limitations.append("Sales-based analytics cannot be calculated for this period.")

        if dataset.cancelled_orders:
            issues.append(
                DataIssue(
                    code="CANCELLED_SALES_EXCLUDED",
                    severity="INFO",
                    message="Cancelled orders are excluded from revenue and units sold.",
                    count=len(dataset.cancelled_orders),
                )
            )

        duplicate_orders = self._duplicates([order["number"] for order in dataset.orders])
        if duplicate_orders:
            issues.append(
                DataIssue(
                    code="DUPLICATE_ORDER_NUMBERS",
                    severity="WARNING",
                    message="Duplicate order numbers were found and counted once each.",
                    count=len(duplicate_orders),
                )
            )
        duplicate_invoices = self._duplicates([row["number"] for row in dataset.invoices])
        if duplicate_invoices:
            issues.append(
                DataIssue(
                    code="DUPLICATE_INVOICES",
                    severity="WARNING",
                    message="Duplicate invoice numbers were found.",
                    count=len(duplicate_invoices),
                )
            )

        missing_cost = [p for p in dataset.products if Decimal(str(p["cost_price"])) <= ZERO]
        if missing_cost:
            issues.append(
                DataIssue(
                    code="MISSING_COST_PRICE",
                    severity="WARNING",
                    message="Some products have no cost price, so cost of goods sold and "
                    "profit are understated for them.",
                    count=len(missing_cost),
                )
            )
            limitations.append(
                "Cost of goods sold uses recorded product cost prices; products without a "
                "cost price contribute zero cost."
            )

        if dataset.period.local_end > utcnow():
            issues.append(
                DataIssue(
                    code="INCOMPLETE_PERIOD",
                    severity="INFO",
                    message="The reporting period has not finished yet; figures are partial.",
                    count=1,
                )
            )
            limitations.append("The current period is still in progress.")

        reversed_expenses = [
            expense for expense in dataset.expenses if expense.get("status") == "REVERSED"
        ]
        if reversed_expenses:
            issues.append(
                DataIssue(
                    code="REVERSED_EXPENSES_EXCLUDED",
                    severity="INFO",
                    message="Reversed expenses are excluded from expense totals.",
                    count=len(reversed_expenses),
                )
            )

        suppliers_without_lead_time = [
            supplier for supplier in dataset.suppliers if supplier.get("lead_time_days") in (None, 0)
        ]
        if suppliers_without_lead_time and dataset.suppliers:
            issues.append(
                DataIssue(
                    code="SUPPLIER_LEAD_TIME_MISSING",
                    severity="INFO",
                    message="Supplier lead times are not recorded, so lead-time analysis "
                    "falls back to observed purchase order to receipt gaps.",
                    count=len(suppliers_without_lead_time),
                )
            )

        blocking = any(issue.severity == "BLOCKING" for issue in issues)
        completeness = "INSUFFICIENT" if blocking else ("PARTIAL" if any(
            issue.severity == "WARNING" for issue in issues
        ) else "COMPLETE")
        return DataQuality(completeness=completeness, issues=issues, limitations=limitations)

    def _duplicates(self, values: list[str]) -> list[str]:
        counts = Counter(values)
        return [value for value, count in counts.items() if count > 1]


def clean_dataset(dataset: BusinessDataset) -> BusinessDataset:
    """Apply the documented cleaning rules in place and return the dataset."""
    dataset.orders = [order for order in dataset.orders if order["status"] == "COMPLETED"]
    dataset.expenses = [
        expense for expense in dataset.expenses if expense.get("status") != "REVERSED"
    ]
    dataset.invoices = [
        invoice for invoice in dataset.invoices if invoice.get("status") != "CANCELLED"
    ]
    seen: set[str] = set()
    unique_orders = []
    for order in dataset.orders:
        if order["number"] in seen:
            continue
        seen.add(order["number"])
        unique_orders.append(order)
    dataset.orders = unique_orders
    return dataset
