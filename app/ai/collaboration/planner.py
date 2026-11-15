"""Collaboration planning: scenarios, task graphs and the shared business context.

The five scenarios from the Phase 5 brief are defined declaratively, so the same
task graph drives execution, the UI graph and the tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from app.ai.collaboration.dependency_manager import DependencyGraph
from app.ai.schemas.collaboration_schema import CollaborationTaskSpec, SharedBusinessContext
from app.core.constants import CollaborationStrategy
from app.core.logging_config import get_logger
from app.utils.date_utils import utcnow

logger = get_logger("ai.collaboration.planner")


@dataclass(frozen=True)
class ScenarioSpec:
    """A collaboration scenario: strategy, task graph and matching keywords."""

    key: str
    label: str
    objective_template: str
    strategy: str
    keywords: tuple[str, ...]
    tasks: tuple[CollaborationTaskSpec, ...]
    default_period: str | None = "this_month"

    @property
    def agents(self) -> list[str]:
        seen: list[str] = []
        for task in self.tasks:
            if task.assigned_agent not in seen:
                seen.append(task.assigned_agent)
        return seen


def _task(key, agent, task_type, objective, *, depends_on=(), priority="MEDIUM", params=None):
    return CollaborationTaskSpec(
        task_key=key,
        assigned_agent=agent,
        task_type=task_type,
        objective=objective,
        depends_on=list(depends_on),
        priority=priority,
        task_params=dict(params or {}),
    )


SALES_GROWTH = ScenarioSpec(
    key="SALES_GROWTH",
    label="Sales growth feasibility",
    objective_template="Can I increase my sales by {target}% next month?",
    strategy=CollaborationStrategy.SUPERVISOR_WORKER,
    keywords=("increase my sales", "grow my sales", "sales growth", "increase sales"),
    tasks=(
        _task("sales_baseline", "sales_agent", "SALES_ANALYSIS",
              "Establish the current sales baseline and recent trend", priority="HIGH"),
        _task("inventory_capacity", "inventory_agent", "INVENTORY_ANALYSIS",
              "Check whether stock can support higher sales", depends_on=("sales_baseline",)),
        _task("customer_opportunity", "customer_agent", "CUSTOMER_ANALYSIS",
              "Identify customers who could buy more", depends_on=("sales_baseline",)),
        _task("finance_capacity", "finance_agent", "FINANCIAL_ANALYSIS",
              "Assess cash and margin headroom for growth", depends_on=("sales_baseline",)),
        _task("synthesis", "business_intelligence_agent", "BUSINESS_HEALTH",
              "Combine the findings into a growth feasibility decision",
              depends_on=("inventory_capacity", "customer_opportunity", "finance_capacity"),
              priority="HIGH"),
    ),
)

INVENTORY_FINANCE = ScenarioSpec(
    key="INVENTORY_FINANCE",
    label="Inventory shortage and cash flow",
    objective_template="Which products should I reorder without affecting my cash flow?",
    strategy=CollaborationStrategy.SEQUENTIAL,
    keywords=("reorder without", "without affecting my cash", "reorder and cash",
              "which products should i reorder", "restock afford"),
    tasks=(
        _task("inventory_reorder", "inventory_agent", "REORDER_PLANNING",
              "Find products needing replenishment and the suggested quantities",
              priority="HIGH"),
        _task("sales_velocity", "sales_agent", "SALES_ANALYSIS",
              "Confirm demand behind the reorder suggestions", depends_on=("inventory_reorder",)),
        _task("finance_budget", "finance_agent", "FINANCIAL_ANALYSIS",
              "Establish available cash and outstanding commitments",
              depends_on=("sales_velocity",), priority="HIGH"),
        _task("synthesis", "business_intelligence_agent", "SALES_INVENTORY_COMPARISON",
              "Prioritise a purchasing sequence within the cash available",
              depends_on=("finance_budget",), priority="HIGH"),
    ),
)

DECLINING_SALES = ScenarioSpec(
    key="DECLINING_SALES",
    label="Declining sales investigation",
    objective_template="Why are my sales decreasing?",
    strategy=CollaborationStrategy.CONSENSUS,
    keywords=("why are my sales", "sales decreasing", "sales declining", "sales dropped",
              "sales falling"),
    tasks=(
        _task("sales_periods", "sales_agent", "SALES_ANALYSIS",
              "Compare sales across periods and quantify the decline", priority="HIGH"),
        _task("customer_activity", "customer_agent", "CUSTOMER_ANALYSIS",
              "Check customer inactivity and concentration"),
        _task("inventory_availability", "inventory_agent", "INVENTORY_ANALYSIS",
              "Check stock availability and stockouts"),
        _task("finance_margin", "finance_agent", "FINANCIAL_ANALYSIS",
              "Check margins and cost movements"),
        _task("synthesis", "business_intelligence_agent", "RISK_ANALYSIS",
              "Separate confirmed causes from possible explanations",
              depends_on=("sales_periods", "customer_activity", "inventory_availability",
                          "finance_margin"), priority="HIGH"),
    ),
)

BUSINESS_HEALTH = ScenarioSpec(
    key="BUSINESS_HEALTH",
    label="Complete business performance",
    objective_template="Analyze my complete business performance.",
    strategy=CollaborationStrategy.PARALLEL,
    keywords=("complete business performance", "business health", "analyse my business",
              "analyze my business", "business performance"),
    tasks=(
        _task("finance_review", "finance_agent", "FINANCIAL_ANALYSIS",
              "Review revenue, costs, profit and cash"),
        _task("sales_review", "sales_agent", "SALES_ANALYSIS",
              "Review sales volume, products and demand"),
        _task("customer_review", "customer_agent", "CUSTOMER_ANALYSIS",
              "Review customer activity and value"),
        _task("inventory_review", "inventory_agent", "INVENTORY_ANALYSIS",
              "Review stock health and replenishment needs"),
        _task("synthesis", "business_intelligence_agent", "BUSINESS_HEALTH",
              "Produce the unified business decision",
              depends_on=("finance_review", "sales_review", "customer_review",
                          "inventory_review"), priority="HIGH"),
    ),
)

SUPPLIER_CASHFLOW = ScenarioSpec(
    key="SUPPLIER_CASHFLOW",
    label="Supplier purchase and cash flow",
    objective_template="Can I purchase inventory from my suppliers this week?",
    strategy=CollaborationStrategy.SEQUENTIAL,
    keywords=("purchase inventory from", "from my suppliers", "buy from suppliers",
              "purchase this week", "supplier purchase"),
    tasks=(
        _task("inventory_needs", "inventory_agent", "REORDER_PLANNING",
              "List what must be purchased and at what cost", priority="HIGH"),
        _task("sales_demand", "sales_agent", "SALES_ANALYSIS",
              "Confirm the demand behind the purchase list",
              depends_on=("inventory_needs",)),
        _task("finance_capacity", "finance_agent", "FINANCIAL_ANALYSIS",
              "Check cash, receivables and commitments",
              depends_on=("sales_demand",), priority="HIGH"),
        _task("synthesis", "business_intelligence_agent", "BUSINESS_HEALTH",
              "Decide what can be purchased this week",
              depends_on=("finance_capacity",), priority="HIGH"),
    ),
)

SCENARIOS: dict[str, ScenarioSpec] = {
    spec.key: spec
    for spec in (
        SALES_GROWTH,
        INVENTORY_FINANCE,
        DECLINING_SALES,
        BUSINESS_HEALTH,
        SUPPLIER_CASHFLOW,
    )
}


class CollaborationPlanner:
    """Builds and validates collaboration plans from a scenario."""

    def __init__(self, *, max_tasks: int = 12) -> None:
        self._max_tasks = max_tasks

    # -- discovery ---------------------------------------------------------
    def scenario(self, key: str) -> ScenarioSpec:
        spec = SCENARIOS.get(key.upper())
        if spec is None:
            raise ValueError(f"Unknown collaboration scenario '{key}'")
        return spec

    def detect_scenario(self, objective: str) -> ScenarioSpec | None:
        text = objective.lower()
        best: tuple[int, ScenarioSpec] | None = None
        for spec in SCENARIOS.values():
            hits = sum(1 for keyword in spec.keywords if keyword in text)
            if hits and (best is None or hits > best[0]):
                best = (hits, spec)
        return best[1] if best else None

    def identify_required_agents(self, scenario_key: str) -> list[str]:
        return self.scenario(scenario_key).agents

    # -- planning ----------------------------------------------------------
    def generate_plan(self, scenario_key: str) -> list[CollaborationTaskSpec]:
        spec = self.scenario(scenario_key)
        if len(spec.tasks) > self._max_tasks:
            raise ValueError(
                f"Scenario '{spec.key}' needs {len(spec.tasks)} tasks, above the limit of "
                f"{self._max_tasks}"
            )
        graph = DependencyGraph(list(spec.tasks))
        errors = graph.validate()
        if errors:
            raise ValueError("; ".join(errors))
        return list(spec.tasks)

    def validate_plan(self, tasks: list[CollaborationTaskSpec]) -> list[str]:
        errors = DependencyGraph(tasks).validate()
        if len(tasks) > self._max_tasks:
            errors.append(f"the plan exceeds the {self._max_tasks}-task limit")
        return errors

    def dependency_edges(self, tasks: list[CollaborationTaskSpec]) -> list[tuple[str, str]]:
        return DependencyGraph(tasks).edges()

    def waves(self, tasks: list[CollaborationTaskSpec]) -> list[list[str]]:
        return DependencyGraph(tasks).waves()

    def objective_for(self, scenario_key: str, *, target_percent: int = 20) -> str:
        return self.scenario(scenario_key).objective_template.format(target=target_percent)


class SharedContextBuilder:
    """Builds the shared business context from authoritative services."""

    def __init__(self, *, runner, period_label: str | None = None) -> None:
        self._runner = runner
        self._period_label = period_label

    def build(
        self,
        *,
        objective: str,
        business_id: int | None,
        user_id: int | None,
        period: str | None = None,
        previous_findings: list[dict] | None = None,
    ) -> SharedBusinessContext:
        snapshot = self._call("get_business_snapshot", {"period": period} if period else {})
        suppliers = self._call("get_supplier_details", {})
        purchase_orders = self._call("get_purchase_order_status", {})

        cash_received = _dec(snapshot.get("cash_received"))
        outstanding = _dec(snapshot.get("outstanding"))
        budget = cash_received if cash_received > 0 else Decimal("0.00")

        constraints: list[str] = []
        if budget <= 0:
            constraints.append("No cash has been collected in the period; no purchase is affordable yet.")
        if outstanding > 0:
            constraints.append(
                f"{outstanding:,.2f} is still receivable and is not counted as available cash."
            )

        return SharedBusinessContext(
            business_id=business_id,
            user_id=user_id,
            objective=objective,
            reporting_period=period or self._period_label,
            financial_context={
                "revenue": str(snapshot.get("revenue", "not reported")),
                "operating_expenses": str(snapshot.get("operating_expenses", "not reported")),
                "net_profit": str(snapshot.get("net_profit", "not reported")),
                "cash_received": str(snapshot.get("cash_received", "not reported")),
                "outstanding_receivables": str(snapshot.get("outstanding", "not reported")),
            },
            sales_context={
                "sales_value": str(snapshot.get("sales_value", "not reported")),
                "completed_orders": str(snapshot.get("completed_orders", 0)),
                "total_orders": str(snapshot.get("total_orders", 0)),
            },
            customer_context={
                "active_customers": str(snapshot.get("active_customers", 0)),
                "total_customers": str(snapshot.get("total_customers", 0)),
            },
            inventory_context={
                "products": str(snapshot.get("products", 0)),
                "low_stock_products": str(snapshot.get("low_stock_products", 0)),
                "stock_value": str(snapshot.get("stock_value", "not reported")),
            },
            supplier_context={
                "suppliers": str(len(suppliers.get("suppliers", []) or [])),
                "purchase_orders": str(purchase_orders.get("total", purchase_orders.get("count", 0))),
                "lead_time": "not recorded in the system",
            },
            previous_findings=list(previous_findings or []),
            constraints=constraints,
            available_budget=budget,
            created_at=utcnow(),
        )

    def _call(self, tool: str, arguments: dict) -> dict:
        result = self._runner(tool, arguments)
        if not getattr(result, "success", False):
            logger.warning("Shared context tool %s failed: %s", tool, getattr(result, "error", ""))
            return {}
        return result.data or {}


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception:  # noqa: BLE001 - defensive
        return Decimal("0.00")
