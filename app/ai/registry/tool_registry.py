"""Central tool registry.

Every capability the orchestrator can reach is registered here with an input
schema, a required permission, a risk level and a timeout. Handlers call the
existing Phase 2 services — there is no direct database access, no SQL and no
Python execution anywhere in the AI layer.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Callable

from pydantic import ValidationError as PydanticValidationError

from app.ai.schemas.tool_schema import ToolContext, ToolDefinition, ToolInvocation, ToolResult
from app.core.constants import AIRiskLevel
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger

logger = get_logger("ai.tools")

PermissionChecker = Callable[[str], bool]


class ToolRegistryError(BizPilotError):
    default_user_message = "The requested tool is not available."


class UnknownToolError(ToolRegistryError):
    default_user_message = "That operation is not registered, so it cannot be executed."


class ToolRegistry:
    """Allowlist of executable tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    # -- registration ------------------------------------------------------
    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._tools:
            raise ToolRegistryError(f"Tool '{definition.name}' is already registered")
        if not definition.required_permission:
            raise ToolRegistryError(
                f"Tool '{definition.name}' must declare a required permission"
            )
        self._tools[definition.name] = definition
        logger.debug("Registered tool %s (%s)", definition.name, definition.risk_level)

    def register_all(self, definitions: list[ToolDefinition]) -> None:
        for definition in definitions:
            self.register(definition)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    # -- lookup ------------------------------------------------------------
    def get(self, name: str) -> ToolDefinition:
        definition = self._tools.get(name)
        if definition is None:
            raise UnknownToolError(f"Unknown tool '{name}'")
        return definition

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def list_tools(self, *, category: str | None = None) -> list[ToolDefinition]:
        tools = [tool for tool in self._tools.values() if tool.enabled]
        if category:
            tools = [tool for tool in tools if tool.category == category]
        return sorted(tools, key=lambda tool: (tool.category, tool.name))

    def categories(self) -> list[str]:
        return sorted({tool.category for tool in self._tools.values()})

    # -- execution ---------------------------------------------------------
    def execute(
        self,
        invocation: ToolInvocation,
        context: ToolContext,
        *,
        permission_checker: PermissionChecker,
        cancelled: Callable[[], bool] | None = None,
    ) -> ToolResult:
        """Validate, authorise and run one tool call."""
        try:
            definition = self.get(invocation.tool_name)
        except UnknownToolError as exc:
            return ToolResult(
                tool_name=invocation.tool_name,
                success=False,
                error=exc.user_message,
            )

        if not definition.enabled:
            return ToolResult(
                tool_name=definition.name,
                success=False,
                error=f"Tool '{definition.name}' is disabled",
                risk_level=definition.risk_level,
            )

        if definition.required_permission and not permission_checker(
            definition.required_permission
        ):
            logger.warning(
                "Tool %s denied: missing %s", definition.name, definition.required_permission
            )
            return ToolResult(
                tool_name=definition.name,
                success=False,
                error=(
                    f"Permission denied: this action requires "
                    f"'{definition.required_permission}'"
                ),
                risk_level=definition.risk_level,
            )

        try:
            arguments = definition.input_model.model_validate(invocation.arguments)
        except PydanticValidationError as exc:
            message = "; ".join(
                f"{'.'.join(str(part) for part in error['loc']) or 'input'}: "
                f"{str(error['msg']).replace('Value error, ', '')}"
                for error in exc.errors()
            )
            return ToolResult(
                tool_name=definition.name,
                success=False,
                error=f"Invalid arguments — {message}",
                risk_level=definition.risk_level,
            )

        if cancelled is not None and cancelled():
            return ToolResult(
                tool_name=definition.name,
                success=False,
                error="Workflow cancelled before this step ran",
                risk_level=definition.risk_level,
            )

        started = time.perf_counter()
        try:
            data = self._run_with_timeout(definition, context, arguments)
        except FutureTimeoutError:
            elapsed = int((time.perf_counter() - started) * 1000)
            logger.warning("Tool %s timed out after %ss", definition.name, definition.timeout_seconds)
            return ToolResult(
                tool_name=definition.name,
                success=False,
                error=f"Tool timed out after {definition.timeout_seconds:.0f}s",
                duration_ms=elapsed,
                risk_level=definition.risk_level,
            )
        except BizPilotError as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            return ToolResult(
                tool_name=definition.name,
                success=False,
                error=exc.safe_message,
                duration_ms=elapsed,
                risk_level=definition.risk_level,
            )
        except Exception:  # pragma: no cover - defensive
            elapsed = int((time.perf_counter() - started) * 1000)
            logger.exception("Tool %s failed unexpectedly", definition.name)
            return ToolResult(
                tool_name=definition.name,
                success=False,
                error="The operation failed unexpectedly; details were logged.",
                duration_ms=elapsed,
                risk_level=definition.risk_level,
            )

        elapsed = int((time.perf_counter() - started) * 1000)
        summary = str((data or {}).get("summary", ""))[:400]
        return ToolResult(
            tool_name=definition.name,
            success=True,
            data=data or {},
            duration_ms=elapsed,
            risk_level=definition.risk_level,
            summary=summary,
        )

    @staticmethod
    def _run_with_timeout(
        definition: ToolDefinition, context: ToolContext, arguments: Any
    ) -> dict[str, Any]:
        """Run the handler in a worker thread so a hung call cannot block forever.

        SQLite work is not pre-emptible, so the timeout stops *waiting* and marks
        the step failed; the documented behaviour is that the workflow fails fast.
        """
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tool") as pool:
            future = pool.submit(definition.handler, context, arguments)
            return future.result(timeout=definition.timeout_seconds)


def risk_rank(risk: str) -> int:
    """Numeric ordering for risk levels (READ_ONLY is lowest)."""
    try:
        return list(AIRiskLevel.ALL).index(risk)
    except ValueError:  # pragma: no cover - defensive
        return 0
