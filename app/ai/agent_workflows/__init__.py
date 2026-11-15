"""Agent task definitions.

Agents run inside the Phase 3 LangGraph workflow: the orchestrator plans one
``run_*_agent`` tool per intent, and the agent performs its own analysis
pipeline. These modules hold the task-type constants and default parameters so
the planner and the UI agree on one vocabulary.
"""

from app.ai.agent_workflows.task_catalogue import AGENT_TASKS, AgentTaskSpec

__all__ = ["AGENT_TASKS", "AgentTaskSpec"]
