"""Unit tests: the tool registry and its execution guard rails."""

from __future__ import annotations

import time

import pytest
from pydantic import BaseModel, Field

from app.ai.registry.tool_catalogue import build_tool_registry
from app.ai.registry.tool_registry import (
    ToolRegistry,
    ToolRegistryError,
    UnknownToolError,
)
from app.ai.schemas.tool_schema import ToolContext, ToolDefinition, ToolInvocation
from app.core.constants import AIRiskLevel
from app.core.exceptions import BizPilotError


class EchoArgs(BaseModel):
    message: str = Field(min_length=1, max_length=50)
    count: int = Field(default=1, ge=1, le=5)


def _context() -> ToolContext:
    return ToolContext(services=None, user_id=1)


def _registry_with(handler, *, timeout: float = 5.0, permission: str = "finance.view") -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="echo_tool",
            description="Echo a message",
            category="test",
            input_model=EchoArgs,
            required_permission=permission,
            timeout_seconds=timeout,
            handler=handler,
        )
    )
    return registry


def _allow(permission: str) -> bool:
    return True


def _deny(permission: str) -> bool:
    return False


def test_register_and_lookup() -> None:
    registry = _registry_with(lambda context, args: {"summary": "ok"})
    assert registry.has("echo_tool")
    definition = registry.get("echo_tool")
    assert definition.required_permission == "finance.view"
    assert registry.names() == ["echo_tool"]


def test_duplicate_registration_rejected() -> None:
    registry = _registry_with(lambda context, args: {})
    with pytest.raises(ToolRegistryError):
        registry.register(registry.get("echo_tool"))


def test_tool_must_declare_a_permission() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolRegistryError):
        registry.register(
            ToolDefinition(
                name="no_permission",
                description="bad",
                category="test",
                input_model=EchoArgs,
                required_permission="",
                handler=lambda context, args: {},
            )
        )


def test_unknown_tool_lookup_raises() -> None:
    registry = _registry_with(lambda context, args: {})
    with pytest.raises(UnknownToolError):
        registry.get("rm_rf")


def test_unknown_tool_execution_returns_error() -> None:
    registry = _registry_with(lambda context, args: {})
    result = registry.execute(
        ToolInvocation(tool_name="os.system", arguments={"cmd": "ls"}),
        _context(),
        permission_checker=_allow,
    )
    assert result.success is False
    assert "not registered" in (result.error or "")


def test_valid_execution() -> None:
    registry = _registry_with(lambda context, args: {"echo": args.message, "summary": "echoed"})
    result = registry.execute(
        ToolInvocation(tool_name="echo_tool", arguments={"message": "hello"}),
        _context(),
        permission_checker=_allow,
    )
    assert result.success is True
    assert result.data["echo"] == "hello"
    assert result.summary == "echoed"
    assert result.duration_ms >= 0


def test_invalid_arguments_are_rejected_before_the_handler_runs() -> None:
    called = {"count": 0}

    def handler(context, args):
        called["count"] += 1
        return {}

    registry = _registry_with(handler)
    result = registry.execute(
        ToolInvocation(tool_name="echo_tool", arguments={"message": "", "count": 99}),
        _context(),
        permission_checker=_allow,
    )
    assert result.success is False
    assert "Invalid arguments" in (result.error or "")
    assert called["count"] == 0


def test_unauthorised_execution_is_blocked() -> None:
    called = {"count": 0}

    def handler(context, args):
        called["count"] += 1
        return {}

    registry = _registry_with(handler)
    result = registry.execute(
        ToolInvocation(tool_name="echo_tool", arguments={"message": "hi"}),
        _context(),
        permission_checker=_deny,
    )
    assert result.success is False
    assert "Permission denied" in (result.error or "")
    assert called["count"] == 0


def test_timeout_is_reported() -> None:
    def slow(context, args):
        time.sleep(0.4)
        return {}

    registry = _registry_with(slow, timeout=0.05)
    result = registry.execute(
        ToolInvocation(tool_name="echo_tool", arguments={"message": "hi"}),
        _context(),
        permission_checker=_allow,
    )
    assert result.success is False
    assert "timed out" in (result.error or "").lower()


def test_tool_error_is_surfaced_without_a_traceback() -> None:
    def failing(context, args):
        raise BizPilotError("Business rule violated")

    registry = _registry_with(failing)
    result = registry.execute(
        ToolInvocation(tool_name="echo_tool", arguments={"message": "hi"}),
        _context(),
        permission_checker=_allow,
    )
    assert result.success is False
    assert result.error == "Business rule violated"
    assert "Traceback" not in (result.error or "")


def test_disabled_tool_cannot_run() -> None:
    definition = ToolDefinition(
        name="disabled_tool",
        description="off",
        category="test",
        input_model=EchoArgs,
        required_permission="finance.view",
        handler=lambda context, args: {},
        enabled=False,
    )
    registry = ToolRegistry()
    registry.register(definition)
    result = registry.execute(
        ToolInvocation(tool_name="disabled_tool", arguments={"message": "hi"}),
        _context(),
        permission_checker=_allow,
    )
    assert result.success is False
    assert "disabled" in (result.error or "")


def test_cancellation_prevents_execution() -> None:
    called = {"count": 0}

    def handler(context, args):
        called["count"] += 1
        return {}

    registry = _registry_with(handler)
    result = registry.execute(
        ToolInvocation(tool_name="echo_tool", arguments={"message": "hi"}),
        _context(),
        permission_checker=_allow,
        cancelled=lambda: True,
    )
    assert result.success is False
    assert called["count"] == 0


# -- the real catalogue ------------------------------------------------------
def test_catalogue_registers_every_phase2_tool() -> None:
    registry = build_tool_registry()
    expected = {
        # finance
        "get_revenue",
        "get_expenses",
        "calculate_profit",
        "get_cash_flow",
        "get_outstanding_payments",
        "generate_financial_report",
        # sales
        "get_sales_summary",
        "get_sales_history",
        "get_top_products",
        "get_sales_trends",
        "get_pending_orders",
        # customers
        "get_customer_summary",
        "get_inactive_customers",
        "get_customer_history",
        "get_customer_purchase_history",
        # inventory
        "get_product_stock",
        "get_low_stock_products",
        "get_stock_movements",
        "get_stock_valuation",
        # suppliers
        "get_supplier_details",
        "get_supplier_purchase_history",
        "get_purchase_order_status",
        # reporting
        "generate_sales_report",
        "generate_inventory_report",
        # approval-gated preparation
        "prepare_sales_order",
        "prepare_expense",
        "create_purchase_recommendation",
    }
    assert expected.issubset(set(registry.names()))
    # 27 Phase 2/3 + 7 data + 5 runners + 1 collaboration + 6 analytics + 2 knowledge
    assert len(registry.names()) == 48


def test_every_catalogue_tool_is_safe_and_typed() -> None:
    registry = build_tool_registry()
    for tool in registry.list_tools():
        assert tool.required_permission, tool.name
        assert tool.risk_level in AIRiskLevel.ALL, tool.name
        assert tool.timeout_seconds > 0
        assert tool.input_model is not None
        assert tool.description


def test_catalogue_contains_no_execution_tools() -> None:
    registry = build_tool_registry()
    forbidden = ("shell", "exec", "eval", "sql", "python", "file", "delete", "drop")
    for name in registry.names():
        assert not any(word in name.lower() for word in forbidden), name
