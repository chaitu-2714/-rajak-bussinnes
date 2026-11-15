"""Agent coordination: registration, discovery and bounded delegation."""

from __future__ import annotations

from typing import Any

from app.ai.agents.base_agent import AgentError, BaseBusinessAgent, ToolRunner
from app.ai.schemas.agent_schema import AgentResult, AgentTask
from app.core.constants import AgentExecutionStatus
from app.core.exceptions import NotFoundError
from app.core.logging_config import get_logger

logger = get_logger("ai.coordinator")


class AgentCoordinator:
    """Holds the agent registry and runs tasks with a hard recursion limit."""

    def __init__(self, *, max_depth: int = 1) -> None:
        self._agents: dict[str, BaseBusinessAgent] = {}
        self._max_depth = max_depth

    # -- registry ----------------------------------------------------------
    def register(self, agent: BaseBusinessAgent) -> None:
        if agent.agent_id in self._agents:
            raise AgentError(f"Agent '{agent.agent_id}' is already registered")
        self._agents[agent.agent_id] = agent
        logger.debug("Registered agent %s", agent.agent_id)

    def get(self, agent_id: str) -> BaseBusinessAgent:
        agent = self._agents.get(agent_id)
        if agent is None:
            raise NotFoundError(f"Agent '{agent_id}' is not registered")
        return agent

    def has(self, agent_id: str) -> bool:
        return agent_id in self._agents

    def list_agents(self) -> list[BaseBusinessAgent]:
        return list(self._agents.values())

    def agent_ids(self) -> list[str]:
        return sorted(self._agents)

    def agents_for_intent(self, intent: str) -> list[BaseBusinessAgent]:
        return [agent for agent in self._agents.values() if agent.can_handle(intent)]

    # -- execution ---------------------------------------------------------
    def run(
        self,
        agent_id: str,
        task: AgentTask,
        *,
        runner: ToolRunner,
        depth: int = 0,
    ) -> AgentResult:
        if depth > self._max_depth:
            raise AgentError(
                "Agent delegation limit reached; agents cannot call each other recursively"
            )
        agent = self.get(agent_id)
        if task.agent_id != agent_id:
            task = task.model_copy(update={"agent_id": agent_id})
        return agent.execute(task, runner=runner)

    def run_many(
        self,
        agent_ids: list[str],
        task: AgentTask,
        *,
        runner: ToolRunner,
        depth: int = 0,
    ) -> list[AgentResult]:
        """Run several agents; a failing agent never stops the others."""
        results: list[AgentResult] = []
        for agent_id in agent_ids:
            try:
                # A batch task may name a task type that only some agents support;
                # each agent falls back to its own default in that case.
                agent = self.get(agent_id)
                agent_task = task
                if task.task_type not in agent.task_types:
                    agent_task = task.model_copy(
                        update={"task_type": getattr(agent, "default_task_type", "")}
                    )
                results.append(self.run(agent_id, agent_task, runner=runner, depth=depth))
            except Exception as exc:  # noqa: BLE001 - isolation is the point
                logger.warning("Agent %s failed: %s", agent_id, exc)
                results.append(
                    AgentResult(
                        agent_id=agent_id,
                        task_id=task.task_id,
                        status=AgentExecutionStatus.FAILED,
                        summary=f"{agent_id} could not complete this analysis.",
                        error=str(exc),
                        confidence=0.05,
                        confidence_basis="agent failed before producing evidence",
                    )
                )
        return results
