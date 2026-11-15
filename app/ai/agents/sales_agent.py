"""Sales Agent: performance, product mix, decline detection and demand."""

from __future__ import annotations

from typing import Any

from app.ai.agent_tools.sales_tools import (
    analyse_demand,
    analyse_products,
    analyse_sales_performance,
    build_sales_recommendations,
)
from app.ai.agents.base_agent import BaseBusinessAgent, ToolRunner
from app.ai.schemas.agent_schema import AgentTask, Finding, Recommendation
from app.ai.schemas.intent_schema import Intent

TASK_SALES_ANALYSIS = "SALES_ANALYSIS"


class SalesAgent(BaseBusinessAgent):
    """Analyses sales volume, product performance, trends and demand."""

    agent_id = "sales_agent"
    name = "Sales Agent"
    description = "Sales performance, product contribution, decline detection and demand analysis"
    intents = (
        Intent.ANALYZE_SALES,
        Intent.GET_TOP_PRODUCTS,
        Intent.GENERATE_SALES_REPORT,
    )
    task_types = (TASK_SALES_ANALYSIS,)
    default_task_type = TASK_SALES_ANALYSIS
    data_tools = (
        "get_sales_summary",
        "get_top_products",
        "get_sales_trends",
        "get_pending_orders",
        "get_product_velocity",
        "get_low_performing_products",
    )
    capabilities = (
        "get_sales_by_category",
        "get_sales_by_customer",
        "compare_sales_periods",
        "generate_sales_report",
    )
    required_permissions = ("sales.view",)

    def collect_context(
        self, task: AgentTask, runner: ToolRunner
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        used: list[str] = []
        failures: list[str] = []
        period_args = {"period": task.period} if task.period else {}

        context: dict[str, Any] = {
            "summary": self._call(
                runner, "get_sales_summary", period_args, used=used, failures=failures
            ),
            "top_products": self._call(
                runner, "get_top_products", {"limit": 10}, used=used, failures=failures
            ),
            "trends": self._call(
                runner, "get_sales_trends", {"months": 6}, used=used, failures=failures
            ),
            "pending": self._call(
                runner, "get_pending_orders", {}, used=used, failures=failures
            ),
            "velocity": self._call(
                runner, "get_product_velocity", {"window_days": 30}, used=used, failures=failures
            ),
            "low_performers": self._call(
                runner, "get_low_performing_products", {"limit": 5}, used=used, failures=failures
            ),
        }
        return context, used, failures

    def analyse(
        self, task: AgentTask, context: dict[str, Any], failures: list[str]
    ) -> tuple[list[Finding], list[Recommendation], dict[str, Any], list[str]]:
        period_label = task.period_label
        findings: list[Finding] = []
        metrics: dict[str, Any] = {}
        gaps: list[str] = []

        performance_findings, performance_metrics = analyse_sales_performance(
            summary=context.get("summary", {}),
            trends=context.get("trends", {}),
            period_label=period_label,
        )
        findings.extend(performance_findings)
        metrics.update(performance_metrics)

        products = context.get("top_products", {}).get("products", []) or []
        product_findings, product_metrics = analyse_products(
            products=products, period_label=period_label
        )
        findings.extend(product_findings)
        metrics.update(product_metrics)

        low_performers = context.get("low_performers", {}).get("products", []) or []
        if low_performers:
            metrics["low_performing_products"] = low_performers[:5]

        velocity_rows = context.get("velocity", {}).get("products", []) or []
        demand_findings, demand_metrics = analyse_demand(
            velocity_rows=velocity_rows, period_label=period_label
        )
        findings.extend(demand_findings)
        metrics.update(demand_metrics)

        if not products:
            gaps.append("completed sales in the selected period")
        if not velocity_rows:
            gaps.append("recent sales velocity (no completed sales in the last 30 days)")
        if failures:
            gaps.append(f"tools unavailable: {', '.join(sorted(set(failures)))}")

        recommendations = build_sales_recommendations(
            findings=findings, metrics=metrics, period_label=period_label
        )
        return findings, recommendations, metrics, gaps
