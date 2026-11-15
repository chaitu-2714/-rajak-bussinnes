"""Collaboration service — the UI's entry point for multi-agent work.

Owns RBAC, persistence of history and the decision exports; the actual
coordination lives in :class:`MultiAgentCollaborationManager`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from app.ai.collaboration.manager import MultiAgentCollaborationManager
from app.ai.collaboration.planner import SCENARIOS
from app.ai.schemas.collaboration_schema import (
    CollaborationDetail,
    CollaborationView,
    UnifiedDecision,
)
from app.core.constants import MODULE_AGENTS, AuditAction, CollaborationStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.schemas.finance_schema import ReportTable
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService
from app.services.export_service import ExportService
from app.utils.date_utils import utcnow

logger = get_logger("services.collaboration")


class CollaborationService(BaseService):
    """Create, run and report multi-agent collaborations."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        manager: MultiAgentCollaborationManager,
        export_service: ExportService,
        audit_service: AuditService,
        services: Any = None,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._manager = manager
        self._export = export_service
        self._audit = audit_service
        self._services = services

    # -- catalogue ---------------------------------------------------------
    def scenarios(self) -> list[dict[str, str]]:
        return [
            {
                "key": spec.key,
                "label": spec.label,
                "strategy": spec.strategy,
                "objective": spec.objective_template.format(target=20),
                "agents": ", ".join(spec.agents),
                "tasks": str(len(spec.tasks)),
            }
            for spec in SCENARIOS.values()
        ]

    # -- lifecycle ---------------------------------------------------------
    def create_collaboration(
        self, objective: str, *, scenario: str | None = None, period: str | None = None
    ) -> CollaborationView:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.execute")
            user_id = user.id
            business_id = self._business_id(db)
        return self._manager.create_collaboration(
            objective, scenario=scenario, period=period, user_id=user_id, business_id=business_id
        )

    def run_collaboration(
        self, objective: str, *, scenario: str | None = None, period: str | None = None
    ) -> CollaborationDetail:
        """Create and execute in one call (used by tests and scripts)."""
        view = self.create_collaboration(objective, scenario=scenario, period=period)
        return self.execute_collaboration(view.collaboration_id)

    def execute_collaboration(self, collaboration_id: str) -> CollaborationDetail:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.execute")
        return self._manager.execute_collaboration(collaboration_id)

    def cancel_collaboration(self, collaboration_id: str) -> bool:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.execute")
            user_id = user.id
        cancelled = self._manager.cancel_collaboration(collaboration_id)
        if cancelled:
            with self.unit_of_work() as db:
                self._audit.record(
                    db,
                    actor_id=user_id,
                    action=AuditAction.COLLABORATION_CANCELLED,
                    module=MODULE_AGENTS,
                    entity_type="AgentCollaboration",
                    entity_id=collaboration_id,
                )
        return cancelled

    def retry_collaboration(self, collaboration_id: str) -> CollaborationDetail:
        """Re-run only the tasks that did not complete (idempotent)."""
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.execute")
        return self._manager.execute_collaboration(collaboration_id)

    def recover_interrupted(self) -> int:
        return self._manager.recover_interrupted()

    # -- read models -------------------------------------------------------
    def list_collaborations(self, limit: int = 25) -> list[CollaborationView]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
        return self._manager.list_collaborations(limit=limit)

    def dashboard_stats(self) -> dict[str, int]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
        return self._manager.dashboard_stats()

    def get_status(self, collaboration_id: str) -> CollaborationView:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
        return self._manager.get_collaboration_status(collaboration_id)

    def get_detail(self, collaboration_id: str) -> CollaborationDetail:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
        return self._manager.get_collaboration_detail(collaboration_id)

    def get_decision(self, collaboration_id: str) -> UnifiedDecision | None:
        return self.get_detail(collaboration_id).decision

    # -- exports -----------------------------------------------------------
    def export_decision_csv(self, collaboration_id: str) -> Path:
        detail = self.get_detail(collaboration_id)
        decision = detail.decision
        if decision is None:
            raise NotFoundError("This collaboration has no decision to export yet")

        rows: list[list[str]] = [
            ["Summary", decision.status, decision.executive_summary, "", ""],
            [
                "Financial impact",
                "available_budget",
                decision.financial_impact.get("available_budget", ""),
                "planned_spend",
                decision.financial_impact.get("planned_spend", ""),
            ],
        ]
        for finding in decision.consolidated_findings:
            rows.append(
                [
                    "Finding",
                    finding.severity,
                    finding.description,
                    finding.finding_type,
                    finding.reporting_period or "",
                ]
            )
        for action in decision.recommended_actions:
            rows.append(
                [
                    "Recommendation",
                    action.priority,
                    action.action,
                    f"cost={action.estimated_cost or '-'}",
                    f"approvals={', '.join(action.required_approvals) or '-'}",
                ]
            )
        for conflict in decision.conflicting_findings:
            rows.append(
                [
                    "Conflict",
                    str(conflict.get("status", "")),
                    str(conflict.get("description", "")),
                    str(conflict.get("type", "")),
                    ", ".join(conflict.get("agents", [])),
                ]
            )
        for limitation in decision.limitations:
            rows.append(["Limitation", "", limitation, "", ""])

        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.execute")
            path = self._export.write_csv(
                f"decision_{collaboration_id}.csv",
                ["section", "priority_or_status", "item", "detail", "extra"],
                rows,
            )
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.COLLABORATION_DECISION_EXPORTED,
                module=MODULE_AGENTS,
                entity_type="AgentCollaboration",
                entity_id=collaboration_id,
                new_values={"format": "CSV", "file": path.name},
            )
        return path

    def export_decision_pdf(self, collaboration_id: str) -> Path:
        detail = self.get_detail(collaboration_id)
        decision = detail.decision
        if decision is None:
            raise NotFoundError("This collaboration has no decision to export yet")

        rows = [
            [
                action.priority,
                action.action,
                str(action.estimated_cost or "-"),
                ", ".join(action.required_approvals) or "-",
            ]
            for action in decision.recommended_actions
        ]
        totals = [
            f"Available budget: {decision.financial_impact.get('available_budget', 'n/a')}",
            f"Planned spend: {decision.financial_impact.get('planned_spend', 'n/a')}",
            f"Decision status: {decision.status}",
            f"Confidence: {decision.confidence}",
        ]
        report = ReportTable(
            title=f"Business decision — {detail.collaboration.scenario.replace('_', ' ').title()}",
            subtitle=detail.collaboration.objective,
            headers=["Priority", "Recommended action", "Estimated cost", "Approvals"],
            rows=rows,
            totals=totals,
            basis=decision.executive_summary,
            generated_at=decision.generated_at or utcnow(),
        )
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.execute")
            path = self._export.write_pdf_report(report, f"decision_{collaboration_id}.pdf")
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.COLLABORATION_DECISION_EXPORTED,
                module=MODULE_AGENTS,
                entity_type="AgentCollaboration",
                entity_id=collaboration_id,
                new_values={"format": "PDF", "file": path.name},
            )
        return path

    # -- helpers -----------------------------------------------------------
    def _business_id(self, db: Session) -> int | None:
        try:
            business = self._services.business_repository.get_primary(db) if self._services else None
        except Exception:  # pragma: no cover - defensive
            business = None
        return business.id if business else None
