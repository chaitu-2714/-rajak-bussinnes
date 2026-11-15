"""Pydantic contracts for autonomous workflows, policies and approvals."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import (
    ApprovalStatus,
    AutonomyMode,
    WorkflowStatus,
    WorkflowTaskStatus,
    WorkflowTaskType,
)


class WorkflowTaskSpec(BaseModel):
    """A planned workflow task, before persistence."""

    model_config = ConfigDict(extra="forbid")

    task_key: str = Field(min_length=2, max_length=60)
    task_type: str
    title: str = ""
    assigned_agent: str | None = None
    action_name: str | None = None
    input_data: dict[str, Any] = Field(default_factory=dict)
    dependencies: list[str] = Field(default_factory=list)
    permission_required: str | None = None
    risk_level: str = "LOW"

    @field_validator("task_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in WorkflowTaskType.ALL:
            raise ValueError(f"'{value}' is not a registered workflow task type")
        return value


class WorkflowTaskView(BaseModel):
    workflow_ref: str
    task_key: str
    task_type: str
    title: str = ""
    assigned_agent: str | None = None
    action_name: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    status: str = WorkflowTaskStatus.PENDING
    retry_count: int = 0
    risk_level: str = "LOW"
    permission_required: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None
    execution_ms: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class WorkflowView(BaseModel):
    workflow_ref: str
    workflow_type: str
    objective: str
    trigger_type: str
    trigger_ref: str | None = None
    status: str = WorkflowStatus.PENDING
    phase: str | None = None
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    pending_approvals: int = 0
    retry_count: int = 0
    current_task: str | None = None
    requested_by: int | None = None
    scheduled_for: datetime | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    @property
    def progress_percent(self) -> int:
        if not self.tasks_total:
            return 0
        return int(round(self.tasks_completed / self.tasks_total * 100))


class WorkflowDetail(BaseModel):
    workflow: WorkflowView
    tasks: list[WorkflowTaskView] = Field(default_factory=list)
    approvals: list[dict[str, Any]] = Field(default_factory=list)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] = Field(default_factory=dict)


class PolicyDecision(BaseModel):
    """The autonomy verdict for one action."""

    action_name: str
    mode: str = AutonomyMode.RESTRICTED
    allowed: bool = False
    requires_approval: bool = True
    reason: str = ""
    policy_id: str | None = None
    maximum_amount: Decimal | None = None
    approval_count: int = 1

    @property
    def is_automatic(self) -> bool:
        return self.allowed and self.mode == AutonomyMode.AUTOMATIC and not self.requires_approval


class ApprovalView(BaseModel):
    approval_ref: str
    workflow_ref: str | None = None
    task_key: str | None = None
    requested_action: str
    action_details: dict[str, Any] = Field(default_factory=dict)
    financial_impact: str | None = None
    risk_level: str = "MEDIUM"
    reason: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    status: str = ApprovalStatus.PENDING
    requested_by: int | None = None
    requested_by_name: str | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None
    decided_by: int | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    execution_result: dict[str, Any] | None = None


class PolicyView(BaseModel):
    policy_id: str
    action_name: str
    display_name: str = ""
    execution_mode: str = AutonomyMode.RESTRICTED
    maximum_amount: str | None = None
    allowed_roles: list[str] = Field(default_factory=list)
    approval_required: bool = True
    approval_count: int = 1
    allow_self_approval: bool = False
    daily_execution_limit: int | None = None
    enabled: bool = True
    updated_at: datetime | None = None


class ScheduleView(BaseModel):
    schedule_key: str
    name: str
    workflow_type: str
    frequency: str
    time_of_day: str = "08:00"
    timezone: str = "Asia/Kolkata"
    enabled: bool = True
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    last_status: str | None = None


class ActionOutcome(BaseModel):
    """Result of executing (or refusing) a business action."""

    action_name: str
    executed: bool = False
    summary: str = ""
    record_type: str | None = None
    record_id: int | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
