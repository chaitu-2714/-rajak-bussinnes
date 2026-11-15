"""Business risk assessment with documented, transparent formulas."""

from __future__ import annotations

from decimal import Decimal

from app.analytics.schemas import (
    CustomerAnalytics,
    FinancialAnalytics,
    InventoryAnalytics,
    RiskItem,
    SalesAnalytics,
    SupplierAnalytics,
    money,
)

ZERO = Decimal("0.00")

LIKELIHOOD_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
IMPACT_WEIGHT = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}

SEVERITY_BANDS = ((7, "CRITICAL"), (5, "HIGH"), (3, "MEDIUM"), (0, "LOW"))


class BusinessRiskAssessmentEngine:
    """Nine business risks, each scored by likelihood × impact (1–9)."""

    def assess(
        self,
        *,
        financial: FinancialAnalytics,
        sales: SalesAnalytics,
        customers: CustomerAnalytics,
        inventory: InventoryAnalytics,
        suppliers: SupplierAnalytics,
    ) -> list[RiskItem]:
        risks = [
            self._cash_flow_risk(financial),
            self._receivables_risk(financial),
            self._revenue_concentration_risk(sales),
            self._customer_dependency_risk(customers),
            self._inventory_shortage_risk(inventory),
            self._excess_inventory_risk(inventory),
            self._supplier_dependency_risk(suppliers),
            self._expense_growth_risk(financial),
            self._sales_decline_risk(sales),
        ]
        return [risk for risk in risks if risk is not None]

    # -- individual risks --------------------------------------------------
    def _cash_flow_risk(self, financial: FinancialAnalytics) -> RiskItem:
        net = financial.net_cash_flow
        expenses = financial.operating_expenses
        likelihood = "LOW"
        if expenses > ZERO and net < ZERO:
            coverage = abs(net) / expenses if expenses else ZERO
            likelihood = "HIGH" if coverage >= Decimal("0.5") else "MEDIUM"
        elif net == ZERO:
            likelihood = "MEDIUM"
        return self._item(
            key="CASH_FLOW",
            category="Cash flow",
            description=(
                f"Net cash flow for {financial.period_label} is {net:,.2f} "
                f"(cash in {financial.cash_received:,.2f}, cash out {financial.cash_paid_out:,.2f})."
            ),
            evidence={
                "net_cash_flow": str(net),
                "cash_received": str(financial.cash_received),
                "cash_paid_out": str(financial.cash_paid_out),
                "operating_expenses": str(expenses),
            },
            likelihood=likelihood,
            impact="HIGH" if net < ZERO else "MEDIUM",
            formula="likelihood = HIGH when net cash flow is negative and at least half of "
            "operating expenses are uncovered; MEDIUM when net cash flow is zero; otherwise LOW. "
            "impact = HIGH when net cash flow is negative.",
            mitigation="Collect receivables, defer discretionary spending, and review the "
            "upcoming expense commitments before committing to new purchases.",
            limitations="Cash flow uses recorded receipts and expenses only; bank balances and "
            "future commitments outside the system are not included.",
        )

    def _receivables_risk(self, financial: FinancialAnalytics) -> RiskItem | None:
        outstanding = financial.outstanding_receivables
        if outstanding <= ZERO:
            return self._item(
                key="RECEIVABLES",
                category="Receivables",
                description="No outstanding receivables were recorded.",
                evidence={"outstanding": str(outstanding)},
                likelihood="LOW",
                impact="LOW",
                formula="No risk when outstanding receivables are zero.",
                mitigation="No action required.",
            )
        old_bucket = next(
            (row for row in financial.receivables_aging if "Over 90" in row.label), None
        )
        old_value = old_bucket.value if old_bucket else ZERO
        share = (old_value / outstanding * 100).quantize(Decimal("0.01")) if outstanding else ZERO
        likelihood = "HIGH" if share >= Decimal("30") else ("MEDIUM" if share > ZERO else "LOW")
        return self._item(
            key="RECEIVABLES",
            category="Receivables",
            description=(
                f"{outstanding:,.2f} is outstanding; {old_value:,.2f} ({share}%) is more than "
                "90 days past due."
            ),
            evidence={
                "outstanding": str(outstanding),
                "over_90_days": str(old_value),
                "share_percent": str(share),
            },
            likelihood=likelihood,
            impact="HIGH" if outstanding > financial.revenue else "MEDIUM",
            formula="likelihood = HIGH when 30% or more of receivables are over 90 days old; "
            "MEDIUM when any amount is over 90 days; otherwise LOW. "
            "impact = HIGH when receivables exceed the period's revenue.",
            mitigation="Follow up on the oldest invoices first and require partial payment "
            "before further credit sales.",
            limitations="Aging uses invoice due dates; actual payment behaviour may differ.",
        )

    def _revenue_concentration_risk(self, sales: SalesAnalytics) -> RiskItem:
        share = sales.concentration_top5_percent
        likelihood = "HIGH" if share >= Decimal("70") else ("MEDIUM" if share >= Decimal("50") else "LOW")
        return self._item(
            key="REVENUE_CONCENTRATION",
            category="Revenue concentration",
            description=(
                f"The top 5 customers account for {share}% of the period's revenue."
            ),
            evidence={"top5_share_percent": str(share), "order_count": sales.order_count},
            likelihood=likelihood,
            impact="HIGH" if share >= Decimal("70") else "MEDIUM",
            formula="likelihood = HIGH when the top 5 customers are 70%+ of revenue, MEDIUM at "
            "50–70%, otherwise LOW.",
            mitigation="Broaden the customer base and protect the key accounts with service "
            "reviews.",
            limitations="Based on completed orders in this period only.",
        )

    def _customer_dependency_risk(self, customers: CustomerAnalytics) -> RiskItem:
        inactive = customers.inactive_customers
        total = max(1, customers.total_customers)
        share = (Decimal(inactive) / Decimal(total) * 100).quantize(Decimal("0.01"))
        likelihood = "HIGH" if share >= Decimal("40") else ("MEDIUM" if share >= Decimal("20") else "LOW")
        return self._item(
            key="CUSTOMER_DEPENDENCY",
            category="Customer dependency",
            description=(
                f"{inactive} of {customers.total_customers} customer(s) ({share}%) have not "
                "purchased in over 90 days; "
                f"{customers.at_risk_customers} more are at risk."
            ),
            evidence={
                "inactive_customers": inactive,
                "at_risk_customers": customers.at_risk_customers,
                "share_percent": str(share),
                "repeat_rate_percent": str(customers.repeat_rate_percent),
            },
            likelihood=likelihood,
            impact="MEDIUM",
            formula="likelihood = HIGH when 40%+ of customers are inactive, MEDIUM at 20–40%, "
            "otherwise LOW.",
            mitigation="Run follow-up campaigns for at-risk customers and ask inactive ones why "
            "they stopped.",
            limitations="Inactivity is measured from recorded purchase dates only.",
        )

    def _inventory_shortage_risk(self, inventory: InventoryAnalytics) -> RiskItem:
        low = inventory.low_stock_count
        total = max(1, inventory.sku_count)
        share = (Decimal(low) / Decimal(total) * 100).quantize(Decimal("0.01"))
        likelihood = "HIGH" if share >= Decimal("30") else ("MEDIUM" if low else "LOW")
        return self._item(
            key="INVENTORY_SHORTAGE",
            category="Inventory shortage",
            description=(
                f"{low} of {inventory.sku_count} SKU(s) are at or below minimum stock and "
                f"{inventory.stockout_products} are out of stock."
            ),
            evidence={
                "low_stock_count": low,
                "stockout_products": inventory.stockout_products,
                "share_percent": str(share),
            },
            likelihood=likelihood,
            impact="HIGH" if inventory.stockout_products else "MEDIUM",
            formula="likelihood = HIGH when 30%+ of SKUs are at or below minimum stock, MEDIUM "
            "when any SKU is low, otherwise LOW.",
            mitigation="Raise purchase orders for the fast-moving low-stock items first.",
            limitations="Demand estimates use sales recorded in the reporting period.",
        )

    def _excess_inventory_risk(self, inventory: InventoryAnalytics) -> RiskItem:
        overstock = len(inventory.overstock)
        likelihood = "HIGH" if overstock >= 5 else ("MEDIUM" if overstock else "LOW")
        return self._item(
            key="EXCESS_INVENTORY",
            category="Excess inventory",
            description=(
                f"{overstock} SKU(s) hold more than 90 days of cover at current demand; "
                f"inventory value is {inventory.inventory_value:,.2f}."
            ),
            evidence={
                "overstock_skus": overstock,
                "inventory_value": str(inventory.inventory_value),
                "slow_moving": len(inventory.slow_moving),
                "non_moving": len(inventory.non_moving),
            },
            likelihood=likelihood,
            impact="MEDIUM",
            formula="likelihood = HIGH at 5+ overstocked SKUs, MEDIUM for any, otherwise LOW.",
            mitigation="Stop reordering slow movers and consider promotions on the oldest stock.",
            limitations="Slow-moving stock is not the same as obsolete stock.",
        )

    def _supplier_dependency_risk(self, suppliers: SupplierAnalytics) -> RiskItem:
        share = suppliers.concentration_top3_percent
        likelihood = "HIGH" if share >= Decimal("80") else ("MEDIUM" if share >= Decimal("60") else "LOW")
        return self._item(
            key="SUPPLIER_DEPENDENCY",
            category="Supplier dependency",
            description=(
                f"The top 3 suppliers account for {share}% of purchase value "
                f"({suppliers.purchase_order_count} order(s) in this period)."
            ),
            evidence={
                "top3_share_percent": str(share),
                "supplier_count": suppliers.supplier_count,
                "on_time_percent": str(suppliers.on_time_delivery_percent),
            },
            likelihood=likelihood,
            impact="MEDIUM",
            formula="likelihood = HIGH when the top 3 suppliers are 80%+ of purchase value, "
            "MEDIUM at 60–80%, otherwise LOW.",
            mitigation="Qualify a second supplier for the most critical products.",
            limitations="On-time delivery is only measurable when expected dates exist.",
        )

    def _expense_growth_risk(self, financial: FinancialAnalytics) -> RiskItem:
        change = None
        for row in financial.comparisons:
            if row.label == "Operating expenses" and row.note:
                try:
                    change = Decimal(row.note.split("(")[-1].rstrip(")").replace("%", ""))
                except Exception:  # noqa: BLE001
                    change = None
        likelihood = "LOW"
        if change is not None and change > ZERO:
            likelihood = "HIGH" if change >= Decimal("25") else ("MEDIUM" if change >= Decimal("10") else "LOW")
        return self._item(
            key="EXPENSE_GROWTH",
            category="Expense growth",
            description=(
                f"Operating expenses for {financial.period_label} were "
                f"{financial.operating_expenses:,.2f}"
                + (f", a change of {change}% versus the previous period." if change is not None else ".")
            ),
            evidence={
                "operating_expenses": str(financial.operating_expenses),
                "change_percent": str(change) if change is not None else "not available",
            },
            likelihood=likelihood,
            impact="MEDIUM",
            formula="likelihood = HIGH when expenses grew 25%+ versus the previous period, "
            "MEDIUM at 10–25%, otherwise LOW.",
            mitigation="Review the largest expense categories and renegotiate recurring costs.",
            limitations="A change is only computed when the previous period has expenses.",
        )

    def _sales_decline_risk(self, sales: SalesAnalytics) -> RiskItem:
        growth = sales.growth_percent
        likelihood = "LOW"
        if growth is not None and growth < ZERO:
            likelihood = "HIGH" if growth <= Decimal("-20") else "MEDIUM"
        return self._item(
            key="SALES_DECLINE",
            category="Sales decline",
            description=(
                f"Revenue for {sales.period_label} was {sales.total_revenue:,.2f}"
                + (
                    f", a change of {growth}% versus the previous period."
                    if growth is not None
                    else "; no comparable previous period exists."
                )
            ),
            evidence={
                "total_revenue": str(sales.total_revenue),
                "growth_percent": str(growth) if growth is not None else "not available",
                "declining_products": [row.product for row in sales.declining_products],
            },
            likelihood=likelihood,
            impact="HIGH" if growth is not None and growth <= Decimal("-20") else "MEDIUM",
            formula="likelihood = HIGH when revenue fell 20%+, MEDIUM for any decline, "
            "otherwise LOW.",
            mitigation="Investigate the declining products and contact the customers who stopped "
            "buying them.",
            limitations="A decline is only measurable when the previous period has revenue.",
        )

    # -- scoring -----------------------------------------------------------
    def _item(
        self,
        *,
        key: str,
        category: str,
        description: str,
        evidence: dict,
        likelihood: str,
        impact: str,
        formula: str,
        mitigation: str,
        limitations: str | None = None,
    ) -> RiskItem:
        score = Decimal(LIKELIHOOD_WEIGHT[likelihood] * IMPACT_WEIGHT[impact])
        severity = next(
            label for threshold, label in SEVERITY_BANDS if score > threshold
        )
        return RiskItem(
            risk_key=key,
            category=category,
            description=description,
            evidence=evidence,
            likelihood=likelihood,
            impact=impact,
            severity=severity,
            score=score.quantize(Decimal("0.01")),
            formula=formula + " score = likelihood weight × impact weight (1–3 each, 1–9 total); "
            "severity bands: 7+ CRITICAL, 5–6 HIGH, 3–4 MEDIUM, 1–2 LOW.",
            mitigation=mitigation,
            data_limitations=limitations,
        )
