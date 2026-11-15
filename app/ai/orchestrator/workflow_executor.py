"""Workflow execution: runs a plan, persists every step, supports cancel/retry."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.orchestrator.workflow_graph import WorkflowGraph
from app.ai.orchestrator.workflow_state import initial_state
from app.ai.registry.tool_registry import ToolRegistry
from app.ai.schemas.tool_schema import ToolContext, ToolInvocation
from app.ai.schemas.workflow_schema import ExecutionPlan, PlanStep, StepResult, WorkflowResult
from app.core.constants import AIStepStatus, AIWorkflowStatus
from app.core.exceptions import NotFoundError
from app.core.logging_config import get_logger
from app.database.models.ai import AIWorkflow, AIWorkflowStep
from app.utils.date_utils import utcnow

logger = get_logger("ai.executor")

PermissionChecker = Callable[[str], bool]


class WorkflowExecutor:
    """Executes plans step by step and records everything in SQLite."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        registry: ToolRegistry,
        checkpoint_path: Path,
        services: Any,
        max_seconds: float = 180.0,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry
        self._checkpoint_path = Path(checkpoint_path)
        self._services = services
        self._max_seconds = max_seconds
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    # -- cancellation ------------------------------------------------------
    def cancel(self, workflow_id: str) -> bool:
        """Request cancellation; the executor stops before the next step."""
        with self._lock:
            self._cancelled.add(workflow_id)
        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is not None and not row.is_terminal:
                row.status = AIWorkflowStatus.CANCELLED
                row.completed_at = utcnow()
                row.error_message = "Cancelled by the user"
                db.commit()
        logger.info("Cancellation requested for workflow %s", workflow_id)
        return True

    def is_cancelled(self, workflow_id: str) -> bool:
        with self._lock:
            return workflow_id in self._cancelled

    def clear_cancellation(self, workflow_id: str) -> None:
        with self._lock:
            self._cancelled.discard(workflow_id)

    # -- execution ---------------------------------------------------------
    def execute(
        self, workflow_id: str, *, permission_checker: PermissionChecker
    ) -> WorkflowResult:
        with self._session_factory() as db:
            row = self._load(db, workflow_id)
            if row is None:
                raise NotFoundError(f"Workflow {workflow_id} was not found")
            plan = ExecutionPlan.model_validate(row.execution_plan or {})
            user_id = row.user_id or 0
            business_id = None
            business = self._services.business_repository.get_primary(db)
            if business is not None:
                business_id = business.id
            conversation_id = row.conversation_id
            row.status = AIWorkflowStatus.RUNNING
            row.started_at = row.started_at or utcnow()
            row.attempts = (row.attempts or 0) + 1
            row.error_message = None
            db.commit()
            row_id = row.id

        self.clear_cancellation(workflow_id)
        graph = WorkflowGraph(
            checkpoint_path=self._checkpoint_path,
            step_runner=self._make_step_runner(
                workflow_row_id=row_id,
                workflow_id=workflow_id,
                user_id=user_id,
                business_id=business_id,
                conversation_id=conversation_id,
                permission_checker=permission_checker,
            ),
            max_seconds=self._max_seconds,
        )
        state = initial_state(
            workflow_id=workflow_id,
            user_id=user_id,
            intent=plan.intent.value,
            steps=[step.model_dump(mode="json") for step in plan.steps],
            await_approval=plan.requires_approval,
        )
        try:
            final = graph.run(state, cancel_check=lambda: self.is_cancelled(workflow_id))
        finally:
            graph.close()

        results = [
            StepResult.model_validate(result)
            for result in final.get("results", [])
            if isinstance(result, dict)
        ]
        status = final.get("status", AIWorkflowStatus.FAILED)
        error = final.get("error") or None
        if self.is_cancelled(workflow_id) and status not in AIWorkflowStatus.TERMINAL:
            status = AIWorkflowStatus.CANCELLED

        with self._session_factory() as db:
            row = db.get(AIWorkflow, row_id)
            if row is not None:
                row.status = status
                row.current_step = int(final.get("index", 0))
                # A workflow waiting for approval is not finished yet.
                row.completed_at = (
                    None if status == AIWorkflowStatus.WAITING_FOR_APPROVAL else utcnow()
                )
                row.error_message = error
                row.result = {
                    "steps": [result.model_dump(mode="json") for result in results],
                    "status": status,
                }
                db.commit()

        return WorkflowResult(
            workflow_id=workflow_id,
            intent=plan.intent,
            status=status,
            steps=results,
            started_at=utcnow(),
            completed_at=utcnow(),
            error=error,
            requires_approval=plan.requires_approval,
            total_duration_ms=sum(result.duration_ms for result in results),
        )

    # -- step runner -------------------------------------------------------
    def _make_step_runner(
        self,
        *,
        workflow_row_id: int,
        workflow_id: str,
        user_id: int,
        business_id: int | None,
        conversation_id: int | None,
        permission_checker: PermissionChecker,
    ) -> Callable[[dict[str, Any], int], dict[str, Any]]:
        context = ToolContext(
            services=self._services,
            user_id=user_id,
            business_id=business_id,
            conversation_id=conversation_id,
            workflow_id=workflow_id,
        )

        def runner(step_data: dict[str, Any], index: int) -> dict[str, Any]:
            step = PlanStep.model_validate(step_data)

            if self.is_cancelled(workflow_id):
                return self._persist_result(
                    workflow_row_id,
                    step,
                    StepResult(
                        step_id=step.step_id,
                        step_number=step.step_number,
                        tool_name=step.tool_name,
                        status=AIStepStatus.CANCELLED,
                        error="Workflow cancelled",
                    ),
                )

            self._mark_running(workflow_row_id, step)
            invocation = ToolInvocation(tool_name=step.tool_name, arguments=step.arguments)
            tool_result = self._registry.execute(
                invocation,
                context,
                permission_checker=permission_checker,
                cancelled=lambda: self.is_cancelled(workflow_id),
            )
            result = StepResult(
                step_id=step.step_id,
                step_number=step.step_number,
                tool_name=step.tool_name,
                status=AIStepStatus.COMPLETED if tool_result.success else AIStepStatus.FAILED,
                data=tool_result.data,
                error=tool_result.error,
                duration_ms=tool_result.duration_ms,
                risk_level=tool_result.risk_level,
                summary=tool_result.summary,
            )
            return self._persist_result(workflow_row_id, step, result)

        return runner

    # -- persistence -------------------------------------------------------
    def _mark_running(self, workflow_row_id: int, step: PlanStep) -> None:
        with self._session_factory() as db:
            row = self._step_row(db, workflow_row_id, step)
            row.status = AIStepStatus.RUNNING
            row.started_at = utcnow()
            row.input_data = step.arguments
            workflow = db.get(AIWorkflow, workflow_row_id)
            if workflow is not None:
                workflow.current_step = step.step_number
            db.commit()

    def _persist_result(
        self, workflow_row_id: int, step: PlanStep, result: StepResult
    ) -> dict[str, Any]:
        with self._session_factory() as db:
            row = self._step_row(db, workflow_row_id, step)
            row.status = result.status
            row.completed_at = utcnow()
            row.output_data = result.data or None
            row.error_message = result.error
            row.duration_ms = result.duration_ms
            row.risk_level = result.risk_level
            row.required_permission = step.required_permission
            db.commit()
        return result.model_dump(mode="json")

    @staticmethod
    def _step_row(db: Session, workflow_row_id: int, step: PlanStep) -> AIWorkflowStep:
        row = db.scalars(
            select(AIWorkflowStep).where(
                AIWorkflowStep.workflow_id == workflow_row_id,
                AIWorkflowStep.step_number == step.step_number,
            )
        ).first()
        if row is None:
            row = AIWorkflowStep(
                workflow_id=workflow_row_id,
                step_number=step.step_number,
                tool_name=step.tool_name,
                required_permission=step.required_permission,
                risk_level=step.risk_level,
                input_data=step.arguments,
                status=AIStepStatus.PENDING,
            )
            db.add(row)
            db.flush()
        return row

    def _load(self, db: Session, workflow_id: str) -> AIWorkflow | None:
        return db.scalars(
            select(AIWorkflow).where(AIWorkflow.workflow_id == workflow_id)
        ).first()

    # -- recovery ----------------------------------------------------------
    def recover_interrupted(self) -> int:
        """Fail workflows left RUNNING by a crash or restart."""
        with self._session_factory() as db:
            rows = db.scalars(
                select(AIWorkflow).where(
                    AIWorkflow.status.in_(
                        (AIWorkflowStatus.RUNNING, AIWorkflowStatus.PENDING)
                    )
                )
            ).all()
            for row in rows:
                row.status = AIWorkflowStatus.FAILED
                row.completed_at = utcnow()
                row.error_message = (
                    "Interrupted by an application restart; retry to run it again"
                )
            db.commit()
            if rows:
                logger.warning("Recovered %s interrupted workflow(s)", len(rows))
            return len(rows)
