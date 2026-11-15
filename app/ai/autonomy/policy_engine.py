"""Autonomy policy engine.

Three modes — AUTOMATIC, APPROVAL, RESTRICTED — evaluated against the stored
policy for each allowlisted action. Default deny: an action with no enabled
policy, an unknown action, or a role that is not allowed never runs.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.autonomy.actions import ACTION_REGISTRY, ActionSpec, get_action, is_registered
from app.ai.schemas.autonomy_schema import PolicyDecision, PolicyView
from app.core.constants import AutonomyMode, WorkflowStatus
from app.core.exceptions import NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.autonomy import (
    ApprovalRequest,
    AutonomousWorkflow,
    AutonomyPolicy,
    WorkflowIdempotencyRecord,
    WorkflowTask,
)
from app.security.authorization import get_user_roles
from app.database.models.user import User
from app.utils.date_utils import local_to_utc, to_local, utcnow

logger = get_logger("ai.autonomy.policy")

MAX_AMOUNT = Decimal("99999999.99")


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


class AutonomyPolicyEngine:
    """Evaluates whether an action may run, and how."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- defaults ----------------------------------------------------------
    def seed_defaults(self, *, created_by: int | None = None) -> int:
        """Create the default policy row for every registered action (idempotent)."""
        created = 0
        with self._session_factory() as db:
            existing = {
                row.action_name
                for row in db.scalars(select(AutonomyPolicy)).all()
            }
            for spec in ACTION_REGISTRY.values():
                if spec.name in existing:
                    continue
                db.add(
                    AutonomyPolicy(
                        policy_id=f"pol-{uuid.uuid4().hex[:10]}",
                        action_name=spec.name,
                        display_name=spec.display_name,
                        execution_mode=spec.default_mode,
                        maximum_amount=float(MAX_AMOUNT) if spec.default_mode == AutonomyMode.AUTOMATIC else None,
                        allowed_roles=[],
                        approval_required=spec.default_mode != AutonomyMode.AUTOMATIC,
                        approval_count=1,
                        allow_self_approval=False,
                        daily_execution_limit=50 if spec.default_mode == AutonomyMode.AUTOMATIC else None,
                        enabled=True,
                        created_by=created_by,
                    )
                )
                created += 1
            db.commit()
        if created:
            logger.info("Seeded %d default autonomy policies", created)
        return created

    # -- reads -------------------------------------------------------------
    def policies(self) -> list[PolicyView]:
        with self._session_factory() as db:
            rows = db.scalars(select(AutonomyPolicy).order_by(AutonomyPolicy.action_name)).all()
            return [self._view(row) for row in rows]

    def policy_for(self, action_name: str) -> PolicyView | None:
        with self._session_factory() as db:
            row = db.scalars(
                select(AutonomyPolicy).where(AutonomyPolicy.action_name == action_name)
            ).first()
            return self._view(row) if row else None

    def _view(self, row: AutonomyPolicy) -> PolicyView:
        return PolicyView(
            policy_id=row.policy_id,
            action_name=row.action_name,
            display_name=row.display_name,
            execution_mode=row.execution_mode,
            maximum_amount=f"{Decimal(str(row.maximum_amount)):,.2f}" if row.maximum_amount else None,
            allowed_roles=list(row.allowed_roles or []),
            approval_required=row.approval_required,
            approval_count=row.approval_count,
            allow_self_approval=row.allow_self_approval,
            daily_execution_limit=row.daily_execution_limit,
            enabled=row.enabled,
            updated_at=row.updated_at,
        )

    # -- writes ------------------------------------------------------------
    def update_policy(self, action_name: str, *, changes: dict[str, Any]) -> PolicyView:
        """Update one policy. The caller must have already authorised the change."""
        if not is_registered(action_name):
            raise ValidationError(f"'{action_name}' is not an allowlisted action")
        spec = get_action(action_name)

        mode = changes.get("execution_mode")
        if mode is not None and mode not in AutonomyMode.ALL:
            raise ValidationError(f"'{mode}' is not a valid execution mode")
        if spec.hard_restricted and mode not in (None, AutonomyMode.RESTRICTED):
            raise ValidationError(
                f"'{action_name}' is restricted by design and cannot be made automatic"
            )

        with self._session_factory() as db:
            row = db.scalars(
                select(AutonomyPolicy).where(AutonomyPolicy.action_name == action_name)
            ).first()
            if row is None:
                raise NotFoundError(f"No policy exists for '{action_name}'")

            if mode is not None:
                row.execution_mode = mode
            if "maximum_amount" in changes:
                row.maximum_amount = (
                    float(_dec(changes["maximum_amount"]))
                    if changes["maximum_amount"] not in (None, "")
                    else None
                )
            if "allowed_roles" in changes:
                row.allowed_roles = list(changes["allowed_roles"] or [])
            if "approval_required" in changes:
                row.approval_required = bool(changes["approval_required"])
            if "approval_count" in changes:
                count = int(changes["approval_count"] or 1)
                if count < 1 or count > 3:
                    raise ValidationError("approval_count must be between 1 and 3")
                row.approval_count = count
            if "allow_self_approval" in changes:
                row.allow_self_approval = bool(changes["allow_self_approval"])
            if "daily_execution_limit" in changes:
                limit = changes["daily_execution_limit"]
                row.daily_execution_limit = int(limit) if limit not in (None, "") else None
            if "enabled" in changes:
                row.enabled = bool(changes["enabled"])
            db.commit()
            return self._view(row)

    # -- evaluation --------------------------------------------------------
    def evaluate(
        self,
        action_name: str,
        *,
        actor_id: int | None,
        amount: Decimal | str | None = None,
    ) -> PolicyDecision:
        """Decide how (or whether) an action may run. Default deny."""
        if not is_registered(action_name):
            return PolicyDecision(
                action_name=action_name,
                mode=AutonomyMode.RESTRICTED,
                allowed=False,
                requires_approval=False,
                reason="Unknown action: not in the allowlist.",
            )
        spec: ActionSpec = get_action(action_name)
        if spec.hard_restricted:
            return PolicyDecision(
                action_name=action_name,
                mode=AutonomyMode.RESTRICTED,
                allowed=False,
                requires_approval=False,
                reason=f"{spec.display_name} is restricted by design and can never be automated.",
            )

        requested_amount = _dec(amount)

        with self._session_factory() as db:
            policy = db.scalars(
                select(AutonomyPolicy).where(AutonomyPolicy.action_name == action_name)
            ).first()
            if policy is None or not policy.enabled:
                return PolicyDecision(
                    action_name=action_name,
                    mode=AutonomyMode.RESTRICTED,
                    allowed=False,
                    requires_approval=False,
                    reason="No enabled autonomy policy exists for this action (default deny).",
                )
            if policy.execution_mode == AutonomyMode.RESTRICTED:
                return PolicyDecision(
                    action_name=action_name,
                    mode=AutonomyMode.RESTRICTED,
                    allowed=False,
                    requires_approval=False,
                    reason="Policy marks this action as restricted.",
                    policy_id=policy.policy_id,
                )

            user = db.get(User, actor_id) if actor_id else None
            if user is None or not user.is_active:
                return PolicyDecision(
                    action_name=action_name,
                    mode=policy.execution_mode,
                    allowed=False,
                    requires_approval=False,
                    reason="No active user is available to authorise this action.",
                    policy_id=policy.policy_id,
                )

            roles = [role.role_name for role in get_user_roles(db, user)]
            allowed_roles = list(policy.allowed_roles or [])
            if allowed_roles and not set(allowed_roles) & set(roles):
                return PolicyDecision(
                    action_name=action_name,
                    mode=policy.execution_mode,
                    allowed=False,
                    requires_approval=False,
                    reason=(
                        f"Role not permitted for this action "
                        f"(allowed: {', '.join(allowed_roles)})."
                    ),
                    policy_id=policy.policy_id,
                )

            permissions = _user_permissions(db, user)
            if spec.permission not in permissions and not user.is_superuser:
                return PolicyDecision(
                    action_name=action_name,
                    mode=policy.execution_mode,
                    allowed=False,
                    requires_approval=False,
                    reason=f"Missing permission '{spec.permission}'.",
                    policy_id=policy.policy_id,
                )

            if policy.daily_execution_limit is not None:
                used = self._daily_usage(db, action_name)
                if used >= policy.daily_execution_limit:
                    return PolicyDecision(
                        action_name=action_name,
                        mode=policy.execution_mode,
                        allowed=False,
                        requires_approval=False,
                        reason=(
                            f"Daily execution limit reached "
                            f"({used}/{policy.daily_execution_limit})."
                        ),
                        policy_id=policy.policy_id,
                    )

            maximum = _dec(policy.maximum_amount)
            requires_approval = policy.execution_mode == AutonomyMode.APPROVAL
            reason = "Policy requires human approval."
            if policy.execution_mode == AutonomyMode.AUTOMATIC:
                if maximum is not None and requested_amount is not None and requested_amount > maximum:
                    requires_approval = True
                    reason = (
                        f"Amount {requested_amount:,.2f} exceeds the automatic limit "
                        f"{maximum:,.2f}; approval required."
                    )
                else:
                    reason = "Automatic execution permitted by policy."

            return PolicyDecision(
                action_name=action_name,
                mode=policy.execution_mode,
                allowed=True,
                requires_approval=requires_approval,
                reason=reason,
                policy_id=policy.policy_id,
                maximum_amount=maximum,
                approval_count=policy.approval_count,
            )

    # -- helpers -----------------------------------------------------------
    def _daily_usage(self, db: Session, action_name: str) -> int:
        start = local_to_utc(datetime.combine(to_local(utcnow()).date(), time.min))
        executed = db.scalar(
            select(func.count(WorkflowIdempotencyRecord.id)).where(
                WorkflowIdempotencyRecord.action_name == action_name,
                WorkflowIdempotencyRecord.created_at >= start,
            )
        )
        approved = db.scalar(
            select(func.count(ApprovalRequest.id)).where(
                ApprovalRequest.requested_action == action_name,
                ApprovalRequest.executed_at.is_not(None),
                ApprovalRequest.executed_at >= start,
            )
        )
        return int((executed or 0) + (approved or 0))

    def self_approval_allowed(self, action_name: str) -> bool:
        with self._session_factory() as db:
            row = db.scalars(
                select(AutonomyPolicy).where(AutonomyPolicy.action_name == action_name)
            ).first()
            return bool(row and row.allow_self_approval)


def _user_permissions(db: Session, user: User) -> set[str]:
    from app.security.authorization import get_user_permissions

    return get_user_permissions(db, user)
