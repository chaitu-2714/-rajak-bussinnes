"""Unit tests: the shared agent framework contract."""

from __future__ import annotations

import pytest

from app.ai.agents.base_agent import AgentError, BaseBusinessAgent
from app.ai.schemas.agent_schema import AgentResult, AgentTask, Evidence, Finding, Recommendation
from app.ai.schemas.intent_schema import Intent
from app.ai.schemas.tool_schema import ToolResult


class StubAgent(BaseBusinessAgent):
    """Minimal agent used to exercise the framework."""

    agent_id = "stub_agent"
    name = "Stub Agent"
    description = "Framework test agent"
    intents = (Intent.GET_REVENUE,)
    task_types = ("TEST_TASK",)
    default_task_type = "TEST_TASK"
    data_tools = ("fake_tool",)
    capabilities = ("fake_capability",)
    required_permissions = ("finance.view",)

    def __init__(self, *, fail_tool: bool = False, no_findings: bool = False) -> None:
        super().__init__()
        self.fail_tool = fail_tool
        self.no_findings = no_findings

    def collect_context(self, task, runner):
        used, failures = [], []
        self._call(
            runner, "fake_tool", {"value": 1}, used=used, failures=failures, default={}
        )
        return {"value": 42}, used, failures

    def analyse(self, task, context, failures):
        if self.no_findings:
            return [], [], {"value": context["value"]}, []
        finding = Finding(
            finding_id="stub-1",
            finding_type="STUB",
            description="Stub finding from the framework test",
            severity="MEDIUM",
            evidence=[Evidence(source="fake_tool", metric="value", value="42")],
        )
        recommendation = Recommendation(
            recommendation_id="stub-rec-1",
            recommendation="Do the stub thing",
            reason="The stub finding says so",
            priority="MEDIUM",
        )
        gaps = [f"tools unavailable: {', '.join(failures)}"] if failures else []
        return [finding], [recommendation], {"value": context["value"]}, gaps


def _runner(result: ToolResult):
    def run(tool_name: str, arguments: dict) -> ToolResult:
        return result

    return run


def _task(**overrides) -> AgentTask:
    data = {
        "task_id": "task-1",
        "agent_id": "stub_agent",
        "task_type": "TEST_TASK",
        "period": "this_month",
    }
    data.update(overrides)
    return AgentTask(**data)


def test_agent_info_is_complete() -> None:
    info = StubAgent().get_agent_info()
    assert info.agent_code == "stub_agent"
    assert info.intents == ["GET_REVENUE"]
    assert info.data_tools == ["fake_tool"]
    assert info.required_permissions == ["finance.view"]


def test_can_handle() -> None:
    agent = StubAgent()
    assert agent.can_handle(Intent.GET_REVENUE) is True
    assert agent.can_handle(Intent.GET_EXPENSES) is False
    assert agent.can_handle("GET_REVENUE") is True


def test_validate_input_rejects_wrong_agent_and_task() -> None:
    agent = StubAgent()
    with pytest.raises(AgentError):
        agent.validate_input(_task(agent_id="other_agent"))
    with pytest.raises(AgentError):
        agent.validate_input(_task(task_type="UNSUPPORTED"))


def test_successful_execution_produces_the_common_schema() -> None:
    result = StubAgent().execute(
        _task(),
        runner=_runner(ToolResult(tool_name="fake_tool", success=True, data={"ok": True})),
    )
    assert isinstance(result, AgentResult)
    assert result.status == "COMPLETED"
    assert result.summary
    assert result.findings[0].agent_id == "stub_agent"
    assert result.recommendations[0].agent_id == "stub_agent"
    assert result.confidence > 0
    assert result.confidence_basis
    assert result.tools_used == ["fake_tool"]
    assert result.execution_ms >= 0


def test_failed_tool_becomes_a_data_gap_not_a_crash() -> None:
    result = StubAgent().execute(
        _task(),
        runner=_runner(
            ToolResult(tool_name="fake_tool", success=False, error="service down")
        ),
    )
    assert result.status == "COMPLETED"
    assert any("tools unavailable" in gap for gap in result.data_gaps)
    assert result.confidence < 0.9


def test_no_findings_is_a_valid_result() -> None:
    result = StubAgent(no_findings=True).execute(
        _task(), runner=_runner(ToolResult(tool_name="fake_tool", success=True, data={}))
    )
    assert result.findings == []
    assert "no findings" in result.summary.lower()


def test_output_validation_requires_evidence() -> None:
    agent = StubAgent()
    bad = AgentResult(
        agent_id="stub_agent",
        task_id="t",
        findings=[
            Finding(
                finding_id="x",
                finding_type="X",
                description="no evidence",
                severity="INFO",
                evidence=[Evidence(source="s", metric="m", value="1")],
            )
        ],
    )
    bad.findings[0].evidence = []  # bypass the schema to simulate a broken agent
    with pytest.raises(AgentError):
        agent.validate_output(bad)


def test_output_validation_rejects_wrong_agent_id() -> None:
    with pytest.raises(AgentError):
        StubAgent().validate_output(AgentResult(agent_id="someone_else", task_id="t"))


def test_findings_and_recommendations_are_capped() -> None:
    agent = StubAgent()
    many = AgentResult(
        agent_id="stub_agent",
        task_id="t",
        findings=[
            Finding(
                finding_id=f"f{i}",
                finding_type="X",
                description="cap test",
                severity="INFO",
                evidence=[Evidence(source="s", metric="m", value="1")],
            )
            for i in range(40)
        ],
        recommendations=[
            Recommendation(
                recommendation_id=f"r{i}",
                recommendation="cap",
                reason="because the cap test says so",
            )
            for i in range(30)
        ],
    )
    validated = agent.validate_output(many)
    assert len(validated.findings) == 20
    assert len(validated.recommendations) == 10


def test_all_five_agents_declare_permissions_and_tools() -> None:
    from app.ai.agents.business_intelligence_agent import BusinessIntelligenceAgent
    from app.ai.agents.customer_agent import CustomerAgent
    from app.ai.agents.finance_agent import FinanceAgent
    from app.ai.agents.inventory_agent import InventoryAgent
    from app.ai.agents.sales_agent import SalesAgent

    for agent in (
        FinanceAgent(),
        SalesAgent(),
        CustomerAgent(),
        InventoryAgent(),
        BusinessIntelligenceAgent(),
    ):
        info = agent.get_agent_info()
        assert info.agent_code
        assert info.required_permissions
        assert info.data_tools
        assert info.capabilities
        assert info.intents
        assert agent.default_task_type in agent.task_types
