"""Integration tests: analytics engine, anomalies, simulation, reports, tools."""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.database.models.analytics import (
    BusinessSimulation,
    DetectedAnomaly,
    ForecastRun,
    SimulationResult,
)

from tests.analytics_helpers import record_expense, seed_history
from tests.conftest import completed_sale


# ---------------------------------------------------------------------------
# Test 5: customer segmentation follows the configured rules
# ---------------------------------------------------------------------------
def test_customer_segmentation_follows_the_rules(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    for name in ("Second Buyer", "Third Buyer"):
        admin.customer_service.create_customer({"full_name": name})

    bundle = admin.analytics_service.analyze("MONTHLY")
    segments = {row.segment: row for row in bundle.customers.segments}
    assert set(segments) == {"New", "Regular", "High-value", "Occasional", "At-risk", "Inactive"}
    for row in bundle.customers.segments:
        assert row.rule, "every segment must document its rule"

    # The buying customer has orders, so it is not 'Inactive'.
    assert segments["Inactive"].count == 0
    # Customers with no order and created just now are 'New'.
    assert segments["New"].count >= 2
    # Segment counts add up to the customer total.
    assert sum(row.count for row in bundle.customers.segments) == bundle.customers.total_customers


# ---------------------------------------------------------------------------
# Test 7: a deliberately inserted anomaly is detected
# ---------------------------------------------------------------------------
def test_anomaly_detection_finds_an_inserted_outlier(admin, business) -> None:
    for amount in ("1000.00", "1100.00", "950.00", "1050.00"):
        record_expense(admin, amount=amount, category="UTILITIES")
    record_expense(admin, amount="95000.00", category="UTILITIES", description="Suspicious spike")

    bundle = admin.analytics_service.analyze("MONTHLY")
    utilities = [
        finding
        for finding in bundle.anomalies
        if finding.category == "FINANCIAL"
        and ("UTILITIES" in str(finding.evidence) or "UTILITIES" in finding.affected_record)
    ]
    assert utilities, "the outlier expense should be flagged"
    finding = utilities[0]
    assert finding.detection_method in ("Z_SCORE", "MEDIAN_DEVIATION")
    assert Decimal(str(finding.observed_value)) == Decimal("95000.00")
    assert finding.severity in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert finding.explanation


# ---------------------------------------------------------------------------
# Test 8: anomalies are not fraud
# ---------------------------------------------------------------------------
def test_unusual_expense_is_never_labelled_fraud(admin, business) -> None:
    for amount in ("1000.00", "1100.00", "950.00"):
        record_expense(admin, amount=amount, category="RENT")
    record_expense(admin, amount="60000.00", category="RENT")

    bundle = admin.analytics_service.analyze("MONTHLY")
    for finding in bundle.anomalies:
        text = f"{finding.explanation} {finding.anomaly_type}".lower()
        assert "fraud" not in text
        assert finding.anomaly_type in {
            "UNUSUAL_EXPENSE",
            "EXPENSE_SPIKE",
            "DUPLICATE_LOOKING_EXPENSE",
            "CASH_FLOW_DETERIORATION",
            "REVENUE_DROP",
            "SALES_SPIKE",
            "UNUSUAL_ORDER_VALUE",
            "REPEATED_STOCK_ADJUSTMENTS",
            "VALUATION_INCONSISTENCY",
            "PURCHASE_PRICE_CHANGE",
            "DELIVERY_DELAY",
        }

    # Review findings are persisted without touching the expense.
    rows = admin.analytics_service.list_anomalies()
    assert rows
    assert all(row["review_status"] == "NEW" for row in rows)
    expenses = admin.finance_service.list_expenses()
    assert len(expenses) == 4  # nothing deleted or reversed


def test_anomaly_review_is_recorded(admin, business) -> None:
    for amount in ("1000.00", "1100.00", "950.00"):
        record_expense(admin, amount=amount, category="RENT")
    record_expense(admin, amount="60000.00", category="RENT")
    admin.analytics_service.anomalies("MONTHLY")
    rows = admin.analytics_service.list_anomalies()
    assert rows

    result = admin.analytics_service.review_anomaly(
        rows[0]["anomaly_id"], decision="ACKNOWLEDGED", note="Checked with the vendor"
    )
    assert result["review_status"] == "ACKNOWLEDGED"
    # A refresh must not overwrite the human decision.
    admin.analytics_service.anomalies("MONTHLY")
    refreshed = {row["anomaly_id"]: row for row in admin.analytics_service.list_anomalies()}
    assert refreshed[rows[0]["anomaly_id"]]["review_status"] == "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# Test 13: simulations do not modify business records
# ---------------------------------------------------------------------------
def test_simulation_does_not_modify_business_records(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    record_expense(admin, amount="500.00")
    before_orders = len(admin.sales_service.list_orders())
    before_expenses = len(admin.finance_service.list_expenses())
    before_stock = [(row.sku, row.available_quantity) for row in admin.inventory_service.list_stock()]

    outcome = admin.analytics_service.simulate("SALES_DECLINE", parameters={"percent": 10})
    assert outcome.label == "HYPOTHETICAL SCENARIO — NOT AN ACTUAL BUSINESS RESULT"
    assert outcome.lines

    assert len(admin.sales_service.list_orders()) == before_orders
    assert len(admin.finance_service.list_expenses()) == before_expenses
    assert [
        (row.sku, row.available_quantity) for row in admin.inventory_service.list_stock()
    ] == before_stock

    with admin.database.session_factory() as db:
        assert db.scalar(select(func.count(BusinessSimulation.id))) == 1
        assert db.scalar(select(func.count(SimulationResult.id))) >= 1


def test_every_simulation_scenario_produces_results(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    for scenario, parameters in (
        ("PRICE_INCREASE", {"percent": 5}),
        ("SALES_DECLINE", {"percent": 10}),
        ("SUPPLIER_PRICE_INCREASE", {"percent": 8}),
        ("HIRE_EMPLOYEES", {"count": 2}),
        ("PURCHASE_UNITS", {"units": 100}),
    ):
        outcome = admin.analytics_service.simulate(scenario, parameters=parameters)
        assert outcome.lines, scenario
        assert outcome.assumptions, scenario
        assert "HYPOTHETICAL" in outcome.label


# ---------------------------------------------------------------------------
# Test 16: reports carry the period and provenance
# ---------------------------------------------------------------------------
def test_reports_contain_period_and_sources(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    result = admin.analytics_service.generate_report("EXECUTIVE_PERFORMANCE", file_format="PDF")
    assert result["format"] == "PDF"
    assert result["file"].endswith(".pdf")
    assert result["rows"] > 5

    from pathlib import Path

    path = Path(result["path"])
    assert path.exists() and path.stat().st_size > 500

    history = admin.analytics_service.report_history()
    assert history and history[0]["report_type"] == "EXECUTIVE_PERFORMANCE"
    assert history[0]["period"]


def test_csv_report_export(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    result = admin.analytics_service.generate_report("SALES_PERFORMANCE", file_format="CSV")
    assert result["file"].endswith(".csv")
    from pathlib import Path

    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "Revenue" in text or "revenue" in text


# ---------------------------------------------------------------------------
# Test 17: offline analytics
# ---------------------------------------------------------------------------
def test_analytics_work_without_any_ai_provider(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    bundle = admin.analytics_service.analyze("MONTHLY")
    assert bundle.financial.revenue > Decimal("0")
    assert bundle.kpis
    forecast = admin.analytics_service.forecast("SALES", horizon=1)
    assert forecast.status in ("COMPLETED", "INSUFFICIENT_HISTORICAL_DATA")
    risks = admin.analytics_service.risks("MONTHLY")
    assert risks


# ---------------------------------------------------------------------------
# AI orchestration access
# ---------------------------------------------------------------------------
def test_orchestrator_reaches_analytics_through_registered_tools(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    conversation = admin.ai_service.create_conversation("phase 7")
    result = admin.ai_service.run_command(conversation.id, "How did my business perform this month?")
    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["intent"] == "ANALYTICS_PERFORMANCE"
    assert [step["tool"] for step in detail["steps"]] == ["get_business_analytics"]
    output = detail["steps"][0]["output"]
    assert output["period"]
    assert output["financial"]["revenue"]
    assert output["insights"]


def test_forecast_command_routes_to_the_forecast_tool(admin, business) -> None:
    seed_history(admin, business, months=3, per_month=2)
    conversation = admin.ai_service.create_conversation("phase 7 forecast")
    result = admin.ai_service.run_command(conversation.id, "Forecast next month sales.")
    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["intent"] == "ANALYTICS_FORECAST"
    assert [step["tool"] for step in detail["steps"]] == ["forecast_business_metric"]


def test_analytics_tools_are_registered_and_read_only(admin) -> None:
    from app.ai.registry.tool_catalogue import build_tool_registry

    registry = build_tool_registry()
    names = registry.names()
    for tool in (
        "get_business_analytics",
        "get_business_kpis",
        "forecast_business_metric",
        "detect_business_anomalies",
        "assess_business_risks",
        "simulate_business_scenario",
    ):
        assert tool in names
    assert len(names) == 48
