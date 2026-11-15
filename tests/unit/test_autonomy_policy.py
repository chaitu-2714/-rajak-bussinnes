"""Unit tests: autonomy policies and the action allowlist."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.ai.autonomy.actions import (
    ACTION_REGISTRY,
    ActionRestricted,
    action_names,
    get_action,
    is_registered,
)
from app.ai.autonomy.policy_engine import AutonomyPolicyEngine
from app.core.constants import AutonomyMode


@pytest.fixture()
def engine(admin) -> AutonomyPolicyEngine:
    return admin.policy_engine


# ---------------------------------------------------------------------------
# the allowlist
# ---------------------------------------------------------------------------
def test_registry_contains_only_known_actions() -> None:
    names = action_names()
    assert "create_purchase_order" in names
    assert "delete_financial_transaction" in names
    assert all(is_registered(name) for name in names)
    assert not is_registered("os.system")


def test_unknown_action_is_refused() -> None:
    with pytest.raises(ActionRestricted):
        get_action("run_sql")
    with pytest.raises(ActionRestricted):
        get_action("eval_python")


def test_every_action_declares_permission_and_risk() -> None:
    for spec in ACTION_REGISTRY.values():
        assert spec.permission
        assert spec.risk_level in ("LOW", "MEDIUM", "HIGH")
        assert spec.default_mode in AutonomyMode.ALL
        assert callable(spec.handler)


def test_business_changing_actions_default_to_approval() -> None:
    for name in (
        "create_purchase_order",
        "record_expense",
        "record_payment",
        "adjust_inventory",
        "change_product_price",
        "send_customer_message",
    ):
        assert ACTION_REGISTRY[name].default_mode == AutonomyMode.APPROVAL
    assert ACTION_REGISTRY["delete_financial_transaction"].hard_restricted is True


def test_read_actions_default_to_automatic() -> None:
    for name in ("retrieve_low_stock", "retrieve_daily_metrics", "generate_daily_report"):
        assert ACTION_REGISTRY[name].default_mode == AutonomyMode.AUTOMATIC


# ---------------------------------------------------------------------------
# policy evaluation
# ---------------------------------------------------------------------------
def test_defaults_are_seeded(engine: AutonomyPolicyEngine, admin) -> None:
    policies = engine.policies()
    assert len(policies) == len(ACTION_REGISTRY)
    assert {policy.action_name for policy in policies} == set(ACTION_REGISTRY)


def test_unknown_action_is_denied_by_default(engine: AutonomyPolicyEngine, admin) -> None:
    decision = engine.evaluate("drop_database", actor_id=admin.auth_context.principal.user_id)
    assert decision.allowed is False
    assert "allowlist" in decision.reason


def test_hard_restricted_action_is_never_allowed(engine: AutonomyPolicyEngine, admin) -> None:
    decision = engine.evaluate(
        "delete_financial_transaction", actor_id=admin.auth_context.principal.user_id
    )
    assert decision.allowed is False
    assert decision.mode == AutonomyMode.RESTRICTED
    assert "restricted by design" in decision.reason


def test_automatic_action_is_allowed(engine: AutonomyPolicyEngine, admin) -> None:
    decision = engine.evaluate("retrieve_low_stock", actor_id=admin.auth_context.principal.user_id)
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.is_automatic is True


def test_business_action_requires_approval(engine: AutonomyPolicyEngine, admin) -> None:
    decision = engine.evaluate(
        "create_purchase_order",
        actor_id=admin.auth_context.principal.user_id,
        amount="5000",
    )
    assert decision.allowed is True
    assert decision.requires_approval is True


def test_amount_above_the_automatic_limit_escalates(engine: AutonomyPolicyEngine, admin) -> None:
    actor = admin.auth_context.principal.user_id
    engine.update_policy(
        "generate_daily_report", changes={"execution_mode": "AUTOMATIC", "maximum_amount": "1000"}
    )
    small = engine.evaluate("generate_daily_report", actor_id=actor, amount="100")
    assert small.requires_approval is False
    # The report action has no amount field, so a large explicit amount escalates.
    large = engine.evaluate("generate_daily_report", actor_id=actor, amount="5000")
    assert large.requires_approval is True
    assert "exceeds the automatic limit" in large.reason


def test_role_restriction_denies_other_roles(engine: AutonomyPolicyEngine, admin) -> None:
    actor = admin.auth_context.principal.user_id
    engine.update_policy("generate_daily_report", changes={"allowed_roles": ["Finance Manager"]})
    decision = engine.evaluate("generate_daily_report", actor_id=actor)
    assert decision.allowed is False
    assert "Role not permitted" in decision.reason


def test_disabled_policy_denies(engine: AutonomyPolicyEngine, admin) -> None:
    actor = admin.auth_context.principal.user_id
    engine.update_policy("retrieve_low_stock", changes={"enabled": False})
    decision = engine.evaluate("retrieve_low_stock", actor_id=actor)
    assert decision.allowed is False
    assert "default deny" in decision.reason


def test_restricted_mode_cannot_be_made_automatic(engine: AutonomyPolicyEngine, admin) -> None:
    from app.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        engine.update_policy(
            "delete_financial_transaction", changes={"execution_mode": "AUTOMATIC"}
        )


def test_daily_limit_blocks_further_runs(engine: AutonomyPolicyEngine, admin) -> None:
    actor = admin.auth_context.principal.user_id
    engine.update_policy("retrieve_low_stock", changes={"daily_execution_limit": 1})
    # Consume the single allowed execution by running a workflow task once.
    from app.database.models.autonomy import WorkflowIdempotencyRecord

    with admin.database.session_factory() as db:
        db.add(
            WorkflowIdempotencyRecord(
                idempotency_key="test:daily-limit",
                action_name="retrieve_low_stock",
                result={"summary": "counted"},
            )
        )
        db.commit()
    decision = engine.evaluate("retrieve_low_stock", actor_id=actor)
    assert decision.allowed is False
    assert "Daily execution limit" in decision.reason


def test_inactive_user_cannot_be_authorised(engine: AutonomyPolicyEngine, admin) -> None:
    decision = engine.evaluate("retrieve_low_stock", actor_id=99999)
    assert decision.allowed is False
    assert "active user" in decision.reason
