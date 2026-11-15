"""Integration tests: the workflow system end to end."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.constants import AIWorkflowStatus, AIStepStatus
from app.core.exceptions import AuthorizationError, BizPilotError
from app.database.models.ai import AIWorkflow, AIWorkflowStep

from tests.conftest import MANAGER_PASSWORD, create_user


def _patch_tool(context, tool_name: str, replacement) -> None:
    """Swap a tool handler for the duration of one test."""
    registry = context.tool_registry
    definition = registry.get(tool_name)
    registry.unregister(tool_name)
    registry.register(
        type(definition)(
            name=definition.name,
            description=definition.description,
            category=definition.category,
            input_model=definition.input_model,
            required_permission=definition.required_permission,
            risk_level=definition.risk_level,
            timeout_seconds=definition.timeout_seconds,
            handler=replacement,
        )
    )


def test_successful_command_executes_and_persists(admin, conversation) -> None:
    result = admin.ai_service.run_command(conversation, "Show this month's revenue.")
    assert result.status == AIWorkflowStatus.COMPLETED
    assert result.intent.value == "GET_REVENUE"
    assert result.response_text
    assert result.provider in ("fallback", "ollama", "gemini")

    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["status"] == AIWorkflowStatus.COMPLETED
    assert detail["trigger"] == "COMMAND"
    # Phase 4: the revenue intent is delegated to the Finance Agent.
    assert [step["tool"] for step in detail["steps"]] == ["run_finance_agent"]
    assert detail["steps"][0]["status"] == AIStepStatus.COMPLETED
    output = detail["steps"][0]["output"]
    assert output["agent_id"] == "finance_agent"
    assert output["metrics"]["revenue"] == "0.00"
    assert output["findings"]


def test_conversation_history_is_recorded(admin, conversation) -> None:
    admin.ai_service.run_command(conversation, "Show this month's revenue.")
    messages = admin.ai_service.messages(conversation)
    assert [message.sender_type for message in messages] == ["USER", "ASSISTANT"]
    assert "revenue" in messages[0].content.lower()
    assert messages[1].meta["workflow_id"]
    assert messages[1].meta["intent"] == "GET_REVENUE"


def test_agent_plan_runs_and_reports(admin, conversation) -> None:
    result = admin.ai_service.run_command(conversation, "Show my cash flow.")
    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert [step["tool"] for step in detail["steps"]] == ["run_finance_agent"]
    assert all(step["status"] == AIStepStatus.COMPLETED for step in detail["steps"])
    assert detail["steps"][0]["output"]["metrics"]["cash_received"] == "0.00"


def test_failed_step_fails_the_workflow(admin, conversation) -> None:
    def boom(context, args):
        raise BizPilotError("Ledger unavailable")

    _patch_tool(admin, "run_finance_agent", boom)
    result = admin.ai_service.run_command(conversation, "Show this month's revenue.")
    assert result.status == AIWorkflowStatus.FAILED
    assert "Ledger unavailable" in (result.error or "")

    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["steps"][0]["status"] == AIStepStatus.FAILED
    assert "Ledger unavailable" in detail["steps"][0]["error"]


def test_retry_after_failure_succeeds(admin, conversation) -> None:
    original = admin.tool_registry.get("run_finance_agent").handler

    def boom(context, args):
        raise BizPilotError("Temporary failure")

    _patch_tool(admin, "run_finance_agent", boom)
    failed = admin.ai_service.run_command(conversation, "Show this month's revenue.")
    assert failed.status == AIWorkflowStatus.FAILED

    _patch_tool(admin, "run_finance_agent", original)
    retried = admin.ai_service.retry_workflow(failed.workflow_id)
    assert retried.status == AIWorkflowStatus.COMPLETED
    assert retried.response_text


def test_retry_rejected_for_completed_workflow(admin, conversation) -> None:
    result = admin.ai_service.run_command(conversation, "Show this month's revenue.")
    with pytest.raises(BizPilotError):
        admin.ai_service.retry_workflow(result.workflow_id)


def test_cancellation_stops_the_workflow(admin, conversation) -> None:
    executor = admin.orchestrator.executor

    def cancel_then_return(context, args):
        executor.cancel(context.workflow_id)
        return {"summary": "agent step ran"}

    _patch_tool(admin, "run_finance_agent", cancel_then_return)
    result = admin.ai_service.run_command(conversation, "Show my cash flow.")
    assert result.status == AIWorkflowStatus.CANCELLED

    detail = admin.ai_service.workflow_detail(result.workflow_id)
    # The workflow is cancelled; the single step that ran before the cancel
    # request is recorded as completed (cancellation is checked between steps).
    assert detail["status"] == AIWorkflowStatus.CANCELLED
    assert len(detail["steps"]) == 1


def test_cancel_completed_workflow_returns_false(admin, conversation) -> None:
    result = admin.ai_service.run_command(conversation, "Show this month's revenue.")
    assert admin.ai_service.cancel_workflow(result.workflow_id) is False


def test_workflow_survives_a_restart(admin, conversation) -> None:
    result = admin.ai_service.run_command(conversation, "Show this month's revenue.")
    admin.database.dispose()
    admin.database.initialize()
    admin.orchestrator.recover()

    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["status"] == AIWorkflowStatus.COMPLETED


def test_interrupted_workflow_is_recovered_as_failed(admin, conversation) -> None:
    result = admin.ai_service.run_command(conversation, "Show this month's revenue.")
    with admin.database.session_factory() as db:
        row = db.scalars(
            select(AIWorkflow).where(AIWorkflow.workflow_id == result.workflow_id)
        ).first()
        row.status = AIWorkflowStatus.RUNNING
        db.commit()

    recovered = admin.orchestrator.recover()
    assert recovered >= 1
    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["status"] == AIWorkflowStatus.FAILED
    assert "restart" in (detail["error"] or "").lower()


def test_unknown_command_is_recorded_with_guidance(admin, conversation) -> None:
    result = admin.ai_service.run_command(conversation, "Sing me a song.")
    assert result.status == AIWorkflowStatus.COMPLETED
    assert "could not map" in result.response_text.lower()
    detail = admin.ai_service.workflow_detail(result.workflow_id)
    assert detail["intent"] == "UNKNOWN_INTENT"


def test_commands_require_the_agents_execute_permission(admin, conversation) -> None:
    """A role that may read finance but may not run agents is refused outright."""
    from app.core.exceptions import AuthorizationError

    role = admin.role_service.create_role(
        {
            "role_name": "Finance Viewer",
            "description": "Read-only finance access without AI execution",
            "permission_keys": ["dashboard.view", "finance.view", "agents.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Finance Viewer",
            "email": "finview@bizpilot.test",
            "password": "Viewer!Passw0rd1",
            "password_confirm": "Viewer!Passw0rd1",
            "role_ids": [role.id],
        }
    )
    conversation_id = admin.ai_service.create_conversation().id
    admin.auth_service.logout()
    admin.auth_service.login("finview@bizpilot.test", "Viewer!Passw0rd1")

    with pytest.raises(AuthorizationError):
        admin.ai_service.begin_command(conversation_id, "Show this month's revenue.")


def test_agent_without_module_permission_reports_data_gaps(admin, conversation) -> None:
    """With agents.execute but no finance.view the agent reports gaps, not numbers."""
    role = admin.role_service.create_role(
        {
            "role_name": "AI Operator",
            "description": "Can run agents but cannot read finance",
            "permission_keys": ["dashboard.view", "agents.view", "agents.execute"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "AI Operator",
            "email": "aioperator@bizpilot.test",
            "password": "Operator!Passw0rd1",
            "password_confirm": "Operator!Passw0rd1",
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("aioperator@bizpilot.test", "Operator!Passw0rd1")
    conversation_id = admin.ai_service.create_conversation().id

    result = admin.ai_service.run_command(conversation_id, "Show this month's revenue.")
    assert result.status == AIWorkflowStatus.COMPLETED
    detail = admin.ai_service.workflow_detail(result.workflow_id)
    output = detail["steps"][0]["output"]
    assert output["data_gaps"]
    assert output["metrics"].get("revenue", "0.00") == "0.00"


def test_approval_flow_creates_the_expense(admin, conversation) -> None:
    preview = admin.ai_service.begin_command(
        conversation, "Record an expense of 5000 for shop rent."
    )
    assert preview.requires_approval is True

    waiting = admin.ai_service.execute_workflow(preview.workflow_id)
    assert waiting.status == AIWorkflowStatus.WAITING_FOR_APPROVAL
    assert "waiting for your approval" in waiting.response_text.lower()

    # Nothing has been written yet.
    assert admin.finance_service.list_expenses() == []

    approved = admin.ai_service.approve_workflow(preview.workflow_id)
    assert approved.status == AIWorkflowStatus.COMPLETED
    expenses = admin.finance_service.list_expenses()
    assert len(expenses) == 1
    assert str(expenses[0].amount) == "5000.00"
    assert expenses[0].expense_category == "RENT"


def test_approval_of_non_waiting_workflow_is_rejected(admin, conversation) -> None:
    result = admin.ai_service.run_command(conversation, "Show this month's revenue.")
    with pytest.raises(BizPilotError):
        admin.ai_service.approve_workflow(result.workflow_id)


def test_workflow_stats_and_listing(admin, conversation) -> None:
    admin.ai_service.run_command(conversation, "Show this month's revenue.")
    admin.ai_service.run_command(conversation, "Find products running out of stock.")
    stats = admin.ai_service.workflow_stats()
    assert stats["total"] == 2
    assert stats["completed"] == 2
    workflows = admin.ai_service.list_workflows(conversation_id=conversation)
    assert len(workflows) == 2
    assert all(workflow.step_count >= 1 for workflow in workflows)


def test_audit_trail_covers_ai_actions(admin, conversation) -> None:
    admin.ai_service.run_command(conversation, "Show this month's revenue.")
    actions = {entry.action for entry in admin.audit_service.list_entries()}
    assert "AI_COMMAND" in actions
    assert "AI_WORKFLOW_COMPLETED" in actions
