"""AI orchestration models: conversations, workflows, tools and model settings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import AIWorkflowStatus
from app.database.base import Base
from app.utils.date_utils import utcnow


class AIConversation(Base):
    """A chat thread in the AI Command Center."""

    __tablename__ = "ai_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="New conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="AIMessage.id"
    )
    workflows: Mapped[list["AIWorkflow"]] = relationship(back_populates="conversation")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIConversation id={self.id} title={self.title!r}>"


class AIMessage(Base):
    """One message in a conversation (user, assistant or system notice)."""

    __tablename__ = "ai_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_type: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    message_content: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional structured context (intent, workflow id, provider, errors).
    meta: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    conversation: Mapped["AIConversation"] = relationship(back_populates="messages")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIMessage id={self.id} sender={self.sender_type!r}>"


class AIWorkflow(Base):
    """A persisted execution plan and its lifecycle."""

    __tablename__ = "ai_workflows"
    __table_args__ = (
        UniqueConstraint("workflow_id", name="uq_ai_workflows_workflow_id"),
        # One AI workflow per business event guarantees duplicate prevention.
        UniqueConstraint("source_event_id", name="uq_ai_workflows_source_event_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("ai_conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    intent: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    command: Mapped[str | None] = mapped_column(Text)
    execution_plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default=AIWorkflowStatus.PENDING,
        index=True,
        server_default=text("'PENDING'"),
    )
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    trigger_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="COMMAND", server_default=text("'COMMAND'")
    )
    source_event_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_events.id", ondelete="SET NULL"), nullable=True, index=True
    )
    provider: Mapped[str | None] = mapped_column(String(30))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default=text("0"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    conversation: Mapped["AIConversation | None"] = relationship(back_populates="workflows")
    steps: Mapped[list["AIWorkflowStep"]] = relationship(
        back_populates="workflow", cascade="all, delete-orphan", order_by="AIWorkflowStep.step_number"
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in AIWorkflowStatus.TERMINAL

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIWorkflow {self.workflow_id} {self.intent} {self.status}>"


class AIWorkflowStep(Base):
    """The persisted outcome of one tool call inside a workflow."""

    __tablename__ = "ai_workflow_steps"
    __table_args__ = (
        UniqueConstraint("workflow_id", "step_number", name="uq_ai_workflow_steps_workflow_step"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("ai_workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    required_permission: Mapped[str | None] = mapped_column(String(64))
    risk_level: Mapped[str | None] = mapped_column(String(20))
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    workflow: Mapped["AIWorkflow"] = relationship(back_populates="steps")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIWorkflowStep #{self.step_number} {self.tool_name} {self.status}>"


class AIToolRegistryEntry(Base):
    """Database mirror of a registered tool (audit and enable/disable)."""

    __tablename__ = "ai_tool_registry"
    __table_args__ = (UniqueConstraint("tool_name", name="uq_ai_tool_registry_tool_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tool_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40))
    required_permission: Mapped[str] = mapped_column(String(64), nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="READ_ONLY")
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIToolRegistryEntry {self.tool_name!r} enabled={self.is_enabled}>"


class AIModelSetting(Base):
    """Provider configuration (never holds an API key — see credentials.py)."""

    __tablename__ = "ai_model_settings"
    __table_args__ = (UniqueConstraint("provider", name="uq_ai_model_settings_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    configuration: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AIModelSetting {self.provider} {self.model_name} enabled={self.is_enabled}>"
