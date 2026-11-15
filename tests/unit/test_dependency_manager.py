"""Unit tests: collaboration dependency graph."""

from __future__ import annotations

import pytest

from app.ai.collaboration.dependency_manager import DependencyError, DependencyGraph
from app.ai.collaboration.planner import SCENARIOS, CollaborationPlanner
from app.ai.schemas.collaboration_schema import CollaborationTaskSpec


def _task(key: str, depends_on=()) -> CollaborationTaskSpec:
    return CollaborationTaskSpec(
        task_key=key,
        assigned_agent="sales_agent",
        task_type="SALES_ANALYSIS",
        objective=f"task {key}",
        depends_on=list(depends_on),
    )


def test_valid_graph_has_no_errors() -> None:
    graph = DependencyGraph([_task("ta"), _task("tb", ("ta",)), _task("tc", ("tb",))])
    assert graph.validate() == []


def test_unknown_dependency_is_rejected() -> None:
    graph = DependencyGraph([_task("ta", ("missing",))])
    errors = graph.validate()
    assert any("unknown task" in error for error in errors)


def test_self_dependency_is_rejected() -> None:
    graph = DependencyGraph([_task("ta", ("ta",))])
    assert any("depends on itself" in error for error in graph.validate())


def test_circular_dependency_is_rejected() -> None:
    graph = DependencyGraph([_task("ta", ("tc",)), _task("tb", ("ta",)), _task("tc", ("tb",))])
    errors = graph.validate()
    assert any("circular" in error.lower() for error in errors)
    with pytest.raises(DependencyError):
        graph.topological_order()


def test_duplicate_task_keys_rejected() -> None:
    graph = DependencyGraph([_task("ta"), _task("ta")])
    assert any("duplicate" in error for error in graph.validate())


def test_topological_order_respects_dependencies() -> None:
    graph = DependencyGraph(
        [_task("ta"), _task("tb", ("ta",)), _task("tc", ("ta",)), _task("td", ("tb", "tc"))]
    )
    order = graph.topological_order()
    assert order.index("ta") < order.index("tb")
    assert order.index("ta") < order.index("tc")
    assert order.index("td") > order.index("tb")
    assert order.index("td") > order.index("tc")


def test_waves_group_independent_tasks() -> None:
    graph = DependencyGraph(
        [_task("ta"), _task("tb"), _task("tc", ("ta", "tb")), _task("td", ("tc",))]
    )
    waves = graph.waves()
    assert sorted(waves[0]) == ["ta", "tb"]
    assert waves[1] == ["tc"]
    assert waves[2] == ["td"]


def test_ready_tasks_and_failure_propagation() -> None:
    graph = DependencyGraph([_task("ta"), _task("tb", ("ta",)), _task("tc", ("tb",)), _task("td")])
    assert sorted(graph.ready_tasks(set())) == ["ta", "td"]
    assert graph.propagate_failure("ta") == ["tb", "tc"]
    assert graph.blocked_after({"ta"}) == {"tb", "tc"}
    assert graph.dependents_of("ta") == ["tb"]


def test_scenario_plans_are_valid_and_bounded() -> None:
    planner = CollaborationPlanner(max_tasks=12)
    for key in SCENARIOS:
        tasks = planner.generate_plan(key)
        assert tasks, key
        assert planner.validate_plan(tasks) == []
        graph = DependencyGraph(tasks)
        assert graph.validate() == []
        # every scenario ends with a synthesis task that depends on the others
        last = tasks[-1]
        assert last.task_key == "synthesis"
        assert last.depends_on


def test_plan_limit_is_enforced() -> None:
    planner = CollaborationPlanner(max_tasks=2)
    with pytest.raises(ValueError):
        planner.generate_plan("BUSINESS_HEALTH")


def test_scenario_detection_from_objective() -> None:
    planner = CollaborationPlanner()
    assert planner.detect_scenario("Can I increase my sales by 20% next month?").key == "SALES_GROWTH"
    assert planner.detect_scenario("Why are my sales decreasing?").key == "DECLINING_SALES"
    assert planner.detect_scenario("Analyze my complete business performance.").key == "BUSINESS_HEALTH"
    assert planner.detect_scenario("Can I purchase inventory from my suppliers this week?").key == "SUPPLIER_CASHFLOW"
    assert planner.detect_scenario("Which products should I reorder without affecting my cash flow?").key == "INVENTORY_FINANCE"
    assert planner.detect_scenario("sing me a song") is None


def test_scenario_agents_are_the_phase4_agents() -> None:
    planner = CollaborationPlanner()
    for key in SCENARIOS:
        agents = planner.identify_required_agents(key)
        assert "business_intelligence_agent" in agents
        assert set(agents) <= {
            "finance_agent",
            "sales_agent",
            "customer_agent",
            "inventory_agent",
            "business_intelligence_agent",
        }
