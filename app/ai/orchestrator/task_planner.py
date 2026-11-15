"""Task planning: turn an intent into a validated, ordered execution plan."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable

from app.ai.registry.tool_registry import ToolRegistry
from app.ai.schemas.intent_schema import Intent, IntentResult
from app.ai.schemas.workflow_schema import ExecutionPlan, PlanStep
from app.core.constants import AIRiskLevel
from app.core.exceptions import BizPilotError
from app.utils.date_utils import utcnow

DEFAULT_MAX_STEPS = 8


class PlanningError(BizPilotError):
    default_user_message = "I could not build a safe plan for that request."


@dataclass(frozen=True)
class PlanTemplate:
    """One step of a canned, intent-specific plan."""

    tool_name: str
    description: str
    build_arguments: Callable[[dict[str, Any]], dict[str, Any]]
    depends_on: tuple[int, ...] = ()


def _knowledge_query(entities: dict[str, Any]) -> str:
    """Use the original question as the retrieval query."""
    for key in ("query", "question", "raw", "text", "command", "objective"):
        value = entities.get(key)
        if isinstance(value, str) and len(value) > 3:
            return value
    values = [str(value) for value in entities.values() if isinstance(value, str)]
    return max(values, key=len) if values else "business documents"


def _granularity(entities: dict[str, Any]) -> str:
    """Map a recognised period onto an analytics granularity."""
    period = str(entities.get("period") or "").lower()
    if "day" in period or "today" in period:
        return "DAILY"
    if "week" in period:
        return "WEEKLY"
    if "quarter" in period:
        return "QUARTERLY"
    if "year" in period or "annual" in period:
        return "YEARLY"
    return "MONTHLY"


def _forecast_target(entities: dict[str, Any]) -> str:
    text = " ".join(str(value) for value in entities.values()).lower()
    if "cash" in text:
        return "CASH_FLOW"
    if "expense" in text:
        return "EXPENSES"
    if "demand" in text or "stock" in text:
        return "DEMAND"
    return "SALES"


def _period_args(entities: dict[str, Any]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    if entities.get("period"):
        arguments["period"] = entities["period"]
    return arguments


def _product_args(entities: dict[str, Any]) -> dict[str, Any]:
    arguments = _period_args(entities)
    if entities.get("product_name"):
        arguments["product_name"] = entities["product_name"]
    return arguments


def _empty_args(entities: dict[str, Any]) -> dict[str, Any]:
    return {}


def _collaboration_args(scenario: str):
    """Plan arguments for the ``run_collaboration`` tool."""

    def build(entities: dict[str, Any]) -> dict[str, Any]:
        arguments: dict[str, Any] = {"scenario": scenario}
        if entities.get("period"):
            arguments["period"] = entities["period"]
        return arguments

    return build


def _agent_args(task_type: str):
    """Plan arguments for a ``run_*_agent`` step."""

    def build(entities: dict[str, Any]) -> dict[str, Any]:
        arguments: dict[str, Any] = {"task_type": task_type}
        if entities.get("period"):
            arguments["period"] = entities["period"]
        return arguments

    return build


def _top_product_args(entities: dict[str, Any]) -> dict[str, Any]:
    return {"limit": 5}


def _inactive_args(entities: dict[str, Any]) -> dict[str, Any]:
    return {"days": 90, "limit": 10}


def _customer_args(entities: dict[str, Any]) -> dict[str, Any]:
    return {"customer_name": entities.get("customer_name")} if entities.get("customer_name") else {}


def _supplier_args(entities: dict[str, Any]) -> dict[str, Any]:
    return {"supplier_name": entities.get("supplier_name")} if entities.get("supplier_name") else {}


def _financial_report_args(entities: dict[str, Any]) -> dict[str, Any]:
    arguments = _period_args(entities)
    arguments.update({"report_type": "profit_and_loss", "file_format": "pdf"})
    return arguments


def _sales_report_args(entities: dict[str, Any]) -> dict[str, Any]:
    return _period_args(entities)


def _sales_order_args(entities: dict[str, Any]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    if entities.get("product_name"):
        items.append(
            {
                "product_name": entities["product_name"],
                "quantity": int(entities.get("quantity") or 1),
            }
        )
    arguments: dict[str, Any] = {"items": items}
    if entities.get("customer_name"):
        arguments["customer_name"] = entities["customer_name"]
    return arguments


def _expense_args(entities: dict[str, Any]) -> dict[str, Any]:
    arguments: dict[str, Any] = {
        "expense_category": entities.get("expense_category", "OTHER"),
        "description": entities.get("description") or "Expense recorded from AI Command Center",
    }
    if entities.get("amount"):
        arguments["amount"] = entities["amount"]
    return arguments


def _recommendation_args(entities: dict[str, Any]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    if entities.get("product_name"):
        arguments["product_name"] = entities["product_name"]
    if entities.get("quantity"):
        arguments["requested_quantity"] = int(entities["quantity"])
    return arguments


INTENT_PLANS: dict[Intent, tuple[PlanTemplate, ...]] = {
    # --- Phase 4: analysis intents are delegated to specialist agents ---
    Intent.GET_REVENUE: (
        PlanTemplate("run_finance_agent", "Finance Agent: revenue analysis", _agent_args("FINANCIAL_ANALYSIS")),
    ),
    Intent.GET_EXPENSES: (
        PlanTemplate("run_finance_agent", "Finance Agent: expense analysis", _agent_args("FINANCIAL_ANALYSIS")),
    ),
    Intent.CALCULATE_PROFIT: (
        PlanTemplate("run_finance_agent", "Finance Agent: profit analysis", _agent_args("FINANCIAL_ANALYSIS")),
    ),
    Intent.GET_CASH_FLOW: (
        PlanTemplate("run_finance_agent", "Finance Agent: cash-flow analysis", _agent_args("FINANCIAL_ANALYSIS")),
    ),
    Intent.FINANCIAL_ANALYSIS: (
        PlanTemplate("run_finance_agent", "Finance Agent: full financial review", _agent_args("FINANCIAL_ANALYSIS")),
    ),
    Intent.ANALYZE_EXPENSE_ANOMALIES: (
        PlanTemplate("run_finance_agent", "Finance Agent: expense anomalies", _agent_args("EXPENSE_ANOMALIES")),
    ),
    Intent.ANALYZE_SALES: (
        PlanTemplate("run_sales_agent", "Sales Agent: performance analysis", _agent_args("SALES_ANALYSIS")),
    ),
    Intent.GET_TOP_PRODUCTS: (
        PlanTemplate("run_sales_agent", "Sales Agent: product performance", _agent_args("SALES_ANALYSIS")),
    ),
    Intent.CHECK_STOCK: (
        PlanTemplate("run_inventory_agent", "Inventory Agent: stock health", _agent_args("INVENTORY_ANALYSIS")),
    ),
    Intent.LOW_STOCK_ANALYSIS: (
        PlanTemplate("run_inventory_agent", "Inventory Agent: reorder planning", _agent_args("REORDER_PLANNING")),
    ),
    Intent.CUSTOMER_ANALYSIS: (
        PlanTemplate("run_customer_agent", "Customer Agent: base analysis", _agent_args("CUSTOMER_ANALYSIS")),
    ),
    Intent.GET_INACTIVE_CUSTOMERS: (
        PlanTemplate("run_customer_agent", "Customer Agent: inactivity analysis", _agent_args("CUSTOMER_ANALYSIS")),
    ),
    Intent.BUSINESS_HEALTH_REPORT: (
        PlanTemplate("run_business_intelligence_agent", "Business Intelligence: health report", _agent_args("BUSINESS_HEALTH")),
    ),
    Intent.BUSINESS_RISK_ANALYSIS: (
        PlanTemplate("run_business_intelligence_agent", "Business Intelligence: risk analysis", _agent_args("RISK_ANALYSIS")),
    ),
    Intent.COMPARE_SALES_INVENTORY: (
        PlanTemplate("run_business_intelligence_agent", "Business Intelligence: sales vs inventory", _agent_args("SALES_INVENTORY_COMPARISON")),
    ),
    Intent.GET_SUPPLIER_DETAILS: (
        PlanTemplate("get_supplier_details", "Read the supplier profile", _supplier_args),
        PlanTemplate("get_purchase_order_status", "Read open purchase orders", _empty_args),
    ),
    Intent.GENERATE_FINANCIAL_REPORT: (
        PlanTemplate("generate_financial_report", "Export the financial report", _financial_report_args),
    ),
    Intent.GENERATE_SALES_REPORT: (
        PlanTemplate("generate_sales_report", "Export the sales report", _sales_report_args),
    ),
    Intent.GENERATE_INVENTORY_REPORT: (
        PlanTemplate("generate_inventory_report", "Export the inventory report", _empty_args),
    ),
    Intent.CREATE_SALES_ORDER: (
        PlanTemplate("prepare_sales_order", "Prepare a sales order draft", _sales_order_args),
    ),
    Intent.CREATE_EXPENSE: (
        PlanTemplate("prepare_expense", "Prepare an expense draft", _expense_args),
    ),
    Intent.CREATE_PURCHASE_RECOMMENDATION: (
        PlanTemplate("get_product_stock", "Read current stock", _product_args),
        PlanTemplate("get_sales_history", "Read recent sales", lambda entities: {"period": "last_30_days", "limit": 20}),
        PlanTemplate("get_cash_flow", "Read available cash", _period_args),
        PlanTemplate(
            "create_purchase_recommendation",
            "Recommend a purchase quantity",
            _recommendation_args,
            depends_on=(0, 1, 2),
        ),
    ),
    # --- Phase 5: collaborations ---
    Intent.COLLAB_SALES_GROWTH: (
        PlanTemplate("run_collaboration", "Five-agent growth feasibility", _collaboration_args("SALES_GROWTH")),
    ),
    Intent.COLLAB_REORDER_CASHFLOW: (
        PlanTemplate("run_collaboration", "Reorder within cash flow", _collaboration_args("INVENTORY_FINANCE")),
    ),
    Intent.KNOWLEDGE_SEARCH: (
        PlanTemplate(
            "search_business_documents",
            "Search business documents",
            lambda entities: {"query": _knowledge_query(entities), "mode": "HYBRID"},
        ),
    ),
    Intent.DOCUMENT_QUESTION: (
        PlanTemplate(
            "ask_business_documents",
            "Answer from business documents",
            lambda entities: {"question": _knowledge_query(entities), "mode": "DOCUMENT"},
        ),
    ),
    Intent.ANALYTICS_PERFORMANCE: (
        PlanTemplate(
            "get_business_analytics",
            "Business performance analytics",
            lambda entities: {"granularity": _granularity(entities)},
        ),
    ),
    Intent.ANALYTICS_FORECAST: (
        PlanTemplate(
            "forecast_business_metric",
            "Forecast with chronological validation",
            lambda entities: {
                "target": _forecast_target(entities),
                "horizon": 1,
            },
        ),
    ),
    Intent.ANALYTICS_ANOMALIES: (
        PlanTemplate(
            "detect_business_anomalies",
            "Anomaly detection",
            lambda entities: {"granularity": _granularity(entities)},
        ),
    ),
    Intent.ANALYTICS_RISK: (
        PlanTemplate(
            "assess_business_risks",
            "Business risk assessment",
            lambda entities: {"granularity": _granularity(entities)},
        ),
    ),
    Intent.ANALYTICS_SIMULATION: (
        PlanTemplate(
            "simulate_business_scenario",
            "What-if simulation",
            lambda entities: {"scenario": "SALES_DECLINE", "percent": 10},
        ),
    ),
    Intent.COLLAB_DECLINING_SALES: (
        PlanTemplate("run_collaboration", "Declining sales investigation", _collaboration_args("DECLINING_SALES")),
    ),
    Intent.COLLAB_BUSINESS_HEALTH: (
        PlanTemplate("run_collaboration", "Complete business performance", _collaboration_args("BUSINESS_HEALTH")),
    ),
    Intent.COLLAB_SUPPLIER_CASHFLOW: (
        PlanTemplate("run_collaboration", "Supplier purchase and cash", _collaboration_args("SUPPLIER_CASHFLOW")),
    ),
    Intent.GENERAL_BUSINESS_ANALYSIS: (
        PlanTemplate(
            "run_business_intelligence_agent",
            "Business Intelligence: cross-functional health",
            _agent_args("BUSINESS_HEALTH"),
        ),
    ),
}


class TaskPlanner:
    """Builds an :class:`ExecutionPlan` from a classified intent."""

    def __init__(self, registry: ToolRegistry, *, max_steps: int = DEFAULT_MAX_STEPS) -> None:
        self._registry = registry
        self._max_steps = max_steps

    @property
    def max_steps(self) -> int:
        return self._max_steps

    def plan(self, intent_result: IntentResult) -> ExecutionPlan:
        intent = intent_result.intent
        if intent is Intent.UNKNOWN_INTENT:
            raise PlanningError(
                "That request does not map to a supported business operation."
            )
        if intent_result.requires_clarification:
            raise PlanningError(
                intent_result.clarification_question
                or "Please rephrase the request with a little more detail."
            )

        templates = INTENT_PLANS.get(intent, ())
        if not templates:
            raise PlanningError(f"No plan is defined for {intent.value}.")

        if len(templates) > self._max_steps:
            raise PlanningError(
                f"This request needs {len(templates)} steps but the limit is {self._max_steps}."
            )

        entities = dict(intent_result.entities or {})
        steps: list[PlanStep] = []
        requires_approval = intent_result.definition.requires_approval

        for index, template in enumerate(templates):
            definition = self._registry.get(template.tool_name)
            if definition.requires_approval:
                requires_approval = True
            steps.append(
                PlanStep(
                    step_id=f"step-{index + 1}",
                    step_number=index + 1,
                    tool_name=definition.name,
                    arguments=template.build_arguments(entities),
                    required_permission=definition.required_permission,
                    depends_on=[f"step-{dep + 1}" for dep in template.depends_on],
                    risk_level=definition.risk_level,
                    description=template.description,
                )
            )

        return ExecutionPlan(
            plan_id=uuid.uuid4().hex[:12],
            intent=intent,
            steps=steps,
            requires_approval=requires_approval,
            notes=(
                "This plan contains an action that changes business data; "
                "it waits for your approval before running."
                if requires_approval
                else "Read-only analysis."
            ),
            created_at=utcnow(),
        )

    def risk_summary(self, plan: ExecutionPlan) -> str:
        if plan.max_risk == AIRiskLevel.READ_ONLY:
            return "Read-only"
        return plan.max_risk.title()
