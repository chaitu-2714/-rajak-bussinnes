"""Phase 6 models: autonomous workflows, tasks, policies, approvals, schedules."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import (
    ApprovalStatus,
    AutonomyMode,
    WorkflowStatus,
    WorkflowTaskStatus,
    WorkflowTriggerType,
    WorkflowType,
)
from app.database.base import Base
from app.utils.date_utils import utcnow


class AutonomousWorkflow(Base):
    """One autonomous business workflow instance."""

    __tablename__ = "autonomous_workflows"
    __table_args__ = (UniqueConstraint("workflow_ref", name="uq_autonomous_workflows_workflow_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    workflow_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkflowTriggerType.MANUAL
    )
    trigger_ref: Mapped[str | None] = mapped_column(String(120), index=True)
    trigger_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkflowStatus.PENDING, index=True,
        server_default=text("'PENDING'"),
    )
    phase: Mapped[str | None] = mapped_column(String(60))
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    current_task_key: Mapped[str | None] = mapped_column(String(60))
    planned_at: Mapped[datetime | None] = mapped_column(DateTime)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    error_message: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    tasks: Mapped[list["WorkflowTask"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )
    approvals: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AutonomousWorkflow {self.workflow_ref} {self.workflow_type} {self.status}>"


class WorkflowTask(Base):
    """One task inside an autonomous workflow."""

    __tablename__ = "workflow_tasks"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_workflow_tasks_idempotency_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("autonomous_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    assigned_agent: Mapped[str | None] = mapped_column(String(60), index=True)
    action_name: Mapped[str | None] = mapped_column(String(60), index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    dependencies: Mapped[list[Any] | None] = mapped_column(JSON)
    execution_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=WorkflowTaskStatus.PENDING, index=True,
        server_default=text("'PENDING'"),
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default=text("2"))
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    permission_required: Mapped[str | None] = mapped_column(String(60))
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="LOW")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_details: Mapped[str | None] = mapped_column(Text)
    execution_ms: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    workflow: Mapped["AutonomousWorkflow"] = relationship(back_populates="tasks")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<WorkflowTask {self.task_key} {self.task_type} {self.execution_status}>"


class WorkflowTrigger(Base):
    """Registered trigger, with a unique key for duplicate prevention."""

    __tablename__ = "workflow_triggers"
    __table_args__ = (UniqueConstraint("trigger_key", name="uq_workflow_triggers_trigger_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trigger_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    event_type: Mapped[str | None] = mapped_column(String(60), index=True)
    event_id: Mapped[int | None] = mapped_column(ForeignKey("business_events.id", ondelete="SET NULL"))
    workflow_type: Mapped[str] = mapped_column(String(60), nullable=False)
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("autonomous_workflows.id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="CONSUMED")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class AutonomyPolicy(Base):
    """Per-action autonomy policy (automatic / approval / restricted)."""

    __tablename__ = "autonomy_policies"
    __table_args__ = (UniqueConstraint("action_name", name="uq_autonomy_policies_action_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    action_name: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    execution_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default=AutonomyMode.RESTRICTED
    )
    maximum_amount: Mapped[float | None] = mapped_column(Numeric(14, 2))
    allowed_roles: Mapped[list[Any] | None] = mapped_column(JSON)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    allow_self_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    daily_execution_limit: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class ApprovalRequest(Base):
    """A human approval checkpoint raised by a workflow."""

    __tablename__ = "approval_requests"
    __table_args__ = (UniqueConstraint("approval_ref", name="uq_approval_requests_approval_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    approval_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("autonomous_workflows.id", ondelete="CASCADE"), index=True
    )
    task_key: Mapped[str | None] = mapped_column(String(60))
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    requested_action: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    action_details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    financial_impact: Mapped[float | None] = mapped_column(Numeric(14, 2))
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ApprovalStatus.PENDING, index=True,
        server_default=text("'PENDING'"),
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime)
    decision_note: Mapped[str | None] = mapped_column(Text)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    workflow: Mapped["AutonomousWorkflow | None"] = relationship(back_populates="approvals")
    decisions: Mapped[list["ApprovalDecision"]] = relationship(
        back_populates="request", cascade="all, delete-orphan"
    )


class ApprovalDecision(Base):
    """An immutable record of an approval decision."""

    __tablename__ = "approval_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    approval_id: Mapped[int] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    decided_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    request: Mapped["ApprovalRequest"] = relationship(back_populates="decisions")


class WorkflowExecutionLog(Base):
    """Structured execution log for a workflow."""

    __tablename__ = "workflow_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("autonomous_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_key: Mapped[str | None] = mapped_column(String(60))
    level: Mapped[str] = mapped_column(String(10), nullable=False, default="INFO")
    event: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class ScheduledWorkflow(Base):
    """Persistent schedule for recurring automations."""

    __tablename__ = "scheduled_workflows"
    __table_args__ = (UniqueConstraint("schedule_key", name="uq_scheduled_workflows_schedule_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    workflow_type: Mapped[str] = mapped_column(String(60), nullable=False)
    frequency: Mapped[str] = mapped_column(String(20), nullable=False, default="DAILY")
    time_of_day: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")
    weekday: Mapped[int | None] = mapped_column(Integer)
    interval_hours: Mapped[int | None] = mapped_column(Integer)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    last_status: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class WorkflowIdempotencyRecord(Base):
    """Guard against executing the same business action twice."""

    __tablename__ = "workflow_idempotency_records"
    __table_args__ = (UniqueConstraint("idempotency_key", name="uq_workflow_idempotency_records_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    workflow_id: Mapped[int | None] = mapped_column(
        ForeignKey("autonomous_workflows.id", ondelete="SET NULL"), index=True
    )
    task_key: Mapped[str | None] = mapped_column(String(60))
    action_name: Mapped[str] = mapped_column(String(60), nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class WorkflowDeadLetter(Base):
    """Events or tasks that could not be processed, kept for retry."""

    __tablename__ = "workflow_dead_letters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="EVENT")
    reference: Mapped[str | None] = mapped_column(String(160), index=True)
    event_type: Mapped[str | None] = mapped_column(String(60))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
