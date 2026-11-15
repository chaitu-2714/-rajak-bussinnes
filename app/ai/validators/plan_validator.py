"""Plan validation: the gate between planning and execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from pydantic import ValidationError as PydanticValidationError

from app.ai.registry.tool_registry import ToolRegistry
from app.ai.schemas.workflow_schema import ExecutionPlan
from app.core.constants import AIRiskLevel
from app.core.logging_config import get_logger

logger = get_logger("ai.plan_validator")

PermissionChecker = Callable[[str], bool]


@dataclass
class PlanValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    requires_approval: bool = False


class PlanValidator:
    """Rejects plans that are unsafe, unauthorised or malformed."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_steps: int = 8,
        allow_high_risk: bool = False,
    ) -> None:
        self._registry = registry
        self._max_steps = max_steps
        self._allow_high_risk = allow_high_risk

    def validate(
        self, plan: ExecutionPlan, *, permission_checker: PermissionChecker
    ) -> PlanValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        requires_approval = plan.requires_approval

        if not plan.steps:
            errors.append("The plan contains no steps.")

        if len(plan.steps) > self._max_steps:
            errors.append(
                f"The plan has {len(plan.steps)} steps; the limit is {self._max_steps}."
            )

        seen_ids: set[str] = set()
        seen_numbers: set[int] = set()
        for step in plan.steps:
            if step.step_id in seen_ids:
                errors.append(f"Duplicate step id '{step.step_id}'.")
            seen_ids.add(step.step_id)

            if step.step_number in seen_numbers:
                errors.append(f"Duplicate step number {step.step_number}.")
            seen_numbers.add(step.step_number)

            if not self._registry.has(step.tool_name):
                errors.append(f"Unknown tool '{step.tool_name}'.")
                continue
            definition = self._registry.get(step.tool_name)
            if not definition.enabled:
                errors.append(f"Tool '{step.tool_name}' is disabled.")
            if definition.risk_level == AIRiskLevel.HIGH and not self._allow_high_risk:
                errors.append(
                    f"Tool '{step.tool_name}' is high risk and is not permitted in Phase 3."
                )
            if definition.requires_approval:
                requires_approval = True

            try:
                definition.input_model.model_validate(step.arguments)
            except PydanticValidationError as exc:
                first = exc.errors()[0]
                location = ".".join(str(part) for part in first["loc"]) or "arguments"
                errors.append(
                    f"Invalid arguments for '{step.tool_name}' at {location}: "
                    f"{str(first['msg']).replace('Value error, ', '')}"
                )

            permission = step.required_permission or definition.required_permission
            if permission and not permission_checker(permission):
                errors.append(
                    f"Step {step.step_number} requires '{permission}', which you do not have."
                )

            for dependency in step.depends_on:
                if dependency not in seen_ids:
                    errors.append(
                        f"Step '{step.step_id}' depends on '{dependency}', which is not an "
                        "earlier step."
                    )

        cycle = self._find_cycle(plan)
        if cycle:
            errors.append(f"Circular dependency detected: {' → '.join(cycle)}.")

        if requires_approval:
            warnings.append("This plan changes business data and will wait for approval.")

        return PlanValidationResult(
            is_valid=not errors,
            errors=errors,
            warnings=warnings,
            requires_approval=requires_approval,
        )

    @staticmethod
    def _find_cycle(plan: ExecutionPlan) -> list[str] | None:
        """Depth-first search for a dependency cycle."""
        graph = {step.step_id: list(step.depends_on) for step in plan.steps}
        visiting: list[str] = []
        visited: set[str] = set()

        def walk(node: str) -> list[str] | None:
            if node in visiting:
                return visiting[visiting.index(node) :] + [node]
            if node in visited:
                return None
            visiting.append(node)
            for dependency in graph.get(node, []):
                found = walk(dependency)
                if found:
                    return found
            visiting.pop()
            visited.add(node)
            return None

        for node in graph:
            cycle = walk(node)
            if cycle:
                return cycle
        return None
