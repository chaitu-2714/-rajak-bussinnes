"""Finance Agent: financial performance, anomalies, cash and recommendations."""

from __future__ import annotations

from typing import Any

from app.ai.agent_tools.finance_tools import (
    AnomalyThresholds,
    analyse_cash_flow,
    analyse_expenses,
    analyse_profit,
    analyse_revenue,
    build_finance_recommendations,
    detect_expense_anomalies,
)
from app.ai.agents.base_agent import BaseBusinessAgent, ToolRunner
from app.ai.schemas.agent_schema import AgentTask, Finding, Recommendation
from app.ai.schemas.intent_schema import Intent

TASK_FINANCIAL_ANALYSIS = "FINANCIAL_ANALYSIS"
TASK_EXPENSE_ANOMALIES = "EXPENSE_ANOMALIES"


class FinanceAgent(BaseBusinessAgent):
    """Analyses revenue, expenses, profit, cash flow and expense outliers."""

    agent_id = "finance_agent"
    name = "Finance Agent"
    description = (
        "Revenue, expense, profit and cash-flow analysis with statistical expense "
        "anomaly detection"
    )
    intents = (
        Intent.GET_REVENUE,
        Intent.GET_EXPENSES,
        Intent.CALCULATE_PROFIT,
        Intent.GET_CASH_FLOW,
        Intent.ANALYZE_EXPENSE_ANOMALIES,
    )
    task_types = (TASK_FINANCIAL_ANALYSIS, TASK_EXPENSE_ANOMALIES)
    default_task_type = TASK_FINANCIAL_ANALYSIS
    data_tools = (
        "get_revenue",
        "get_expenses",
        "calculate_profit",
        "get_cash_flow",
        "get_outstanding_payments",
        "get_expense_breakdown",
        "get_monthly_financial_summary",
    )
    capabilities = (
        "detect_expense_anomalies",
        "get_payment_history",
        "get_monthly_financial_summary",
        "generate_financial_report",
    )
    required_permissions = ("finance.view",)

    def __init__(
        self,
        *,
        thresholds: AnomalyThresholds | None = None,
        currency: str = "INR",
    ) -> None:
        super().__init__()
        self._thresholds = thresholds or AnomalyThresholds()
        self._currency = currency

    # -- context -----------------------------------------------------------
    def collect_context(
        self, task: AgentTask, runner: ToolRunner
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        used: list[str] = []
        failures: list[str] = []
        period_args = {"period": task.period} if task.period else {}

        context: dict[str, Any] = {
            "revenue": self._call(
                runner, "get_revenue", period_args, used=used, failures=failures
            ),
            "expenses": self._call(
                runner, "get_expenses", period_args, used=used, failures=failures
            ),
            "profit": self._call(
                runner, "calculate_profit", period_args, used=used, failures=failures
            ),
            "cash": self._call(
                runner, "get_cash_flow", period_args, used=used, failures=failures
            ),
            "outstanding": self._call(
                runner, "get_outstanding_payments", {}, used=used, failures=failures
            ),
            "breakdown": self._call(
                runner, "get_expense_breakdown", period_args, used=used, failures=failures
            ),
            "monthly": self._call(
                runner, "get_monthly_financial_summary", {"months": 6}, used=used, failures=failures
            ),
        }

        # Comparison period: only when the task names a month.
        if task.period in ("this_month", "last_month", "this_year"):
            previous = "last_month" if task.period == "this_month" else None
            if previous:
                context["previous_revenue"] = self._call(
                    runner,
                    "get_revenue",
                    {"period": previous},
                    used=used,
                    failures=failures,
                )
        return context, used, failures

    # -- analysis ----------------------------------------------------------
    def analyse(
        self, task: AgentTask, context: dict[str, Any], failures: list[str]
    ) -> tuple[list[Finding], list[Recommendation], dict[str, Any], list[str]]:
        period_label = task.period_label
        findings: list[Finding] = []
        metrics: dict[str, Any] = {}
        gaps: list[str] = []

        revenue_findings, revenue_metrics = analyse_revenue(
            current=context.get("revenue", {}),
            previous=context.get("previous_revenue"),
            period_label=period_label,
            currency=self._currency,
        )
        findings.extend(revenue_findings)
        metrics.update(revenue_metrics)

        expense_findings, expense_metrics = analyse_expenses(
            expenses=context.get("expenses", {}), period_label=period_label
        )
        findings.extend(expense_findings)
        metrics.update(expense_metrics)

        profit_findings, profit_metrics = analyse_profit(
            profit=context.get("profit", {}),
            revenue=context.get("revenue", {}),
            period_label=period_label,
        )
        findings.extend(profit_findings)
        metrics.update(profit_metrics)

        cash_findings, cash_metrics = analyse_cash_flow(
            cash=context.get("cash", {}),
            outstanding=context.get("outstanding", {}),
            period_label=period_label,
        )
        findings.extend(cash_findings)
        metrics.update(cash_metrics)

        monthly = context.get("monthly", {}).get("monthly", []) or []
        if monthly:
            metrics["monthly_summary"] = monthly[-6:]
        else:
            gaps.append("monthly financial history")

        raw_expenses = context.get("breakdown", {}).get("expenses", []) or []
        anomaly_findings, anomalies = detect_expense_anomalies(
            raw_expenses, thresholds=self._thresholds
        )
        if task.task_type == TASK_EXPENSE_ANOMALIES or anomalies:
            findings.extend(anomaly_findings)
        metrics["expense_anomalies"] = anomalies
        if len(raw_expenses) < self._thresholds.minimum_history:
            gaps.append(
                f"expense history (fewer than {self._thresholds.minimum_history} records, "
                "so anomaly detection is limited)"
            )

        if failures:
            gaps.append(f"tools unavailable: {', '.join(sorted(set(failures)))}")

        recommendations = build_finance_recommendations(
            findings=findings, metrics=metrics, period_label=period_label
        )
        return findings, recommendations, metrics, gaps
