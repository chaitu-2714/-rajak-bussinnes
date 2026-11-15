"""Integration tests: autonomous workflows, approvals, triggers, scheduler, recovery."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.constants import (
    ApprovalStatus,
    WorkflowStatus,
    WorkflowTaskStatus,
)
from app.core.exceptions import ConflictError
from app.database.models.autonomy import (
    ApprovalRequest,
    AutonomousWorkflow,
    ScheduledWorkflow,
    WorkflowIdempotencyRecord,
    WorkflowTask,
)
from app.database.models.events import BusinessEvent
from app.utils.date_utils import utcnow

from tests.conftest import completed_sale


@pytest.fixture()
def stock_setup(admin, business) -> dict:
    """A product below minimum, a supplier, a customer and a paid sale."""
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 9,
            "movement_type": "ADJUSTMENT",
            "reason": "Breakage",
            "direction": -1,
        }
    )
    sale = completed_sale(admin, business, quantity=1)
    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "50.00"}
    )
    return business


def _po_payload(business) -> dict:
    return {
        "product_id": business["tea"].id,
        "product_name": business["tea"].product_name,
        "supplier_id": business["supplier"].id,
        "items": [
            {
                "product_id": business["tea"].id,
                "ordered_quantity": 20,
                "unit_cost": "180.00",
            }
        ],
    }


def _start_low_stock(admin, business) -> str:
    view = admin.autonomy_service.create_workflow(
        "LOW_STOCK_REPLENISHMENT", payload=_po_payload(business)
    )
    admin.autonomy_service.start_workflow(view.workflow_ref)
    return view.workflow_ref


# ---------------------------------------------------------------------------
# Test 1: low-stock event creates a workflow
# ---------------------------------------------------------------------------
def test_low_stock_event_creates_a_workflow(admin, stock_setup) -> None:
    with admin.database.session_factory() as db:
        events = db.scalars(
            select(BusinessEvent).where(BusinessEvent.event_type == "StockBelowMinimum")
        ).all()
    assert events, "the stock write-off should have published a StockBelowMinimum event"

    report = admin.autonomy_service.process_events()
    assert report["created"] >= 1

    with admin.database.session_factory() as db:
        workflows = db.scalars(
            select(AutonomousWorkflow).where(
                AutonomousWorkflow.trigger_type == "EVENT",
                AutonomousWorkflow.workflow_type == "LOW_STOCK_REPLENISHMENT",
            )
        ).all()
    assert workflows
    assert workflows[0].trigger_ref.startswith("EVENT:")


# ---------------------------------------------------------------------------
# Test 2: the workflow coordinates Inventory, Sales and Finance agents
# ---------------------------------------------------------------------------
def test_workflow_coordinates_multiple_agents(admin, stock_setup) -> None:
    workflow_ref = _start_low_stock(admin, stock_setup)
    detail = admin.autonomy_service.get_workflow(workflow_ref)
    agents = {task.assigned_agent for task in detail.tasks if task.assigned_agent}
    assert {"inventory_agent", "sales_agent", "finance_agent"} <= agents
    analysis = [
        task for task in detail.tasks if task.task_type == "BUSINESS_ANALYSIS"
    ]
    assert analysis
    assert all(task.status == WorkflowTaskStatus.COMPLETED for task in analysis)
    assert all((task.result or {}).get("agent_id") for task in analysis)


# ---------------------------------------------------------------------------
# Tests 3 and 4: nothing before approval, exactly once after
# ---------------------------------------------------------------------------
def test_purchase_order_is_not_created_before_approval(admin, stock_setup) -> None:
    before = len(admin.purchasing_service.list_purchase_orders())
    workflow_ref = _start_low_stock(admin, stock_setup)

    detail = admin.autonomy_service.get_workflow(workflow_ref)
    assert detail.workflow.status == WorkflowStatus.WAITING_APPROVAL
    assert detail.workflow.pending_approvals == 1
    assert len(admin.purchasing_service.list_purchase_orders()) == before
    approval = admin.autonomy_service.pending_approvals()[0]
    assert approval.requested_action == "create_purchase_order"
    assert approval.financial_impact == "3,600.00"


def test_approved_action_executes_exactly_once(admin, stock_setup) -> None:
    before = len(admin.purchasing_service.list_purchase_orders())
    workflow_ref = _start_low_stock(admin, stock_setup)
    approval = admin.autonomy_service.pending_approvals()[0]

    approved = admin.autonomy_service.approve(approval.approval_ref, note="Approved by test")
    assert approved.status == ApprovalStatus.APPROVED
    assert approved.execution_result["record_type"] == "purchase_order"
    after = len(admin.purchasing_service.list_purchase_orders())
    assert after == before + 1

    # A second approval attempt must not create a second order.
    with pytest.raises(ConflictError):
        admin.autonomy_service.approve(approval.approval_ref)
    assert len(admin.purchasing_service.list_purchase_orders()) == after

    detail = admin.autonomy_service.get_workflow(workflow_ref)
    assert detail.workflow.status == WorkflowStatus.COMPLETED
    assert detail.verification["verified"] is True
    checks = detail.verification["checks"]
    assert checks and checks[0]["record_type"] == "purchase_order"
    assert checks[0]["verified"] is True


# ---------------------------------------------------------------------------
# Test 5: a rejected approval prevents execution
# ---------------------------------------------------------------------------
def test_rejected_approval_prevents_execution(admin, stock_setup) -> None:
    before = len(admin.purchasing_service.list_purchase_orders())
    workflow_ref = _start_low_stock(admin, stock_setup)
    approval = admin.autonomy_service.pending_approvals()[0]

    rejected = admin.autonomy_service.reject(
        approval.approval_ref, reason="Not enough cash this week"
    )
    assert rejected.status == ApprovalStatus.REJECTED
    assert len(admin.purchasing_service.list_purchase_orders()) == before

    detail = admin.autonomy_service.get_workflow(workflow_ref)
    approval_task = next(task for task in detail.tasks if task.task_key == "approval")
    assert approval_task.status != WorkflowTaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Test 6: an expired approval cannot authorise execution
# ---------------------------------------------------------------------------
def test_expired_approval_cannot_authorise_execution(admin, stock_setup) -> None:
    before = len(admin.purchasing_service.list_purchase_orders())
    _start_low_stock(admin, stock_setup)
    approval = admin.autonomy_service.pending_approvals()[0]

    with admin.database.session_factory() as db:
        row = db.scalars(
            select(ApprovalRequest).where(ApprovalRequest.approval_ref == approval.approval_ref)
        ).first()
        row.expires_at = utcnow() - timedelta(hours=1)
        db.commit()

    with pytest.raises(ConflictError):
        admin.autonomy_service.approve(approval.approval_ref)
    assert len(admin.purchasing_service.list_purchase_orders()) == before
    assert admin.autonomy_service.expire_approvals() >= 1


# ---------------------------------------------------------------------------
# Test 8: duplicate events do not create duplicate workflows
# ---------------------------------------------------------------------------
def test_duplicate_events_do_not_create_duplicate_workflows(admin, stock_setup) -> None:
    first = admin.autonomy_service.process_events()
    second = admin.autonomy_service.process_events()
    assert first["created"] >= 1
    assert second["created"] == 0

    with admin.database.session_factory() as db:
        count = db.scalar(
            select(func.count(AutonomousWorkflow.id)).where(
                AutonomousWorkflow.workflow_type == "LOW_STOCK_REPLENISHMENT"
            )
        )
    assert count == first["created"]


# ---------------------------------------------------------------------------
# Test 9: retries never duplicate business records
# ---------------------------------------------------------------------------
def test_retry_does_not_duplicate_business_records(admin, stock_setup) -> None:
    workflow_ref = _start_low_stock(admin, stock_setup)
    approval = admin.autonomy_service.pending_approvals()[0]
    admin.autonomy_service.approve(approval.approval_ref)
    after_approval = len(admin.purchasing_service.list_purchase_orders())

    admin.autonomy_service.retry_workflow(workflow_ref)
    assert len(admin.purchasing_service.list_purchase_orders()) == after_approval

    with admin.database.session_factory() as db:
        records = db.scalars(
            select(WorkflowIdempotencyRecord).where(
                WorkflowIdempotencyRecord.action_name == "create_purchase_order"
            )
        ).all()
    assert len(records) == 1


# ---------------------------------------------------------------------------
# Test 10: scheduled daily report
# ---------------------------------------------------------------------------
def test_daily_report_runs_on_schedule(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    with admin.database.session_factory() as db:
        schedule = db.scalars(
            select(ScheduledWorkflow).where(ScheduledWorkflow.schedule_key == "daily_summary")
        ).first()
        schedule.next_run_at = utcnow() - timedelta(minutes=1)
        db.commit()

    result = admin.autonomy_service.run_due_schedules()
    assert result["ran"], "the daily summary schedule should have run"
    assert "error" not in result["ran"][0]

    with admin.database.session_factory() as db:
        workflow = db.scalars(
            select(AutonomousWorkflow).where(
                AutonomousWorkflow.workflow_type == "DAILY_SUMMARY",
                AutonomousWorkflow.trigger_type == "SCHEDULE",
            )
        ).first()
        schedule = db.scalars(
            select(ScheduledWorkflow).where(ScheduledWorkflow.schedule_key == "daily_summary")
        ).first()
    assert workflow is not None
    assert workflow.status == WorkflowStatus.COMPLETED
    assert schedule.next_run_at > utcnow()

    # A second tick at the same slot must not run it again.
    second = admin.autonomy_service.run_due_schedules()
    assert second["ran"] == []


# ---------------------------------------------------------------------------
# Test 11: restart recovery
# ---------------------------------------------------------------------------
def test_restart_recovery_pauses_running_workflows(admin, stock_setup) -> None:
    workflow_ref = _start_low_stock(admin, stock_setup)
    with admin.database.session_factory() as db:
        row = db.scalars(
            select(AutonomousWorkflow).where(AutonomousWorkflow.workflow_ref == workflow_ref)
        ).first()
        row.status = WorkflowStatus.RUNNING
        db.commit()

    recovered = admin.workflow_engine.recover_interrupted()
    assert recovered >= 1

    detail = admin.autonomy_service.get_workflow(workflow_ref)
    assert detail.workflow.status == WorkflowStatus.PAUSED
    assert "restart" in (detail.workflow.error or "").lower()
    assert any(entry["event"] == "RECOVERED" for entry in detail.logs)


# ---------------------------------------------------------------------------
# Test 12: a failed agent is never reported as success
# ---------------------------------------------------------------------------
def test_failed_agent_does_not_falsely_complete(admin, stock_setup) -> None:
    original = admin.agent_manager.run_agent

    def failing(agent_code, **kwargs):
        from app.core.exceptions import BizPilotError

        raise BizPilotError("Agent unavailable")

    admin.agent_manager.run_agent = failing
    try:
        workflow_ref = _start_low_stock(admin, stock_setup)
    finally:
        admin.agent_manager.run_agent = original

    detail = admin.autonomy_service.get_workflow(workflow_ref)
    failed = [task for task in detail.tasks if task.status == WorkflowTaskStatus.FAILED]
    assert failed, "the failed analysis task must be recorded as failed"
    assert detail.workflow.status != WorkflowStatus.COMPLETED


# ---------------------------------------------------------------------------
# Test 14: offline deterministic workflow
# ---------------------------------------------------------------------------
def test_offline_deterministic_workflow_completes(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    view = admin.autonomy_service.create_workflow("DAILY_SUMMARY", objective="Offline daily summary")
    detail = admin.autonomy_service.start_workflow(view.workflow_ref)
    assert detail.workflow.status == WorkflowStatus.COMPLETED
    report_task = next(task for task in detail.tasks if task.task_key == "report")
    assert report_task.status == WorkflowTaskStatus.COMPLETED
    assert report_task.result["file"].endswith(".csv")
    assert detail.verification["verified"] is True


# ---------------------------------------------------------------------------
# other workflows
# ---------------------------------------------------------------------------
def test_unusual_expense_review_preserves_the_expense(admin, business) -> None:
    expense = admin.finance_service.create_expense(
        {
            "expense_category": "MAINTENANCE",
            "description": "Compressor replacement",
            "amount": "48000.00",
            "payment_method": "CASH",
            "expense_date": "2026-11-02T10:00:00",
        }
    )
    view = admin.autonomy_service.create_workflow(
        "UNUSUAL_EXPENSE_REVIEW",
        payload={"expense_id": expense.id, "amount": str(expense.amount)},
    )
    detail = admin.autonomy_service.start_workflow(view.workflow_ref)
    assert detail.workflow.status == WorkflowStatus.COMPLETED
    # The transaction is untouched: no reversal, no deletion.
    still_there = next(
        (item for item in admin.finance_service.list_expenses() if item.id == expense.id), None
    )
    assert still_there is not None
    assert still_there.status != "REVERSED"


def test_customer_followup_keeps_the_draft_internal(admin, business) -> None:
    view = admin.autonomy_service.create_workflow(
        "CUSTOMER_FOLLOWUP",
        payload={"customer_id": business["customer"].id,
                 "customer_name": business["customer"].full_name},
    )
    detail = admin.autonomy_service.start_workflow(view.workflow_ref)
    draft = next(task for task in detail.tasks if task.task_key == "draft")
    assert draft.result["sent"] is False
    assert draft.result["channel"] == "INTERNAL"
    approval_task = next(task for task in detail.tasks if task.task_key == "approval")
    # No messaging provider is connected, so the approval step is skipped honestly.
    assert approval_task.status == WorkflowTaskStatus.SKIPPED
    assert "provider" in (approval_task.error or "").lower()


def test_cancelled_workflow_stops_and_cancels_pending_approvals(admin, stock_setup) -> None:
    workflow_ref = _start_low_stock(admin, stock_setup)
    admin.autonomy_service.cancel_workflow(workflow_ref)
    detail = admin.autonomy_service.get_workflow(workflow_ref)
    assert detail.workflow.status == WorkflowStatus.CANCELLED
    assert all(approval["status"] != "PENDING" for approval in detail.approvals)


def test_rollback_reverses_only_reversible_actions(admin, stock_setup) -> None:
    workflow_ref = _start_low_stock(admin, stock_setup)
    approval = admin.autonomy_service.pending_approvals()[0]
    admin.autonomy_service.approve(approval.approval_ref)
    result = admin.autonomy_service.rollback_workflow(workflow_ref, reason="Test rollback")
    assert "create_purchase_order" in result["reversed"]
    detail = admin.autonomy_service.get_workflow(workflow_ref)
    assert detail.workflow.status == WorkflowStatus.ROLLED_BACK


def test_pause_and_resume(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    view = admin.autonomy_service.create_workflow("DAILY_SUMMARY")
    admin.autonomy_service.pause_workflow(view.workflow_ref)
    assert admin.autonomy_service.get_workflow_status(view.workflow_ref).status == WorkflowStatus.PAUSED
    detail = admin.autonomy_service.resume_workflow(view.workflow_ref)
    assert detail.workflow.status == WorkflowStatus.COMPLETED
