"""AI agent security policy: what each agent may do, enforced at the tool boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import AITaskKind
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.security import AgentSecurityPolicy
from app.utils.date_utils import utcnow

logger = get_logger("security.agents")

DEFAULT_AGENTS: tuple[dict[str, Any], ...] = (
    {
        "agent_code": "finance_agent",
        "risk_classification": "HIGH",
        "requires_approval": False,
        "cloud_ai_eligible": False,
        "allowed_data_categories": ["FINANCIAL", "INTERNAL"],
    },
    {
        "agent_code": "sales_agent",
        "risk_classification": "MEDIUM",
        "cloud_ai_eligible": False,
        "allowed_data_categories": ["SALES", "CUSTOMER", "INTERNAL"],
    },
    {
        "agent_code": "customer_agent",
        "risk_classification": "MEDIUM",
        "cloud_ai_eligible": False,
        "allowed_data_categories": ["CUSTOMER", "INTERNAL"],
    },
    {
        "agent_code": "inventory_agent",
        "risk_classification": "MEDIUM",
        "cloud_ai_eligible": False,
        "allowed_data_categories": ["INVENTORY", "SUPPLIER", "INTERNAL"],
    },
    {
        "agent_code": "business_intelligence_agent",
        "risk_classification": "MEDIUM",
        "cloud_ai_eligible": False,
        "allowed_data_categories": ["FINANCIAL", "SALES", "CUSTOMER", "INVENTORY", "INTERNAL"],
    },
)

ADMINISTRATIVE_PERMISSIONS = frozenset(
    {
        "users.create", "users.update", "users.deactivate",
        "roles.create", "roles.update", "roles.delete",
        "settings.update", "agents.configure", "security.manage",
        "backup.restore", "audit.delete",
    }
)


@dataclass(frozen=True)
class AgentDecision:
    allowed: bool
    reason: str


class AIAgentSecurityPolicyService:
    """Enforces per-agent tool, data, scope and duration limits."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- defaults ----------------------------------------------------------
    def seed_defaults(self) -> int:
        created = 0
        with self._session_factory() as db:
            existing = {row.agent_code for row in db.scalars(select(AgentSecurityPolicy)).all()}
            for spec in DEFAULT_AGENTS:
                if spec["agent_code"] in existing:
                    continue
                db.add(
                    AgentSecurityPolicy(
                        agent_code=spec["agent_code"],
                        is_enabled=True,
                        allowed_tools=None,  # None = any tool the user may use
                        allowed_data_categories=spec.get("allowed_data_categories"),
                        business_scope="CURRENT",
                        max_execution_depth=3,
                        max_task_count=12,
                        max_duration_seconds=300,
                        cloud_ai_eligible=spec.get("cloud_ai_eligible", False),
                        requires_approval=spec.get("requires_approval", False),
                        risk_classification=spec.get("risk_classification", "LOW"),
                    )
                )
                created += 1
            db.commit()
        return created

    # -- reads and writes --------------------------------------------------
    def list_policies(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(select(AgentSecurityPolicy).order_by(AgentSecurityPolicy.agent_code)).all()
            return [self._view(row) for row in rows]

    def get_policy(self, agent_code: str) -> dict[str, Any] | None:
        with self._session_factory() as db:
            row = db.scalars(
                select(AgentSecurityPolicy).where(AgentSecurityPolicy.agent_code == agent_code)
            ).first()
            return self._view(row) if row else None

    def _view(self, row: AgentSecurityPolicy) -> dict[str, Any]:
        return {
            "agent_code": row.agent_code,
            "is_enabled": row.is_enabled,
            "allowed_tools": list(row.allowed_tools or []),
            "allowed_data_categories": list(row.allowed_data_categories or []),
            "business_scope": row.business_scope,
            "max_execution_depth": row.max_execution_depth,
            "max_task_count": row.max_task_count,
            "max_duration_seconds": row.max_duration_seconds,
            "cloud_ai_eligible": row.cloud_ai_eligible,
            "requires_approval": row.requires_approval,
            "risk_classification": row.risk_classification,
            "updated_at": row.updated_at,
        }

    def update_policy(self, agent_code: str, *, changes: dict[str, Any], actor_id: int | None) -> dict:
        allowed_fields = {
            "is_enabled", "allowed_tools", "allowed_data_categories", "max_execution_depth",
            "max_task_count", "max_duration_seconds", "cloud_ai_eligible",
            "requires_approval", "risk_classification",
        }
        unknown = set(changes) - allowed_fields
        if unknown:
            raise ValidationError(f"Unknown policy fields: {', '.join(sorted(unknown))}")
        with self._session_factory() as db:
            row = db.scalars(
                select(AgentSecurityPolicy).where(AgentSecurityPolicy.agent_code == agent_code)
            ).first()
            if row is None:
                raise NotFoundError(f"No security policy exists for '{agent_code}'")
            for key, value in changes.items():
                setattr(row, key, value)
            row.updated_by = actor_id
            row.updated_at = utcnow()
            db.commit()
            return self._view(row)

    # -- enforcement -------------------------------------------------------
    def check_agent_enabled(self, agent_code: str) -> AgentDecision:
        policy = self.get_policy(agent_code)
        if policy is None:
            return AgentDecision(False, f"No security policy exists for '{agent_code}'")
        if not policy["is_enabled"]:
            return AgentDecision(False, f"Agent '{agent_code}' is disabled by policy")
        return AgentDecision(True, "Agent enabled")

    def check_tool(self, agent_code: str, tool_name: str) -> AgentDecision:
        enabled = self.check_agent_enabled(agent_code)
        if not enabled.allowed:
            return enabled
        policy = self.get_policy(agent_code) or {}
        allowed = policy.get("allowed_tools") or []
        if allowed and tool_name not in allowed:
            return AgentDecision(
                False, f"'{tool_name}' is not in the allowed tool list for '{agent_code}'"
            )
        if tool_name.startswith(("run_sql", "execute_", "eval_")):
            return AgentDecision(False, f"'{tool_name}' is not an agent-executable tool")
        return AgentDecision(True, "Tool permitted")

    def check_permission(self, agent_code: str, permission: str) -> AgentDecision:
        if permission in ADMINISTRATIVE_PERMISSIONS:
            return AgentDecision(
                False, f"An agent may never use the administrative permission '{permission}'"
            )
        return AgentDecision(True, "Permission permitted")

    def check_data_category(self, agent_code: str, category: str) -> AgentDecision:
        policy = self.get_policy(agent_code)
        if policy is None:
            return AgentDecision(False, "No policy")
        allowed = policy.get("allowed_data_categories") or []
        if allowed and category not in allowed:
            return AgentDecision(
                False, f"'{agent_code}' may not access {category} data"
            )
        return AgentDecision(True, "Data category permitted")

    def check_cloud_eligibility(self, agent_code: str) -> AgentDecision:
        policy = self.get_policy(agent_code)
        if policy is None:
            return AgentDecision(False, "No policy")
        if not policy.get("cloud_ai_eligible"):
            return AgentDecision(
                False, f"'{agent_code}' is not eligible for cloud AI; keep processing local"
            )
        return AgentDecision(True, "Cloud eligible")

    def check_execution_limits(
        self, agent_code: str, *, depth: int = 0, task_count: int = 0, elapsed_seconds: float = 0.0
    ) -> AgentDecision:
        policy = self.get_policy(agent_code)
        if policy is None:
            return AgentDecision(False, "No policy")
        if depth > policy["max_execution_depth"]:
            return AgentDecision(
                False, f"Execution depth {depth} exceeds the limit of {policy['max_execution_depth']}"
            )
        if task_count > policy["max_task_count"]:
            return AgentDecision(
                False, f"Task count {task_count} exceeds the limit of {policy['max_task_count']}"
            )
        if elapsed_seconds > policy["max_duration_seconds"]:
            return AgentDecision(
                False,
                f"Execution time exceeds the {policy['max_duration_seconds']}s limit",
            )
        return AgentDecision(True, "Within execution limits")

    def assert_tool_allowed(self, agent_code: str, tool_name: str, *, permission: str | None) -> None:
        """Raise if an agent tool call must not proceed."""
        for decision in (
            self.check_tool(agent_code, tool_name),
            self.check_permission(agent_code, permission) if permission else AgentDecision(True, ""),
        ):
            if not decision.allowed:
                raise AuthorizationError(decision.reason)

    def cloud_task_allowed(self, agent_code: str, task: str) -> bool:
        if task in AITaskKind.LOCAL_ONLY:
            return False
        return self.check_cloud_eligibility(agent_code).allowed
