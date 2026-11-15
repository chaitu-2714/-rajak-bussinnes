"""Task vocabulary shared by the planner, the agents and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AgentTaskSpec:
    """One runnable task type for an agent."""

    agent_id: str
    task_type: str
    label: str
    description: str
    default_period: str | None = "this_month"
    parameters: dict = field(default_factory=dict)


AGENT_TASKS: tuple[AgentTaskSpec, ...] = (
    AgentTaskSpec(
        "finance_agent",
        "FINANCIAL_ANALYSIS",
        "Financial analysis",
        "Revenue, expenses, profit and cash flow for a period",
    ),
    AgentTaskSpec(
        "finance_agent",
        "EXPENSE_ANOMALIES",
        "Expense anomalies",
        "Statistical outliers in recorded expenses",
        default_period="all_time",
    ),
    AgentTaskSpec(
        "sales_agent",
        "SALES_ANALYSIS",
        "Sales analysis",
        "Sales volume, product contribution, trends and demand",
    ),
    AgentTaskSpec(
        "customer_agent",
        "CUSTOMER_ANALYSIS",
        "Customer analysis",
        "Segmentation, inactivity, value and follow-up priority",
        default_period=None,
    ),
    AgentTaskSpec(
        "inventory_agent",
        "INVENTORY_ANALYSIS",
        "Inventory analysis",
        "Stock health, reorder points, overstock and dead stock",
        default_period=None,
    ),
    AgentTaskSpec(
        "inventory_agent",
        "REORDER_PLANNING",
        "Reorder planning",
        "Demand-aware purchase suggestions",
        default_period=None,
    ),
    AgentTaskSpec(
        "business_intelligence_agent",
        "BUSINESS_HEALTH",
        "Business health",
        "Cross-functional health report from all agents",
    ),
    AgentTaskSpec(
        "business_intelligence_agent",
        "RISK_ANALYSIS",
        "Risk analysis",
        "Risks across finance, sales, customers and inventory",
    ),
    AgentTaskSpec(
        "business_intelligence_agent",
        "SALES_INVENTORY_COMPARISON",
        "Sales vs inventory",
        "Demand versus stock cover, with stockout risk",
        default_period="this_month",
    ),
    AgentTaskSpec(
        "business_intelligence_agent",
        "SCENARIO_SIMULATION",
        "What-if scenario",
        "Hypothetical revenue effect of a price change",
        default_period="this_month",
        parameters={"price_change_pct": 5.0},
    ),
)


def tasks_for(agent_id: str) -> list[AgentTaskSpec]:
    return [task for task in AGENT_TASKS if task.agent_id == agent_id]


def default_task_for(agent_id: str) -> AgentTaskSpec | None:
    tasks = tasks_for(agent_id)
    return tasks[0] if tasks else None
