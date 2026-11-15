"""The ``run_collaboration`` tool: the orchestrator's entry point for Phase 5."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.registry.tool_inputs import PeriodName
from app.ai.schemas.tool_schema import ToolContext, ToolDefinition
from app.core.constants import AIRiskLevel
from app.core.exceptions import NotFoundError

SCENARIO_KEYS = (
    "SALES_GROWTH",
    "INVENTORY_FINANCE",
    "DECLINING_SALES",
    "BUSINESS_HEALTH",
    "SUPPLIER_CASHFLOW",
)


class CollaborationArgs(BaseModel):
    """Arguments for a multi-agent collaboration."""

    model_config = ConfigDict(extra="forbid")

    scenario: Literal[
        "SALES_GROWTH",
        "INVENTORY_FINANCE",
        "DECLINING_SALES",
        "BUSINESS_HEALTH",
        "SUPPLIER_CASHFLOW",
    ]
    objective: str | None = Field(default=None, max_length=400)
    period: PeriodName | None = None


def _run_collaboration(context: ToolContext, args: CollaborationArgs) -> dict:
    manager = getattr(context.services, "collaboration_manager", None)
    if manager is None:
        raise NotFoundError("The collaboration manager is not available")

    objective = args.objective or {
        "SALES_GROWTH": "Can I increase my sales by 20% next month?",
        "INVENTORY_FINANCE": "Which products should I reorder without affecting my cash flow?",
        "DECLINING_SALES": "Why are my sales decreasing?",
        "BUSINESS_HEALTH": "Analyze my complete business performance.",
        "SUPPLIER_CASHFLOW": "Can I purchase inventory from my suppliers this week?",
    }[args.scenario]

    view = manager.create_collaboration(
        objective,
        scenario=args.scenario,
        period=args.period,
        user_id=context.user_id,
        business_id=getattr(context.services, "business_id", None),
    )
    detail = manager.execute_collaboration(view.collaboration_id)
    decision = detail.decision

    if decision is None:
        return {
            "collaboration_id": view.collaboration_id,
            "status": detail.collaboration.status,
            "summary": (
                f"The collaboration finished with status {detail.collaboration.status} "
                f"and produced no decision: {detail.collaboration.error or 'no verified findings'}."
            ),
            "decision": None,
            "findings": [],
            "recommendations": [],
            "conflicts": [],
        }

    return {
        "collaboration_id": view.collaboration_id,
        "status": detail.collaboration.status,
        "decision_status": decision.status,
        "summary": decision.executive_summary,
        "confidence": decision.confidence,
        "participating_agents": decision.participating_agents,
        "findings": [
            finding.model_dump(mode="json") for finding in decision.consolidated_findings[:10]
        ],
        "risks": [finding.model_dump(mode="json") for finding in decision.identified_risks[:5]],
        "recommendations": [
            recommendation.model_dump(mode="json")
            for recommendation in decision.recommended_actions[:5]
        ],
        "conflicts": decision.conflicting_findings,
        "financial_impact": decision.financial_impact,
        "limitations": decision.limitations,
        "approval_requirements": decision.approval_requirements,
        "tasks": [
            {
                "task_key": task.task_key,
                "agent": task.assigned_agent,
                "status": task.status,
                "depends_on": task.dependencies,
            }
            for task in detail.tasks
        ],
        "messages": len(detail.messages),
    }


def build_collaboration_tools() -> list[ToolDefinition]:
    """Register the collaboration tool in the shared tool registry."""
    return [
        ToolDefinition(
            name="run_collaboration",
            description=(
                "Run a coordinated multi-agent collaboration (five agents, evidence "
                "validation, conflict resolution and a unified decision)"
            ),
            category="collaboration",
            input_model=CollaborationArgs,
            required_permission="agents.execute",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=300.0,
            handler=_run_collaboration,
        )
    ]
