"""Unit tests: deterministic agent analysis functions."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.ai.agent_tools.business_tools import (
    compare_periods,
    dedupe_findings,
    simulate_price_change,
)
from app.ai.agent_tools.customer_tools import (
    SegmentationRules,
    classify_customer,
    find_inactive_customers,
    prioritise_followups,
    segment_customers,
)
from app.ai.agent_tools.finance_tools import (
    AnomalyThresholds,
    analyse_profit,
    analyse_revenue,
    detect_expense_anomalies,
)
from app.ai.agent_tools.inventory_tools import (
    ReorderPolicy,
    calculate_reorder,
    detect_dead_stock,
    detect_overstock,
)
from app.ai.agent_tools.sales_tools import analyse_products, analyse_sales_performance
from app.ai.schemas.agent_schema import AgentResult, ConfidenceCalculator, Finding, Evidence
from app.utils.date_utils import utcnow


# ---------------------------------------------------------------------------
# finance
# ---------------------------------------------------------------------------
def test_revenue_finding_cites_evidence() -> None:
    findings, metrics = analyse_revenue(
        current={"revenue": "1000.00", "refunds_paid": "0.00"},
        previous=None,
        period_label="this month",
    )
    assert findings[0].finding_type == "REVENUE_LEVEL"
    assert findings[0].evidence[0].value == "1,000.00"
    assert metrics["revenue"] == "1,000.00"


def test_revenue_decline_is_detected() -> None:
    findings, metrics = analyse_revenue(
        current={"revenue": "700.00"},
        previous={"revenue": "1000.00", "period": "last month"},
        period_label="this month",
    )
    types = {finding.finding_type for finding in findings}
    assert "REVENUE_DECLINE" in types
    assert metrics["revenue_change_pct"] == -30.0
    decline = next(f for f in findings if f.finding_type == "REVENUE_DECLINE")
    assert decline.severity == "HIGH"


def test_profit_margins_are_computed_from_records() -> None:
    findings, metrics = analyse_profit(
        profit={
            "revenue": "1000.00",
            "cogs": "600.00",
            "gross_profit": "400.00",
            "operating_expenses": "250.00",
            "net_profit": "150.00",
        },
        revenue={"revenue": "1000.00"},
        period_label="this month",
    )
    assert metrics["gross_margin_pct"] == 40.0
    assert metrics["net_margin_pct"] == 15.0
    assert any(f.finding_type == "PROFIT_MARGIN" for f in findings)


def test_no_revenue_is_reported_not_invented() -> None:
    findings, _ = analyse_profit(
        profit={"revenue": "0.00", "gross_profit": "0.00", "net_profit": "0.00"},
        revenue={"revenue": "0.00"},
        period_label="this month",
    )
    assert findings[0].finding_type == "NO_REVENUE"


def test_expense_anomaly_detection_flags_outlier() -> None:
    expenses = [
        {"expense_number": "E1", "expense_category": "RENT", "amount": "1000.00"},
        {"expense_number": "E2", "expense_category": "RENT", "amount": "1050.00"},
        {"expense_number": "E3", "expense_category": "RENT", "amount": "980.00"},
        {"expense_number": "E4", "expense_category": "MAINTENANCE", "amount": "9000.00"},
    ]
    findings, anomalies = detect_expense_anomalies(expenses)
    assert anomalies
    assert anomalies[0]["expense"] == "E4"
    assert findings[0].finding_type == "EXPENSE_ANOMALY"
    assert findings[0].evidence


def test_anomaly_detection_needs_enough_history() -> None:
    findings, anomalies = detect_expense_anomalies(
        [{"expense_number": "E1", "amount": "100.00"}, {"expense_number": "E2", "amount": "5000.00"}],
        thresholds=AnomalyThresholds(minimum_history=3),
    )
    assert findings == [] and anomalies == []


def test_anomaly_detection_ignores_uniform_expenses() -> None:
    expenses = [
        {"expense_number": f"E{i}", "expense_category": "RENT", "amount": "1000.00"}
        for i in range(6)
    ]
    findings, anomalies = detect_expense_anomalies(expenses)
    assert findings == [] and anomalies == []


# ---------------------------------------------------------------------------
# sales
# ---------------------------------------------------------------------------
def test_sales_performance_separates_quantity_and_revenue() -> None:
    findings, metrics = analyse_sales_performance(
        summary={
            "completed_orders": 3,
            "sales_value": "1200.00",
            "average_order_value": "400.00",
            "pending_orders": 1,
            "total_orders": 4,
        },
        trends={"monthly": []},
        period_label="this month",
    )
    assert metrics["completed_orders"] == 3
    assert metrics["pending_orders"] == 1
    assert any(f.finding_type == "PENDING_ORDERS" for f in findings)


def test_top_product_analysis_reports_both_dimensions() -> None:
    findings, metrics = analyse_products(
        products=[
            {"product": "Tea", "quantity": 10, "revenue": "2600.00"},
            {"product": "Coffee", "quantity": 30, "revenue": "1600.00"},
        ],
        period_label="this month",
    )
    assert metrics["top_product"] == "Tea"
    assert metrics["top_product_quantity"] == 10
    assert findings[0].finding_type == "TOP_PRODUCT"


def test_sales_decline_from_monthly_trend() -> None:
    findings, metrics = analyse_sales_performance(
        summary={"completed_orders": 2, "sales_value": "500.00"},
        trends={
            "monthly": [
                {"month": "Sep 26", "sales": "1000.00"},
                {"month": "Oct 26", "sales": "500.00"},
            ]
        },
        period_label="this month",
    )
    assert metrics["month_over_month_pct"] == -50.0
    assert any(f.finding_type == "SALES_DECLINE" for f in findings)


# ---------------------------------------------------------------------------
# customers
# ---------------------------------------------------------------------------
def _customer(days_ago: int | None, orders: int, value: str, created_days: int = 200) -> dict:
    now = utcnow()
    return {
        "full_name": f"Customer {days_ago}-{orders}",
        "order_count": orders,
        "total_purchase": value,
        "last_purchase_at": (now - timedelta(days=days_ago)).strftime("%d %b %Y")
        if days_ago is not None
        else None,
        "created_at": (now - timedelta(days=created_days)).strftime("%d %b %Y"),
    }


def test_segmentation_rules_are_transparent() -> None:
    rules = SegmentationRules()
    now = utcnow()
    assert classify_customer(_customer(5, 5, "1000.00"), rules, now) == "Regular"
    assert classify_customer(_customer(10, 1, "90000.00"), rules, now) == "High value"
    assert classify_customer(_customer(200, 4, "5000.00"), rules, now) == "Inactive"
    assert classify_customer(_customer(10, 2, "1000.00"), rules, now) == "Occasional"
    assert classify_customer(_customer(None, 0, "0.00", created_days=5), rules, now) == "New"


def test_segment_counts_and_evidence() -> None:
    customers = [_customer(5, 5, "1000.00"), _customer(200, 3, "2000.00")]
    findings, metrics = segment_customers(
        customers=customers, rules=SegmentationRules(), period_label="all time"
    )
    assert metrics["total_customers"] == 2
    assert sum(metrics["segments"].values()) == 2
    assert findings[0].evidence


def test_inactive_detection_uses_the_threshold() -> None:
    customers = [_customer(10, 3, "1000.00"), _customer(100, 3, "5000.00")]
    findings, inactive = find_inactive_customers(
        customers=customers, days=60, period_label="all time"
    )
    assert len(inactive) == 1
    assert inactive[0]["total_purchase"] == "5000.00"
    assert findings[0].severity in ("MEDIUM", "HIGH")


def test_followup_priority_ranks_by_value_and_recency() -> None:
    inactive = [
        {"customer": "Small", "total_purchase": "100.00", "days_inactive": 70, "order_count": 1},
        {"customer": "Big", "total_purchase": "9000.00", "days_inactive": 200, "order_count": 6},
    ]
    recommendations, ranked = prioritise_followups(
        inactive=inactive, rules=SegmentationRules(), limit=2
    )
    assert ranked[0]["customer"] == "Big"
    assert recommendations[0].priority == "HIGH"
    assert "9000.00" in recommendations[0].reason


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------
def test_reorder_point_formula() -> None:
    calculation = calculate_reorder(
        available=5,
        minimum=10,
        units_per_day=2.0,
        policy=ReorderPolicy(lead_time_days=7, safety_days=7, review_days=30),
    )
    assert calculation["reorder_point"] == 28.0  # 2*7 + 2*7
    assert calculation["suggested_quantity"] == 83  # 28 + 60 - 5
    assert calculation["days_of_cover"] == 2.5


def test_reorder_reports_missing_inputs() -> None:
    calculation = calculate_reorder(
        available=0, minimum=5, units_per_day=None, policy=ReorderPolicy()
    )
    assert any("velocity" in gap for gap in calculation["missing_inputs"])
    assert any("lead time" in gap for gap in calculation["missing_inputs"])
    assert calculation["suggested_quantity"] == 0


def test_overstock_detection() -> None:
    stock = [{"product": "Tea", "sku": "SKU-1", "available": 500, "stock_value": "90000.00"}]
    findings, overstocked = detect_overstock(
        stock_rows=stock, velocity_by_product={"SKU-1": 1.0}, policy=ReorderPolicy(overstock_days=60)
    )
    assert overstocked and overstocked[0]["days_of_cover"] == 500.0
    assert findings[0].finding_type == "OVERSTOCK"


def test_dead_stock_detection_is_not_an_obsolete_claim() -> None:
    stock = [{"product": "Old", "sku": "SKU-9", "available": 10, "stock_value": "500.00"}]
    findings, dead = detect_dead_stock(
        stock_rows=stock, last_sold={"SKU-9": None}, policy=ReorderPolicy()
    )
    assert len(dead) == 1
    assert "not by itself mean" in findings[0].description


# ---------------------------------------------------------------------------
# business intelligence helpers
# ---------------------------------------------------------------------------
def test_duplicate_findings_are_merged() -> None:
    finding = Finding(
        finding_id="a",
        finding_type="LOW_STOCK",
        description="3 products are low",
        severity="MEDIUM",
        evidence=[Evidence(source="x", metric="m", value="1")],
    )
    duplicate = finding.model_copy(update={"finding_id": "b", "severity": "HIGH"})
    merged = dedupe_findings(
        [
            AgentResult(agent_id="a1", task_id="t", findings=[finding]),
            AgentResult(agent_id="a2", task_id="t", findings=[duplicate]),
        ]
    )
    assert len(merged) == 1
    assert merged[0].severity == "HIGH"


def test_period_comparison_maths() -> None:
    findings, metrics = compare_periods(
        current={"revenue": "1200.00", "operating_expenses": "900.00"},
        previous={"revenue": "1000.00", "operating_expenses": "600.00"},
        period_label="comparison",
        label_current="Oct",
        label_previous="Sep",
    )
    assert metrics["revenue"]["change_pct"] == 20.0
    assert metrics["operating_expenses"]["change_pct"] == 50.0
    assert any(f.finding_type == "PERIOD_COMPARISON" for f in findings)


def test_price_change_simulation_is_labelled_hypothetical() -> None:
    result = simulate_price_change(
        products=[{"product": "Tea", "quantity": 10, "revenue": "1000.00"}], change_pct=5
    )
    assert result["simulated_revenue"] == "1,050.00"
    assert "Hypothetical" in result["assumption"]


# ---------------------------------------------------------------------------
# confidence
# ---------------------------------------------------------------------------
def test_confidence_rules_are_deterministic() -> None:
    calculator = ConfidenceCalculator()
    high, basis_high = calculator.compute(
        evidence_sources={"a", "b", "c", "d"}, tools_requested=4, tools_failed=0, data_gaps=0
    )
    low, basis_low = calculator.compute(
        evidence_sources={"a"}, tools_requested=4, tools_failed=3, data_gaps=2
    )
    assert high == 0.90  # base 0.45 + 4 sources (0.40) + all tools (0.05)
    assert low < high
    assert "sources" in basis_high and "failed" in basis_low


def test_confidence_floor_and_ceiling() -> None:
    calculator = ConfidenceCalculator()
    floor, _ = calculator.compute(
        evidence_sources=set(), tools_requested=5, tools_failed=5, data_gaps=5
    )
    assert floor == ConfidenceCalculator.FLOOR
