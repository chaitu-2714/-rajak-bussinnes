"""Workflow schemas: plans, steps, results and previews."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import AIRiskLevel, AIStepStatus, AIWorkflowStatus
from app.ai.schemas.intent_schema import Intent


class PlanStep(BaseModel):
    """One executable step in a plan."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(min_length=1, max_length=40)
    step_number: int = Field(ge=1, le=50)
    tool_name: str = Field(min_length=2, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)
    required_permission: str = ""
    status: str = AIStepStatus.PENDING
    depends_on: list[str] = Field(default_factory=list)
    risk_level: str = AIRiskLevel.READ_ONLY
    description: str = ""


class ExecutionPlan(BaseModel):
    """A validated plan produced by the task planner."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str
    intent: Intent
    steps: list[PlanStep] = Field(default_factory=list)
    requires_approval: bool = False
    notes: str = ""
    created_at: datetime | None = None

    @property
    def tool_names(self) -> list[str]:
        return [step.tool_name for step in self.steps]

    @property
    def max_risk(self) -> str:
        order = list(AIRiskLevel.ALL)
        highest = AIRiskLevel.READ_ONLY
        for step in self.steps:
            if order.index(step.risk_level) > order.index(highest):
                highest = step.risk_level
        return highest


class StepResult(BaseModel):
    """Outcome of one executed step."""

    step_id: str
    step_number: int
    tool_name: str
    status: str
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    risk_level: str = AIRiskLevel.READ_ONLY
    summary: str = ""


class WorkflowResult(BaseModel):
    """The complete outcome returned to the UI."""

    workflow_id: str
    intent: Intent
    status: str
    steps: list[StepResult] = Field(default_factory=list)
    response_text: str = ""
    provider: str = "fallback"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    requires_approval: bool = False
    pending_action: dict[str, Any] | None = None
    total_duration_ms: int = 0

    @property
    def succeeded(self) -> bool:
        return self.status == AIWorkflowStatus.COMPLETED

    @property
    def is_waiting(self) -> bool:
        return self.status == AIWorkflowStatus.WAITING_FOR_APPROVAL


class WorkflowPreview(BaseModel):
    """What the orchestrator created before execution starts."""

    workflow_id: str
    intent: Intent
    confidence: float = 0.0
    classified_by: str = "rules"
    steps: list[PlanStep] = Field(default_factory=list)
    requires_approval: bool = False
    clarification_question: str | None = None


class ConversationView(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class MessageView(BaseModel):
    id: int
    sender_type: str
    content: str
    created_at: datetime
    meta: dict[str, Any] | None = None


class WorkflowView(BaseModel):
    """Read model for the workflow history panel."""

    id: int
    workflow_id: str
    intent: str
    status: str
    command: str | None = None
    trigger_type: str = "COMMAND"
    provider: str | None = None
    current_step: int = 0
    step_count: int = 0
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    steps: list[dict[str, Any]] = Field(default_factory=list)
