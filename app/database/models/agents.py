"""Phase 4 models: registered agents, executions, findings, recommendations, memory."""

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
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import AgentExecutionStatus, AgentMemoryType, RecommendationStatus
from app.database.base import Base
from app.utils.date_utils import utcnow


class Agent(Base):
    """A registered specialist agent."""

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("agent_code", name="uq_agents_agent_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    agent_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    executions: Mapped[list["AgentExecution"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    memories: Mapped[list["AgentMemory"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Agent {self.agent_code} enabled={self.is_enabled}>"


class AgentExecution(Base):
    """One agent run, linked to the orchestrator workflow that triggered it."""

    __tablename__ = "agent_executions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workflow_id: Mapped[str | None] = mapped_column(String(40), index=True)
    task_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(String(40))
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AgentExecutionStatus.PENDING,
        index=True,
        server_default=text("'PENDING'"),
    )
    summary: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    execution_time: Mapped[float | None] = mapped_column(Float)
    error_message: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    agent: Mapped["Agent"] = relationship(back_populates="executions")
    findings: Mapped[list["AgentFinding"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["AgentRecommendation"]] = relationship(
        back_populates="execution", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentExecution {self.agent_id} {self.task_type} {self.status}>"


class AgentFinding(Base):
    """A structured observation produced by an agent, with its evidence."""

    __tablename__ = "agent_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    finding_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="INFO", index=True)
    evidence_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    reporting_period: Mapped[str | None] = mapped_column(String(80))
    metric_value: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    execution: Mapped["AgentExecution"] = relationship(back_populates="findings")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentFinding {self.finding_type} {self.severity}>"


class AgentRecommendation(Base):
    """An actionable recommendation with its reason and status."""

    __tablename__ = "agent_recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    execution_id: Mapped[int] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="MEDIUM", index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=RecommendationStatus.OPEN,
        index=True,
        server_default=text("'OPEN'"),
    )
    supporting_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    execution: Mapped["AgentExecution"] = relationship(back_populates="recommendations")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentRecommendation {self.priority} {self.status}>"


class AgentMemory(Base):
    """Limited, auditable business memory written by agents."""

    __tablename__ = "agent_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    memory_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AgentMemoryType.NOTE, index=True
    )
    memory_content: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    source_execution_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_executions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    agent: Mapped["Agent"] = relationship(back_populates="memories")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AgentMemory {self.memory_type}>"
