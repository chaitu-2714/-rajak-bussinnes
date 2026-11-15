"""Structured agent-to-agent messages."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import CollaborationMessageType

MAX_PAYLOAD_BYTES = 20_000


class AgentMessage(BaseModel):
    """One message on the collaboration bus.

    Agents never call each other directly: every exchange is a validated,
    persisted message routed by the collaboration manager.
    """

    model_config = ConfigDict(extra="forbid")

    message_id: str
    collaboration_id: str
    sender_agent: str
    receiver_agent: str
    message_type: str
    task_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    evidence_references: list[str] = Field(default_factory=list)
    timestamp: datetime | None = None
    status: str = "DELIVERED"

    @field_validator("message_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in CollaborationMessageType.ALL:
            raise ValueError(f"'{value}' is not a registered message type")
        return value

    @field_validator("sender_agent", "receiver_agent")
    @classmethod
    def _named_agent(cls, value: str) -> str:
        if not value or len(value) > 60:
            raise ValueError("agent names must be 1-60 characters")
        return value

    @field_validator("payload")
    @classmethod
    def _bounded_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        size = len(str(value))
        if size > MAX_PAYLOAD_BYTES:
            raise ValueError(f"payload too large ({size} bytes)")
        return value
