"""Integration tests: the five specialist agents on real business records."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.ai.agents.business_intelligence_agent import TASK_BUSINESS_HEALTH, TASK_RISK_ANALYSIS
from app.ai.agents.finance_agent import TASK_EXPENSE_ANOMALIES
from app.ai.agents.inventory_agent import TASK_REORDER
from app.ai.schemas.agent_schema import AgentTask
from app.core.exceptions import NotFoundError
from app.database.models.agents import (
    Agent,
    AgentExecution,
    AgentFinding,
    AgentMemory,
    AgentRecommendation,
)

from tests.conftest import completed_sale


@pytest.fixture()
def trading(admin, business) -> dict:
    """Business data with completed sales, payments and expenses."""
    for index, quantity in enumerate((2, 3, 1)):
        sale = completed_sale(admin, business, quantity=quantity)
        # Partial payments only: an amount above the outstanding balance is refused.
        admin.sales_service.record_payment(
            {"invoice_id": sale["invoice"].id, "amount": str(50 * (index + 1))}
        )
    for amount, category, description in (
        ("5000.00", "RENT", "Shop rent"),
        ("800.00", "UTILITIES", "Electricity"),
        ("700.00", "TRANSPORT", "Fuel"),
        ("25000.00", "MAINTENANCE", "Compressor replacement"),
    ):
        admin.finance_service.create_expense(
            {
                "expense_category": category,
                "description": description,
                "amount": amount,
                "payment_method": "CASH",
                "expense_date": "2026-11-02T10:00:00",
            }
        )
    return business


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------
def test_all_five_agents_are_registered_and_persisted(admin) -> None:
    codes = admin.agent_coordinator.agent_ids()
    assert codes == [
        "business_intelligence_agent",
        "customer_agent",
        "finance_agent",
        "inventory_agent",
        "sales_agent",
    ]
    with admin.database.session_factory() as db:
        rows = db.scalars(select(Agent)).all()
    assert len(rows) == 5
    assert {row.agent_code for row in rows} == set(codes)


# ---------------------------------------------------------------------------
# finance agent
# ---------------------------------------------------------------------------
def test_finance_agent_analyses_real_records(admin, trading) -> None:
    result = admin.agent_manager.run_agent("finance_agent", period="this_month")
    assert result.status == "COMPLETED"
    assert result.confidence >= 0.6
    assert result.findings
    types = {finding.finding_type for finding in result.findings}
    assert "REVENUE_LEVEL" in types
    assert "PROFIT_MARGIN" in types
    assert result.metrics["revenue"]
    for finding in result.findings:
        assert finding.evidence
        assert finding.agent_id == "finance_agent"


def test_finance_agent_detects_expense_anomalies(admin, trading) -> None:
    result = admin.agent_manager.run_agent(
        "finance_agent", period="this_month", task_type=TASK_EXPENSE_ANOMALIES
    )
    assert result.metrics["expense_anomalies"]
    assert any(
        finding.finding_type == "EXPENSE_ANOMALY" for finding in result.findings
    )
    assert any(rec.recommendation_id.startswith("fin-rec") for rec in result.recommendations)


def test_finance_agent_with_no_data_reports_gaps(admin) -> None:
    result = admin.agent_manager.run_agent("finance_agent", period="this_month")
    assert result.status == "COMPLETED"
    assert result.confidence <= 0.75
    assert any(finding.finding_type == "NO_REVENUE" for finding in result.findings)


# ---------------------------------------------------------------------------
# sales agent
# ---------------------------------------------------------------------------
def test_sales_agent_reports_products_and_demand(admin, trading) -> None:
    result = admin.agent_manager.run_agent("sales_agent", period="this_month")
    assert result.status == "COMPLETED"
    assert result.metrics["completed_orders"] >= 1
    assert result.metrics["top_product"]
    assert any(finding.finding_type == "TOP_PRODUCT" for finding in result.findings)
    assert any(finding.finding_type == "DEMAND_LEVEL" for finding in result.findings)


def test_sales_agent_with_empty_history(admin) -> None:
    result = admin.agent_manager.run_agent("sales_agent", period="this_month")
    assert result.status == "COMPLETED"
    assert result.findings == [] or result.metrics["completed_orders"] == 0
    assert result.data_gaps


# ---------------------------------------------------------------------------
# customer agent
# ---------------------------------------------------------------------------
def test_customer_agent_segments_and_values(admin, trading) -> None:
    result = admin.agent_manager.run_agent("customer_agent")
    assert result.status == "COMPLETED"
    assert result.metrics["total_customers"] >= 1
    assert sum(result.metrics["segments"].values()) == result.metrics["total_customers"]
    assert any(finding.finding_type == "SEGMENTATION" for finding in result.findings)
    assert result.metrics["rules"]["inactive_days"] == 90


def test_customer_agent_proposes_followups_for_lapsed_customers(admin, business) -> None:
    from datetime import timedelta

    from app.database.models.crm import Customer
    from app.utils.date_utils import utcnow

    sale = completed_sale(admin, business, quantity=1)
    with admin.database.session_factory() as db:
        customer = db.get(Customer, business["customer"].id)
        customer.created_at = utcnow() - timedelta(days=400)
        db.commit()
    with admin.database.session_factory() as db:
        from app.database.models.sales import SalesOrder

        order = db.scalars(select(SalesOrder)).first()
        order.created_at = utcnow() - timedelta(days=150)
        db.commit()

    result = admin.agent_manager.run_agent("customer_agent")
    assert result.metrics["inactive_customers"] >= 1
    assert any(rec.recommendation_id.startswith("crm-rec-followup") for rec in result.recommendations)


# ---------------------------------------------------------------------------
# inventory agent
# ---------------------------------------------------------------------------
def test_inventory_agent_detects_low_stock_and_reorders(admin, business) -> None:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 8,
            "movement_type": "ADJUSTMENT",
            "reason": "Breakage",
            "direction": -1,
        }
    )
    completed_sale(admin, business, quantity=1)

    result = admin.agent_manager.run_agent(
        "inventory_agent", task_type=TASK_REORDER
    )
    assert result.status == "COMPLETED"
    assert any(finding.finding_type == "LOW_STOCK" for finding in result.findings)
    reorder = result.metrics["reorder_analysis"]
    assert reorder
    tea_row = next(row for row in reorder if row["sku"] == business["tea"].sku)
    assert tea_row["suggested_quantity"] >= 0
    assert any("lead time" in gap for gap in result.data_gaps)


def test_inventory_agent_never_creates_purchase_orders(admin, business) -> None:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 9,
            "movement_type": "ADJUSTMENT",
            "reason": "Breakage",
            "direction": -1,
        }
    )
    before = len(admin.purchasing_service.list_purchase_orders())
    admin.agent_manager.run_agent("inventory_agent")
    after = len(admin.purchasing_service.list_purchase_orders())
    assert before == after


# ---------------------------------------------------------------------------
# business intelligence agent
# ---------------------------------------------------------------------------
def test_bi_agent_runs_the_specialists_and_finds_risks(admin, trading) -> None:
    result = admin.agent_manager.run_agent(
        "business_intelligence_agent", period="this_month", task_type=TASK_BUSINESS_HEALTH
    )
    assert result.status == "COMPLETED"
    agents_run = result.metrics["agents_run"]
    assert set(agents_run) == {
        "finance_agent",
        "sales_agent",
        "customer_agent",
        "inventory_agent",
    }
    assert result.metrics["risk_count"] >= 1
    assert any(finding.finding_type == "BUSINESS_RISK" for finding in result.findings)
    assert result.recommendations


def test_bi_agent_risk_analysis_task(admin, trading) -> None:
    result = admin.agent_manager.run_agent(
        "business_intelligence_agent", period="this_month", task_type=TASK_RISK_ANALYSIS
    )
    assert result.status == "COMPLETED"
    assert result.metrics["risk_count"] >= 1


# ---------------------------------------------------------------------------
# persistence, memory and recommendations
# ---------------------------------------------------------------------------
def test_execution_history_is_persisted(admin, trading) -> None:
    result = admin.agent_manager.run_agent("finance_agent", period="this_month")
    with admin.database.session_factory() as db:
        executions = db.scalars(select(AgentExecution)).all()
        findings = db.scalars(select(AgentFinding)).all()
        recommendations = db.scalars(select(AgentRecommendation)).all()
        memories = db.scalars(select(AgentMemory)).all()
    assert len(executions) == 1
    assert executions[0].status == "COMPLETED"
    assert executions[0].confidence == result.confidence
    assert len(findings) == len(result.findings)
    assert len(recommendations) == len(result.recommendations)
    assert memories, "a snapshot should be written to agent memory"


def test_agent_detail_and_stats(admin, trading) -> None:
    admin.agent_manager.run_agent("sales_agent", period="this_month")
    detail = admin.agent_manager.agent_detail("sales_agent")
    assert detail["info"]["agent_code"] == "sales_agent"
    assert detail["stats"]["executions"] == 1
    assert detail["executions"][0]["status"] == "COMPLETED"
    assert detail["findings"]
    agents = admin.agent_manager.list_agents()
    sales = next(agent for agent in agents if agent["info"]["agent_code"] == "sales_agent")
    assert sales["completed"] == 1


def test_recommendation_status_can_be_updated(admin, trading) -> None:
    admin.agent_manager.run_agent("finance_agent", period="this_month")
    open_items = admin.agent_manager.recommendations(status="OPEN")
    assert open_items
    updated = admin.agent_manager.update_recommendation(open_items[0]["id"], "ACCEPTED")
    assert updated["status"] == "ACCEPTED"
    assert all(
        item["id"] != open_items[0]["id"]
        for item in admin.agent_manager.recommendations(status="OPEN")
    )


def test_memory_records_are_readable(admin, trading) -> None:
    admin.agent_manager.run_agent("finance_agent", period="this_month")
    memory = admin.agent_manager.memory("finance_agent", limit=5)
    assert memory
    assert memory[0]["memory_type"] in ("SNAPSHOT", "RECOMMENDATION")
    assert memory[0]["source_execution_id"]


def test_unknown_agent_raises(admin) -> None:
    with pytest.raises(NotFoundError):
        admin.agent_manager.run_agent("marketing_agent")


# ---------------------------------------------------------------------------
# multi-agent coordination
# ---------------------------------------------------------------------------
def test_coordinator_isolates_a_failing_agent(admin, trading) -> None:
    coordinator = admin.agent_coordinator
    task = AgentTask(
        task_id="multi-1",
        agent_id="finance_agent",
        task_type="FINANCIAL_ANALYSIS",
        period="this_month",
    )
    runner = admin.agent_manager._make_runner(admin.auth_context.principal.user_id, None)

    results = coordinator.run_many(
        ["finance_agent", "does_not_exist", "sales_agent"], task, runner=runner
    )
    assert len(results) == 3
    assert results[0].status == "COMPLETED"
    assert results[1].status == "FAILED"
    assert results[2].status == "COMPLETED"


def test_agents_cannot_recurse_beyond_the_limit(admin) -> None:
    from app.ai.agents.base_agent import AgentError

    task = AgentTask(task_id="rec-1", agent_id="finance_agent", task_type="FINANCIAL_ANALYSIS")
    runner = admin.agent_manager._make_runner(admin.auth_context.principal.user_id, None)
    with pytest.raises(AgentError):
        admin.agent_coordinator.run("finance_agent", task, runner=runner, depth=2)


def test_coordinator_finds_agents_for_intents(admin) -> None:
    assert [agent.agent_id for agent in admin.agent_coordinator.agents_for_intent("LOW_STOCK_ANALYSIS")] == [
        "inventory_agent"
    ]
    assert [agent.agent_id for agent in admin.agent_coordinator.agents_for_intent("BUSINESS_HEALTH_REPORT")] == [
        "business_intelligence_agent"
    ]


# ---------------------------------------------------------------------------
# command routing through the orchestrator
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "command,expected_tool,expected_intent",
    [
        ("Analyze my monthly finances.", "run_finance_agent", "FINANCIAL_ANALYSIS"),
        ("Show my top-selling products.", "run_sales_agent", "GET_TOP_PRODUCTS"),
        ("Identify inactive customers.", "run_customer_agent", "GET_INACTIVE_CUSTOMERS"),
        ("Which products should I reorder?", "run_inventory_agent", "LOW_STOCK_ANALYSIS"),
        ("Find unusual business expenses.", "run_finance_agent", "ANALYZE_EXPENSE_ANOMALIES"),
        (
            "Give me a complete business health report.",
            "run_business_intelligence_agent",
            "BUSINESS_HEALTH_REPORT",
        ),
        ("Identify business risks.", "run_business_intelligence_agent", "BUSINESS_RISK_ANALYSIS"),
        (
            "Compare sales and inventory performance.",
            "run_business_intelligence_agent",
            "COMPARE_SALES_INVENTORY",
        ),
    ],
)
def test_commands_route_to_the_right_agent(
    admin, trading, command, expected_tool, expected_intent
) -> None:
    conversation = admin.ai_service.create_conversation("routing")
    result = admin.ai_service.run_command(conversation.id, command)
    assert result.status == "COMPLETED"
    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["intent"] == expected_intent
    assert [step["tool"] for step in detail["steps"]] == [expected_tool]
    assert detail["steps"][0]["output"]["agent_id"]
    assert detail["steps"][0]["output"]["findings"] is not None


def test_agent_answers_reach_the_chat(admin, trading) -> None:
    conversation = admin.ai_service.create_conversation("chat")
    result = admin.ai_service.run_command(conversation.id, "Analyze my monthly finances.")
    assert "Finance Agent" in result.response_text
    messages = admin.ai_service.messages(conversation.id)
    assert len(messages) == 2
    assert "Finance Agent" in messages[1].content
