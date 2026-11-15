"""Unit tests for the analytics calculations (tests 1, 2, 3, 4, 6, 14)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.analytics.periods import previous_period, resolve_period
from app.analytics.schemas import DataQuality, FinancialAnalytics, InventoryAnalytics, SalesAnalytics
from app.analytics.risk.business_risk_engine import BusinessRiskAssessmentEngine
from app.core.constants import WorkflowStatus

from tests.analytics_helpers import record_expense, seed_history
from tests.conftest import completed_sale


# ---------------------------------------------------------------------------
# Test 1: financial figures match the recorded rows
# ---------------------------------------------------------------------------
def test_financial_figures_match_the_database(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=4)  # 4 x 150 = 600 revenue
    admin.sales_service.record_payment({"invoice_id": sale["invoice"].id, "amount": "250.00"})
    record_expense(admin, amount="100.00")

    bundle = admin.analytics_service.analyze("MONTHLY")
    financial = bundle.financial

    assert financial.revenue == Decimal("600.00")
    # COGS uses the recorded cost price: 4 x 100
    assert financial.cogs == Decimal("400.00")
    assert financial.gross_profit == Decimal("200.00")
    assert financial.operating_expenses == Decimal("100.00")
    assert financial.net_profit == Decimal("100.00")
    # Cash is what was actually received, not what was invoiced.
    assert financial.cash_received == Decimal("250.00")
    assert financial.outstanding_receivables == Decimal("350.00")
    assert bundle.sales.total_revenue == Decimal("600.00")
    assert bundle.sales.units_sold == 4


# ---------------------------------------------------------------------------
# Test 2: unpaid invoices are not cash
# ---------------------------------------------------------------------------
def test_unpaid_invoice_is_not_counted_as_cash(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    bundle = admin.analytics_service.analyze("MONTHLY")
    assert bundle.financial.revenue == Decimal("300.00")
    assert bundle.financial.cash_received == Decimal("0.00")
    assert bundle.financial.outstanding_receivables == Decimal("300.00")
    assert bundle.financial.net_cash_flow < Decimal("300.00")


# ---------------------------------------------------------------------------
# Test 3: cancelled sales are excluded
# ---------------------------------------------------------------------------
def test_cancelled_sales_are_excluded(admin, business) -> None:
    kept = completed_sale(admin, business, quantity=2)
    cancelled = completed_sale(admin, business, quantity=3)
    admin.sales_service.cancel_order(cancelled["order"].id, "Customer changed their mind")

    bundle = admin.analytics_service.analyze("MONTHLY")
    assert bundle.financial.revenue == Decimal("300.00")  # only the kept order
    assert bundle.sales.order_count == 1
    assert bundle.sales.units_sold == 2
    codes = {issue.code for issue in bundle.quality.issues}
    assert "CANCELLED_SALES_EXCLUDED" in codes
    assert kept["order"].id


# ---------------------------------------------------------------------------
# Test 4: growth across periods
# ---------------------------------------------------------------------------
def test_sales_growth_is_calculated_correctly(admin, business) -> None:
    from datetime import timedelta

    from app.utils.date_utils import utcnow

    # One order this month, two orders last month.
    completed_sale(admin, business, quantity=2)  # 300 this month
    now = utcnow()
    last_month = now - timedelta(days=32)
    for _ in range(2):
        order = admin.sales_service.create_order(
            {
                "customer_id": business["customer"].id,
                "items": [{"product_id": business["tea"].id, "quantity": 1}],
            }
        )
        done = admin.sales_service.complete_order(order.id)
        from tests.analytics_helpers import backdate

        backdate(admin, done.order_number, last_month)

    bundle = admin.analytics_service.analyze("MONTHLY")
    # this month 300 vs previous 300 -> 0%
    assert bundle.financial.revenue == Decimal("300.00")
    assert bundle.sales.growth_percent == Decimal("0.00")

    previous = previous_period(bundle.period)
    assert previous.label != bundle.period.label
    assert previous.local_end < bundle.period.local_start


def test_period_resolution_covers_every_granularity() -> None:
    for granularity in ("DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY"):
        period = resolve_period(granularity)
        assert period.days >= 1
        assert period.start <= period.end
        assert period.label
    with pytest.raises(ValueError):
        resolve_period("FORTNIGHTLY")


# ---------------------------------------------------------------------------
# Test 6: turnover needs cost and inventory data
# ---------------------------------------------------------------------------
def test_inventory_turnover_requires_cost_data(admin, business) -> None:
    no_cost = admin.inventory_service.create_product(
        {
            "product_name": "Mystery Item",
            "category_id": business["category"].id,
            "cost_price": "0.00",
            "selling_price": "20.00",
            "minimum_stock": 1,
        }
    )
    admin.inventory_service.opening_stock(no_cost.id, 5)
    completed_sale(admin, business, quantity=1)

    bundle = admin.analytics_service.analyze("MONTHLY")
    assert bundle.inventory.turnover_ratio is None
    assert "no cost price" in bundle.inventory.turnover_basis.lower()

    codes = {issue.code for issue in bundle.quality.issues}
    assert "MISSING_COST_PRICE" in codes
    # Profit is not claimed when the cost base is incomplete.
    assert bundle.financial.net_profit is None


def test_turnover_is_calculated_when_data_allows(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    bundle = admin.analytics_service.analyze("MONTHLY")
    assert bundle.inventory.turnover_ratio is not None
    assert "cost of goods sold" in bundle.inventory.turnover_basis.lower()


# ---------------------------------------------------------------------------
# Test 14: risk scores follow the documented formula
# ---------------------------------------------------------------------------
def test_risk_scores_follow_the_documented_formula(admin, business) -> None:
    for _ in range(3):
        completed_sale(admin, business, quantity=1)
    bundle = admin.analytics_service.analyze("MONTHLY")
    assert bundle.risks, "risks should be assessed"

    weights = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
    for risk in bundle.risks:
        expected = Decimal(weights[risk.likelihood] * weights[risk.impact])
        assert risk.score == expected, risk.category
        assert "likelihood weight" in risk.formula
        if risk.score >= 7:
            assert risk.severity == "CRITICAL"
        elif risk.score >= 5:
            assert risk.severity == "HIGH"
        elif risk.score >= 3:
            assert risk.severity == "MEDIUM"
        else:
            assert risk.severity == "LOW"


def test_concentrated_revenue_raises_the_risk_score(admin, business) -> None:
    for _ in range(4):
        completed_sale(admin, business, quantity=1)
    bundle = admin.analytics_service.analyze("MONTHLY")
    concentration = next(r for r in bundle.risks if r.risk_key == "REVENUE_CONCENTRATION")
    # One customer buys everything, so the top-5 share is 100%.
    assert Decimal(concentration.evidence["top5_share_percent"]) == Decimal("100.00")
    assert concentration.likelihood == "HIGH"
    # likelihood HIGH (3) x impact HIGH (3) = 9
    assert concentration.impact == "HIGH"
    assert concentration.score == Decimal("9.00")


# ---------------------------------------------------------------------------
# data quality
# ---------------------------------------------------------------------------
def test_empty_period_is_reported_as_insufficient(admin, business) -> None:
    bundle = admin.analytics_service.analyze("MONTHLY")
    assert bundle.quality.completeness == "INSUFFICIENT"
    assert any(issue.code == "NO_SALES" for issue in bundle.quality.issues)
    assert bundle.financial.net_profit is None
    insights = admin.analytics_engine.generate_business_insights(bundle)
    assert any("no completed order" in line.lower() or "0.00 from 0" in line for line in insights)
