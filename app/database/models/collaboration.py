"""Phase 5 models: multi-agent collaborations, tasks, messages and decisions."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import (
    CollaborationStatus,
    CollaborationTaskStatus,
    ConflictStatus,
)
from app.database.base import Base
from app.utils.date_utils import utcnow


class AgentCollaboration(Base):
    """One coordinated, multi-agent business objective."""

    __tablename__ = "agent_collaborations"
    __table_args__ = (UniqueConstraint("collaboration_id", name="uq_agent_collaborations_collaboration_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collaboration_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    scenario: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CollaborationStatus.PENDING, index=True,
        server_default=text("'PENDING'"),
    )
    reporting_period: Mapped[str | None] = mapped_column(String(40))
    shared_context: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    phase: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    tasks: Mapped[list["CollaborationTask"]] = relationship(
        back_populates="collaboration", cascade="all, delete-orphan"
    )
    messages: Mapped[list["CollaborationMessage"]] = relationship(
        back_populates="collaboration", cascade="all, delete-orphan"
    )
    findings: Mapped[list["CollaborationFinding"]] = relationship(
        back_populates="collaboration", cascade="all, delete-orphan"
    )
    conflicts: Mapped[list["CollaborationConflict"]] = relationship(
        back_populates="collaboration", cascade="all, delete-orphan"
    )
    decision: Mapped["CollaborationDecision | None"] = relationship(
        back_populates="collaboration", cascade="all, delete-orphan", uselist=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentCollaboration {self.collaboration_id} {self.status}>"


class CollaborationTask(Base):
    """One agent task inside a collaboration."""

    __tablename__ = "collaboration_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_collaboration_tasks_idempotency_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collaboration_id: Mapped[int] = mapped_column(
        ForeignKey("agent_collaborations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    parent_task_key: Mapped[str | None] = mapped_column(String(60))
    assigned_agent: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    task_type: Mapped[str] = mapped_column(String(60), nullable=False)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    input_context: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=CollaborationTaskStatus.PENDING, index=True,
        server_default=text("'PENDING'"),
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    agent_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="SET NULL")
    )
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_message: Mapped[str | None] = mapped_column(Text)
    execution_ms: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    collaboration: Mapped["AgentCollaboration"] = relationship(back_populates="tasks")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<CollaborationTask {self.task_key} {self.assigned_agent} {self.status}>"


class CollaborationDependency(Base):
    """Edge in the collaboration dependency graph."""

    __tablename__ = "collaboration_dependencies"
    __table_args__ = (
        UniqueConstraint("collaboration_id", "task_key", "depends_on_key", name="uq_collaboration_dependencies_edge"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collaboration_id: Mapped[int] = mapped_column(
        ForeignKey("agent_collaborations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    depends_on_key: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class CollaborationMessage(Base):
    """A structured, validated message between two agents."""

    __tablename__ = "collaboration_messages"
    __table_args__ = (UniqueConstraint("message_id", name="uq_collaboration_messages_message_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collaboration_id: Mapped[int] = mapped_column(
        ForeignKey("agent_collaborations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sender_agent: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    receiver_agent: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    message_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    task_key: Mapped[str | None] = mapped_column(String(60))
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    evidence_refs: Mapped[list[Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DELIVERED")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    collaboration: Mapped["AgentCollaboration"] = relationship(back_populates="messages")


class CollaborationFinding(Base):
    """A validated finding contributed to a collaboration."""

    __tablename__ = "collaboration_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collaboration_id: Mapped[int] = mapped_column(
        ForeignKey("agent_collaborations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    finding_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    evidence: Mapped[list[Any] | None] = mapped_column(JSON)
    reporting_period: Mapped[str | None] = mapped_column(String(80))
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNVERIFIED")
    validation_issues: Mapped[list[Any] | None] = mapped_column(JSON)
    source_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    collaboration: Mapped["AgentCollaboration"] = relationship(back_populates="findings")


class CollaborationConflict(Base):
    """A detected disagreement between agents, with its resolution."""

    __tablename__ = "collaboration_conflicts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collaboration_id: Mapped[int] = mapped_column(
        ForeignKey("agent_collaborations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conflict_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    conflict_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    agents: Mapped[list[Any] | None] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ConflictStatus.OPEN, index=True
    )
    resolution: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

    collaboration: Mapped["AgentCollaboration"] = relationship(back_populates="conflicts")


class CollaborationDecision(Base):
    """The unified business decision produced by a collaboration."""

    __tablename__ = "collaboration_decisions"
    __table_args__ = (
        UniqueConstraint("collaboration_id", name="uq_collaboration_decisions_collaboration_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collaboration_id: Mapped[int] = mapped_column(
        ForeignKey("agent_collaborations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    executive_summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="FINAL")
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    collaboration: Mapped["AgentCollaboration"] = relationship(back_populates="decision")


class CollaborationCheckpoint(Base):
    """Persisted execution state, used for recovery after a restart."""

    __tablename__ = "collaboration_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collaboration_id: Mapped[int] = mapped_column(
        ForeignKey("agent_collaborations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phase: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    collaboration: Mapped["AgentCollaboration"] = relationship()
