"""Integration tests: the five collaboration scenarios on real business records."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.constants import (
    CollaborationStatus,
    CollaborationStrategy,
    CollaborationTaskStatus,
    ConflictStatus,
)
from app.database.models.collaboration import (
    AgentCollaboration,
    CollaborationCheckpoint,
    CollaborationConflict,
    CollaborationDecision,
    CollaborationFinding,
    CollaborationMessage,
    CollaborationTask,
)

from tests.conftest import completed_sale


@pytest.fixture()
def trading(admin, business) -> dict:
    """Business data with sales, payments and expenses (cash on hand is small)."""
    for index, quantity in enumerate((2, 3, 1)):
        sale = completed_sale(admin, business, quantity=quantity)
        admin.sales_service.record_payment(
            {"invoice_id": sale["invoice"].id, "amount": str(50 * (index + 1))}
        )
    for amount, category, description in (
        ("5000.00", "RENT", "Shop rent"),
        ("800.00", "UTILITIES", "Electricity"),
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


def _run(admin, scenario: str, objective: str | None = None, period: str = "this_month"):
    objective = objective or f"integration {scenario}"
    view = admin.collaboration_manager.create_collaboration(
        objective, scenario=scenario, period=period, user_id=admin.auth_context.principal.user_id
    )
    return admin.collaboration_manager.execute_collaboration(view.collaboration_id)


# ---------------------------------------------------------------------------
# strategies
# ---------------------------------------------------------------------------
def test_parallel_collaboration_runs_independent_tasks(admin, trading) -> None:
    detail = _run(admin, "BUSINESS_HEALTH")
    assert detail.collaboration.strategy == CollaborationStrategy.PARALLEL
    # A detected conflict can downgrade the decision to PARTIAL; tasks still all run.
    assert detail.collaboration.status in (
        CollaborationStatus.COMPLETED,
        CollaborationStatus.PARTIAL,
    )
    independent = [task for task in detail.tasks if not task.dependencies]
    assert len(independent) == 4
    assert all(task.status == CollaborationTaskStatus.COMPLETED for task in detail.tasks)
    assert detail.decision is not None
    assert set(detail.decision.participating_agents) >= {
        "finance_agent",
        "sales_agent",
        "customer_agent",
        "inventory_agent",
    }


def test_sequential_collaboration_respects_dependencies(admin, trading) -> None:
    detail = _run(admin, "INVENTORY_FINANCE")
    assert detail.collaboration.strategy == CollaborationStrategy.SEQUENTIAL
    by_key = {task.task_key: task for task in detail.tasks}
    assert by_key["sales_velocity"].dependencies == ["inventory_reorder"]
    assert by_key["finance_budget"].dependencies == ["sales_velocity"]
    # the dependency must finish before the dependent task starts
    assert by_key["inventory_reorder"].completed_at <= by_key["sales_velocity"].started_at
    assert by_key["sales_velocity"].completed_at <= by_key["finance_budget"].started_at


def test_supervisor_worker_collaboration(admin, trading) -> None:
    detail = _run(admin, "SALES_GROWTH")
    assert detail.collaboration.strategy == CollaborationStrategy.SUPERVISOR_WORKER
    by_key = {task.task_key: task for task in detail.tasks}
    assert by_key["synthesis"].assigned_agent == "business_intelligence_agent"
    assert set(by_key["synthesis"].dependencies) == {
        "inventory_capacity",
        "customer_opportunity",
        "finance_capacity",
    }
    assert detail.decision is not None
    assert detail.decision.financial_impact["available_budget"]


def test_consensus_collaboration_collects_all_agents(admin, trading) -> None:
    detail = _run(admin, "DECLINING_SALES")
    assert detail.collaboration.strategy == CollaborationStrategy.CONSENSUS
    assert len(detail.decision.participating_agents) == 5
    assert detail.decision.evidence_references


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------
def test_sales_growth_scenario_reports_baseline_and_gap(admin, trading) -> None:
    detail = _run(admin, "SALES_GROWTH", "Can I increase my sales by 20% next month?")
    decision = detail.decision
    assert decision is not None
    assert decision.business_objective.startswith("Can I increase my sales")
    assert decision.financial_impact["revenue"] != "not reported"
    assert decision.assumptions
    assert decision.recommended_actions


def test_inventory_finance_scenario_prioritises_purchases(admin, trading) -> None:
    detail = _run(admin, "INVENTORY_FINANCE")
    decision = detail.decision
    assert decision is not None
    assert decision.financial_impact["available_budget"]
    assert "planned_spend" in decision.financial_impact
    assert decision.operational_impact or decision.consolidated_findings


def test_supplier_cashflow_scenario_uses_real_figures(admin, trading) -> None:
    detail = _run(admin, "SUPPLIER_CASHFLOW")
    decision = detail.decision
    assert decision is not None
    assert decision.financial_impact["cash_received"] != "not reported"
    context = detail.shared_context
    assert "supplier_context" in context
    assert context["supplier_context"]["lead_time"] == "not recorded in the system"


def test_business_health_scenario_covers_every_module(admin, trading) -> None:
    detail = _run(admin, "BUSINESS_HEALTH")
    decision = detail.decision
    agents = set(decision.participating_agents)
    assert {"finance_agent", "sales_agent", "customer_agent", "inventory_agent"} <= agents
    assert decision.identified_risks
    assert decision.executive_summary


# ---------------------------------------------------------------------------
# messaging and persistence
# ---------------------------------------------------------------------------
def test_messages_are_persisted_and_typed(admin, trading) -> None:
    detail = _run(admin, "BUSINESS_HEALTH")
    assert detail.messages
    types = {message["type"] for message in detail.messages}
    assert "TASK_REQUEST" in types
    assert "TASK_COMPLETED" in types
    assert any(message["sender"] == "collaboration_manager" for message in detail.messages)


def test_everything_is_persisted(admin, trading) -> None:
    detail = _run(admin, "BUSINESS_HEALTH")
    with admin.database.session_factory() as db:
        assert db.scalars(select(AgentCollaboration)).all()
        assert db.scalars(select(CollaborationTask)).all()
        assert db.scalars(select(CollaborationMessage)).all()
        assert db.scalars(select(CollaborationFinding)).all()
        assert db.scalars(select(CollaborationDecision)).all()
        assert db.scalars(select(CollaborationCheckpoint)).all()
    assert detail.collaboration.findings > 0
    assert detail.collaboration.confidence is not None


def test_findings_are_validated(admin, trading) -> None:
    detail = _run(admin, "BUSINESS_HEALTH")
    statuses = {finding["validation_status"] for finding in detail.findings}
    assert statuses <= {"VERIFIED", "PARTIAL", "UNVERIFIED"}
    assert "VERIFIED" in statuses
    for finding in detail.findings:
        assert finding["evidence"]


# ---------------------------------------------------------------------------
# conflicts
# ---------------------------------------------------------------------------
def test_financial_conflict_is_detected_and_resolved(admin, business) -> None:
    """A purchase recommendation that exceeds cash must be flagged and balanced."""
    # Enough stock and demand to make the agent recommend a real purchase, but
    # only a small amount of cash collected.
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 60,
            "movement_type": "ADJUSTMENT",
            "reason": "Opening batch",
            "direction": 1,
        }
    )
    sale = completed_sale(admin, business, quantity=30)
    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "100.00"}
    )
    admin.finance_service.create_expense(
        {
            "expense_category": "RENT",
            "description": "Shop rent",
            "amount": "20000.00",
            "payment_method": "CASH",
            "expense_date": "2026-11-02T10:00:00",
        }
    )

    detail = _run(admin, "INVENTORY_FINANCE")
    financial = [c for c in detail.conflicts if c["conflict_type"] == "FINANCIAL_CONFLICT"]
    assert financial, f"expected a financial conflict, saw {[c['conflict_type'] for c in detail.conflicts]}"
    conflict = financial[0]
    assert conflict["status"] in (ConflictStatus.RESOLVED, ConflictStatus.UNRESOLVED)
    assert conflict["resolution"]["explanation"]
    assert conflict["evidence"]["available_budget"] == detail.shared_context["available_budget"]
    # The decision must carry the conflict and its explanation forward.
    assert detail.decision is not None
    assert any(
        item["type"] == "FINANCIAL_CONFLICT"
        for item in detail.decision.conflicting_findings
    )
    assert any("purchase" in action.action.lower() or "cash" in action.action.lower()
               for action in detail.decision.recommended_actions) or detail.decision.limitations


def test_conflict_records_preserve_original_evidence(admin, business) -> None:
    """A resolved conflict keeps the original findings alongside its explanation."""
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 60,
            "movement_type": "ADJUSTMENT",
            "reason": "Opening batch",
            "direction": 1,
        }
    )
    sale = completed_sale(admin, business, quantity=30)
    admin.sales_service.record_payment({"invoice_id": sale["invoice"].id, "amount": "100.00"})
    admin.finance_service.create_expense(
        {
            "expense_category": "RENT",
            "description": "Shop rent",
            "amount": "20000.00",
            "payment_method": "CASH",
            "expense_date": "2026-11-02T10:00:00",
        }
    )
    detail = _run(admin, "INVENTORY_FINANCE")
    assert detail.conflicts, "this dataset should produce at least one conflict"
    for conflict in detail.conflicts:
        assert conflict["evidence"]
        resolution = conflict["resolution"] or {}
        assert resolution.get("explanation")
        if conflict["status"] == ConflictStatus.RESOLVED:
            assert resolution.get("original_evidence")


# ---------------------------------------------------------------------------
# failure, retry, idempotency, cancellation
# ---------------------------------------------------------------------------
def test_agent_failure_is_reported_not_hidden(admin, trading) -> None:
    original = admin.agent_manager.run_agent

    def failing_run_agent(agent_code, **kwargs):
        if agent_code == "inventory_agent":
            from app.core.exceptions import BizPilotError

            raise BizPilotError("Inventory agent unavailable")
        return original(agent_code, **kwargs)

    admin.agent_manager.run_agent = failing_run_agent
    try:
        detail = _run(admin, "BUSINESS_HEALTH")
    finally:
        admin.agent_manager.run_agent = original

    failed = [task for task in detail.tasks if task.status != CollaborationTaskStatus.COMPLETED]
    assert failed, "the failing agent's task must not be marked completed"
    assert any(task.assigned_agent == "inventory_agent" for task in failed)
    assert detail.collaboration.status in (
        CollaborationStatus.PARTIAL,
        CollaborationStatus.FAILED,
    )
    if detail.decision is not None:
        assert detail.decision.status != "FINAL" or detail.decision.limitations


def test_retry_does_not_duplicate_completed_tasks(admin, trading) -> None:
    detail = _run(admin, "BUSINESS_HEALTH")
    with admin.database.session_factory() as db:
        executions_before = len(
            db.scalars(select(CollaborationTask).where(CollaborationTask.status == "COMPLETED")).all()
        )
    # Re-execute a finished collaboration: it is terminal, so nothing re-runs.
    again = admin.collaboration_manager.execute_collaboration(
        detail.collaboration.collaboration_id
    )
    with admin.database.session_factory() as db:
        executions_after = len(
            db.scalars(select(CollaborationTask).where(CollaborationTask.status == "COMPLETED")).all()
        )
    assert executions_before == executions_after
    assert again.collaboration.status == detail.collaboration.status


def test_task_idempotency_keys_are_unique(admin, trading) -> None:
    detail = _run(admin, "BUSINESS_HEALTH")
    with admin.database.session_factory() as db:
        tasks = db.scalars(select(CollaborationTask)).all()
    keys = [task.idempotency_key for task in tasks]
    assert len(keys) == len(set(keys))
    assert all(task.collaboration_id for task in tasks)


def test_cancellation_stops_the_collaboration(admin, trading) -> None:
    view = admin.collaboration_manager.create_collaboration(
        "cancel me", scenario="BUSINESS_HEALTH", period="this_month",
        user_id=admin.auth_context.principal.user_id,
    )
    assert admin.collaboration_manager.cancel_collaboration(view.collaboration_id) is True
    detail = admin.collaboration_manager.get_collaboration_detail(view.collaboration_id)
    assert detail.collaboration.status == CollaborationStatus.CANCELLED
    # cancelling twice is a no-op
    assert admin.collaboration_manager.cancel_collaboration(view.collaboration_id) is False


def test_restart_recovery_marks_interrupted_collaborations(admin, trading) -> None:
    view = admin.collaboration_manager.create_collaboration(
        "interrupted", scenario="BUSINESS_HEALTH", period="this_month",
        user_id=admin.auth_context.principal.user_id,
    )
    with admin.database.session_factory() as db:
        row = db.scalars(
            select(AgentCollaboration).where(
                AgentCollaboration.collaboration_id == view.collaboration_id
            )
        ).first()
        row.status = CollaborationStatus.RUNNING
        db.commit()

    recovered = admin.collaboration_manager.recover_interrupted()
    assert recovered >= 1
    detail = admin.collaboration_manager.get_collaboration_detail(view.collaboration_id)
    assert detail.collaboration.status == CollaborationStatus.FAILED
    assert "restart" in (detail.collaboration.error or "").lower()
    assert any(checkpoint["phase"] == "RECOVERY" for checkpoint in detail.checkpoints)


def test_unknown_scenario_is_rejected(admin) -> None:
    from app.ai.collaboration.manager import CollaborationError

    with pytest.raises(CollaborationError):
        admin.collaboration_manager.create_collaboration(
            "do something odd", scenario="NOT_A_SCENARIO", user_id=1
        )


def test_dashboard_stats_reflect_real_rows(admin, trading) -> None:
    _run(admin, "BUSINESS_HEALTH")
    stats = admin.collaboration_manager.dashboard_stats()
    assert stats["total"] == 1
    assert stats["completed"] + stats["partial"] == 1
    assert stats["active"] == 0


# ---------------------------------------------------------------------------
# orchestrator routing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "command,expected_intent,expected_scenario",
    [
        ("Can I increase my sales by 20% next month?", "COLLAB_SALES_GROWTH", "SALES_GROWTH"),
        (
            "Which products should I reorder without affecting my cash flow?",
            "COLLAB_REORDER_CASHFLOW",
            "INVENTORY_FINANCE",
        ),
        ("Why are my sales decreasing?", "COLLAB_DECLINING_SALES", "DECLINING_SALES"),
        (
            "Analyze my complete business performance.",
            "COLLAB_BUSINESS_HEALTH",
            "BUSINESS_HEALTH",
        ),
        (
            "Can I purchase inventory from my suppliers this week?",
            "COLLAB_SUPPLIER_CASHFLOW",
            "SUPPLIER_CASHFLOW",
        ),
    ],
)
def test_commands_route_to_collaboration(admin, trading, command, expected_intent, expected_scenario):
    conversation = admin.ai_service.create_conversation("phase 5")
    result = admin.ai_service.run_command(conversation.id, command)
    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["intent"] == expected_intent
    assert [step["tool"] for step in detail["steps"]] == ["run_collaboration"]
    output = detail["steps"][0]["output"]
    assert output["collaboration_id"]
    assert output["summary"]


def test_decision_exports_produce_real_files(admin, trading) -> None:
    detail = _run(admin, "BUSINESS_HEALTH")
    csv_path = admin.collaboration_service.export_decision_csv(
        detail.collaboration.collaboration_id
    )
    pdf_path = admin.collaboration_service.export_decision_pdf(
        detail.collaboration.collaboration_id
    )
    assert csv_path.exists() and csv_path.stat().st_size > 200
    assert pdf_path.exists() and pdf_path.read_bytes()[:4] == b"%PDF"
