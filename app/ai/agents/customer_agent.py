"""Customer Agent: segmentation, inactivity, value and follow-up priority."""

from __future__ import annotations

from typing import Any

from app.ai.agent_tools.customer_tools import (
    SegmentationRules,
    analyse_customer_value,
    find_inactive_customers,
    prioritise_followups,
    segment_customers,
)
from app.ai.agents.base_agent import BaseBusinessAgent, ToolRunner
from app.ai.schemas.agent_schema import AgentTask, Finding, Recommendation
from app.ai.schemas.intent_schema import Intent

TASK_CUSTOMER_ANALYSIS = "CUSTOMER_ANALYSIS"


class CustomerAgent(BaseBusinessAgent):
    """Analyses the customer base, inactivity, value and follow-up priorities."""

    agent_id = "customer_agent"
    name = "Customer Agent"
    description = (
        "Customer segmentation, inactive-customer detection, historical value and "
        "follow-up prioritisation"
    )
    intents = (
        Intent.CUSTOMER_ANALYSIS,
        Intent.GET_INACTIVE_CUSTOMERS,
    )
    task_types = (TASK_CUSTOMER_ANALYSIS,)
    default_task_type = TASK_CUSTOMER_ANALYSIS
    data_tools = (
        "get_customer_portfolio",
        "get_customer_summary",
        "get_inactive_customers",
    )
    capabilities = (
        "segment_customers",
        "calculate_customer_value",
        "get_customer_last_purchase",
        "schedule_customer_followup",
        "generate_customer_report",
    )
    required_permissions = ("customers.view",)

    def __init__(self, *, rules: SegmentationRules | None = None) -> None:
        super().__init__()
        self._rules = rules or SegmentationRules()

    def collect_context(
        self, task: AgentTask, runner: ToolRunner
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        used: list[str] = []
        failures: list[str] = []
        days = int(task.parameters.get("inactive_days", self._rules.inactive_days))

        context: dict[str, Any] = {
            "portfolio": self._call(
                runner, "get_customer_portfolio", {}, used=used, failures=failures
            ),
            "summary": self._call(
                runner, "get_customer_summary", {}, used=used, failures=failures
            ),
            "inactive": self._call(
                runner,
                "get_inactive_customers",
                {"days": days, "limit": 20},
                used=used,
                failures=failures,
            ),
            "inactive_days": days,
        }
        return context, used, failures

    def analyse(
        self, task: AgentTask, context: dict[str, Any], failures: list[str]
    ) -> tuple[list[Finding], list[Recommendation], dict[str, Any], list[str]]:
        period_label = task.period_label
        findings: list[Finding] = []
        metrics: dict[str, Any] = {}
        gaps: list[str] = []

        customers = context.get("portfolio", {}).get("customers", []) or []
        if not customers:
            gaps.append("customer records (the customer list is empty)")

        segment_findings, segment_metrics = segment_customers(
            customers=customers, rules=self._rules, period_label=period_label
        )
        findings.extend(segment_findings)
        metrics.update(segment_metrics)

        days = int(context.get("inactive_days", self._rules.inactive_days))
        inactive_findings, inactive_rows = find_inactive_customers(
            customers=customers, days=days, period_label=period_label
        )
        findings.extend(inactive_findings)
        metrics["inactive_customers"] = len(inactive_rows)
        metrics["inactive_threshold_days"] = days
        if inactive_rows:
            metrics["inactive_sample"] = inactive_rows[:5]

        value_findings, value_metrics = analyse_customer_value(
            customers=customers, period_label=period_label
        )
        findings.extend(value_findings)
        metrics.update(value_metrics)

        recommendations, ranked = prioritise_followups(
            inactive=inactive_rows, rules=self._rules, limit=5
        )
        if ranked:
            metrics["followup_priorities"] = ranked
        if failures:
            gaps.append(f"tools unavailable: {', '.join(sorted(set(failures)))}")

        return findings, recommendations, metrics, gaps
