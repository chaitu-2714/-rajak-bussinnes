"""Unit tests: task planning and plan validation."""

from __future__ import annotations

import pytest

from app.ai.orchestrator.task_planner import PlanningError, TaskPlanner
from app.ai.registry.tool_catalogue import build_tool_registry
from app.ai.schemas.intent_schema import ClassifiedBy, Intent, IntentResult
from app.ai.schemas.workflow_schema import ExecutionPlan, PlanStep
from app.ai.validators.plan_validator import PlanValidator


def _result(intent: Intent, **entities) -> IntentResult:
    return IntentResult(
        intent=intent,
        confidence=0.9,
        classified_by=ClassifiedBy.RULES,
        entities=entities,
    )


@pytest.fixture()
def registry():
    return build_tool_registry()


def test_plan_for_revenue_routes_to_the_finance_agent(registry) -> None:
    """Phase 4: analysis intents are delegated to a specialist agent."""
    planner = TaskPlanner(registry)
    plan = planner.plan(_result(Intent.GET_REVENUE, period="this_month"))
    assert plan.intent is Intent.GET_REVENUE
    assert plan.tool_names == ["run_finance_agent"]
    step = plan.steps[0]
    assert step.arguments == {"task_type": "FINANCIAL_ANALYSIS", "period": "this_month"}
    assert step.required_permission == "agents.execute"
    assert step.risk_level == "READ_ONLY"
    assert plan.requires_approval is False


def test_plan_for_business_health_uses_the_bi_agent(registry) -> None:
    planner = TaskPlanner(registry)
    plan = planner.plan(_result(Intent.BUSINESS_HEALTH_REPORT))
    assert plan.tool_names == ["run_business_intelligence_agent"]
    assert plan.steps[0].arguments["task_type"] == "BUSINESS_HEALTH"


def test_plan_for_purchase_recommendation_is_multi_step(registry) -> None:
    planner = TaskPlanner(registry)
    plan = planner.plan(
        _result(Intent.CREATE_PURCHASE_RECOMMENDATION, product_name="Assam Tea", quantity=50)
    )
    assert plan.tool_names == [
        "get_product_stock",
        "get_sales_history",
        "get_cash_flow",
        "create_purchase_recommendation",
    ]
    final = plan.steps[-1]
    assert final.depends_on == ["step-1", "step-2", "step-3"]
    assert final.arguments["requested_quantity"] == 50


def test_action_plans_require_approval(registry) -> None:
    planner = TaskPlanner(registry)
    plan = planner.plan(_result(Intent.CREATE_EXPENSE, amount="500", expense_category="RENT"))
    assert plan.requires_approval is True
    assert plan.max_risk == "MEDIUM"


def test_unknown_intent_cannot_be_planned(registry) -> None:
    planner = TaskPlanner(registry)
    with pytest.raises(PlanningError):
        planner.plan(_result(Intent.UNKNOWN_INTENT))


def test_clarification_blocks_planning(registry) -> None:
    planner = TaskPlanner(registry)
    result = _result(Intent.GET_REVENUE)
    result.requires_clarification = True
    result.clarification_question = "Revenue or expenses?"
    with pytest.raises(PlanningError):
        planner.plan(result)


def test_excessive_steps_rejected(registry) -> None:
    """A plan longer than the configured limit is refused."""
    planner = TaskPlanner(registry, max_steps=0)
    with pytest.raises(PlanningError):
        planner.plan(_result(Intent.GET_REVENUE))


def test_valid_plan_passes_validation(registry) -> None:
    plan = TaskPlanner(registry).plan(_result(Intent.GET_REVENUE))
    result = PlanValidator(registry).validate(plan, permission_checker=lambda permission: True)
    assert result.is_valid
    assert result.errors == []


def test_unknown_tool_rejected(registry) -> None:
    plan = ExecutionPlan(
        plan_id="p1",
        intent=Intent.GET_REVENUE,
        steps=[
            PlanStep(
                step_id="step-1",
                step_number=1,
                tool_name="run_shell_command",
                arguments={"command": "rm -rf /"},
                required_permission="finance.view",
            )
        ],
    )
    result = PlanValidator(registry).validate(plan, permission_checker=lambda p: True)
    assert not result.is_valid
    assert any("Unknown tool" in error for error in result.errors)


def test_invalid_arguments_rejected(registry) -> None:
    plan = ExecutionPlan(
        plan_id="p2",
        intent=Intent.CREATE_EXPENSE,
        steps=[
            PlanStep(
                step_id="step-1",
                step_number=1,
                tool_name="prepare_expense",
                arguments={"description": "x", "amount": "-5"},
                required_permission="finance.create",
            )
        ],
    )
    result = PlanValidator(registry).validate(plan, permission_checker=lambda p: True)
    assert not result.is_valid
    assert any("Invalid arguments" in error for error in result.errors)


def test_missing_permission_rejected(registry) -> None:
    plan = TaskPlanner(registry).plan(_result(Intent.GET_REVENUE))
    result = PlanValidator(registry).validate(
        plan, permission_checker=lambda permission: permission == "dashboard.view"
    )
    assert not result.is_valid
    assert any("requires 'agents.execute'" in error for error in result.errors)


def test_circular_dependency_rejected(registry) -> None:
    plan = ExecutionPlan(
        plan_id="p3",
        intent=Intent.GET_REVENUE,
        steps=[
            PlanStep(
                step_id="step-1",
                step_number=1,
                tool_name="get_revenue",
                arguments={},
                required_permission="finance.view",
                depends_on=["step-2"],
            ),
            PlanStep(
                step_id="step-2",
                step_number=2,
                tool_name="calculate_profit",
                arguments={},
                required_permission="finance.view",
                depends_on=["step-1"],
            ),
        ],
    )
    result = PlanValidator(registry).validate(plan, permission_checker=lambda p: True)
    assert not result.is_valid
    assert any("Circular dependency" in error for error in result.errors)


def test_high_risk_tool_rejected(registry) -> None:
    definition = registry.get("prepare_expense")
    registry.register(
        type(definition)(
            name="delete_all_sales",
            description="Dangerous",
            category="actions",
            input_model=definition.input_model,
            required_permission="sales.cancel",
            risk_level="HIGH",
            handler=lambda context, args: {},
        )
    )
    plan = ExecutionPlan(
        plan_id="p4",
        intent=Intent.GET_REVENUE,
        steps=[
            PlanStep(
                step_id="step-1",
                step_number=1,
                tool_name="delete_all_sales",
                arguments={},
                required_permission="sales.cancel",
            )
        ],
    )
    result = PlanValidator(registry).validate(plan, permission_checker=lambda p: True)
    assert not result.is_valid
    assert any("high risk" in error.lower() for error in result.errors)


def test_duplicate_step_ids_rejected(registry) -> None:
    plan = ExecutionPlan(
        plan_id="p5",
        intent=Intent.GET_REVENUE,
        steps=[
            PlanStep(step_id="dup", step_number=1, tool_name="get_revenue", arguments={}),
            PlanStep(step_id="dup", step_number=2, tool_name="calculate_profit", arguments={}),
        ],
    )
    result = PlanValidator(registry).validate(plan, permission_checker=lambda p: True)
    assert not result.is_valid
    assert any("Duplicate step id" in error for error in result.errors)


def test_plan_serialises_for_persistence(registry) -> None:
    plan = TaskPlanner(registry).plan(_result(Intent.GET_CASH_FLOW))
    payload = plan.model_dump(mode="json")
    restored = ExecutionPlan.model_validate(payload)
    assert restored.tool_names == plan.tool_names
