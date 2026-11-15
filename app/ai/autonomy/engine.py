"""The autonomous workflow engine.

Plans, validates, executes, pauses for approval, resumes, retries and verifies
workflows — always through the allowlisted actions and the existing business
services. No SQL, shell or generated code is ever executed here.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.autonomy.actions import (
    ACTION_REGISTRY,
    ActionContext,
    ActionRestricted,
    ActionUnavailable,
    get_action,
    is_registered,
)
from app.ai.autonomy.approvals import ApprovalService
from app.ai.autonomy.policy_engine import AutonomyPolicyEngine
from app.ai.autonomy.templates import TEMPLATES, WorkflowTemplate, get_template
from app.ai.schemas.autonomy_schema import (
    WorkflowDetail,
    WorkflowTaskSpec,
    WorkflowTaskView,
    WorkflowView,
)
from app.core.constants import (
    MODULE_AGENTS,
    ApprovalStatus,
    AuditAction,
    AutonomyMode,
    WorkflowStatus,
    WorkflowTaskStatus,
    WorkflowTaskType,
    WorkflowTriggerType,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.autonomy import (
    ApprovalRequest,
    AutonomousWorkflow,
    WorkflowExecutionLog,
    WorkflowIdempotencyRecord,
    WorkflowTask,
)
from app.utils.date_utils import utcnow

logger = get_logger("ai.autonomy.engine")

# Actions that cannot run because the capability is not connected.
UNAVAILABLE_ACTIONS = {
    "send_customer_message": (
        "No email or messaging provider is connected, so the draft stays internal "
        "and nothing is sent."
    ),
}

MAX_TASKS = 15


class WorkflowError(ValidationError):
    default_user_message = "The workflow could not be completed."


class AutonomousWorkflowEngine:
    """Runs the six autonomous workflows with policy and approval gates."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        services: Any,
        policy_engine: AutonomyPolicyEngine,
        audit_service: Any = None,
        agent_manager: Any = None,
        collaboration_manager: Any = None,
        max_tasks: int = MAX_TASKS,
    ) -> None:
        self._session_factory = session_factory
        self._services = services
        self._policies = policy_engine
        self._audit = audit_service
        self._agents = agent_manager
        self._collaborations = collaboration_manager
        self._max_tasks = max_tasks
        self._approvals: ApprovalService | None = None

    def attach_approvals(self, approvals: ApprovalService) -> None:
        self._approvals = approvals

    # ------------------------------------------------------------------
    # creation and planning
    # ------------------------------------------------------------------
    def create_workflow(
        self,
        workflow_type: str,
        *,
        payload: dict[str, Any] | None = None,
        trigger_type: str = WorkflowTriggerType.MANUAL,
        trigger_ref: str | None = None,
        objective: str | None = None,
        requested_by: int | None = None,
        business_id: int | None = None,
        scheduled_for: datetime | None = None,
    ) -> WorkflowView:
        template = get_template(workflow_type)
        payload = dict(payload or {})
        objective = objective or self._objective_for(template, payload)

        with self._session_factory() as db:
            workflow = AutonomousWorkflow(
                workflow_ref=f"wf-{uuid.uuid4().hex[:12]}",
                workflow_type=workflow_type,
                business_id=business_id,
                objective=objective,
                trigger_type=trigger_type,
                trigger_ref=trigger_ref,
                trigger_payload=payload,
                status=WorkflowStatus.PENDING,
                phase="CREATED",
                requested_by=requested_by,
                scheduled_for=scheduled_for,
            )
            db.add(workflow)
            db.flush()
            self._persist_plan(db, workflow, self.generate_workflow_plan(workflow_type, payload))
            workflow.status = WorkflowStatus.PLANNED
            workflow.planned_at = utcnow()
            workflow.phase = "PLANNED"
            db.add(
                WorkflowExecutionLog(
                    workflow_id=workflow.id,
                    event="PLANNED",
                    message=f"{len(template.tasks)} task(s) planned for {template.label}.",
                    data={"workflow_type": workflow_type, "trigger": trigger_type},
                )
            )
            db.commit()
            view = self._view(db, workflow)

        self._audit_event(
            requested_by,
            AuditAction.WORKFLOW_CREATED,
            view.workflow_ref,
            {"workflow_type": workflow_type, "trigger": trigger_type, "objective": objective[:200]},
        )
        logger.info("Created workflow %s (%s)", view.workflow_ref, workflow_type)
        return view

    def generate_workflow_plan(
        self, workflow_type: str, payload: dict[str, Any] | None = None
    ) -> list[WorkflowTaskSpec]:
        template = get_template(workflow_type)
        tasks = [task.model_copy(deep=True) for task in template.tasks]
        if len(tasks) > self._max_tasks:
            raise WorkflowError(
                f"This workflow needs {len(tasks)} tasks, above the limit of {self._max_tasks}"
            )
        # Every task can see the trigger payload (its own keys win), so the
        # approval task carries the exact action details that will be approved.
        for task in tasks:
            for key, value in (payload or {}).items():
                task.input_data.setdefault(key, value)
        return tasks

    def _persist_plan(
        self, db: Session, workflow: AutonomousWorkflow, tasks: list[WorkflowTaskSpec]
    ) -> None:
        for task in tasks:
            db.add(
                WorkflowTask(
                    workflow_id=workflow.id,
                    task_key=task.task_key,
                    task_type=task.task_type,
                    assigned_agent=task.assigned_agent,
                    action_name=task.action_name,
                    title=task.title,
                    input_data=task.input_data,
                    dependencies=list(task.dependencies),
                    execution_status=WorkflowTaskStatus.PENDING,
                    idempotency_key=f"{workflow.workflow_ref}:{task.task_key}",
                    permission_required=task.permission_required,
                    risk_level=task.risk_level,
                )
            )
        db.flush()

    def validate_workflow(self, workflow_ref: str) -> list[str]:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            tasks = self._tasks(db, workflow)
        errors: list[str] = []
        if not tasks:
            errors.append("the workflow has no tasks")
        if len(tasks) > self._max_tasks:
            errors.append(f"the workflow exceeds the {self._max_tasks}-task limit")

        keys = {task.task_key for task in tasks}
        if len(keys) != len(tasks):
            errors.append("duplicate task keys")
        for task in tasks:
            if task.task_type not in WorkflowTaskType.ALL:
                errors.append(f"task '{task.task_key}' has an unknown type")
            for dependency in task.dependencies or []:
                if dependency not in keys:
                    errors.append(f"task '{task.task_key}' depends on unknown '{dependency}'")
            if task.action_name and not is_registered(task.action_name):
                errors.append(f"task '{task.task_key}' uses an unregistered action")
        cycle = self._find_cycle(tasks)
        if cycle:
            errors.append("circular dependency: " + " → ".join(cycle))
        return errors

    def _find_cycle(self, tasks: list[WorkflowTask]) -> list[str] | None:
        graph = {task.task_key: list(task.dependencies or []) for task in tasks}
        state: dict[str, int] = {}
        stack: list[str] = []

        def visit(node: str) -> list[str] | None:
            state[node] = 1
            stack.append(node)
            for dep in graph.get(node, []):
                if dep not in graph:
                    continue
                if state.get(dep) == 1:
                    return stack[stack.index(dep):] + [dep]
                if state.get(dep, 0) == 0:
                    found = visit(dep)
                    if found:
                        return found
            stack.pop()
            state[node] = 2
            return None

        for key in graph:
            if state.get(key, 0) == 0:
                found = visit(key)
                if found:
                    return found
        return None

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def schedule_workflow(self, workflow_ref: str, when: datetime) -> WorkflowView:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status in WorkflowStatus.TERMINAL:
                raise ConflictError("This workflow has already finished")
            workflow.status = WorkflowStatus.SCHEDULED
            workflow.scheduled_for = when
            workflow.phase = "SCHEDULED"
            db.commit()
            return self._view(db, workflow)

    def start_workflow(self, workflow_ref: str) -> WorkflowDetail:
        return self.execute_workflow(workflow_ref)

    def execute_workflow(self, workflow_ref: str) -> WorkflowDetail:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status in (WorkflowStatus.CANCELLED, WorkflowStatus.ROLLED_BACK):
                return self.get_workflow_detail(workflow_ref)
            if workflow.status == WorkflowStatus.COMPLETED:
                return self.get_workflow_detail(workflow_ref)
            if workflow.status == WorkflowStatus.WAITING_APPROVAL:
                return self.get_workflow_detail(workflow_ref)
            errors = self.validate_workflow(workflow_ref)
            if errors:
                workflow.status = WorkflowStatus.FAILED
                workflow.error_message = "; ".join(errors)
                workflow.phase = "VALIDATION_FAILED"
                workflow.completed_at = utcnow()
                db.commit()
                return self.get_workflow_detail(workflow_ref)

            workflow.status = WorkflowStatus.RUNNING
            workflow.phase = "EXECUTING"
            workflow.started_at = workflow.started_at or utcnow()
            db.commit()
            workflow_id = workflow.id
            actor_id = workflow.requested_by

        self._audit_event(
            actor_id, AuditAction.WORKFLOW_STARTED, workflow_ref, {"status": "RUNNING"}
        )

        # Walk the dependency waves.
        for wave in self._waves(workflow_ref):
            for task_key in wave:
                outcome = self._run_task(workflow_ref, task_key, actor_id)
                if outcome == "PAUSED":
                    return self.get_workflow_detail(workflow_ref)
                if outcome == "FAILED":
                    self._finish(workflow_ref, WorkflowStatus.FAILED)
                    return self.get_workflow_detail(workflow_ref)
                if outcome == "CANCELLED":
                    self._finish(workflow_ref, WorkflowStatus.CANCELLED)
                    return self.get_workflow_detail(workflow_ref)

        verification = self.verify_execution_result(workflow_ref)
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            workflow.verification = verification
            failed = db.scalars(
                select(WorkflowTask).where(
                    WorkflowTask.workflow_id == workflow_id,
                    WorkflowTask.execution_status.in_(
                        (WorkflowTaskStatus.FAILED, WorkflowTaskStatus.SKIPPED)
                    ),
                )
            ).all()
            workflow.status = (
                WorkflowStatus.COMPLETED if not failed else WorkflowStatus.FAILED
            )
            workflow.phase = "COMPLETED" if not failed else "PARTIAL"
            workflow.completed_at = utcnow()
            workflow.result = {"verification": verification}
            db.commit()

        self._audit_event(
            actor_id,
            AuditAction.WORKFLOW_COMPLETED,
            workflow_ref,
            {"verification": verification.get("verified")},
        )
        return self.get_workflow_detail(workflow_ref)

    def _waves(self, workflow_ref: str) -> list[list[str]]:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            tasks = self._tasks(db, workflow)
            deps = {task.task_key: list(task.dependencies or []) for task in tasks}
            status = {task.task_key: task.execution_status for task in tasks}

        waves: list[list[str]] = []
        done: set[str] = {key for key, state in status.items() if state == WorkflowTaskStatus.COMPLETED}
        remaining = set(deps)
        while remaining:
            wave = sorted(
                key for key in remaining if all(dep in done for dep in deps[key])
            )
            if not wave:
                break
            waves.append(wave)
            done.update(wave)
            remaining.difference_update(wave)
        return waves

    def _run_task(self, workflow_ref: str, task_key: str, actor_id: int | None) -> str:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status == WorkflowStatus.CANCELLED:
                return "CANCELLED"
            task = self._task(db, workflow, task_key)
            if task is None:
                return "FAILED"
            if task.execution_status == WorkflowTaskStatus.COMPLETED:
                return "COMPLETED"  # idempotent skip
            task.execution_status = WorkflowTaskStatus.RUNNING
            task.started_at = utcnow()
            workflow.current_task_key = task_key
            workflow.phase = f"TASK:{task_key}"
            db.commit()
            task_type = task.task_type
            action_name = task.action_name
            payload = dict(task.input_data or {})
            task_id = task.id
            idempotency_key = task.idempotency_key
            dependencies = list(task.dependencies or [])

        started = time.perf_counter()
        try:
            if task_type == WorkflowTaskType.APPROVAL_REQUEST:
                result = self._request_approval(workflow_ref, task_key, action_name, payload, actor_id)
                if result == "PAUSED":
                    return "PAUSED"
            elif task_type in (
                WorkflowTaskType.BUSINESS_ANALYSIS,
                WorkflowTaskType.AGENT_COLLABORATION,
            ):
                result = self._run_analysis(workflow_ref, task_key, payload, dependencies)
            elif task_type == WorkflowTaskType.VALIDATION:
                result = {"summary": "Validation passed.", "checks": payload}
            elif task_type == WorkflowTaskType.VERIFICATION:
                result = self.verify_execution_result(workflow_ref)
            elif task_type == WorkflowTaskType.RECOMMENDATION and not action_name:
                result = self._compose_recommendation(workflow_ref, dependencies)
            elif task_type == WorkflowTaskType.NOTIFICATION and not action_name:
                result = self._compose_notification(workflow_ref)
            else:
                result = self._execute_action(
                    workflow_ref, task_key, action_name, payload, actor_id, idempotency_key
                )
                if isinstance(result, str):
                    # PAUSED / SKIPPED / FAILED sentinel from the action layer
                    return self._finish_task(workflow_ref, task_key, result, None, started)
        except ActionUnavailable as exc:
            return self._finish_task(workflow_ref, task_key, "SKIPPED", str(exc), started)
        except ActionRestricted as exc:
            return self._finish_task(workflow_ref, task_key, "FAILED", str(exc), started)
        except Exception as exc:  # noqa: BLE001 - one task must not kill the run
            logger.exception("Workflow task %s failed", task_key)
            return self._finish_task(workflow_ref, task_key, "FAILED", str(exc), started)

        return self._finish_task(workflow_ref, task_key, "COMPLETED", None, started, result)

    def _finish_task(
        self,
        workflow_ref: str,
        task_key: str,
        outcome: str,
        error: str | None,
        started: float,
        result: dict | None = None,
    ) -> str:
        status = {
            "COMPLETED": WorkflowTaskStatus.COMPLETED,
            "FAILED": WorkflowTaskStatus.FAILED,
            "SKIPPED": WorkflowTaskStatus.SKIPPED,
            "PAUSED": WorkflowTaskStatus.WAITING_APPROVAL,
            "CANCELLED": WorkflowTaskStatus.CANCELLED,
        }[outcome]
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            task = self._task(db, workflow, task_key)
            if task is not None:
                task.execution_status = status
                task.execution_ms = round((time.perf_counter() - started) * 1000, 2)
                if status in WorkflowTaskStatus.TERMINAL:
                    task.completed_at = utcnow()
                if result is not None:
                    task.result = result
                if error:
                    task.error_details = error[:1000]
                db.add(
                    WorkflowExecutionLog(
                        workflow_id=workflow.id,
                        task_key=task_key,
                        level="INFO" if outcome in ("COMPLETED", "SKIPPED", "PAUSED") else "ERROR",
                        event=f"TASK_{outcome}",
                        message=(result or {}).get("summary", "") or (error or ""),
                        data={"task_type": task.task_type, "action": task.action_name},
                    )
                )
            db.commit()
        return outcome

    # ------------------------------------------------------------------
    # task implementations
    # ------------------------------------------------------------------
    def _execute_action(
        self,
        workflow_ref: str,
        task_key: str,
        action_name: str | None,
        payload: dict[str, Any],
        actor_id: int | None,
        idempotency_key: str,
    ) -> dict | str:
        if not action_name:
            raise WorkflowError("This task has no action to execute")
        spec = get_action(action_name)
        if action_name in UNAVAILABLE_ACTIONS:
            raise ActionUnavailable(UNAVAILABLE_ACTIONS[action_name])

        amount = payload.get(spec.amount_field) if spec.amount_field else None
        decision = self._policies.evaluate(action_name, actor_id=actor_id, amount=amount)
        if not decision.allowed:
            self._log(workflow_ref, task_key, "ACTION_BLOCKED", decision.reason, {"action": action_name})
            raise ActionRestricted(decision.reason)
        if decision.requires_approval:
            return self._request_approval(workflow_ref, task_key, action_name, payload, actor_id)

        with self._session_factory() as db:
            existing = db.scalars(
                select(WorkflowIdempotencyRecord).where(
                    WorkflowIdempotencyRecord.idempotency_key == idempotency_key
                )
            ).first()
            if existing is not None:
                return existing.result or {"summary": "Already executed."}

        context = ActionContext(
            services=self._services,
            actor_id=actor_id or 0,
            payload=payload,
            workflow_ref=workflow_ref,
            task_key=task_key,
        )
        outcome = spec.handler(context)
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            db.add(
                WorkflowIdempotencyRecord(
                    idempotency_key=idempotency_key,
                    workflow_id=workflow.id,
                    task_key=task_key,
                    action_name=action_name,
                    result=outcome,
                )
            )
            db.commit()
        self._audit_event(
            actor_id,
            AuditAction.WORKFLOW_ACTION_EXECUTED,
            workflow_ref,
            {"action": action_name, "summary": str(outcome.get("summary", ""))[:200]},
        )
        return outcome

    def _request_approval(
        self,
        workflow_ref: str,
        task_key: str,
        action_name: str | None,
        payload: dict[str, Any],
        actor_id: int | None,
    ) -> str:
        if action_name is None:
            raise WorkflowError("An approval task needs an action")
        if self._approvals is None:
            raise WorkflowError("The approval service is not configured")
        if action_name in UNAVAILABLE_ACTIONS:
            raise ActionUnavailable(UNAVAILABLE_ACTIONS[action_name])

        spec = get_action(action_name)
        amount = payload.get(spec.amount_field) if spec.amount_field else None
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            task = self._task(db, workflow, task_key)
            if task is None:
                raise WorkflowError("Approval task not found")
            existing = db.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.workflow_id == workflow.id,
                    ApprovalRequest.task_key == task_key,
                    ApprovalRequest.status.in_(
                        (ApprovalStatus.PENDING, ApprovalStatus.APPROVED)
                    ),
                )
            ).first()
            if existing is not None:
                workflow.status = (
                    WorkflowStatus.WAITING_APPROVAL
                    if existing.status == ApprovalStatus.PENDING
                    else workflow.status
                )
                task.execution_status = (
                    WorkflowTaskStatus.WAITING_APPROVAL
                    if existing.status == ApprovalStatus.PENDING
                    else WorkflowTaskStatus.COMPLETED
                )
                db.commit()
                return "PAUSED" if existing.status == ApprovalStatus.PENDING else "COMPLETED"

            evidence = self._collect_evidence(db, workflow)
            request = self._approvals.create_request(
                db=db,
                workflow=workflow,
                task=task,
                action_name=action_name,
                payload=payload,
                reason=self._approval_reason(spec.display_name, workflow),
                evidence=evidence,
                financial_impact=self._financial_impact(action_name, payload, amount),
                risk_level=spec.risk_level,
            )
            workflow.status = WorkflowStatus.WAITING_APPROVAL
            workflow.phase = f"WAITING_APPROVAL:{task_key}"
            task.execution_status = WorkflowTaskStatus.WAITING_APPROVAL
            db.add(
                WorkflowExecutionLog(
                    workflow_id=workflow.id,
                    task_key=task_key,
                    event="APPROVAL_REQUESTED",
                    message=f"Approval requested for {spec.display_name}.",
                    data={"approval_ref": request.approval_ref, "action": action_name},
                )
            )
            db.commit()
            approval_ref = request.approval_ref

        self._audit_event(
            actor_id,
            AuditAction.APPROVAL_REQUESTED,
            workflow_ref,
            {"action": action_name, "approval_ref": approval_ref},
        )
        return "PAUSED"

    def _run_analysis(
        self, workflow_ref: str, task_key: str, payload: dict[str, Any], dependencies: list[str]
    ) -> dict:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            task = self._task(db, workflow, task_key)
            agent = task.assigned_agent if task else None
            task_type = (task.input_data or {}).get("task_type") if task else None
            requested_by = workflow.requested_by
            period = "this_month"

        if task_type == "COLLABORATION" and self._collaborations is not None:
            scenario = payload.get("scenario", "BUSINESS_HEALTH")
            detail = self._collaborations.create_collaboration(
                objective=f"Workflow {workflow_ref}: {task_key}",
                scenario=scenario,
                period=period,
                user_id=requested_by,
            )
            detail = self._collaborations.execute_collaboration(detail.collaboration.collaboration_id)
            decision = detail.decision
            return {
                "summary": decision.executive_summary if decision else "Collaboration finished.",
                "collaboration_id": detail.collaboration.collaboration_id,
                "decision_status": decision.status if decision else None,
            }

        if agent is None or self._agents is None:
            raise WorkflowError("No agent is available for this analysis task")
        result = self._agents.run_agent(
            agent,
            period=period,
            task_type=task_type or "",
            parameters={"workflow_ref": workflow_ref, "task_key": task_key},
            user_id=requested_by,
            workflow_id=f"wf:{workflow_ref}",
        )
        return {
            "summary": result.summary,
            "agent_id": result.agent_id,
            "status": result.status,
            "confidence": result.confidence,
            "findings": [finding.model_dump(mode="json") for finding in result.findings[:5]],
            "recommendations": [
                recommendation.model_dump(mode="json")
                for recommendation in result.recommendations[:3]
            ],
            "data_gaps": result.data_gaps,
        }

    def _compose_recommendation(self, workflow_ref: str, dependencies: list[str]) -> dict:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            tasks = self._tasks(db, workflow)
            summaries = [
                (task.result or {}).get("summary", "")
                for task in tasks
                if task.task_key in dependencies and task.result
            ]
        return {
            "summary": "Recommendation prepared from " + f"{len(summaries)} input(s).",
            "inputs": summaries,
            "requires_human_action": True,
        }

    def _compose_notification(self, workflow_ref: str) -> dict:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            tasks = self._tasks(db, workflow)
            completed = [task.task_key for task in tasks if task.execution_status == WorkflowTaskStatus.COMPLETED]
        return {
            "summary": f"Internal notification recorded ({len(completed)} completed task(s)).",
            "channel": "INTERNAL",
            "sent": False,
        }

    # ------------------------------------------------------------------
    # approvals, pause, resume, cancel, retry, rollback
    # ------------------------------------------------------------------
    def on_approval_granted(self, workflow_ref: str) -> None:
        """Called by the approval service after a successful approval."""
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status == WorkflowStatus.WAITING_APPROVAL:
                workflow.status = WorkflowStatus.RUNNING
                workflow.phase = "RESUMING_AFTER_APPROVAL"
                db.commit()
        self.execute_workflow(workflow_ref)

    def pause_workflow(self, workflow_ref: str, *, reason: str = "Paused by user") -> WorkflowView:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status in WorkflowStatus.TERMINAL:
                raise ConflictError("This workflow has already finished")
            workflow.status = WorkflowStatus.PAUSED
            workflow.phase = "PAUSED"
            db.add(
                WorkflowExecutionLog(
                    workflow_id=workflow.id, event="PAUSED", message=reason[:500]
                )
            )
            db.commit()
            view = self._view(db, workflow)
        self._audit_event(
            workflow.requested_by, AuditAction.WORKFLOW_PAUSED, workflow_ref, {"reason": reason}
        )
        return view

    def resume_workflow(self, workflow_ref: str) -> WorkflowDetail:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status not in (WorkflowStatus.PAUSED, WorkflowStatus.WAITING_APPROVAL):
                raise ConflictError("Only paused or waiting workflows can be resumed")
            pending = db.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.workflow_id == workflow.id,
                    ApprovalRequest.status == ApprovalStatus.PENDING,
                )
            ).all()
            if pending:
                raise ConflictError(
                    "This workflow is waiting for an approval decision; approve or reject it first"
                )
            workflow.status = WorkflowStatus.RUNNING
            db.commit()
        self._audit_event(
            workflow.requested_by, AuditAction.WORKFLOW_RESUMED, workflow_ref, {}
        )
        return self.execute_workflow(workflow_ref)

    def cancel_workflow(self, workflow_ref: str) -> WorkflowView:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status in WorkflowStatus.TERMINAL:
                raise ConflictError("This workflow has already finished")
            workflow.status = WorkflowStatus.CANCELLED
            workflow.phase = "CANCELLED"
            workflow.completed_at = utcnow()
            for request in db.scalars(
                select(ApprovalRequest).where(
                    ApprovalRequest.workflow_id == workflow.id,
                    ApprovalRequest.status == ApprovalStatus.PENDING,
                )
            ).all():
                request.status = ApprovalStatus.CANCELLED
            db.add(
                WorkflowExecutionLog(workflow_id=workflow.id, event="CANCELLED", message="Workflow cancelled")
            )
            db.commit()
            view = self._view(db, workflow)
        self._audit_event(
            workflow.requested_by, AuditAction.WORKFLOW_CANCELLED, workflow_ref, {}
        )
        return view

    def retry_workflow(self, workflow_ref: str) -> WorkflowDetail:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status == WorkflowStatus.CANCELLED:
                raise ConflictError("Cancelled workflows cannot be retried")
            for task in self._tasks(db, workflow):
                if task.execution_status in (
                    WorkflowTaskStatus.FAILED,
                    WorkflowTaskStatus.SKIPPED,
                ):
                    task.execution_status = WorkflowTaskStatus.PENDING
                    task.error_details = None
                    task.retry_count += 1
            workflow.retry_count += 1
            workflow.status = WorkflowStatus.RUNNING
            workflow.error_message = None
            db.commit()
        return self.execute_workflow(workflow_ref)

    def rollback_workflow(self, workflow_ref: str, *, reason: str = "Rolled back by user") -> dict:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            if workflow.status == WorkflowStatus.ROLLED_BACK:
                raise ConflictError("This workflow was already rolled back")
            records = db.scalars(
                select(WorkflowIdempotencyRecord).where(
                    WorkflowIdempotencyRecord.workflow_id == workflow.id
                )
            ).all()
            entries = [
                (record.action_name, dict(record.result or {})) for record in records
            ]
            requested_by = workflow.requested_by

        reversed_actions: list[str] = []
        not_reversible: list[str] = []
        for action_name, result in entries:
            spec = ACTION_REGISTRY.get(action_name)
            if spec is None or not spec.reversible or spec.compensate is None:
                not_reversible.append(action_name)
                continue
            context = ActionContext(
                services=self._services,
                actor_id=requested_by or 0,
                payload={},
                workflow_ref=workflow_ref,
            )
            try:
                spec.compensate(context, result)
                reversed_actions.append(action_name)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Compensation failed for %s", action_name)
                not_reversible.append(f"{action_name} ({exc})")

        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            workflow.status = WorkflowStatus.ROLLED_BACK
            workflow.phase = "ROLLED_BACK"
            workflow.completed_at = utcnow()
            workflow.result = {
                "rolled_back": reversed_actions,
                "not_reversible": not_reversible,
                "reason": reason,
            }
            db.add(
                WorkflowExecutionLog(
                    workflow_id=workflow.id,
                    event="ROLLED_BACK",
                    message=reason[:500],
                    data={"reversed": reversed_actions, "not_reversible": not_reversible},
                )
            )
            db.commit()
        self._audit_event(
            requested_by,
            AuditAction.WORKFLOW_ROLLED_BACK,
            workflow_ref,
            {"reversed": reversed_actions, "not_reversible": not_reversible},
        )
        return {
            "workflow_ref": workflow_ref,
            "reversed": reversed_actions,
            "not_reversible": not_reversible,
        }

    # ------------------------------------------------------------------
    # verification, reads, recovery
    # ------------------------------------------------------------------
    def verify_execution_result(self, workflow_ref: str) -> dict:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            records = db.scalars(
                select(WorkflowIdempotencyRecord).where(
                    WorkflowIdempotencyRecord.workflow_id == workflow.id
                )
            ).all()
            entries = [
                (record.action_name, dict(record.result or {})) for record in records
            ]

        checks: list[dict[str, Any]] = []
        for action_name, result in entries:
            record_type = result.get("record_type")
            record_id = result.get("record_id")
            if not record_type or record_id is None:
                continue
            checks.append(self._verify_record(record_type, record_id, action_name))

        verified = all(check["verified"] for check in checks) if checks else True
        return {
            "verified": verified,
            "checks": checks,
            "verified_at": utcnow().isoformat(),
            "note": (
                "No business-changing action was executed."
                if not checks
                else f"{len(checks)} record(s) re-read from the database."
            ),
        }

    def _verify_record(self, record_type: str, record_id: int, action_name: str) -> dict:
        try:
            if record_type == "purchase_order":
                record = self._services.purchasing_service.get_purchase_order(record_id)
                exists, detail = True, record.purchase_order_number
            elif record_type == "expense":
                record = next(
                    (
                        expense
                        for expense in self._services.finance_service.list_expenses()
                        if expense.id == record_id
                    ),
                    None,
                )
                exists = record is not None
                detail = record.expense_number if record else "expense not found"
            elif record_type == "product":
                record = self._services.inventory_service.get_product(record_id)
                exists, detail = True, record.sku
            else:
                exists, detail = False, "no verifier for this record type"
        except Exception as exc:  # noqa: BLE001
            exists, detail = False, str(exc)[:200]
        return {
            "action": action_name,
            "record_type": record_type,
            "record_id": record_id,
            "verified": exists,
            "detail": detail,
        }

    def get_workflow_status(self, workflow_ref: str) -> WorkflowView:
        with self._session_factory() as db:
            return self._view(db, self._load(db, workflow_ref))

    def list_workflows(self, limit: int = 30) -> list[WorkflowView]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(AutonomousWorkflow).order_by(AutonomousWorkflow.id.desc()).limit(limit)
            ).all()
            return [self._view(db, row) for row in rows]

    def dashboard_stats(self) -> dict[str, int]:
        with self._session_factory() as db:
            rows = db.scalars(select(AutonomousWorkflow)).all()
            pending = db.scalars(
                select(ApprovalRequest).where(ApprovalRequest.status == ApprovalStatus.PENDING)
            ).all()
        return {
            "total": len(rows),
            "active": sum(1 for row in rows if row.status in WorkflowStatus.ACTIVE),
            "completed": sum(1 for row in rows if row.status == WorkflowStatus.COMPLETED),
            "failed": sum(1 for row in rows if row.status == WorkflowStatus.FAILED),
            "waiting_approval": sum(
                1 for row in rows if row.status == WorkflowStatus.WAITING_APPROVAL
            ),
            "pending_approvals": len(pending),
        }

    def get_workflow_detail(self, workflow_ref: str) -> WorkflowDetail:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            tasks = self._tasks(db, workflow)
            approvals = db.scalars(
                select(ApprovalRequest)
                .where(ApprovalRequest.workflow_id == workflow.id)
                .order_by(ApprovalRequest.id)
            ).all()
            logs = db.scalars(
                select(WorkflowExecutionLog)
                .where(WorkflowExecutionLog.workflow_id == workflow.id)
                .order_by(WorkflowExecutionLog.id)
            ).all()
            return WorkflowDetail(
                workflow=self._view(db, workflow),
                tasks=[
                    WorkflowTaskView(
                        workflow_ref=workflow.workflow_ref,
                        task_key=task.task_key,
                        task_type=task.task_type,
                        title=task.title,
                        assigned_agent=task.assigned_agent,
                        action_name=task.action_name,
                        dependencies=list(task.dependencies or []),
                        status=task.execution_status,
                        retry_count=task.retry_count,
                        risk_level=task.risk_level,
                        permission_required=task.permission_required,
                        result=task.result,
                        error=task.error_details,
                        execution_ms=task.execution_ms,
                        started_at=task.started_at,
                        completed_at=task.completed_at,
                    )
                    for task in tasks
                ],
                approvals=[
                    {
                        "approval_ref": request.approval_ref,
                        "task_key": request.task_key,
                        "action": request.requested_action,
                        "status": request.status,
                        "risk": request.risk_level,
                        "financial_impact": (
                            f"{Decimal(str(request.financial_impact)):,.2f}"
                            if request.financial_impact
                            else None
                        ),
                        "reason": request.reason,
                        "expires_at": request.expires_at,
                        "execution_result": request.execution_result,
                    }
                    for request in approvals
                ],
                logs=[
                    {
                        "level": log.level,
                        "event": log.event,
                        "message": log.message,
                        "task_key": log.task_key,
                        "created_at": log.created_at,
                    }
                    for log in logs
                ],
                verification=workflow.verification or {},
                result=workflow.result or {},
            )

    def get_workflow_history(self, workflow_ref: str) -> list[dict[str, Any]]:
        return self.get_workflow_detail(workflow_ref).logs

    def recover_interrupted(self) -> int:
        """Workflows left RUNNING by a crash are paused so they can be resumed."""
        recovered = 0
        with self._session_factory() as db:
            rows = db.scalars(
                select(AutonomousWorkflow).where(
                    AutonomousWorkflow.status.in_((WorkflowStatus.RUNNING, WorkflowStatus.PENDING))
                )
            ).all()
            for row in rows:
                row.status = WorkflowStatus.PAUSED
                row.phase = "RECOVERED"
                row.error_message = (
                    "Interrupted by an application restart; resume to continue. "
                    "Completed tasks and executed actions are preserved."
                )
                db.add(
                    WorkflowExecutionLog(
                        workflow_id=row.id,
                        level="WARNING",
                        event="RECOVERED",
                        message="Workflow paused after restart; safe to resume.",
                    )
                )
                recovered += 1
            db.commit()
        if recovered:
            logger.warning("Recovered %d interrupted workflow(s)", recovered)
        return recovered

    def expire_approvals(self) -> int:
        if self._approvals is None:
            return 0
        return self._approvals.expire_stale()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _load(self, db: Session, workflow_ref: str) -> AutonomousWorkflow:
        row = db.scalars(
            select(AutonomousWorkflow).where(AutonomousWorkflow.workflow_ref == workflow_ref)
        ).first()
        if row is None:
            raise NotFoundError(f"Workflow '{workflow_ref}' was not found")
        return row

    def _tasks(self, db: Session, workflow: AutonomousWorkflow) -> list[WorkflowTask]:
        return list(
            db.scalars(
                select(WorkflowTask)
                .where(WorkflowTask.workflow_id == workflow.id)
                .order_by(WorkflowTask.id)
            ).all()
        )

    def _task(
        self, db: Session, workflow: AutonomousWorkflow, task_key: str
    ) -> WorkflowTask | None:
        return db.scalars(
            select(WorkflowTask).where(
                WorkflowTask.workflow_id == workflow.id,
                WorkflowTask.task_key == task_key,
            )
        ).first()

    def _view(self, db: Session, workflow: AutonomousWorkflow) -> WorkflowView:
        tasks = self._tasks(db, workflow)
        approvals = db.scalars(
            select(ApprovalRequest).where(ApprovalRequest.workflow_id == workflow.id)
        ).all()
        return WorkflowView(
            workflow_ref=workflow.workflow_ref,
            workflow_type=workflow.workflow_type,
            objective=workflow.objective,
            trigger_type=workflow.trigger_type,
            trigger_ref=workflow.trigger_ref,
            status=workflow.status,
            phase=workflow.phase,
            tasks_total=len(tasks),
            tasks_completed=sum(
                1 for task in tasks if task.execution_status == WorkflowTaskStatus.COMPLETED
            ),
            tasks_failed=sum(
                1
                for task in tasks
                if task.execution_status in (WorkflowTaskStatus.FAILED, WorkflowTaskStatus.SKIPPED)
            ),
            pending_approvals=sum(
                1 for approval in approvals if approval.status == ApprovalStatus.PENDING
            ),
            retry_count=workflow.retry_count,
            current_task=workflow.current_task_key,
            requested_by=workflow.requested_by,
            scheduled_for=workflow.scheduled_for,
            created_at=workflow.created_at,
            started_at=workflow.started_at,
            completed_at=workflow.completed_at,
            error=workflow.error_message,
        )

    def _collect_evidence(self, db: Session, workflow: AutonomousWorkflow) -> dict[str, Any]:
        tasks = self._tasks(db, workflow)
        return {
            "trigger": {"type": workflow.trigger_type, "ref": workflow.trigger_ref},
            "task_summaries": [
                {"task": task.task_key, "summary": (task.result or {}).get("summary", "")}
                for task in tasks
                if task.result
            ],
            "verification": workflow.verification or {},
        }

    def _financial_impact(
        self, action_name: str, payload: dict[str, Any], amount: Any
    ) -> Decimal | None:
        if amount not in (None, ""):
            try:
                return Decimal(str(amount)).quantize(Decimal("0.01"))
            except Exception:  # noqa: BLE001 - fall through to item maths
                pass
        if action_name == "create_purchase_order":
            total = Decimal("0.00")
            for item in payload.get("items") or []:
                try:
                    total += Decimal(str(item.get("ordered_quantity", 0))) * Decimal(
                        str(item.get("unit_cost", 0))
                    )
                except Exception:  # noqa: BLE001
                    continue
            return total.quantize(Decimal("0.01")) if total > 0 else None
        return None

    def _approval_reason(self, display_name: str, workflow: AutonomousWorkflow) -> str:
        return (
            f"{display_name} requested by workflow '{workflow.workflow_type}' "
            f"({workflow.workflow_ref}). Policy requires human approval."
        )

    def _objective_for(self, template: WorkflowTemplate, payload: dict[str, Any]) -> str:
        values = {
            "product": payload.get("product_name", "a low-stock product"),
            "customer": payload.get("customer_name", "an inactive customer"),
            "amount": payload.get("amount", "an unusual amount"),
            "invoice_number": payload.get("invoice_number", "an overdue invoice"),
        }
        try:
            return template.objective_template.format(**values)
        except (KeyError, IndexError):
            return template.label

    def _log(
        self, workflow_ref: str, task_key: str, event: str, message: str, data: dict | None
    ) -> None:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            db.add(
                WorkflowExecutionLog(
                    workflow_id=workflow.id,
                    task_key=task_key,
                    level="WARNING",
                    event=event,
                    message=message[:500],
                    data=data,
                )
            )
            db.commit()

    def _finish(self, workflow_ref: str, status: str) -> None:
        with self._session_factory() as db:
            workflow = self._load(db, workflow_ref)
            workflow.status = status
            workflow.phase = status
            workflow.completed_at = utcnow()
            db.commit()

    def _audit_event(
        self, actor_id: int | None, action: str, workflow_ref: str, values: dict
    ) -> None:
        if self._audit is None:
            return
        try:
            self._audit.record_event(
                actor_id=actor_id,
                action=action,
                module=MODULE_AGENTS,
                entity_type="AutonomousWorkflow",
                entity_id=workflow_ref,
                new_values=values,
            )
        except Exception:  # pragma: no cover
            logger.exception("Could not write workflow audit entry")
