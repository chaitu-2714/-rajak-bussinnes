"""Pydantic contracts for multi-agent collaboration."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.ai.schemas.agent_schema import Evidence, Finding, Recommendation
from app.core.constants import (
    CollaborationStatus,
    CollaborationTaskStatus,
    ConflictStatus,
    EvidenceStatus,
)


# ---------------------------------------------------------------------------
# tasks
# ---------------------------------------------------------------------------
class CollaborationTaskSpec(BaseModel):
    """A planned task, before it is persisted."""

    model_config = ConfigDict(extra="forbid")

    task_key: str = Field(min_length=2, max_length=60)
    assigned_agent: str
    task_type: str
    objective: str
    depends_on: list[str] = Field(default_factory=list)
    priority: str = "MEDIUM"
    task_params: dict[str, Any] = Field(default_factory=dict)
    parent_task_key: str | None = None


class CollaborationTaskView(BaseModel):
    """A persisted task as shown to the UI."""

    collaboration_id: str
    task_key: str
    parent_task_key: str | None = None
    assigned_agent: str
    task_type: str
    objective: str
    input_context: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    priority: str = "MEDIUM"
    status: str = CollaborationTaskStatus.PENDING
    attempts: int = 0
    execution_ms: float | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


# ---------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------
class AgentCollaborationResult(BaseModel):
    """One agent's contribution to a collaboration."""

    model_config = ConfigDict(extra="forbid")

    collaboration_id: str
    task_key: str
    agent_id: str
    status: str
    summary: str = ""
    findings: list[Finding] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    data_sources: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    execution_time_ms: float = 0.0
    requires_approval: bool = False
    metrics: dict[str, Any] = Field(default_factory=dict)
    agent_execution_id: int | None = None

    @classmethod
    def from_agent_result(cls, *, collaboration_id: str, task_key: str, result, execution_id=None):
        """Convert a Phase 4 :class:`AgentResult` into a collaboration result."""
        return cls(
            collaboration_id=collaboration_id,
            task_key=task_key,
            agent_id=result.agent_id,
            status=result.status,
            summary=result.summary,
            findings=result.findings,
            recommendations=result.recommendations,
            evidence=result.evidence,
            data_sources=sorted({item.source for item in result.evidence}),
            assumptions=list(result.metrics.get("assumptions", []) or []),
            limitations=list(result.data_gaps),
            confidence=result.confidence,
            execution_time_ms=round(result.execution_ms, 2),
            requires_approval=result.requires_approval,
            metrics=result.metrics,
            agent_execution_id=execution_id,
        )


# ---------------------------------------------------------------------------
# shared context
# ---------------------------------------------------------------------------
class SharedBusinessContext(BaseModel):
    """The business facts every participating agent works from."""

    model_config = ConfigDict(extra="forbid")

    business_id: int | None = None
    user_id: int | None = None
    objective: str
    reporting_period: str | None = None
    financial_context: dict[str, str] = Field(default_factory=dict)
    sales_context: dict[str, str] = Field(default_factory=dict)
    customer_context: dict[str, str] = Field(default_factory=dict)
    inventory_context: dict[str, str] = Field(default_factory=dict)
    supplier_context: dict[str, str] = Field(default_factory=dict)
    previous_findings: list[dict[str, Any]] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    available_budget: Decimal = Field(default=Decimal("0.00"))
    created_at: datetime | None = None

    @field_validator("available_budget")
    @classmethod
    def _quantise(cls, value: Decimal) -> Decimal:
        return Decimal(str(value)).quantize(Decimal("0.01"))


# ---------------------------------------------------------------------------
# decision
# ---------------------------------------------------------------------------
class DecisionRecommendation(BaseModel):
    """A unified, ranked recommendation with its evidence and constraints."""

    model_config = ConfigDict(extra="forbid")

    recommendation_id: str
    action: str
    reason: str
    supporting_evidence: list[Evidence] = Field(default_factory=list)
    expected_benefit: Decimal | None = None
    estimated_cost: Decimal | None = None
    risk: str = "MEDIUM"
    priority: str = "MEDIUM"
    required_approvals: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source_agents: list[str] = Field(default_factory=list)
    score: float = 0.0


class UnifiedDecision(BaseModel):
    """The single business decision produced by a collaboration."""

    model_config = ConfigDict(extra="forbid")

    collaboration_id: str
    business_objective: str
    executive_summary: str
    participating_agents: list[str] = Field(default_factory=list)
    consolidated_findings: list[Finding] = Field(default_factory=list)
    identified_risks: list[Finding] = Field(default_factory=list)
    opportunities: list[Finding] = Field(default_factory=list)
    conflicting_findings: list[dict[str, Any]] = Field(default_factory=list)
    recommended_actions: list[DecisionRecommendation] = Field(default_factory=list)
    financial_impact: dict[str, str] = Field(default_factory=dict)
    operational_impact: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    evidence_references: list[Evidence] = Field(default_factory=list)
    approval_requirements: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    status: str = "FINAL"
    confidence: float = 0.0
    generated_at: datetime | None = None

    @property
    def is_conclusive(self) -> bool:
        return self.status == "FINAL"


# ---------------------------------------------------------------------------
# collaboration views
# ---------------------------------------------------------------------------
class CollaborationView(BaseModel):
    """Row model for the Collaboration Center dashboard."""

    collaboration_id: str
    objective: str
    scenario: str
    strategy: str
    status: str = CollaborationStatus.PENDING
    phase: str | None = None
    reporting_period: str | None = None
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    agents: list[str] = Field(default_factory=list)
    conflicts: int = 0
    unresolved_conflicts: int = 0
    findings: int = 0
    confidence: float | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    @property
    def progress_percent(self) -> int:
        """Progress derived from real task statuses, never estimated."""
        if not self.tasks_total:
            return 0
        return int(round(self.tasks_completed / self.tasks_total * 100))


class CollaborationDetail(BaseModel):
    """Everything the detail screen needs."""

    collaboration: CollaborationView
    shared_context: dict[str, Any] = Field(default_factory=dict)
    tasks: list[CollaborationTaskView] = Field(default_factory=list)
    dependencies: list[tuple[str, str]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    decision: UnifiedDecision | None = None
    checkpoints: list[dict[str, Any]] = Field(default_factory=list)


class ValidationOutcome(BaseModel):
    """Result of evidence validation for one finding."""

    finding: Finding
    status: str = EvidenceStatus.UNVERIFIED
    issues: list[str] = Field(default_factory=list)
    verified_sources: list[str] = Field(default_factory=list)


class ConflictRecord(BaseModel):
    """A detected conflict between agent results."""

    model_config = ConfigDict(extra="forbid")

    conflict_id: str
    conflict_type: str
    agents: list[str] = Field(default_factory=list)
    description: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str = ConflictStatus.OPEN
    resolution: dict[str, Any] = Field(default_factory=dict)
