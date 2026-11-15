"""Business Intelligence Agent: cross-functional synthesis of the other agents."""

from __future__ import annotations

from typing import Any, Callable

from app.ai.agent_tools.business_tools import (
    analyse_revenue_and_expenses,
    analyse_sales_and_inventory,
    combine_metrics,
    compare_periods,
    dedupe_findings,
    identify_risks,
    simulate_price_change,
)
from app.ai.agents.base_agent import BaseBusinessAgent, ToolRunner
from app.ai.schemas.agent_schema import AgentResult, AgentTask, Finding, Recommendation
from app.ai.schemas.intent_schema import Intent
from app.core.constants import AgentExecutionStatus

TASK_BUSINESS_HEALTH = "BUSINESS_HEALTH"
TASK_RISK_ANALYSIS = "RISK_ANALYSIS"
TASK_SALES_INVENTORY = "SALES_INVENTORY_COMPARISON"
TASK_SCENARIO = "SCENARIO_SIMULATION"

SPECIALIST_AGENTS = ("finance_agent", "sales_agent", "customer_agent", "inventory_agent")


class BusinessIntelligenceAgent(BaseBusinessAgent):
    """Combines the four specialist agents into one evidence-based view."""

    agent_id = "business_intelligence_agent"
    name = "Business Intelligence Agent"
    description = (
        "Cross-functional business health, risk detection, period comparison and "
        "what-if simulation built on the other four agents"
    )
    intents = (
        Intent.GENERAL_BUSINESS_ANALYSIS,
        Intent.BUSINESS_HEALTH_REPORT,
        Intent.BUSINESS_RISK_ANALYSIS,
        Intent.COMPARE_SALES_INVENTORY,
    )
    task_types = (
        TASK_BUSINESS_HEALTH,
        TASK_RISK_ANALYSIS,
        TASK_SALES_INVENTORY,
        TASK_SCENARIO,
    )
    default_task_type = TASK_BUSINESS_HEALTH
    data_tools = ("get_business_snapshot",)
    capabilities = (
        "compare_business_periods",
        "analyze_revenue_and_expenses",
        "analyze_sales_and_inventory",
        "analyze_customer_and_sales_relationship",
        "identify_business_risks",
        "generate_management_report",
        "simulate_business_scenario",
    )
    required_permissions = ("dashboard.view",)

    def __init__(
        self, *, coordinator_provider: Callable[[], Any] | None = None
    ) -> None:
        super().__init__()
        self._coordinator_provider = coordinator_provider

    # -- context: run the specialists -------------------------------------
    def collect_context(
        self, task: AgentTask, runner: ToolRunner
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        used: list[str] = []
        failures: list[str] = []

        snapshot = self._call(
            runner,
            "get_business_snapshot",
            {"period": task.period} if task.period else {},
            used=used,
            failures=failures,
        )

        results: list[AgentResult] = []
        coordinator = self._coordinator_provider() if self._coordinator_provider else None
        if coordinator is None:
            failures.append("agent coordinator")
        else:
            for agent_id in SPECIALIST_AGENTS:
                sub_task = AgentTask(
                    task_id=f"{task.task_id}-{agent_id}",
                    agent_id=agent_id,
                    task_type="",
                    period=task.period,
                    parameters=dict(task.parameters),
                    requested_by=task.requested_by,
                    workflow_id=task.workflow_id,
                )
                try:
                    agent = coordinator.get(agent_id)
                    sub_task = sub_task.model_copy(
                        update={"task_type": getattr(agent, "default_task_type", "")}
                    )
                    result = coordinator.run(
                        agent_id, sub_task, runner=runner, depth=1
                    )
                    results.append(result)
                    used.extend(result.tools_used)
                    if result.status != AgentExecutionStatus.COMPLETED:
                        failures.append(agent_id)
                except Exception:
                    failures.append(agent_id)

        return {
            "snapshot": snapshot,
            "results": results,
            "failures": failures,
        }, used, failures

    # -- analysis ----------------------------------------------------------
    def analyse(
        self, task: AgentTask, context: dict[str, Any], failures: list[str]
    ) -> tuple[list[Finding], list[Recommendation], dict[str, Any], list[str]]:
        period_label = task.period_label
        results: list[AgentResult] = context.get("results", []) or []
        by_agent = {result.agent_id: result for result in results}
        gaps: list[str] = []

        findings = dedupe_findings(results)
        recommendations: list[Recommendation] = []
        metrics: dict[str, Any] = {
            "agents_run": list(by_agent),
            "agent_summaries": combine_metrics(results),
            "business_snapshot": context.get("snapshot", {}),
        }

        finance = by_agent.get("finance_agent")
        if finance is not None:
            finance_findings, finance_recs = analyse_revenue_and_expenses(
                finance_result=finance, period_label=period_label
            )
            findings.extend(finance_findings)
            recommendations.extend(finance_recs)

        sales = by_agent.get("sales_agent")
        inventory = by_agent.get("inventory_agent")
        if sales is not None and inventory is not None:
            combo_findings, combo_recs = analyse_sales_and_inventory(
                sales_result=sales, inventory_result=inventory, period_label=period_label
            )
            findings.extend(combo_findings)
            recommendations.extend(combo_recs)

        customer = by_agent.get("customer_agent")
        if customer is not None:
            metrics["customer_metrics"] = customer.metrics

        findings = dedupe_findings(
            [AgentResult(agent_id=self.agent_id, task_id=task.task_id, findings=findings)]
        )

        risks = identify_risks(results=results, period_label=period_label)
        if task.task_type in (TASK_RISK_ANALYSIS, TASK_BUSINESS_HEALTH):
            findings.extend(risks)
        metrics["risk_count"] = len(risks)

        if task.task_type == TASK_SCENARIO:
            change_pct = float(task.parameters.get("price_change_pct", 5.0))
            products = (sales.metrics.get("top_products") if sales else None) or []
            if not products and sales is not None:
                products = []
            metrics["scenario"] = simulate_price_change(
                products=products, change_pct=change_pct
            )

        # Period comparison uses the snapshot's own monthly history.
        snapshot = context.get("snapshot", {}) or {}
        monthly = snapshot.get("monthly", []) or []
        if len(monthly) >= 2:
            comparison_findings, comparison_metrics = compare_periods(
                current=monthly[-1],
                previous=monthly[-2],
                period_label=period_label,
                label_current=str(monthly[-1].get("month")),
                label_previous=str(monthly[-2].get("month")),
            )
            findings.extend(comparison_findings)
            metrics["period_comparison"] = comparison_metrics

        if not results:
            gaps.append("specialist agent results (none completed)")
        failed_agents = [agent for agent in SPECIALIST_AGENTS if agent not in by_agent]
        if failed_agents:
            gaps.append(f"agents unavailable: {', '.join(failed_agents)}")

        # Escalate the highest-severity risks into recommendations.
        for finding in risks[:3]:
            recommendations.append(
                Recommendation(
                    recommendation_id=f"bi-rec-risk-{finding.finding_id[-12:]}",
                    recommendation="Address this risk with an owner and a review date.",
                    reason=finding.description,
                    priority="HIGH" if finding.severity == "HIGH" else "MEDIUM",
                    supporting_figures={"period": period_label},
                    agent_id=self.agent_id,
                )
            )

        return findings, recommendations, metrics, gaps
