"""Multi-agent collaboration manager.

Runs a scenario's task graph: independent tasks in parallel, dependent tasks in
order, every exchange as a persisted message, every finding validated, conflicts
resolved deterministically and one unified decision produced. All state is in
SQLite so a restart can recover cleanly.
"""

from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.collaboration.conflict_resolution import ConflictDetector, ConflictResolver
from app.ai.collaboration.decision_engine import BusinessDecisionEngine
from app.ai.collaboration.dependency_manager import DependencyGraph
from app.ai.collaboration.evidence_validator import EvidenceValidator
from app.ai.collaboration.message_bus import MessageBus
from app.ai.collaboration.planner import (
    SCENARIOS,
    CollaborationPlanner,
    ScenarioSpec,
    SharedContextBuilder,
)
from app.ai.schemas.collaboration_schema import (
    AgentCollaborationResult,
    CollaborationDetail,
    CollaborationTaskSpec,
    CollaborationTaskView,
    CollaborationView,
    ConflictRecord,
    SharedBusinessContext,
    UnifiedDecision,
    ValidationOutcome,
)
from app.ai.schemas.message_schema import AgentMessage
from app.core.constants import (
    MODULE_AGENTS,
    AgentExecutionStatus,
    AuditAction,
    CollaborationMessageType,
    CollaborationStatus,
    CollaborationStrategy,
    CollaborationTaskStatus,
    ConflictStatus,
    EvidenceStatus,
    FindingSeverity,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.collaboration import (
    AgentCollaboration,
    CollaborationCheckpoint,
    CollaborationConflict,
    CollaborationDecision,
    CollaborationDependency,
    CollaborationFinding,
    CollaborationMessage,
    CollaborationTask,
)
from app.utils.date_utils import utcnow

logger = get_logger("ai.collaboration.manager")

MANAGER_AGENT = "collaboration_manager"


class CollaborationError(ValidationError):
    default_user_message = "The collaboration could not be completed."


@dataclass
class _TaskOutcome:
    task_key: str
    ok: bool
    result: AgentCollaborationResult | None = None
    error: str | None = None


class MultiAgentCollaborationManager:
    """Creates, executes and reports multi-agent collaborations."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        agent_manager: Any,
        planner: CollaborationPlanner | None = None,
        decision_engine: BusinessDecisionEngine | None = None,
        conflict_detector: ConflictDetector | None = None,
        conflict_resolver: ConflictResolver | None = None,
        tool_runner_factory: Callable[[int], Callable[[str, dict], Any]] | None = None,
        known_sources: set[str] | None = None,
        audit_service: Any = None,
        max_parallel: int = 4,
        task_timeout: float = 180.0,
        max_tasks: int = 12,
    ) -> None:
        self._session_factory = session_factory
        self._agents = agent_manager
        self._planner = planner or CollaborationPlanner(max_tasks=max_tasks)
        self._decision_engine = decision_engine or BusinessDecisionEngine()
        self._conflict_detector = conflict_detector or ConflictDetector()
        self._conflict_resolver = conflict_resolver or ConflictResolver()
        self._tool_runner_factory = tool_runner_factory
        self._known_sources = known_sources or set()
        self._audit = audit_service
        self._max_parallel = max_parallel
        self._task_timeout = task_timeout
        self._max_tasks = max_tasks
        self._cancelled: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # creation and planning
    # ------------------------------------------------------------------
    def create_collaboration(
        self,
        objective: str,
        *,
        scenario: str | None = None,
        period: str | None = None,
        user_id: int | None = None,
        business_id: int | None = None,
    ) -> CollaborationView:
        self._require("agents.execute", user_id)
        objective = (objective or "").strip()
        if len(objective) < 5:
            raise CollaborationError("A collaboration needs a business objective")

        if scenario:
            try:
                spec = self._planner.scenario(scenario)
            except ValueError as exc:
                raise CollaborationError(str(exc)) from exc
        else:
            spec = self._planner.detect_scenario(objective)
        if spec is None:
            raise CollaborationError(
                "No collaboration scenario matches that objective. Available: "
                + ", ".join(sorted(SCENARIOS))
            )
        tasks = self._planner.generate_plan(spec.key)

        with self._session_factory() as db:
            row = AgentCollaboration(
                collaboration_id=f"collab-{uuid.uuid4().hex[:12]}",
                business_id=business_id,
                user_id=user_id,
                objective=objective,
                scenario=spec.key,
                strategy=spec.strategy,
                status=CollaborationStatus.PENDING,
                reporting_period=period or spec.default_period,
                phase="PLANNED",
            )
            db.add(row)
            db.flush()
            row_id = row.id
            collaboration_id = row.collaboration_id
            self._persist_tasks(db, row_id, collaboration_id, tasks)
            db.commit()

        self._audit_event(
            user_id,
            AuditAction.COLLABORATION_STARTED,
            collaboration_id,
            {"scenario": spec.key, "strategy": spec.strategy, "tasks": len(tasks)},
        )
        logger.info("Created collaboration %s (%s, %s)", collaboration_id, spec.key, spec.strategy)
        return self.get_collaboration_status(collaboration_id)

    def identify_required_agents(self, scenario: str) -> list[str]:
        return self._planner.identify_required_agents(scenario)

    def generate_collaboration_plan(
        self, scenario: str
    ) -> tuple[list[CollaborationTaskSpec], str]:
        spec = self._planner.scenario(scenario)
        return self._planner.generate_plan(spec.key), spec.strategy

    def _persist_tasks(
        self,
        db: Session,
        row_id: int,
        collaboration_id: str,
        tasks: list[CollaborationTaskSpec],
    ) -> None:
        for task in tasks:
            db.add(
                CollaborationTask(
                    collaboration_id=row_id,
                    task_key=task.task_key,
                    parent_task_key=task.parent_task_key,
                    assigned_agent=task.assigned_agent,
                    task_type=task.task_type,
                    objective=task.objective,
                    input_context=dict(task.task_params),
                    priority=task.priority,
                    status=CollaborationTaskStatus.PENDING,
                    idempotency_key=f"{collaboration_id}:{task.task_key}",
                )
            )
            for dependency in task.depends_on:
                db.add(
                    CollaborationDependency(
                        collaboration_id=row_id,
                        task_key=task.task_key,
                        depends_on_key=dependency,
                    )
                )
        db.flush()

    # ------------------------------------------------------------------
    # execution
    # ------------------------------------------------------------------
    def execute_collaboration(self, collaboration_id: str) -> CollaborationDetail:
        self._require("agents.execute")
        row = self._load_row(collaboration_id)
        if row.status in CollaborationStatus.TERMINAL:
            return self.get_collaboration_detail(collaboration_id)

        self._update_collaboration(
            row.id, status=CollaborationStatus.RUNNING, phase="CONTEXT",
            started_at=row.started_at or utcnow(),
        )

        tasks = self._task_specs(row.id)
        graph = DependencyGraph(tasks)
        errors = graph.validate()
        if errors:
            self._fail(row.id, "; ".join(errors))
            return self.get_collaboration_detail(collaboration_id)

        runner = self._runner_for(row.user_id)
        try:
            context = SharedContextBuilder(
                runner=runner, period_label=row.reporting_period
            ).build(
                objective=row.objective,
                business_id=row.business_id,
                user_id=row.user_id,
                period=row.reporting_period,
            )
        except Exception as exc:  # noqa: BLE001 - context failure must not crash the UI
            logger.exception("Shared context failed for %s", collaboration_id)
            self._fail(row.id, f"Shared business context could not be built: {exc}")
            return self.get_collaboration_detail(collaboration_id)

        self._save_context(row.id, context)
        bus = MessageBus(
            collaboration_id=collaboration_id,
            participants=set(spec_agents(tasks)) | {MANAGER_AGENT},
            on_message=self._message_persister(row.id),
        )
        bus.send(
            sender=MANAGER_AGENT,
            receiver="business_intelligence_agent"
            if "business_intelligence_agent" in bus.participants
            else spec_agents(tasks)[0],
            message_type=CollaborationMessageType.CONTEXT_RESPONSE,
            payload={"context_summary": _context_summary(context)},
        )

        completed: set[str] = set()
        failed: set[str] = set()
        skipped: set[str] = set()
        results: list[AgentCollaborationResult] = []

        for wave in graph.waves():
            if self._is_cancelled(collaboration_id):
                self._cancel(row.id)
                return self.get_collaboration_detail(collaboration_id)

            runnable = [
                key
                for key in wave
                if key not in completed and key not in failed and key not in skipped
            ]
            if not runnable:
                continue
            self._update_collaboration(row.id, phase=f"EXECUTING:{','.join(runnable)}")
            outcomes = self._run_wave(row, runnable, runner, bus, context)

            for outcome in outcomes:
                if outcome.ok and outcome.result is not None:
                    completed.add(outcome.task_key)
                    results.append(outcome.result)
                else:
                    failed.add(outcome.task_key)
                    blocked = graph.propagate_failure(outcome.task_key)
                    for key in blocked:
                        if key in completed or key in failed or key in skipped:
                            continue
                        skipped.add(key)
                        self._skip_task(row.id, key, f"Dependency '{outcome.task_key}' failed")
                        try:
                            bus.send(
                                sender=MANAGER_AGENT,
                                receiver=self._agent_of(key, tasks),
                                message_type=CollaborationMessageType.TASK_FAILED,
                                task_id=key,
                                payload={"reason": f"dependency '{outcome.task_key}' failed"},
                            )
                        except Exception:  # pragma: no cover - bus limits
                            logger.debug("could not announce skipped task %s", key)
            self._checkpoint(
                row.id,
                f"WAVE:{len(completed)}/{len(tasks)}",
                {
                    "completed": sorted(completed),
                    "failed": sorted(failed),
                    "skipped": sorted(skipped),
                },
            )
            if self._is_cancelled(collaboration_id):
                self._cancel(row.id)
                return self.get_collaboration_detail(collaboration_id)

        if not results:
            self._fail(row.id, "No agent completed its task; the collaboration produced no findings.")
            return self.get_collaboration_detail(collaboration_id)

        # ---- validation -------------------------------------------------
        self._update_collaboration(row.id, phase="VALIDATION")
        validations = self.validate_agent_results(results)
        self._persist_validations(row.id, results, validations)

        # ---- conflicts --------------------------------------------------
        self._update_collaboration(row.id, phase="CONFLICTS")
        conflicts = self.detect_conflicts(results, context)
        if conflicts:
            conflicts = self.resolve_conflicts(conflicts, context, results)
            self._persist_conflicts(row.id, conflicts)
            for conflict in conflicts:
                receiver = conflict.agents[0] if conflict.agents else "business_intelligence_agent"
                if receiver in bus.participants:
                    try:
                        bus.notify_conflict(
                            sender=MANAGER_AGENT,
                            receiver=receiver,
                            conflict={
                                "type": conflict.conflict_type,
                                "status": conflict.status,
                                "description": conflict.description,
                            },
                        )
                    except Exception:  # pragma: no cover
                        logger.debug("conflict notification skipped")
        self._checkpoint(
            row.id,
            "CONFLICTS",
            {"conflicts": [c.model_dump(mode="json") for c in conflicts]},
        )

        # ---- decision ---------------------------------------------------
        self._update_collaboration(row.id, phase="DECISION")
        decision = self.synthesize_business_decision(
            collaboration_id=collaboration_id,
            objective=row.objective,
            results=results,
            context=context,
            conflicts=conflicts,
            validations=validations,
            failed_tasks=sorted(failed | skipped),
        )
        self._persist_decision(row.id, decision)

        final_status = (
            CollaborationStatus.COMPLETED
            if decision.status == "FINAL"
            else CollaborationStatus.PARTIAL
        )
        self._update_collaboration(
            row.id,
            status=final_status,
            phase="COMPLETED" if final_status == CollaborationStatus.COMPLETED else "PARTIAL",
            completed_at=utcnow(),
        )
        self._audit_event(
            row.user_id,
            AuditAction.COLLABORATION_COMPLETED,
            collaboration_id,
            {
                "status": final_status,
                "decision_status": decision.status,
                "findings": len(decision.consolidated_findings),
                "conflicts": len(conflicts),
                "confidence": decision.confidence,
            },
        )
        self._audit_event(
            row.user_id,
            AuditAction.COLLABORATION_DECISION_GENERATED,
            collaboration_id,
            {"summary": decision.executive_summary[:300]},
        )
        return self.get_collaboration_detail(collaboration_id)

    # -- waves -------------------------------------------------------------
    def _run_wave(
        self,
        row: AgentCollaboration,
        keys: list[str],
        runner: Callable[[str, dict], Any],
        bus: MessageBus,
        context: SharedBusinessContext,
    ) -> list[_TaskOutcome]:
        if len(keys) == 1:
            return [self._run_task(row, keys[0], runner, bus, context)]

        outcomes: list[_TaskOutcome] = []
        with ThreadPoolExecutor(max_workers=min(self._max_parallel, len(keys))) as pool:
            futures = {
                pool.submit(self._run_task, row, key, runner, bus, context): key for key in keys
            }
            for future, key in futures.items():
                try:
                    outcomes.append(future.result(timeout=self._task_timeout))
                except FutureTimeoutError:
                    self._mark_task(row.id, key, CollaborationTaskStatus.FAILED,
                                    error=f"timed out after {self._task_timeout:.0f}s")
                    outcomes.append(_TaskOutcome(key, False, error="timed out"))
                except Exception as exc:  # noqa: BLE001 - isolate task failures
                    logger.exception("Task %s crashed", key)
                    self._mark_task(row.id, key, CollaborationTaskStatus.FAILED, error=str(exc))
                    outcomes.append(_TaskOutcome(key, False, error=str(exc)))
        return outcomes

    def _run_task(
        self,
        row: AgentCollaboration,
        task_key: str,
        runner: Callable[[str, dict], Any],
        bus: MessageBus,
        context: SharedBusinessContext,
    ) -> _TaskOutcome:
        task = self._task_row(row.id, task_key)
        if task is None:
            return _TaskOutcome(task_key, False, error="task not found")
        if task.status == CollaborationTaskStatus.COMPLETED:
            # Idempotency: a completed task is never executed twice.
            return _TaskOutcome(task_key, True, result=self._result_from_row(task))
        if self._is_cancelled(row.collaboration_id):
            return _TaskOutcome(task_key, False, error="cancelled")

        self._mark_task(row.id, task_key, CollaborationTaskStatus.RUNNING, increment_attempts=True)
        try:
            bus.send(
                sender=MANAGER_AGENT,
                receiver=task.assigned_agent,
                message_type=CollaborationMessageType.TASK_REQUEST,
                task_id=task_key,
                payload={
                    "objective": task.objective,
                    "task_type": task.task_type,
                    "period": row.reporting_period,
                    "context": {
                        "available_budget": str(context.available_budget),
                        "constraints": context.constraints,
                    },
                },
            )
        except Exception:  # pragma: no cover - bus limits
            logger.debug("task request message skipped for %s", task_key)

        try:
            agent_result = self._agents.run_agent(
                task.assigned_agent,
                period=row.reporting_period,
                task_type=task.task_type,
                parameters={"objective": task.objective, "collaboration_id": row.collaboration_id},
                user_id=row.user_id,
                workflow_id=f"collab:{row.collaboration_id}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Agent %s failed in collaboration", task.assigned_agent)
            self._mark_task(row.id, task_key, CollaborationTaskStatus.FAILED, error=str(exc))
            try:
                bus.send(
                    sender=task.assigned_agent,
                    receiver=MANAGER_AGENT,
                    message_type=CollaborationMessageType.TASK_FAILED,
                    task_id=task_key,
                    payload={"error": str(exc)[:300]},
                )
            except Exception:  # pragma: no cover
                pass
            return _TaskOutcome(task_key, False, error=str(exc))

        result = AgentCollaborationResult.from_agent_result(
            collaboration_id=row.collaboration_id,
            task_key=task_key,
            result=agent_result,
        )
        ok = agent_result.status == AgentExecutionStatus.COMPLETED
        self._mark_task(
            row.id,
            task_key,
            CollaborationTaskStatus.COMPLETED if ok else CollaborationTaskStatus.FAILED,
            result=result.model_dump(mode="json"),
            error=agent_result.error,
            execution_ms=agent_result.execution_ms,
        )
        self._persist_result_findings(row.id, task_key, result)
        try:
            bus.send(
                sender=task.assigned_agent,
                receiver=MANAGER_AGENT,
                message_type=CollaborationMessageType.TASK_COMPLETED
                if ok
                else CollaborationMessageType.TASK_FAILED,
                task_id=task_key,
                payload={
                    "summary": result.summary[:400],
                    "findings": len(result.findings),
                    "confidence": result.confidence,
                },
            )
            for finding in result.findings[:3]:
                bus.report_finding(
                    sender=task.assigned_agent,
                    receiver=MANAGER_AGENT,
                    task_id=task_key,
                    finding=finding.model_dump(mode="json"),
                )
        except Exception:  # pragma: no cover - bus limits
            logger.debug("completion message skipped for %s", task_key)

        return _TaskOutcome(task_key, ok, result=result if ok else None,
                            error=None if ok else agent_result.error)

    # ------------------------------------------------------------------
    # collection, validation, conflicts, synthesis
    # ------------------------------------------------------------------
    def collect_agent_results(self, collaboration_id: str) -> list[AgentCollaborationResult]:
        row = self._load_row(collaboration_id)
        with self._session_factory() as db:
            tasks = db.scalars(
                select(CollaborationTask).where(CollaborationTask.collaboration_id == row.id)
            ).all()
            results: list[AgentCollaborationResult] = []
            for task in tasks:
                if task.status == CollaborationTaskStatus.COMPLETED and task.result:
                    results.append(AgentCollaborationResult.model_validate(task.result))
            return results

    def validate_agent_results(
        self, results: list[AgentCollaborationResult]
    ) -> dict[str, list[ValidationOutcome]]:
        validator = EvidenceValidator(known_sources=self._known_sources)
        return {result.task_key: validator.validate_result(result)[0] for result in results}

    def detect_conflicts(
        self, results: list[AgentCollaborationResult], context: SharedBusinessContext
    ) -> list[ConflictRecord]:
        return self._conflict_detector.detect(results=results, context=context)

    def resolve_conflicts(
        self,
        conflicts: list[ConflictRecord],
        context: SharedBusinessContext,
        results: list[AgentCollaborationResult],
    ) -> list[ConflictRecord]:
        return [
            self._conflict_resolver.resolve(conflict=conflict, context=context, results=results)
            for conflict in conflicts
        ]

    def synthesize_business_decision(
        self,
        *,
        collaboration_id: str,
        objective: str,
        results: list[AgentCollaborationResult],
        context: SharedBusinessContext,
        conflicts: list[ConflictRecord],
        validations: dict[str, list[ValidationOutcome]],
        failed_tasks: list[str] | None = None,
    ) -> UnifiedDecision:
        return self._decision_engine.build(
            collaboration_id=collaboration_id,
            objective=objective,
            results=results,
            context=context,
            conflicts=conflicts,
            validations=validations,
            failed_tasks=failed_tasks or [],
        )

    # ------------------------------------------------------------------
    # status, cancellation, recovery
    # ------------------------------------------------------------------
    def get_collaboration_status(self, collaboration_id: str) -> CollaborationView:
        self._require("agents.view")
        row = self._load_row(collaboration_id)
        with self._session_factory() as db:
            return self._build_view(db, row)

    def list_collaborations(self, limit: int = 25) -> list[CollaborationView]:
        self._require("agents.view")
        with self._session_factory() as db:
            rows = db.scalars(
                select(AgentCollaboration)
                .order_by(AgentCollaboration.id.desc())
                .limit(limit)
            ).all()
            return [self._build_view(db, row) for row in rows]

    def dashboard_stats(self) -> dict[str, int]:
        self._require("agents.view")
        with self._session_factory() as db:
            rows = db.scalars(select(AgentCollaboration)).all()
            conflicts = db.scalars(
                select(CollaborationConflict).where(
                    CollaborationConflict.status == ConflictStatus.UNRESOLVED
                )
            ).all()
        return {
            "total": len(rows),
            "active": sum(
                1 for row in rows if row.status in (CollaborationStatus.RUNNING, CollaborationStatus.PENDING)
            ),
            "completed": sum(1 for row in rows if row.status == CollaborationStatus.COMPLETED),
            "partial": sum(1 for row in rows if row.status == CollaborationStatus.PARTIAL),
            "failed": sum(1 for row in rows if row.status == CollaborationStatus.FAILED),
            "cancelled": sum(1 for row in rows if row.status == CollaborationStatus.CANCELLED),
            "unresolved_conflicts": len(conflicts),
        }

    def cancel_collaboration(self, collaboration_id: str) -> bool:
        self._require("agents.execute")
        row = self._load_row(collaboration_id)
        if row.status in CollaborationStatus.TERMINAL:
            return False
        with self._lock:
            self._cancelled.add(collaboration_id)
        self._cancel(row.id)
        self._audit_event(
            row.user_id, AuditAction.COLLABORATION_CANCELLED, collaboration_id,
            {"phase": row.phase},
        )
        return True

    def is_cancelled(self, collaboration_id: str) -> bool:
        return self._is_cancelled(collaboration_id)

    def recover_interrupted(self) -> int:
        """Mark collaborations left RUNNING by a crash as failed but recoverable."""
        recovered = 0
        with self._session_factory() as db:
            rows = db.scalars(
                select(AgentCollaboration).where(
                    AgentCollaboration.status.in_(
                        (CollaborationStatus.RUNNING, CollaborationStatus.PENDING)
                    )
                )
            ).all()
            for row in rows:
                row.status = CollaborationStatus.FAILED
                row.phase = "INTERRUPTED"
                row.error_message = (
                    "Interrupted by an application restart. Retry to resume: completed tasks "
                    "are kept and will not run again."
                )
                row.completed_at = utcnow()
                db.add(
                    CollaborationCheckpoint(
                        collaboration_id=row.id,
                        phase="RECOVERY",
                        state={"reason": "application restart", "previous_status": row.status},
                    )
                )
                recovered += 1
            db.commit()
        if recovered:
            logger.warning("Recovered %d interrupted collaboration(s)", recovered)
        return recovered

    # ------------------------------------------------------------------
    # detail views
    # ------------------------------------------------------------------
    def get_collaboration_detail(self, collaboration_id: str) -> CollaborationDetail:
        self._require("agents.view")
        row = self._load_row(collaboration_id)
        with self._session_factory() as db:
            view = self._build_view(db, row)
            tasks = db.scalars(
                select(CollaborationTask)
                .where(CollaborationTask.collaboration_id == row.id)
                .order_by(CollaborationTask.id)
            ).all()
            dependencies = db.scalars(
                select(CollaborationDependency).where(
                    CollaborationDependency.collaboration_id == row.id
                )
            ).all()
            messages = db.scalars(
                select(CollaborationMessage)
                .where(CollaborationMessage.collaboration_id == row.id)
                .order_by(CollaborationMessage.id)
            ).all()
            findings = db.scalars(
                select(CollaborationFinding)
                .where(CollaborationFinding.collaboration_id == row.id)
                .order_by(CollaborationFinding.id.desc())
            ).all()
            conflicts = db.scalars(
                select(CollaborationConflict)
                .where(CollaborationConflict.collaboration_id == row.id)
                .order_by(CollaborationConflict.id)
            ).all()
            checkpoints = db.scalars(
                select(CollaborationCheckpoint)
                .where(CollaborationCheckpoint.collaboration_id == row.id)
                .order_by(CollaborationCheckpoint.id)
            ).all()
            decision_row = db.scalars(
                select(CollaborationDecision).where(
                    CollaborationDecision.collaboration_id == row.id
                )
            ).first()

            task_views = [
                CollaborationTaskView(
                    collaboration_id=row.collaboration_id,
                    task_key=task.task_key,
                    parent_task_key=task.parent_task_key,
                    assigned_agent=task.assigned_agent,
                    task_type=task.task_type,
                    objective=task.objective,
                    input_context=task.input_context or {},
                    dependencies=sorted(
                        edge.depends_on_key
                        for edge in dependencies
                        if edge.task_key == task.task_key
                    ),
                    priority=task.priority,
                    status=task.status,
                    attempts=task.attempts,
                    execution_ms=task.execution_ms,
                    error=task.error_message,
                    started_at=task.started_at,
                    completed_at=task.completed_at,
                )
                for task in tasks
            ]

            decision = (
                UnifiedDecision.model_validate(decision_row.payload)
                if decision_row and decision_row.payload
                else None
            )

            return CollaborationDetail(
                collaboration=view,
                shared_context=row.shared_context or {},
                tasks=task_views,
                dependencies=[(edge.task_key, edge.depends_on_key) for edge in dependencies],
                messages=[
                    {
                        "message_id": message.message_id,
                        "sender": message.sender_agent,
                        "receiver": message.receiver_agent,
                        "type": message.message_type,
                        "task_key": message.task_key,
                        "payload": message.payload or {},
                        "created_at": message.created_at,
                    }
                    for message in messages
                ],
                findings=[
                    {
                        "task_key": finding.task_key,
                        "agent_id": finding.agent_id,
                        "finding_type": finding.finding_type,
                        "description": finding.description,
                        "severity": finding.severity,
                        "evidence": finding.evidence or [],
                        "reporting_period": finding.reporting_period,
                        "validation_status": finding.validation_status,
                        "validation_issues": finding.validation_issues or [],
                        "created_at": finding.created_at,
                    }
                    for finding in findings
                ],
                conflicts=[
                    {
                        "conflict_id": conflict.conflict_id,
                        "conflict_type": conflict.conflict_type,
                        "agents": conflict.agents or [],
                        "description": conflict.description,
                        "status": conflict.status,
                        "evidence": conflict.evidence or {},
                        "resolution": conflict.resolution or {},
                        "created_at": conflict.created_at,
                        "resolved_at": conflict.resolved_at,
                    }
                    for conflict in conflicts
                ],
                decision=decision,
                checkpoints=[
                    {
                        "phase": checkpoint.phase,
                        "state": checkpoint.state or {},
                        "created_at": checkpoint.created_at,
                    }
                    for checkpoint in checkpoints
                ],
            )

    def get_decision(self, collaboration_id: str) -> UnifiedDecision | None:
        return self.get_collaboration_detail(collaboration_id).decision

    # ------------------------------------------------------------------
    # persistence helpers
    # ------------------------------------------------------------------
    def _load_row(self, collaboration_id: str) -> AgentCollaboration:
        with self._session_factory() as db:
            row = db.scalars(
                select(AgentCollaboration).where(
                    AgentCollaboration.collaboration_id == collaboration_id
                )
            ).first()
            if row is None:
                raise NotFoundError(f"Collaboration '{collaboration_id}' was not found")
            db.expunge(row)
            return row

    def _task_row(self, row_id: int, task_key: str) -> CollaborationTask | None:
        with self._session_factory() as db:
            task = db.scalars(
                select(CollaborationTask).where(
                    CollaborationTask.collaboration_id == row_id,
                    CollaborationTask.task_key == task_key,
                )
            ).first()
            if task is not None:
                db.expunge(task)
            return task

    def _task_specs(self, row_id: int) -> list[CollaborationTaskSpec]:
        with self._session_factory() as db:
            tasks = db.scalars(
                select(CollaborationTask).where(CollaborationTask.collaboration_id == row_id)
            ).all()
            edges = db.scalars(
                select(CollaborationDependency).where(
                    CollaborationDependency.collaboration_id == row_id
                )
            ).all()
            by_task: dict[str, list[str]] = {}
            for edge in edges:
                by_task.setdefault(edge.task_key, []).append(edge.depends_on_key)
            return [
                CollaborationTaskSpec(
                    task_key=task.task_key,
                    assigned_agent=task.assigned_agent,
                    task_type=task.task_type,
                    objective=task.objective,
                    depends_on=sorted(by_task.get(task.task_key, [])),
                    priority=task.priority,
                    task_params=task.input_context or {},
                    parent_task_key=task.parent_task_key,
                )
                for task in tasks
            ]

    def _update_collaboration(self, row_id: int, **values) -> None:
        with self._session_factory() as db:
            row = db.get(AgentCollaboration, row_id)
            if row is None:
                return
            for key, value in values.items():
                setattr(row, key, value)
            db.commit()

    def _save_context(self, row_id: int, context: SharedBusinessContext) -> None:
        self._update_collaboration(row_id, shared_context=context.model_dump(mode="json"))
        self._checkpoint(row_id, "CONTEXT", {"available_budget": str(context.available_budget)})

    def _mark_task(
        self,
        row_id: int,
        task_key: str,
        status: str,
        *,
        result: dict | None = None,
        error: str | None = None,
        execution_ms: float | None = None,
        increment_attempts: bool = False,
    ) -> None:
        with self._session_factory() as db:
            task = db.scalars(
                select(CollaborationTask).where(
                    CollaborationTask.collaboration_id == row_id,
                    CollaborationTask.task_key == task_key,
                )
            ).first()
            if task is None:
                return
            task.status = status
            if increment_attempts:
                task.attempts += 1
                task.started_at = task.started_at or utcnow()
            if result is not None:
                task.result = result
            if error is not None:
                task.error_message = error
            if execution_ms is not None:
                task.execution_ms = execution_ms
            if status in CollaborationTaskStatus.TERMINAL:
                task.completed_at = utcnow()
            db.commit()

    def _skip_task(self, row_id: int, task_key: str, reason: str) -> None:
        self._mark_task(row_id, task_key, CollaborationTaskStatus.SKIPPED, error=reason)

    def _persist_result_findings(
        self, row_id: int, task_key: str, result: AgentCollaborationResult
    ) -> None:
        if not result.findings:
            return
        with self._session_factory() as db:
            for finding in result.findings:
                db.add(
                    CollaborationFinding(
                        collaboration_id=row_id,
                        task_key=task_key,
                        agent_id=result.agent_id,
                        finding_type=finding.finding_type,
                        description=finding.description,
                        severity=finding.severity,
                        evidence=[item.model_dump(mode="json") for item in finding.evidence],
                        reporting_period=finding.reporting_period,
                        source_execution_id=result.agent_execution_id,
                    )
                )
            db.commit()

    def _persist_validations(
        self,
        row_id: int,
        results: list[AgentCollaborationResult],
        validations: dict[str, list[ValidationOutcome]],
    ) -> None:
        with self._session_factory() as db:
            for result in results:
                for outcome in validations.get(result.task_key, []):
                    rows = db.scalars(
                        select(CollaborationFinding).where(
                            CollaborationFinding.collaboration_id == row_id,
                            CollaborationFinding.task_key == result.task_key,
                            CollaborationFinding.description == outcome.finding.description,
                        )
                    ).all()
                    for row in rows:
                        row.validation_status = outcome.status
                        row.validation_issues = outcome.issues
            db.commit()

    def _persist_conflicts(self, row_id: int, conflicts: list[ConflictRecord]) -> None:
        if not conflicts:
            return
        with self._session_factory() as db:
            for conflict in conflicts:
                db.add(
                    CollaborationConflict(
                        collaboration_id=row_id,
                        conflict_id=conflict.conflict_id,
                        conflict_type=conflict.conflict_type,
                        agents=conflict.agents,
                        description=conflict.description,
                        evidence=conflict.evidence,
                        status=conflict.status,
                        resolution=conflict.resolution,
                        resolved_at=utcnow()
                        if conflict.status != ConflictStatus.OPEN
                        else None,
                    )
                )
            db.commit()

    def _persist_decision(self, row_id: int, decision: UnifiedDecision) -> None:
        with self._session_factory() as db:
            existing = db.scalars(
                select(CollaborationDecision).where(
                    CollaborationDecision.collaboration_id == row_id
                )
            ).first()
            payload = decision.model_dump(mode="json")
            if existing is None:
                db.add(
                    CollaborationDecision(
                        collaboration_id=row_id,
                        executive_summary=decision.executive_summary,
                        status=decision.status,
                        payload=payload,
                        generated_at=decision.generated_at or utcnow(),
                    )
                )
            else:
                existing.executive_summary = decision.executive_summary
                existing.status = decision.status
                existing.payload = payload
                existing.generated_at = decision.generated_at or utcnow()
            db.commit()

    def _checkpoint(self, row_id: int, phase: str, state: dict) -> None:
        with self._session_factory() as db:
            db.add(CollaborationCheckpoint(collaboration_id=row_id, phase=phase, state=state))
            db.commit()

    def _message_persister(self, row_id: int):
        def persist(message: AgentMessage) -> None:
            with self._session_factory() as db:
                db.add(
                    CollaborationMessage(
                        collaboration_id=row_id,
                        message_id=message.message_id,
                        sender_agent=message.sender_agent,
                        receiver_agent=message.receiver_agent,
                        message_type=message.message_type,
                        task_key=message.task_id,
                        payload=message.payload,
                        evidence_refs=message.evidence_references,
                        status=message.status,
                        created_at=message.timestamp or utcnow(),
                    )
                )
                db.commit()

        return persist

    def _build_view(self, db: Session, row: AgentCollaboration) -> CollaborationView:
        tasks = db.scalars(
            select(CollaborationTask).where(CollaborationTask.collaboration_id == row.id)
        ).all()
        findings = db.scalars(
            select(CollaborationFinding).where(CollaborationFinding.collaboration_id == row.id)
        ).all()
        conflicts = db.scalars(
            select(CollaborationConflict).where(CollaborationConflict.collaboration_id == row.id)
        ).all()
        decision = db.scalars(
            select(CollaborationDecision).where(CollaborationDecision.collaboration_id == row.id)
        ).first()
        return CollaborationView(
            collaboration_id=row.collaboration_id,
            objective=row.objective,
            scenario=row.scenario,
            strategy=row.strategy,
            status=row.status,
            phase=row.phase,
            reporting_period=row.reporting_period,
            tasks_total=len(tasks),
            tasks_completed=sum(
                1 for task in tasks if task.status == CollaborationTaskStatus.COMPLETED
            ),
            tasks_failed=sum(
                1
                for task in tasks
                if task.status in (CollaborationTaskStatus.FAILED, CollaborationTaskStatus.SKIPPED)
            ),
            agents=sorted({task.assigned_agent for task in tasks}),
            conflicts=len(conflicts),
            unresolved_conflicts=sum(
                1 for conflict in conflicts if conflict.status == ConflictStatus.UNRESOLVED
            ),
            findings=len(findings),
            confidence=(decision.payload or {}).get("confidence") if decision else None,
            created_at=row.created_at,
            started_at=row.started_at,
            completed_at=row.completed_at,
            error=row.error_message,
        )

    # -- misc --------------------------------------------------------------
    def _require(self, permission: str, user_id: int | None = None) -> None:
        """Delegate the permission check to the agent manager (single source)."""
        self._agents.require_permission(permission, user_id)

    def _runner_for(self, user_id: int | None) -> Callable[[str, dict], Any]:
        if self._tool_runner_factory is not None and user_id is not None:
            return self._tool_runner_factory(user_id)
        raise CollaborationError("No tool runner is configured for collaborations")

    def _result_from_row(self, task: CollaborationTask) -> AgentCollaborationResult:
        return AgentCollaborationResult.model_validate(task.result or {})

    def _agent_of(self, task_key: str, tasks: list[CollaborationTaskSpec]) -> str:
        for task in tasks:
            if task.task_key == task_key:
                return task.assigned_agent
        return MANAGER_AGENT

    def _is_cancelled(self, collaboration_id: str) -> bool:
        with self._lock:
            return collaboration_id in self._cancelled

    def _cancel(self, row_id: int) -> None:
        self._update_collaboration(
            row_id, status=CollaborationStatus.CANCELLED, phase="CANCELLED",
            completed_at=utcnow(),
        )

    def _fail(self, row_id: int, message: str) -> None:
        self._update_collaboration(
            row_id,
            status=CollaborationStatus.FAILED,
            phase="FAILED",
            error_message=message[:500],
            completed_at=utcnow(),
        )

    def _audit_event(self, user_id: int | None, action: str, collaboration_id: str, values: dict) -> None:
        if self._audit is None or user_id is None:
            return
        try:
            self._audit.record_event(
                actor_id=user_id,
                action=action,
                module=MODULE_AGENTS,
                entity_type="AgentCollaboration",
                entity_id=collaboration_id,
                new_values=values,
            )
        except Exception:  # pragma: no cover - audit must not break execution
            logger.exception("Could not write collaboration audit entry")


def spec_agents(tasks: list[CollaborationTaskSpec]) -> list[str]:
    seen: list[str] = []
    for task in tasks:
        if task.assigned_agent not in seen:
            seen.append(task.assigned_agent)
    return seen


def _context_summary(context: SharedBusinessContext) -> dict[str, str]:
    return {
        "reporting_period": context.reporting_period or "all time",
        "available_budget": f"{context.available_budget:,.2f}",
        "revenue": context.financial_context.get("revenue", "not reported"),
        "sales_value": context.sales_context.get("sales_value", "not reported"),
        "low_stock_products": context.inventory_context.get("low_stock_products", "0"),
    }
