"""Schemas for specialised agents: tasks, findings, recommendations, results."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import (
    AgentExecutionStatus,
    FindingSeverity,
    RecommendationStatus,
)

Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH"]
Priority = Literal["LOW", "MEDIUM", "HIGH"]


class Evidence(BaseModel):
    """One traceable data point behind a finding."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Tool or service that produced the value")
    metric: str
    value: str
    period: str | None = None
    record_count: int | None = None


class Finding(BaseModel):
    """A structured observation with severity and evidence."""

    model_config = ConfigDict(extra="forbid")

    finding_id: str
    finding_type: str
    description: str
    severity: Severity = FindingSeverity.INFO
    evidence: list[Evidence] = Field(default_factory=list)
    reporting_period: str | None = None
    metric_value: float | None = None
    agent_id: str = ""

    @field_validator("evidence")
    @classmethod
    def _require_evidence(cls, value: list[Evidence]) -> list[Evidence]:
        if not value:
            raise ValueError("every finding must cite at least one piece of evidence")
        return value


class Recommendation(BaseModel):
    """An actionable recommendation with its reason and supporting figures."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str
    recommendation: str
    reason: str
    priority: Priority = "MEDIUM"
    status: str = RecommendationStatus.OPEN
    supporting_figures: dict[str, str] = Field(default_factory=dict)
    agent_id: str = ""

    @field_validator("reason")
    @classmethod
    def _require_reason(cls, value: str) -> str:
        if len(value.strip()) < 5:
            raise ValueError("a recommendation must explain its reason")
        return value


class AgentTask(BaseModel):
    """A structured task handed to one agent."""

    model_config = ConfigDict(extra="forbid")

    task_id: str
    agent_id: str
    task_type: str
    period: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    requested_by: int | None = None
    workflow_id: str | None = None

    @property
    def period_label(self) -> str:
        return self.period or "all recorded time"


class AgentResult(BaseModel):
    """The common output schema every agent returns."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    task_id: str
    status: str = AgentExecutionStatus.COMPLETED
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    requires_approval: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_basis: str = ""
    tools_used: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    execution_ms: float = 0.0
    error: str | None = None

    @property
    def succeeded(self) -> bool:
        return self.status == AgentExecutionStatus.COMPLETED

    @property
    def high_severity_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.severity in ("HIGH", "MEDIUM")]

    def top_findings(self, limit: int = 3) -> list[Finding]:
        ordered = sorted(
            self.findings, key=lambda f: FindingSeverity.ORDER.get(f.severity, 0), reverse=True
        )
        return ordered[:limit]


class AgentInfo(BaseModel):
    """Public description of an agent (used by the registry and the UI)."""

    agent_code: str
    agent_name: str
    description: str
    intents: list[str] = Field(default_factory=list)
    data_tools: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    required_permissions: list[str] = Field(default_factory=list)
    is_enabled: bool = True

    @property
    def tool_count(self) -> int:
        return len(set(self.data_tools) | set(self.capabilities))


class AgentStats(BaseModel):
    """Execution statistics for the monitoring dashboard."""

    agent_code: str
    agent_name: str
    status: str = "idle"
    executions: int = 0
    completed: int = 0
    failed: int = 0
    last_execution_at: datetime | None = None
    last_status: str | None = None
    open_recommendations: int = 0
    tool_count: int = 0
    workload: int = 0
    avg_execution_ms: float = 0.0


class ConfidenceCalculator:
    """Deterministic confidence scoring.

    Confidence reflects *evidence coverage*, never model opinion:

    * base 0.45
    * +0.10 for each distinct evidence source used (max 4 sources → +0.40)
    * +0.05 when every requested tool returned data
    * −0.10 for each failed tool (max −0.30)
    * −0.10 for each declared data gap (max −0.20)
    * capped to [0.05, 0.95]
    """

    BASE = 0.45
    PER_SOURCE = 0.10
    MAX_SOURCES = 4
    ALL_TOOLS_BONUS = 0.05
    PER_FAILED_TOOL = 0.10
    MAX_FAILED_PENALTY = 0.30
    PER_GAP = 0.10
    MAX_GAP_PENALTY = 0.20
    FLOOR = 0.05
    CEILING = 0.95

    def compute(
        self,
        *,
        evidence_sources: set[str],
        tools_requested: int,
        tools_failed: int,
        data_gaps: int,
    ) -> tuple[float, str]:
        sources = min(len(evidence_sources), self.MAX_SOURCES)
        score = self.BASE + self.PER_SOURCE * sources
        parts = [f"base {self.BASE:.2f}", f"+{self.PER_SOURCE:.2f}×{sources} sources"]

        if tools_requested and tools_failed == 0:
            score += self.ALL_TOOLS_BONUS
            parts.append(f"+{self.ALL_TOOLS_BONUS:.2f} all tools answered")
        if tools_failed:
            penalty = min(self.PER_FAILED_TOOL * tools_failed, self.MAX_FAILED_PENALTY)
            score -= penalty
            parts.append(f"−{penalty:.2f} for {tools_failed} failed tool(s)")
        if data_gaps:
            penalty = min(self.PER_GAP * data_gaps, self.MAX_GAP_PENALTY)
            score -= penalty
            parts.append(f"−{penalty:.2f} for {data_gaps} data gap(s)")

        score = max(self.FLOOR, min(self.CEILING, score))
        parts.append(f"→ {score:.2f}")
        return round(score, 2), ", ".join(parts)
