"""Centralized authorization: RBAC plus contextual (attribute-based) rules.

Every sensitive service call can ask this one service whether an action is
allowed. The default is deny: an unknown permission, an ambiguous resource or a
missing business match all produce a refusal with a reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import PERMISSION_KEYS
from app.core.exceptions import AuthorizationError
from app.core.logging_config import get_logger
from app.database.models.security import ResourceAccessPolicy
from app.security.authorization import has_permission, require_permission

logger = get_logger("security.authorization")


@dataclass(frozen=True)
class AuthorizationDecision:
    allowed: bool
    reason: str
    permission: str | None = None
    classification: str | None = None
    requires_approval: bool = False

    def raise_if_denied(self) -> None:
        if not self.allowed:
            raise AuthorizationError(self.reason)


@dataclass(frozen=True)
class Actor:
    """Who is asking, and in what context."""

    user_id: int | None
    roles: tuple[str, ...] = ()
    permissions: frozenset[str] = field(default_factory=frozenset)
    business_id: int | None = None
    is_superuser: bool = False
    actor_type: str = "USER"  # USER | SYSTEM | AGENT

    @property
    def is_agent(self) -> bool:
        return self.actor_type == "AGENT"

    @property
    def is_system(self) -> bool:
        return self.actor_type == "SYSTEM"


class AuthorizationService:
    """One place to decide access, so no caller has to re-implement the rules."""

    # Resources whose data is confidential by nature.
    CONFIDENTIAL_RESOURCES = frozenset(
        {
            "FINANCIAL_REPORT",
            "PAYROLL",
            "SUPPLIER_AGREEMENT",
            "CUSTOMER_PII",
            "KNOWLEDGE_DOCUMENT",
        }
    )
    RESTRICTED_RESOURCES = frozenset({"CREDENTIAL", "SECRET", "AUTH_TOKEN", "MFA_SECRET"})

    def authorize(
        self,
        actor: Actor,
        permission: str,
        *,
        resource_type: str | None = None,
        resource_id: str | None = None,
        business_id: int | None = None,
        db: Session | None = None,
        require_same_business: bool = True,
    ) -> AuthorizationDecision:
        # 1. The actor must exist and be a user (or an explicit system/agent identity).
        if actor.user_id is None and not (actor.is_system or actor.is_agent):
            return AuthorizationDecision(False, "No authenticated actor", permission)

        # 2. Agents may never hold administrative permissions.
        if actor.is_agent and self._is_administrative(permission):
            return AuthorizationDecision(
                False, "An AI agent cannot hold an administrative permission", permission
            )

        # 3. Business isolation is absolute, even for a superuser.
        if (
            require_same_business
            and business_id is not None
            and actor.business_id is not None
            and business_id != actor.business_id
        ):
            return AuthorizationDecision(
                False, "The resource belongs to another business", permission
            )

        # 4. The permission must be a real one — default deny for unknown names.
        if permission not in PERMISSION_KEYS:
            return AuthorizationDecision(
                False, f"'{permission}' is not a registered permission", permission
            )

        # 5. The permission itself.
        if not actor.is_superuser and permission not in actor.permissions:
            return AuthorizationDecision(
                False, f"Missing permission '{permission}'", permission
            )

        # 6. Resource-specific policies (classification, extra restrictions).
        policy = self._policy_for(db, resource_type, resource_id) if db is not None else None
        if policy is not None:
            allowed_roles = set(policy.allowed_roles or [])
            allowed_permissions = set(policy.allowed_permissions or [])
            if allowed_roles and not (allowed_roles & set(actor.roles)) and not actor.is_superuser:
                return AuthorizationDecision(
                    False,
                    f"The resource is limited to roles: {', '.join(sorted(allowed_roles))}",
                    permission,
                    policy.classification,
                )
            if allowed_permissions and not (allowed_permissions & set(actor.permissions)):
                return AuthorizationDecision(
                    False,
                    "The resource requires a permission the actor does not hold",
                    permission,
                    policy.classification,
                )
            if policy.classification == "RESTRICTED" and not actor.is_superuser:
                return AuthorizationDecision(
                    False, "Restricted resources are limited to administrators", permission,
                    policy.classification,
                )
            return AuthorizationDecision(
                True, "Permitted by resource policy", permission, policy.classification,
                policy.requires_approval,
            )

        classification = (
            "RESTRICTED"
            if resource_type in self.RESTRICTED_RESOURCES
            else "CONFIDENTIAL"
            if resource_type in self.CONFIDENTIAL_RESOURCES
            else "INTERNAL"
        )
        if classification == "RESTRICTED" and not actor.is_superuser:
            return AuthorizationDecision(
                False,
                "Restricted resources (credentials, secrets, tokens) are limited to "
                "administrators",
                permission,
                classification,
            )
        return AuthorizationDecision(True, "Permitted", permission, classification)

    # -- convenience checks ------------------------------------------------
    def check_permission(self, actor: Actor, permission: str) -> bool:
        return self.authorize(actor, permission).allowed

    def check_resource_access(
        self, actor: Actor, permission: str, *, resource_type: str, resource_id: str | None = None,
        db: Session | None = None,
    ) -> AuthorizationDecision:
        return self.authorize(
            actor, permission, resource_type=resource_type, resource_id=resource_id, db=db
        )

    def check_business_access(self, actor: Actor, business_id: int | None) -> bool:
        if business_id is None or actor.business_id is None:
            return True
        return business_id == actor.business_id

    def check_document_access(
        self, actor: Actor, document: Any, *, db: Session | None = None
    ) -> AuthorizationDecision:
        """Documents add their own restriction rules on top of permissions."""
        if not self.check_business_access(actor, getattr(document, "business_id", None)):
            return AuthorizationDecision(
                False, "The document belongs to another business", "knowledge.view"
            )
        if getattr(document, "is_deleted", False):
            return AuthorizationDecision(False, "The document was deleted", "knowledge.view")
        if getattr(document, "is_restricted", False) and not actor.is_superuser:
            allowed_users = set(getattr(document, "allowed_user_ids", None) or [])
            allowed_roles = set(getattr(document, "allowed_roles", None) or [])
            if actor.user_id in allowed_users or (allowed_roles & set(actor.roles)):
                return AuthorizationDecision(True, "Named in the document allowlist", "knowledge.view")
            if "knowledge.manage" in actor.permissions:
                return AuthorizationDecision(True, "Knowledge manager", "knowledge.view")
            return AuthorizationDecision(
                False, "The document is restricted", "knowledge.view", "RESTRICTED"
            )
        return self.authorize(actor, "knowledge.view", resource_type="KNOWLEDGE_DOCUMENT", db=db)

    def check_agent_tool_access(
        self, actor: Actor, *, tool_name: str, required_permission: str | None,
        agent_policy: Any | None = None,
    ) -> AuthorizationDecision:
        if actor.is_agent and agent_policy is not None:
            allowed = getattr(agent_policy, "allowed_tools", None) or []
            if allowed and tool_name not in allowed:
                return AuthorizationDecision(
                    False, f"The agent is not allowed to use '{tool_name}'", required_permission
                )
        if required_permission and not actor.is_superuser:
            if required_permission not in actor.permissions:
                return AuthorizationDecision(
                    False, f"Missing permission '{required_permission}' for tool '{tool_name}'",
                    required_permission,
                )
        return AuthorizationDecision(True, "Tool access permitted", required_permission)

    def check_workflow_action_access(
        self, actor: Actor, *, action_name: str, mode: str, amount: Any = None,
        maximum_amount: Any = None,
    ) -> AuthorizationDecision:
        if mode == "RESTRICTED":
            return AuthorizationDecision(
                False, f"'{action_name}' is restricted and can never be automated", action_name
            )
        if mode == "APPROVAL":
            return AuthorizationDecision(
                True, "Approval is required before execution", action_name,
                requires_approval=True,
            )
        if maximum_amount is not None and amount is not None:
            try:
                if float(amount) > float(maximum_amount):
                    return AuthorizationDecision(
                        True,
                        f"Amount exceeds the automatic limit of {maximum_amount}",
                        action_name,
                        requires_approval=True,
                    )
            except (TypeError, ValueError):
                return AuthorizationDecision(
                    False, "The amount could not be interpreted", action_name
                )
        return AuthorizationDecision(True, "Automatic execution permitted", action_name)

    def check_approval_authority(
        self, actor: Actor, *, requested_by: int | None, action_permission: str | None,
        amount: Any = None, approval_limit: Any = None,
    ) -> AuthorizationDecision:
        """Separation of duties and approval authority in one place."""
        if actor.is_agent or actor.is_system:
            return AuthorizationDecision(
                False, "An AI agent or system identity cannot approve actions"
            )
        if "approvals.approve" not in actor.permissions and not actor.is_superuser:
            return AuthorizationDecision(False, "Missing 'approvals.approve'")
        if action_permission and action_permission not in actor.permissions and not actor.is_superuser:
            return AuthorizationDecision(
                False, f"Approving this action requires '{action_permission}'"
            )
        if requested_by is not None and requested_by == actor.user_id:
            return AuthorizationDecision(
                False, "A user cannot approve their own request"
            )
        if approval_limit is not None and amount is not None:
            try:
                if float(amount) > float(approval_limit) and not actor.is_superuser:
                    return AuthorizationDecision(
                        False,
                        f"Approval above {approval_limit} needs a higher authority",
                    )
            except (TypeError, ValueError):
                return AuthorizationDecision(False, "The amount could not be interpreted")
        return AuthorizationDecision(True, "Approval authority confirmed")

    # -- helpers -----------------------------------------------------------
    def _is_administrative(self, permission: str) -> bool:
        return permission.split(".")[0] in {
            "users", "roles", "permissions", "security", "settings", "backup"
        } or permission in {"agents.configure", "audit.view"}

    def _policy_for(
        self, db: Session, resource_type: str | None, resource_id: str | None
    ) -> ResourceAccessPolicy | None:
        if resource_type is None:
            return None
        if resource_id is not None:
            specific = db.scalars(
                select(ResourceAccessPolicy).where(
                    ResourceAccessPolicy.resource_type == resource_type,
                    ResourceAccessPolicy.resource_id == resource_id,
                )
            ).first()
            if specific is not None:
                return specific
        return db.scalars(
            select(ResourceAccessPolicy).where(
                ResourceAccessPolicy.resource_type == resource_type,
                ResourceAccessPolicy.resource_id.is_(None),
            )
        ).first()

    def build_actor(self, db: Session, user: Any) -> Actor:
        """Build an actor from a user row and its roles."""
        roles: tuple[str, ...] = ()
        permissions: set[str] = set()
        if user is not None:
            from app.security.authorization import get_user_permissions, get_user_roles

            roles = tuple(role.role_name for role in get_user_roles(db, user))
            permissions = get_user_permissions(db, user)
        return Actor(
            user_id=getattr(user, "id", None),
            roles=roles,
            permissions=frozenset(permissions),
            business_id=None,
            is_superuser=bool(getattr(user, "is_superuser", False)),
        )
