"""Workflow state: the serialisable shape persisted by LangGraph."""

from __future__ import annotations

from typing import Any, TypedDict

from app.core.constants import AIWorkflowStatus
from app.utils.date_utils import utcnow


class WorkflowState(TypedDict, total=False):
    """State passed between LangGraph nodes.

    Everything here is JSON-serialisable so the SQLite checkpointer can persist
    and resume a workflow.
    """

    workflow_id: str
    user_id: int
    intent: str
    steps: list[dict[str, Any]]
    index: int
    results: list[dict[str, Any]]
    status: str
    error: str
    await_approval: bool
    started_at: str
    finished_at: str
    cancelled: bool


def initial_state(
    *,
    workflow_id: str,
    user_id: int,
    intent: str,
    steps: list[dict[str, Any]],
    await_approval: bool,
) -> WorkflowState:
    return WorkflowState(
        workflow_id=workflow_id,
        user_id=user_id,
        intent=intent,
        steps=steps,
        index=0,
        results=[],
        status=AIWorkflowStatus.PENDING,
        error="",
        await_approval=await_approval,
        started_at=utcnow().isoformat(),
        finished_at="",
        cancelled=False,
    )


def summarise_state(state: WorkflowState) -> dict[str, Any]:
    """Compact view used by the UI and tests."""
    results = state.get("results", [])
    completed = sum(1 for result in results if result.get("status") == "COMPLETED")
    return {
        "workflow_id": state.get("workflow_id"),
        "status": state.get("status", AIWorkflowStatus.PENDING),
        "intent": state.get("intent"),
        "steps_total": len(state.get("steps", [])),
        "steps_completed": completed,
        "index": state.get("index", 0),
        "error": state.get("error", ""),
    }
