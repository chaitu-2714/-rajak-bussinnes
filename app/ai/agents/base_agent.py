"""Shared framework for the five specialist agents.

Each agent: validates a structured task, collects data through permission-checked
tools, runs deterministic analysis, validates its own output and returns the
common :class:`AgentResult` schema. Confidence is computed from evidence coverage,
never invented.
"""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable

from app.ai.schemas.agent_schema import (
    AgentInfo,
    AgentResult,
    AgentTask,
    ConfidenceCalculator,
    Evidence,
    Finding,
    Recommendation,
)
from app.ai.schemas.intent_schema import Intent
from app.ai.schemas.tool_schema import ToolResult
from app.core.constants import AgentExecutionStatus, FindingSeverity
from app.core.exceptions import ValidationError
from app.core.logging_config import get_logger
from app.utils.date_utils import utcnow

logger = get_logger("ai.agents")

#: ``runner(tool_name, arguments) -> ToolResult`` supplied by the orchestrator.
ToolRunner = Callable[[str, dict[str, Any]], ToolResult]

MAX_FINDINGS = 20
MAX_RECOMMENDATIONS = 10


class AgentError(ValidationError):
    default_user_message = "The agent could not complete this analysis."


class BaseBusinessAgent(ABC):
    """Common behaviour for every specialist agent."""

    agent_id: str = ""
    name: str = ""
    description: str = ""
    intents: tuple[Intent, ...] = ()
    task_types: tuple[str, ...] = ()
    default_task_type: str = ""
    data_tools: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()

    def __init__(self, *, confidence: ConfidenceCalculator | None = None) -> None:
        self._confidence = confidence or ConfidenceCalculator()

    # -- identity ----------------------------------------------------------
    def get_agent_info(self) -> AgentInfo:
        return AgentInfo(
            agent_code=self.agent_id,
            agent_name=self.name,
            description=self.description,
            intents=[intent.value for intent in self.intents],
            data_tools=list(self.data_tools),
            capabilities=list(self.capabilities),
            required_permissions=list(self.required_permissions),
            is_enabled=True,
        )

    def can_handle(self, intent: Intent | str) -> bool:
        value = intent.value if isinstance(intent, Intent) else str(intent)
        return value in {item.value for item in self.intents}

    # -- validation --------------------------------------------------------
    def validate_input(self, task: AgentTask) -> None:
        if task.agent_id != self.agent_id:
            raise AgentError(
                f"Task {task.task_id} is addressed to {task.agent_id}, not {self.agent_id}"
            )
        if self.task_types and task.task_type not in self.task_types:
            raise AgentError(
                f"{self.name} does not support task type '{task.task_type}' "
                f"(supported: {', '.join(self.task_types)})"
            )

    # -- contract ----------------------------------------------------------
    @abstractmethod
    def collect_context(
        self, task: AgentTask, runner: ToolRunner
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        """Return ``(context, tools_used, failed_tools)``."""

    @abstractmethod
    def analyse(
        self,
        task: AgentTask,
        context: dict[str, Any],
        failures: list[str],
    ) -> tuple[list[Finding], list[Recommendation], dict[str, Any], list[str]]:
        """Return ``(findings, recommendations, metrics, data_gaps)``."""

    # -- execution ---------------------------------------------------------
    def execute(self, task: AgentTask, *, runner: ToolRunner) -> AgentResult:
        started = utcnow()
        clock_start = time.perf_counter()
        self.validate_input(task)

        try:
            context, tools_used, failures = self.collect_context(task, runner)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Agent %s failed during context collection", self.agent_id)
            return AgentResult(
                agent_id=self.agent_id,
                task_id=task.task_id,
                status=AgentExecutionStatus.FAILED,
                summary=f"{self.name} could not collect the data it needs.",
                error=str(exc),
                started_at=started,
                completed_at=utcnow(),
                confidence=0.05,
                confidence_basis="no data collected",
            )

        findings, recommendations, metrics, data_gaps = self.analyse(task, context, failures)

        evidence_sources = {
            item.source for finding in findings for item in finding.evidence
        }
        confidence, basis = self._confidence.compute(
            evidence_sources=evidence_sources,
            tools_requested=len(tools_used) + len(failures),
            tools_failed=len(failures),
            data_gaps=len(data_gaps),
        )

        result = AgentResult(
            agent_id=self.agent_id,
            task_id=task.task_id,
            status=AgentExecutionStatus.COMPLETED,
            summary=self._summarise(findings, recommendations, data_gaps),
            findings=findings,
            recommendations=recommendations,
            evidence=[item for finding in findings for item in finding.evidence],
            metrics=metrics,
            # Analysis never mutates business data, so nothing needs approval.
            requires_approval=False,
            confidence=confidence,
            confidence_basis=basis,
            tools_used=tools_used,
            data_gaps=data_gaps,
            started_at=started,
            completed_at=utcnow(),
        )
        result.execution_ms = (time.perf_counter() - clock_start) * 1000
        return self.validate_output(result)

    def validate_output(self, result: AgentResult) -> AgentResult:
        """Enforce the shared output contract before anything is stored."""
        if result.agent_id != self.agent_id:
            raise AgentError("Agent result has the wrong agent id")
        if not 0.0 <= result.confidence <= 1.0:
            raise AgentError("Confidence must be between 0 and 1")

        findings = result.findings[:MAX_FINDINGS]
        for finding in findings:
            if not finding.evidence:
                raise AgentError(f"Finding {finding.finding_id} has no evidence")
            if finding.severity not in FindingSeverity.ALL:
                raise AgentError(f"Finding {finding.finding_id} has an invalid severity")
            finding.agent_id = self.agent_id

        recommendations = result.recommendations[:MAX_RECOMMENDATIONS]
        for recommendation in recommendations:
            if len(recommendation.reason.strip()) < 5:
                raise AgentError(
                    f"Recommendation {recommendation.recommendation_id} has no reason"
                )
            recommendation.agent_id = self.agent_id

        result.findings = findings
        result.recommendations = recommendations
        if not result.summary:
            result.summary = f"{self.name} completed the analysis."
        return result

    # -- helpers -----------------------------------------------------------
    def _call(
        self,
        runner: ToolRunner,
        tool: str,
        arguments: dict[str, Any],
        *,
        used: list[str],
        failures: list[str],
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one tool, recording success or failure instead of raising."""
        try:
            result = runner(tool, arguments)
        except Exception:  # pragma: no cover - runner should not raise
            logger.exception("Tool %s crashed inside %s", tool, self.agent_id)
            failures.append(tool)
            return default or {}
        if result.success:
            used.append(tool)
            return result.data or {}
        logger.warning("Agent %s: tool %s failed: %s", self.agent_id, tool, result.error)
        failures.append(tool)
        return default or {}

    def _summarise(
        self,
        findings: list[Finding],
        recommendations: list[Recommendation],
        data_gaps: list[str],
    ) -> str:
        if not findings:
            base = f"{self.name}: no findings for the requested period."
        else:
            ordered = sorted(
                findings,
                key=lambda f: FindingSeverity.ORDER.get(f.severity, 0),
                reverse=True,
            )
            headline = ordered[0].description
            base = f"{self.name}: {headline}"
            if len(ordered) > 1:
                base += f" (+{len(ordered) - 1} further finding(s))"
        if recommendations:
            base += f" {len(recommendations)} recommendation(s)."
        if data_gaps:
            base += f" Data gaps: {'; '.join(data_gaps[:2])}."
        return base

    @staticmethod
    def new_task_id() -> str:
        return f"task-{uuid.uuid4().hex[:10]}"

    @staticmethod
    def evidence(source: str, metric: str, value: str, period: str | None = None) -> Evidence:
        return Evidence(source=source, metric=metric, value=value, period=period)
