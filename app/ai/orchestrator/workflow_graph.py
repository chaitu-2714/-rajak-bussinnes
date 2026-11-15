"""LangGraph workflow graph with SQLite checkpointing.

The graph is deliberately small: it decides *when* a step runs and when a
workflow stops. The actual business work happens in the injected step runner,
which calls the tool registry (and therefore the existing services).

Checkpoints live in their own SQLite file so a workflow can be inspected or
resumed after a restart without touching the business database.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph

from app.ai.orchestrator.workflow_state import WorkflowState, summarise_state
from app.core.constants import AIWorkflowStatus
from app.core.logging_config import get_logger
from app.utils.date_utils import utcnow

logger = get_logger("ai.graph")

StepRunner = Callable[[dict[str, Any], int], dict[str, Any]]
CancelCheck = Callable[[], bool]


class WorkflowGraph:
    """Compiles and runs the orchestration graph."""

    def __init__(self, *, checkpoint_path: Path, step_runner: StepRunner, max_seconds: float = 180.0):
        self._checkpoint_path = Path(checkpoint_path)
        self._checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        self._step_runner = step_runner
        self._max_seconds = max_seconds
        self._connection = sqlite3.connect(
            str(self._checkpoint_path), check_same_thread=False
        )
        self._saver = SqliteSaver(self._connection)
        self._app = self._build()

    # -- graph construction ------------------------------------------------
    def _build(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("prepare", self._prepare)
        graph.add_node("run_step", self._run_step)
        graph.add_node("cancelled", self._cancelled)
        graph.add_node("finalise", self._finalise)

        graph.set_entry_point("prepare")
        graph.add_conditional_edges(
            "prepare",
            self._after_prepare,
            {"run": "run_step", "finalise": "finalise"},
        )
        graph.add_conditional_edges(
            "run_step",
            self._after_step,
            {
                "continue": "run_step",
                "cancel": "cancelled",
                "finalise": "finalise",
            },
        )
        graph.add_edge("cancelled", END)
        graph.add_edge("finalise", END)
        return graph.compile(checkpointer=self._saver)

    # -- nodes -------------------------------------------------------------
    @staticmethod
    def _prepare(state: WorkflowState) -> dict[str, Any]:
        return {
            "status": AIWorkflowStatus.RUNNING,
            "started_at": state.get("started_at") or utcnow().isoformat(),
            "error": "",
        }

    def _run_step(self, state: WorkflowState) -> dict[str, Any]:
        index = int(state.get("index", 0))
        steps = state.get("steps", [])
        if index >= len(steps):
            return {"status": AIWorkflowStatus.COMPLETED}

        step = steps[index]
        result = self._step_runner(step, index)
        results = list(state.get("results", [])) + [result]
        error = state.get("error", "")
        status = state.get("status", AIWorkflowStatus.RUNNING)

        if result.get("status") == "FAILED":
            error = result.get("error") or "A workflow step failed"
            status = AIWorkflowStatus.FAILED
        elif result.get("status") == "CANCELLED":
            status = AIWorkflowStatus.CANCELLED

        return {
            "index": index + 1,
            "results": results,
            "status": status,
            "error": error,
        }

    @staticmethod
    def _cancelled(state: WorkflowState) -> dict[str, Any]:
        return {
            "status": AIWorkflowStatus.CANCELLED,
            "cancelled": True,
            "error": state.get("error") or "Workflow cancelled",
        }

    @staticmethod
    def _finalise(state: WorkflowState) -> dict[str, Any]:
        status = state.get("status", AIWorkflowStatus.RUNNING)
        if status == AIWorkflowStatus.CANCELLED:
            final = AIWorkflowStatus.CANCELLED
        elif status == AIWorkflowStatus.FAILED:
            final = AIWorkflowStatus.FAILED
        else:
            results = state.get("results", [])
            if any(result.get("status") == "FAILED" for result in results):
                final = AIWorkflowStatus.FAILED
            elif state.get("await_approval"):
                # The read-only preparation succeeded; the data-changing action
                # itself only runs after a human approves it.
                final = AIWorkflowStatus.WAITING_FOR_APPROVAL
            else:
                final = AIWorkflowStatus.COMPLETED
        return {"status": final, "finished_at": utcnow().isoformat()}

    # -- routing -----------------------------------------------------------
    @staticmethod
    def _after_prepare(state: WorkflowState) -> str:
        if not state.get("steps"):
            return "finalise"
        return "run"

    def _after_step(self, state: WorkflowState) -> str:
        if state.get("status") == AIWorkflowStatus.CANCELLED:
            return "cancel"
        if state.get("status") == AIWorkflowStatus.FAILED:
            return "finalise"
        index = int(state.get("index", 0))
        steps = state.get("steps", [])
        if index >= len(steps):
            return "finalise"
        started = state.get("started_at")
        if started:
            try:
                from datetime import datetime

                elapsed = utcnow() - datetime.fromisoformat(started)
                if elapsed.total_seconds() > self._max_seconds:
                    state["status"] = AIWorkflowStatus.FAILED
                    state["error"] = (
                        f"Workflow exceeded its {self._max_seconds:.0f}s time budget"
                    )
                    return "finalise"
            except ValueError:  # pragma: no cover - defensive
                pass
        return "continue"

    # -- execution ---------------------------------------------------------
    def run(
        self, state: WorkflowState, *, cancel_check: CancelCheck | None = None
    ) -> dict[str, Any]:
        """Execute the graph for one workflow and return the final state."""
        config = {"configurable": {"thread_id": state["workflow_id"]}}
        final = self._app.invoke(state, config)
        if cancel_check is not None and cancel_check():
            final = dict(final)
            final["status"] = AIWorkflowStatus.CANCELLED
        logger.info(
            "Workflow %s finished: %s", state.get("workflow_id"), final.get("status")
        )
        return final

    def resume(self, workflow_id: str) -> dict[str, Any] | None:
        """Resume a persisted workflow from its checkpoint."""
        config = {"configurable": {"thread_id": workflow_id}}
        try:
            snapshot = self._app.get_state(config)
        except Exception:  # pragma: no cover - no checkpoint
            return None
        if not snapshot or not snapshot.values:
            return None
        return self._app.invoke(None, config)

    def state_of(self, workflow_id: str) -> dict[str, Any] | None:
        config = {"configurable": {"thread_id": workflow_id}}
        try:
            snapshot = self._app.get_state(config)
        except Exception:  # pragma: no cover - no checkpoint
            return None
        if not snapshot or not snapshot.values:
            return None
        return summarise_state(snapshot.values)

    def close(self) -> None:
        try:
            self._connection.close()
        except Exception:  # pragma: no cover
            pass
