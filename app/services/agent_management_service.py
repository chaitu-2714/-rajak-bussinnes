"""Agent management: registration, execution, persistence and reporting.

This is the only entry point the orchestrator and the UI use to run an agent.
Executions, findings, recommendations and memory are all persisted here, and
every run is audited.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.agents.base_agent import BaseBusinessAgent, ToolRunner
from app.ai.agents.coordinator import AgentCoordinator
from app.ai.memory.business_memory import BusinessMemory
from app.ai.schemas.agent_schema import AgentResult, AgentTask, AgentInfo
from app.ai.schemas.tool_schema import ToolContext, ToolInvocation
from app.core.constants import (
    MODULE_AGENTS,
    AgentExecutionStatus,
    AgentMemoryType,
    AuditAction,
    RecommendationStatus,
)
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.agents import (
    Agent,
    AgentExecution,
    AgentFinding,
    AgentRecommendation,
)
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService
from app.utils.date_utils import utcnow

logger = get_logger("services.agents")


class AgentManagementService(BaseService):
    """Runs agents and keeps their history."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        coordinator: AgentCoordinator,
        memory: BusinessMemory,
        audit_service: AuditService,
        registry: Any,
        orchestrator: Any,
        services: Any,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._coordinator = coordinator
        self._memory = memory
        self._audit = audit_service
        self._registry = registry
        self._orchestrator = orchestrator
        self._services = services

    # -- registration ------------------------------------------------------
    def sync_agents(self) -> int:
        """Mirror the coordinator's agents into the ``agents`` table."""
        with self.unit_of_work() as db:
            existing = {row.agent_code: row for row in db.scalars(select(Agent)).all()}
            created = 0
            for agent in self._coordinator.list_agents():
                info = agent.get_agent_info()
                row = existing.get(info.agent_code)
                if row is None:
                    db.add(
                        Agent(
                            agent_code=info.agent_code,
                            agent_name=info.agent_name,
                            description=info.description[:255],
                            is_enabled=True,
                        )
                    )
                    created += 1
                else:
                    row.agent_name = info.agent_name
                    row.description = info.description[:255]
            return created

    # -- execution ---------------------------------------------------------
    def run_agent(
        self,
        agent_code: str,
        *,
        period: str | None = None,
        task_type: str | None = None,
        parameters: dict[str, Any] | None = None,
        user_id: int | None = None,
        workflow_id: str | None = None,
    ) -> AgentResult:
        """Execute one agent and persist everything it produced."""
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "agents.execute")
            agent_row = self._agent_row(db, agent_code)
            if agent_row is None:
                raise NotFoundError(f"Agent '{agent_code}' is not registered")
            if not agent_row.is_enabled:
                raise ValidationError(f"Agent '{agent_code}' is disabled")
            agent_row_id = agent_row.id
            actor_id = user_id or user.id

        agent = self._coordinator.get(agent_code)
        task = AgentTask(
            task_id=f"task-{uuid.uuid4().hex[:10]}",
            agent_id=agent_code,
            task_type=task_type or getattr(agent, "default_task_type", "") or "ANALYSIS",
            period=period,
            parameters=dict(parameters or {}),
            requested_by=actor_id,
            workflow_id=workflow_id,
        )

        execution_id = self._start_execution(
            agent_row_id=agent_row_id, task=task, actor_id=actor_id, workflow_id=workflow_id
        )

        # Phase 9: the runner enforces this agent's own security policy.
        runner = self._make_runner(actor_id, workflow_id, agent_code)
        try:
            result = agent.execute(task, runner=runner)
        except Exception as exc:  # noqa: BLE001 - agents must never crash the app
            logger.exception("Agent %s crashed", agent_code)
            result = AgentResult(
                agent_id=agent_code,
                task_id=task.task_id,
                status=AgentExecutionStatus.FAILED,
                summary=f"{agent.get_agent_info().agent_name} failed to complete the analysis.",
                error=str(exc),
                confidence=0.05,
                confidence_basis="agent crashed before producing evidence",
            )

        self._finish_execution(execution_id, result, actor_id=actor_id)
        return result

    def require_permission(self, permission: str, user_id: int | None = None) -> int:
        """Authorise the acting user (and refuse acting on behalf of someone else)."""
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, permission)
            if user_id is not None and user_id != user.id:
                raise AuthorizationError(
                    "A collaboration can only be run by the signed-in user"
                )
            return user.id

    def current_user_id(self) -> int | None:
        principal = self._auth_context.principal
        return principal.user_id if principal else None

    def attach_agent_security(self, policy_service: Any) -> None:
        """Enable Phase 9 per-agent tool enforcement."""
        self._agent_security = policy_service

    def make_tool_runner(self, user_id: int) -> ToolRunner:
        """Public permission-checked tool runner (used by collaborations)."""
        return self._make_runner(user_id, None)

    def _make_runner(
        self, user_id: int, workflow_id: str | None, agent_code: str | None = None
    ) -> ToolRunner:
        checker = self._orchestrator.permission_checker(user_id)
        context = ToolContext(
            services=self._services,
            user_id=user_id,
            workflow_id=workflow_id,
        )

        def run(tool_name: str, arguments: dict[str, Any]):
            self._enforce_agent_policy(agent_code, tool_name)
            return self._registry.execute(
                ToolInvocation(tool_name=tool_name, arguments=arguments or {}),
                context,
                permission_checker=checker,
            )

        return run

    def _enforce_agent_policy(self, agent_code: str | None, tool_name: str) -> None:
        """Phase 9: an agent may only use tools its security policy allows."""
        policy_service = getattr(self, "_agent_security", None)
        if policy_service is None or not agent_code:
            return
        decision = policy_service.check_tool(agent_code, tool_name)
        if not decision.allowed:
            from app.core.exceptions import AuthorizationError

            raise AuthorizationError(decision.reason)

    # -- persistence -------------------------------------------------------
    def _agent_row(self, db: Session, agent_code: str) -> Agent | None:
        return db.scalars(select(Agent).where(Agent.agent_code == agent_code)).first()

    def _start_execution(
        self, *, agent_row_id: int, task: AgentTask, actor_id: int, workflow_id: str | None
    ) -> int:
        with self.unit_of_work() as db:
            row = AgentExecution(
                agent_id=agent_row_id,
                workflow_id=workflow_id,
                task_type=task.task_type,
                task_id=task.task_id,
                input_data={
                    "period": task.period,
                    "parameters": task.parameters,
                },
                status=AgentExecutionStatus.RUNNING,
                started_at=utcnow(),
                triggered_by=actor_id,
            )
            db.add(row)
            db.flush()
            return row.id

    def _finish_execution(self, execution_id: int, result: AgentResult, *, actor_id: int) -> None:
        with self.unit_of_work() as db:
            row = db.get(AgentExecution, execution_id)
            if row is None:  # pragma: no cover - defensive
                return
            row.status = result.status
            row.summary = result.summary
            row.confidence = result.confidence
            row.completed_at = result.completed_at or utcnow()
            row.execution_time = round(result.execution_ms, 2)
            row.error_message = result.error
            row.output_data = result.model_dump(mode="json")

            for finding in result.findings:
                db.add(
                    AgentFinding(
                        execution_id=row.id,
                        finding_type=finding.finding_type,
                        description=finding.description,
                        severity=finding.severity,
                        evidence_data={
                            "evidence": [item.model_dump(mode="json") for item in finding.evidence],
                            "metric_value": finding.metric_value,
                        },
                        reporting_period=finding.reporting_period,
                        metric_value=finding.metric_value,
                    )
                )
            for recommendation in result.recommendations:
                db.add(
                    AgentRecommendation(
                        execution_id=row.id,
                        recommendation=recommendation.recommendation,
                        reason=recommendation.reason,
                        priority=recommendation.priority,
                        status=RecommendationStatus.OPEN,
                        supporting_data=recommendation.supporting_figures,
                    )
                )

            self._audit.record(
                db,
                actor_id=actor_id,
                action=AuditAction.AGENT_EXECUTED
                if result.succeeded
                else AuditAction.AGENT_FAILED,
                module=MODULE_AGENTS,
                entity_type="AgentExecution",
                entity_id=row.id,
                new_values={
                    "agent_id": result.agent_id,
                    "task_type": row.task_type,
                    "status": result.status,
                    "findings": len(result.findings),
                    "recommendations": len(result.recommendations),
                    "confidence": result.confidence,
                    "workflow_id": row.workflow_id,
                },
            )

        agent_code = result.agent_id
        self._memory.record_execution_snapshot(
            agent_code=agent_code,
            execution_id=execution_id,
            metrics=result.metrics,
            summary=result.summary,
        )
        self._memory.record_recommendations(
            agent_code=agent_code,
            execution_id=execution_id,
            recommendations=[
                {
                    "recommendation": rec.recommendation,
                    "priority": rec.priority,
                    "reason": rec.reason,
                }
                for rec in result.recommendations
            ],
        )

    # -- read models -------------------------------------------------------
    def list_agents(self) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
            rows = {row.agent_code: row for row in db.scalars(select(Agent)).all()}
            agents: list[dict[str, Any]] = []
            for agent in self._coordinator.list_agents():
                info = agent.get_agent_info()
                row = rows.get(info.agent_code)
                stats = self._stats(db, row.id if row else None)
                agents.append(
                    {
                        "info": info.model_dump(),
                        "agent_row_id": row.id if row else None,
                        "is_enabled": row.is_enabled if row else True,
                        **stats,
                    }
                )
            return agents

    def _stats(self, db: Session, agent_row_id: int | None) -> dict[str, Any]:
        if agent_row_id is None:
            return {
                "executions": 0,
                "completed": 0,
                "failed": 0,
                "last_execution_at": None,
                "last_status": None,
                "open_recommendations": 0,
                "avg_execution_ms": 0.0,
                "status": "idle",
            }
        executions = db.scalars(
            select(AgentExecution).where(AgentExecution.agent_id == agent_row_id)
        ).all()
        completed = sum(1 for row in executions if row.status == AgentExecutionStatus.COMPLETED)
        failed = sum(1 for row in executions if row.status == AgentExecutionStatus.FAILED)
        latest = max(executions, key=lambda row: row.id) if executions else None
        open_recommendations = db.scalar(
            select(func.count(AgentRecommendation.id))
            .join(AgentExecution, AgentRecommendation.execution_id == AgentExecution.id)
            .where(
                AgentExecution.agent_id == agent_row_id,
                AgentRecommendation.status == RecommendationStatus.OPEN,
            )
        ) or 0
        durations = [row.execution_time for row in executions if row.execution_time]
        return {
            "executions": len(executions),
            "completed": completed,
            "failed": failed,
            "last_execution_at": latest.completed_at if latest else None,
            "last_status": latest.status if latest else None,
            "open_recommendations": int(open_recommendations),
            "avg_execution_ms": round(sum(durations) / len(durations), 1) if durations else 0.0,
            "status": "running"
            if any(row.status == AgentExecutionStatus.RUNNING for row in executions)
            else ("idle" if executions else "never run"),
        }

    def agent_detail(self, agent_code: str) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
            row = self._agent_row(db, agent_code)
            if row is None:
                raise NotFoundError(f"Agent '{agent_code}' is not registered")
            agent = self._coordinator.get(agent_code)
            stats = self._stats(db, row.id)
            executions = db.scalars(
                select(AgentExecution)
                .where(AgentExecution.agent_id == row.id)
                .order_by(AgentExecution.id.desc())
                .limit(10)
            ).all()
            findings = db.scalars(
                select(AgentFinding)
                .join(AgentExecution, AgentFinding.execution_id == AgentExecution.id)
                .where(AgentExecution.agent_id == row.id)
                .order_by(AgentFinding.id.desc())
                .limit(20)
            ).all()
            recommendations = db.scalars(
                select(AgentRecommendation)
                .join(AgentExecution, AgentRecommendation.execution_id == AgentExecution.id)
                .where(AgentExecution.agent_id == row.id)
                .order_by(AgentRecommendation.id.desc())
                .limit(20)
            ).all()
            return {
                "info": agent.get_agent_info().model_dump(),
                "stats": stats,
                "executions": [
                    {
                        "id": execution.id,
                        "task_type": execution.task_type,
                        "status": execution.status,
                        "confidence": execution.confidence,
                        "execution_time": execution.execution_time,
                        "started_at": execution.started_at,
                        "completed_at": execution.completed_at,
                        "summary": execution.summary,
                        "error": execution.error_message,
                        "workflow_id": execution.workflow_id,
                    }
                    for execution in executions
                ],
                "findings": [
                    {
                        "id": finding.id,
                        "finding_type": finding.finding_type,
                        "description": finding.description,
                        "severity": finding.severity,
                        "reporting_period": finding.reporting_period,
                        "evidence": (finding.evidence_data or {}).get("evidence", []),
                        "created_at": finding.created_at,
                    }
                    for finding in findings
                ],
                "recommendations": [
                    {
                        "id": recommendation.id,
                        "recommendation": recommendation.recommendation,
                        "reason": recommendation.reason,
                        "priority": recommendation.priority,
                        "status": recommendation.status,
                        "supporting_data": recommendation.supporting_data,
                        "created_at": recommendation.created_at,
                    }
                    for recommendation in recommendations
                ],
            }

    def recommendations(self, *, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
            stmt = (
                select(AgentRecommendation, Agent, AgentExecution)
                .join(AgentExecution, AgentRecommendation.execution_id == AgentExecution.id)
                .join(Agent, AgentExecution.agent_id == Agent.id)
                .order_by(AgentRecommendation.id.desc())
                .limit(limit)
            )
            if status:
                stmt = stmt.where(AgentRecommendation.status == status)
            rows = db.execute(stmt).all()
            return [
                {
                    "id": recommendation.id,
                    "agent": agent.agent_name,
                    "recommendation": recommendation.recommendation,
                    "reason": recommendation.reason,
                    "priority": recommendation.priority,
                    "status": recommendation.status,
                    "created_at": recommendation.created_at,
                    "execution_id": execution.id,
                }
                for recommendation, agent, execution in rows
            ]

    def update_recommendation(self, recommendation_id: int, status: str) -> dict[str, Any]:
        if status not in RecommendationStatus.ALL:
            raise ValidationError(f"'{status}' is not a valid recommendation status")
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.execute")
            row = db.get(AgentRecommendation, recommendation_id)
            if row is None:
                raise NotFoundError(f"Recommendation {recommendation_id} was not found")
            previous = row.status
            row.status = status
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.AGENT_RECOMMENDATION_UPDATED,
                module=MODULE_AGENTS,
                entity_type="AgentRecommendation",
                entity_id=row.id,
                old_values={"status": previous},
                new_values={"status": status},
            )
            return {
                "id": row.id,
                "status": row.status,
                "recommendation": row.recommendation,
            }

    def memory(self, agent_code: str, limit: int = 10) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "agents.view")
        return self._memory.recent(agent_code=agent_code, limit=limit)

    def note(self, agent_code: str, content: str) -> int | None:
        """Record an operator note in agent memory (auditable)."""
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.execute")
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.AGENT_EXECUTED,
                module=MODULE_AGENTS,
                entity_type="AgentMemory",
                entity_id=agent_code,
                new_values={"note": content[:200]},
            )
        return self._memory.remember(
            agent_code=agent_code,
            memory_type=AgentMemoryType.NOTE,
            content={"note": content},
        )
