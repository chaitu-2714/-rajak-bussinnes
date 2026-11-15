"""Autonomy service — the UI's entry point for workflows, approvals and policies."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.ai.autonomy.approvals import ApprovalService
from app.ai.autonomy.engine import AutonomousWorkflowEngine
from app.ai.autonomy.policy_engine import AutonomyPolicyEngine
from app.ai.autonomy.scheduler import WorkflowScheduler
from app.ai.autonomy.templates import TEMPLATES, workflow_types
from app.ai.autonomy.triggers import WorkflowTriggerManager
from app.ai.schemas.autonomy_schema import (
    ApprovalView,
    PolicyView,
    WorkflowDetail,
    WorkflowView,
)
from app.core.constants import MODULE_AUTOMATION, AuditAction
from app.core.exceptions import NotFoundError
from app.core.logging_config import get_logger
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService

logger = get_logger("services.autonomy")


class AutonomyService(BaseService):
    """Workflows, approvals, policies and schedules with RBAC applied."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        engine: AutonomousWorkflowEngine,
        policy_engine: AutonomyPolicyEngine,
        approvals: ApprovalService,
        scheduler: WorkflowScheduler,
        triggers: WorkflowTriggerManager,
        audit_service: AuditService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._engine = engine
        self._policies = policy_engine
        self._approvals = approvals
        self._scheduler = scheduler
        self._triggers = triggers
        self._audit = audit_service

    # -- catalogue ---------------------------------------------------------
    def workflow_catalogue(self) -> list[dict[str, Any]]:
        return [
            {
                "workflow_type": template.workflow_type,
                "label": template.label,
                "trigger": template.trigger_description,
                "agents": ", ".join(template.agents) or "—",
                "tasks": str(len(template.tasks)),
                "requires_approval": template.requires_approval,
            }
            for template in TEMPLATES.values()
        ]

    # -- workflows ---------------------------------------------------------
    def create_workflow(
        self,
        workflow_type: str,
        *,
        payload: dict[str, Any] | None = None,
        objective: str | None = None,
    ) -> WorkflowView:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "automation.execute")
            user_id = user.id
        return self._engine.create_workflow(
            workflow_type,
            payload=payload or {},
            objective=objective,
            requested_by=user_id,
        )

    def start_workflow(self, workflow_ref: str) -> WorkflowDetail:
        self._authorise_execute()
        return self._engine.start_workflow(workflow_ref)

    def execute_workflow(self, workflow_ref: str) -> WorkflowDetail:
        self._authorise_execute()
        return self._engine.execute_workflow(workflow_ref)

    def pause_workflow(self, workflow_ref: str) -> WorkflowView:
        self._authorise_execute()
        return self._engine.pause_workflow(workflow_ref)

    def resume_workflow(self, workflow_ref: str) -> WorkflowDetail:
        self._authorise_execute()
        return self._engine.resume_workflow(workflow_ref)

    def cancel_workflow(self, workflow_ref: str) -> WorkflowView:
        self._authorise_execute()
        return self._engine.cancel_workflow(workflow_ref)

    def retry_workflow(self, workflow_ref: str) -> WorkflowDetail:
        self._authorise_execute()
        return self._engine.retry_workflow(workflow_ref)

    def rollback_workflow(self, workflow_ref: str, *, reason: str) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "approvals.approve")
            actor = user.id
        result = self._engine.rollback_workflow(workflow_ref, reason=reason)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor,
                action=AuditAction.WORKFLOW_ROLLED_BACK,
                module=MODULE_AUTOMATION,
                entity_type="AutonomousWorkflow",
                entity_id=workflow_ref,
                new_values={"reason": reason, "reversed": result.get("reversed")},
            )
        return result

    def list_workflows(self, limit: int = 40) -> list[WorkflowView]:
        self._authorise_view()
        return self._engine.list_workflows(limit=limit)

    def get_workflow(self, workflow_ref: str) -> WorkflowDetail:
        self._authorise_view()
        return self._engine.get_workflow_detail(workflow_ref)

    def get_workflow_status(self, workflow_ref: str) -> WorkflowView:
        self._authorise_view()
        return self._engine.get_workflow_status(workflow_ref)

    def verify_workflow(self, workflow_ref: str) -> dict[str, Any]:
        self._authorise_view()
        return self._engine.verify_execution_result(workflow_ref)

    def dashboard_stats(self) -> dict[str, int]:
        self._authorise_view()
        return self._engine.dashboard_stats()

    def workflow_history(self, workflow_ref: str) -> list[dict[str, Any]]:
        self._authorise_view()
        return self._engine.get_workflow_history(workflow_ref)

    # -- approvals ---------------------------------------------------------
    def pending_approvals(self) -> list[ApprovalView]:
        return self._approvals.list_requests(status="PENDING")

    def all_approvals(self, limit: int = 50) -> list[ApprovalView]:
        return self._approvals.list_requests(limit=limit)

    def approve(self, approval_ref: str, *, note: str | None = None) -> ApprovalView:
        return self._approvals.approve(approval_ref, note=note)

    def reject(self, approval_ref: str, *, reason: str) -> ApprovalView:
        return self._approvals.reject(approval_ref, reason=reason)

    def expire_approvals(self) -> int:
        self._authorise_execute()
        return self._approvals.expire_stale()

    # -- policies ----------------------------------------------------------
    def policies(self) -> list[PolicyView]:
        self._authorise_view()
        return self._policies.policies()

    def update_policy(self, action_name: str, *, changes: dict[str, Any]) -> PolicyView:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.configure")
            actor = user.id
        view = self._policies.update_policy(action_name, changes=changes)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor,
                action=AuditAction.AUTONOMY_POLICY_UPDATED,
                module=MODULE_AUTOMATION,
                entity_type="AutonomyPolicy",
                entity_id=action_name,
                new_values={"changes": changes},
            )
        return view

    # -- schedules ---------------------------------------------------------
    def schedules(self) -> list[dict[str, Any]]:
        self._authorise_view()
        return self._scheduler.list_schedules()

    def update_schedule(self, schedule_key: str, *, changes: dict[str, Any]) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.configure")
            actor = user.id
        result = self._scheduler.update_schedule(schedule_key, changes=changes)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor,
                action=AuditAction.SCHEDULE_UPDATED,
                module=MODULE_AUTOMATION,
                entity_type="ScheduledWorkflow",
                entity_id=schedule_key,
                new_values={"changes": changes},
            )
        return result

    def run_due_schedules(self) -> dict[str, Any]:
        self._authorise_execute()
        return self._scheduler.tick()

    # -- triggers ----------------------------------------------------------
    def process_events(self, limit: int = 20) -> dict[str, int]:
        self._authorise_execute()
        return self._triggers.process_pending(limit=limit)

    def dead_letters(self, limit: int = 20) -> list[dict[str, Any]]:
        self._authorise_view()
        return self._triggers.list_dead_letters(limit=limit)

    def retry_dead_letters(self) -> int:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.configure")
        return self._triggers.retry_dead_letters()

    # -- startup -----------------------------------------------------------
    def recover(self) -> dict[str, int]:
        return {
            "workflows": self._engine.recover_interrupted(),
            "approvals": self._approvals.expire_stale(),
        }

    # -- helpers -----------------------------------------------------------
    def _authorise_view(self) -> None:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "automation.view")

    def _authorise_execute(self) -> None:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "automation.execute")
