"""Multi-agent collaboration: planning, dependencies, messaging, conflicts, decisions."""

from app.ai.collaboration.conflict_resolution import ConflictDetector, ConflictResolver
from app.ai.collaboration.decision_engine import BusinessDecisionEngine
from app.ai.collaboration.dependency_manager import DependencyError, DependencyGraph
from app.ai.collaboration.evidence_validator import EvidenceValidator
from app.ai.collaboration.manager import CollaborationError, MultiAgentCollaborationManager
from app.ai.collaboration.message_bus import MessageBus, MessageBusError
from app.ai.collaboration.planner import (
    SCENARIOS,
    CollaborationPlanner,
    ScenarioSpec,
    SharedContextBuilder,
)

__all__ = [
    "BusinessDecisionEngine",
    "CollaborationError",
    "CollaborationPlanner",
    "ConflictDetector",
    "ConflictResolver",
    "DependencyError",
    "DependencyGraph",
    "EvidenceValidator",
    "MessageBus",
    "MessageBusError",
    "MultiAgentCollaborationManager",
    "SCENARIOS",
    "ScenarioSpec",
    "SharedContextBuilder",
]
