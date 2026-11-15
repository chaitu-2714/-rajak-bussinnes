"""KPI engine: every KPI states its formula, period, provenance and completeness."""

from __future__ import annotations

from decimal import Decimal

from app.analytics.schemas import (
    CustomerAnalytics,
    DataQuality,
    FinancialAnalytics,
    InventoryAnalytics,
    KPIItem,
    SalesAnalytics,
    SupplierAnalytics,
    money,
)
from app.utils.date_utils import utcnow

ZERO = Decimal("0.00")


class BusinessKPIEngine:
    """Calculates the KPI board from the analytics results (no separate maths)."""

    def calculate_business_kpis(
        self,
        *,
        financial: FinancialAnalytics,
        sales: SalesAnalytics,
        customers: CustomerAnalytics,
        inventory: InventoryAnalytics,
        suppliers: SupplierAnalytics,
        quality: DataQuality | None = None,
    ) -> list[KPIItem]:
        quality = quality or DataQuality()
        limitations = list(quality.limitations)
        now = utcnow()
        rows: list[KPIItem] = []

        def add(
            key: str,
            name: str,
            category: str,
            formula: str,
            actual: Decimal | None,
            comparison: Decimal | None,
            unit: str,
            source: dict,
            limitation: str | None = None,
        ) -> None:
            completeness = "COMPLETE"
            if actual is None:
                completeness = "INSUFFICIENT"
            elif quality.completeness != "COMPLETE":
                completeness = quality.completeness
            rows.append(
                KPIItem(
                    kpi_key=key,
                    kpi_name=name,
                    category=category,
                    formula=formula,
                    period_label=financial.period_label,
                    actual=actual,
                    comparison=comparison,
                    unit=unit,
                    completeness=completeness,
                    source_records=source,
                    limitation=limitation,
                    updated_at=now,
                )
            )

        # ---- finance
        add(
            "revenue_growth",
            "Revenue growth",
            "Finance",
            "(current revenue − previous revenue) ÷ previous revenue × 100",
            sales.growth_percent,
            None,
            "%",
            {"revenue": str(financial.revenue), "period": financial.period_label},
            "Not calculable without a previous period of revenue.",
        )
        add(
            "gross_margin",
            "Gross margin",
            "Finance",
            "(revenue − cost of goods sold) ÷ revenue × 100",
            financial.gross_margin_percent,
            None,
            "%",
            {"revenue": str(financial.revenue), "cogs": str(financial.cogs)},
            None if financial.cogs > ZERO else "Cost of goods sold is zero or unavailable.",
        )
        add(
            "operating_expense_ratio",
            "Operating expense ratio",
            "Finance",
            "operating expenses ÷ revenue × 100",
            (
                (financial.operating_expenses / financial.revenue * 100).quantize(Decimal("0.01"))
                if financial.revenue > ZERO
                else None
            ),
            None,
            "%",
            {"expenses": str(financial.operating_expenses), "revenue": str(financial.revenue)},
        )
        add(
            "net_cash_flow",
            "Net cash flow",
            "Finance",
            "cash received − cash paid out",
            financial.net_cash_flow,
            None,
            "₹",
            {"cash_in": str(financial.cash_received), "cash_out": str(financial.cash_paid_out)},
        )
        add(
            "outstanding_receivables",
            "Outstanding receivables",
            "Finance",
            "sum of unpaid invoice balances",
            financial.outstanding_receivables,
            None,
            "₹",
            {"invoices": "sales_invoices"},
        )

        # ---- sales
        add(
            "sales_growth",
            "Sales growth",
            "Sales",
            "(current revenue − previous revenue) ÷ previous revenue × 100",
            sales.growth_percent,
            None,
            "%",
            {"orders": sales.order_count},
        )
        add(
            "average_order_value",
            "Average order value",
            "Sales",
            "revenue ÷ number of completed orders",
            sales.average_order_value,
            None,
            "₹",
            {"orders": sales.order_count, "revenue": str(sales.total_revenue)},
        )
        add(
            "units_sold",
            "Units sold",
            "Sales",
            "sum of quantities on completed order lines",
            Decimal(sales.units_sold),
            None,
            "units",
            {"lines": "sales_order_lines"},
        )
        add(
            "product_contribution",
            "Top product contribution",
            "Sales",
            "top product revenue ÷ total product revenue × 100",
            (
                (sales.by_product[0].revenue / sales.total_revenue * 100).quantize(Decimal("0.01"))
                if sales.by_product and sales.total_revenue > ZERO
                else None
            ),
            None,
            "%",
            {"product": sales.by_product[0].product if sales.by_product else None},
        )

        # ---- customers
        add(
            "new_customers",
            "New customers",
            "Customers",
            "customers created within the period",
            Decimal(customers.new_customers),
            None,
            "count",
            {"customers": customers.total_customers},
        )
        add(
            "repeat_purchase_rate",
            "Repeat purchase rate",
            "Customers",
            "customers with 2+ orders ÷ total customers × 100",
            customers.repeat_rate_percent,
            None,
            "%",
            {"repeat_customers": customers.repeat_customers},
        )
        add(
            "inactive_customers",
            "Inactive customers",
            "Customers",
            "customers with no purchase for more than 90 days",
            Decimal(customers.inactive_customers),
            None,
            "count",
            {"at_risk": customers.at_risk_customers},
        )
        add(
            "customer_concentration",
            "Customer concentration",
            "Customers",
            "top 5 customers' revenue ÷ total revenue × 100",
            customers.concentration_top5_percent,
            None,
            "%",
            {"customers": customers.total_customers},
        )

        # ---- inventory
        add(
            "stock_turnover",
            "Stock turnover",
            "Inventory",
            "cost of goods sold ÷ inventory value",
            inventory.turnover_ratio,
            None,
            "ratio",
            {"inventory_value": str(inventory.inventory_value)},
            inventory.turnover_basis if inventory.turnover_ratio is None else None,
        )
        add(
            "low_stock_count",
            "Low-stock items",
            "Inventory",
            "products at or below minimum stock",
            Decimal(inventory.low_stock_count),
            None,
            "count",
            {"skus": inventory.sku_count},
        )
        add(
            "stockout_frequency",
            "Stockout products",
            "Inventory",
            "products with zero stock on hand",
            Decimal(inventory.stockout_products),
            None,
            "count",
            {"skus": inventory.sku_count},
        )
        add(
            "slow_moving_value",
            "Slow-moving stock value",
            "Inventory",
            "sum of the value of stock with no sale for 60+ days",
            money(
                sum(
                    (Decimal(str(row["value"])) for row in inventory.slow_moving + inventory.non_moving),
                    ZERO,
                )
            ),
            None,
            "₹",
            {"items": len(inventory.slow_moving) + len(inventory.non_moving)},
        )

        # ---- suppliers
        add(
            "on_time_delivery",
            "On-time delivery rate",
            "Suppliers",
            "orders received on or before the expected date ÷ measurable orders × 100",
            suppliers.on_time_delivery_percent,
            None,
            "%",
            {"orders": suppliers.purchase_order_count},
            "Only measurable when purchase orders have expected delivery dates.",
        )
        add(
            "average_lead_time",
            "Average lead time",
            "Suppliers",
            "mean days from purchase order to first goods receipt",
            suppliers.average_lead_time_days,
            None,
            "days",
            {"receipts": suppliers.receipt_count},
        )
        add(
            "purchase_price_variation",
            "Purchase price variation",
            "Suppliers",
            "largest recorded change between first and latest unit cost per product",
            self._largest_price_change(suppliers),
            None,
            "%",
            {"products": len(suppliers.price_trends)},
            "Requires at least two purchase orders for the same product.",
        )

        return rows

    def _largest_price_change(self, suppliers: SupplierAnalytics) -> Decimal | None:
        changes = []
        for row in suppliers.price_trends:
            value = row.get("change_percent")
            if value in (None, "not calculable"):
                continue
            changes.append(abs(Decimal(str(value))))
        return max(changes) if changes else None
