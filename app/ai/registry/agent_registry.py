"""Agent registry.

Phase 3 registers the five specialist agents and the interfaces through which
Phase 4 will give them reasoning of their own. They are **metadata only**: no
agent returns canned answers, and every tool call still goes through the
orchestrator and the tool registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.ai.schemas.intent_schema import Intent
from app.core.exceptions import NotFoundError
from app.core.logging_config import get_logger

logger = get_logger("ai.agents")


@dataclass(frozen=True)
class AgentDefinition:
    """Registration record for a specialist agent."""

    agent_id: str
    name: str
    description: str
    supported_intents: tuple[Intent, ...]
    supported_tools: tuple[str, ...]
    required_permissions: tuple[str, ...]
    available: bool = True
    phase: str = "Phase 4"

    def status_label(self, permission_checker: Callable[[str], bool] | None = None) -> str:
        if not self.available:
            return "unavailable"
        if permission_checker is not None:
            missing = [perm for perm in self.required_permissions if not permission_checker(perm)]
            if missing:
                return "restricted"
        return "ready"


@dataclass
class AgentHealth:
    agent_id: str
    name: str
    status: str
    detail: str
    intents: int = 0
    tools: int = 0


class AgentRegistry:
    """Holds the agent catalogue and resolves agents for an intent."""

    def __init__(self) -> None:
        self._agents: dict[str, AgentDefinition] = {}

    def register(self, definition: AgentDefinition) -> None:
        if definition.agent_id in self._agents:
            raise ValueError(f"Agent '{definition.agent_id}' is already registered")
        self._agents[definition.agent_id] = definition
        logger.debug("Registered agent %s", definition.agent_id)

    def get(self, agent_id: str) -> AgentDefinition:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise NotFoundError(f"Agent '{agent_id}' is not registered")
        return agent

    def list_agents(self) -> list[AgentDefinition]:
        return list(self._agents.values())

    def for_intent(self, intent: Intent) -> list[AgentDefinition]:
        return [agent for agent in self._agents.values() if intent in agent.supported_intents]

    def health(
        self, permission_checker: Callable[[str], bool] | None = None
    ) -> list[AgentHealth]:
        report: list[AgentHealth] = []
        for agent in self._agents.values():
            status = agent.status_label(permission_checker)
            if status == "ready":
                detail = "Registered; specialist reasoning arrives in Phase 4"
            elif status == "restricted":
                detail = "Your role does not cover every permission this agent needs"
            else:
                detail = "Disabled"
            report.append(
                AgentHealth(
                    agent_id=agent.agent_id,
                    name=agent.name,
                    status=status,
                    detail=detail,
                    intents=len(agent.supported_intents),
                    tools=len(agent.supported_tools),
                )
            )
        return report


def build_agent_registry() -> AgentRegistry:
    """Register the five Phase 4 agents."""
    registry = AgentRegistry()

    registry.register(
        AgentDefinition(
            agent_id="finance_agent",
            name="Finance Agent",
            description="Owns revenue, expenses, profit and cash-flow analysis",
            supported_intents=(
                Intent.GET_REVENUE,
                Intent.GET_EXPENSES,
                Intent.CALCULATE_PROFIT,
                Intent.GET_CASH_FLOW,
                Intent.GENERATE_FINANCIAL_REPORT,
            ),
            supported_tools=(
                "get_revenue",
                "get_expenses",
                "calculate_profit",
                "get_cash_flow",
                "get_outstanding_payments",
                "generate_financial_report",
            ),
            required_permissions=("finance.view",),
        )
    )
    registry.register(
        AgentDefinition(
            agent_id="sales_agent",
            name="Sales Agent",
            description="Owns order analysis, product performance and sales reporting",
            supported_intents=(
                Intent.ANALYZE_SALES,
                Intent.GET_TOP_PRODUCTS,
                Intent.CREATE_SALES_ORDER,
                Intent.GENERATE_SALES_REPORT,
            ),
            supported_tools=(
                "get_sales_summary",
                "get_sales_history",
                "get_top_products",
                "get_sales_trends",
                "get_pending_orders",
                "prepare_sales_order",
                "generate_sales_report",
            ),
            required_permissions=("sales.view",),
        )
    )
    registry.register(
        AgentDefinition(
            agent_id="customer_agent",
            name="Customer Agent",
            description="Owns customer segmentation, history and retention analysis",
            supported_intents=(
                Intent.CUSTOMER_ANALYSIS,
                Intent.GET_INACTIVE_CUSTOMERS,
            ),
            supported_tools=(
                "get_customer_summary",
                "get_inactive_customers",
                "get_customer_history",
                "get_customer_purchase_history",
            ),
            required_permissions=("customers.view",),
        )
    )
    registry.register(
        AgentDefinition(
            agent_id="inventory_agent",
            name="Inventory Agent",
            description="Owns stock levels, movements, valuation and purchase recommendations",
            supported_intents=(
                Intent.CHECK_STOCK,
                Intent.LOW_STOCK_ANALYSIS,
                Intent.CREATE_PURCHASE_RECOMMENDATION,
                Intent.GENERATE_INVENTORY_REPORT,
            ),
            supported_tools=(
                "get_product_stock",
                "get_low_stock_products",
                "get_stock_movements",
                "get_stock_valuation",
                "create_purchase_recommendation",
                "generate_inventory_report",
            ),
            required_permissions=("inventory.view",),
        )
    )
    registry.register(
        AgentDefinition(
            agent_id="business_intelligence_agent",
            name="Business Intelligence Agent",
            description="Owns cross-module summaries and business health analysis",
            supported_intents=(Intent.GENERAL_BUSINESS_ANALYSIS,),
            supported_tools=(
                "get_revenue",
                "get_sales_summary",
                "get_low_stock_products",
                "calculate_profit",
            ),
            required_permissions=("dashboard.view",),
        )
    )
    return registry
