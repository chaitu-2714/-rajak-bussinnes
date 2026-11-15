"""Tool registry schemas: definitions, invocations and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from app.core.constants import AIRiskLevel


class ToolInvocation(BaseModel):
    """A single requested tool call inside a plan."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str = Field(min_length=2, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """The verified outcome of one tool call."""

    tool_name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0
    risk_level: str = AIRiskLevel.READ_ONLY
    summary: str = ""

    @property
    def failed(self) -> bool:
        return not self.success


@dataclass(frozen=True)
class ToolDefinition:
    """Everything the orchestrator needs to know about a tool."""

    name: str
    description: str
    category: str
    input_model: type[BaseModel]
    required_permission: str
    risk_level: str = AIRiskLevel.READ_ONLY
    timeout_seconds: float = 20.0
    handler: Callable[..., dict[str, Any]] = field(default=None)  # type: ignore[assignment]
    output_hint: str = ""
    enabled: bool = True

    @property
    def requires_approval(self) -> bool:
        return self.risk_level in AIRiskLevel.APPROVAL_REQUIRED


@dataclass
class ToolContext:
    """Runtime context handed to tool handlers."""

    services: Any
    user_id: int
    business_id: int | None = None
    conversation_id: int | None = None
    workflow_id: str | None = None
