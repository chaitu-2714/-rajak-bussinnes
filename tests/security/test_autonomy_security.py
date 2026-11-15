"""Security tests for autonomous workflows and approvals."""

from __future__ import annotations

import pytest

from app.ai.autonomy.actions import ACTION_REGISTRY, is_registered
from app.core.constants import AutonomyMode
from app.core.exceptions import AuthorizationError, ConflictError

from tests.conftest import MANAGER_PASSWORD, completed_sale, create_user


def _low_stock_workflow(admin, business) -> tuple[str, str]:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 9,
            "movement_type": "ADJUSTMENT",
            "reason": "Breakage",
            "direction": -1,
        }
    )
    completed_sale(admin, business, quantity=1)
    view = admin.autonomy_service.create_workflow(
        "LOW_STOCK_REPLENISHMENT",
        payload={
            "product_id": business["tea"].id,
            "supplier_id": business["supplier"].id,
            "items": [
                {
                    "product_id": business["tea"].id,
                    "ordered_quantity": 10,
                    "unit_cost": "180.00",
                }
            ],
        },
    )
    admin.autonomy_service.start_workflow(view.workflow_ref)
    approval = admin.autonomy_service.pending_approvals()[0]
    return view.workflow_ref, approval.approval_ref


# ---------------------------------------------------------------------------
# Test 7: unauthorised approval
# ---------------------------------------------------------------------------
def test_user_without_approval_permission_cannot_approve(admin, business) -> None:
    _, approval_ref = _low_stock_workflow(admin, business)
    role = admin.role_service.create_role(
        {
            "role_name": "Workflow Watcher",
            "description": "Can see approvals but not decide them",
            "permission_keys": ["dashboard.view", "automation.view", "approvals.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Watcher",
            "email": "watcher@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("watcher@bizpilot.test", MANAGER_PASSWORD)

    assert admin.autonomy_service.pending_approvals()
    with pytest.raises(AuthorizationError):
        admin.autonomy_service.approve(approval_ref)


def test_approver_without_the_action_permission_is_refused(admin, business) -> None:
    _, approval_ref = _low_stock_workflow(admin, business)
    role = admin.role_service.create_role(
        {
            "role_name": "Approvals Only",
            "description": "May approve, but has no purchasing rights",
            "permission_keys": ["dashboard.view", "automation.view", "approvals.view", "approvals.approve"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Approver",
            "email": "approver@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("approver@bizpilot.test", MANAGER_PASSWORD)
    with pytest.raises(AuthorizationError):
        admin.autonomy_service.approve(approval_ref)


def test_self_approval_is_refused_when_another_approver_exists(admin, business) -> None:
    _, approval_ref = _low_stock_workflow(admin, business)
    # A second Super Admin is eligible to approve, so the requester may not.
    create_user(admin, "Super Admin", "second-admin@bizpilot.test", MANAGER_PASSWORD, "Second Admin")
    with pytest.raises(AuthorizationError):
        admin.autonomy_service.approve(approval_ref)


# ---------------------------------------------------------------------------
# Test 15: a workflow cannot change its own autonomy policy
# ---------------------------------------------------------------------------
def test_no_action_can_modify_policies() -> None:
    for name in ACTION_REGISTRY:
        assert "policy" not in name
        assert "permission" not in name
        assert "autonomy" not in name
    assert not is_registered("update_autonomy_policy")
    assert not is_registered("grant_permission")


def test_running_a_workflow_never_changes_policies(admin, business) -> None:
    before = {policy.action_name: policy.execution_mode for policy in admin.autonomy_service.policies()}
    completed_sale(admin, business, quantity=1)
    view = admin.autonomy_service.create_workflow("DAILY_SUMMARY")
    admin.autonomy_service.start_workflow(view.workflow_ref)
    after = {policy.action_name: policy.execution_mode for policy in admin.autonomy_service.policies()}
    assert before == after


def test_restricted_action_can_never_be_approved(admin, business) -> None:
    spec = ACTION_REGISTRY["delete_financial_transaction"]
    assert spec.hard_restricted is True
    decision = admin.policy_engine.evaluate(
        "delete_financial_transaction", actor_id=admin.auth_context.principal.user_id
    )
    assert decision.allowed is False
    assert decision.mode == AutonomyMode.RESTRICTED


def test_workflow_cannot_execute_an_unregistered_action(admin, business) -> None:
    from app.ai.autonomy.actions import ActionRestricted

    with pytest.raises(ActionRestricted):
        admin.workflow_engine._execute_action(
            "wf-does-not-exist", "task", "run_arbitrary_sql", {}, 1, "key:test"
        )


# ---------------------------------------------------------------------------
# RBAC on the automation surface
# ---------------------------------------------------------------------------
def test_employee_cannot_view_or_run_automations(employee_context) -> None:
    with pytest.raises(AuthorizationError):
        employee_context.autonomy_service.list_workflows()
    with pytest.raises(AuthorizationError):
        employee_context.autonomy_service.create_workflow("DAILY_SUMMARY")


def test_view_only_role_cannot_start_workflows(admin) -> None:
    role = admin.role_service.create_role(
        {
            "role_name": "Automation Viewer",
            "description": "Read-only automation access",
            "permission_keys": ["dashboard.view", "automation.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Automation Viewer",
            "email": "autoviewer@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("autoviewer@bizpilot.test", MANAGER_PASSWORD)

    assert admin.autonomy_service.list_workflows() == []
    with pytest.raises(AuthorizationError):
        admin.autonomy_service.create_workflow("DAILY_SUMMARY")
    with pytest.raises(AuthorizationError):
        admin.autonomy_service.process_events()


def test_only_configurators_can_change_policies(admin) -> None:
    role = admin.role_service.create_role(
        {
            "role_name": "Automation Operator",
            "description": "Runs workflows but may not change policies",
            "permission_keys": ["dashboard.view", "automation.view", "automation.execute"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Operator",
            "email": "operator@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("operator@bizpilot.test", MANAGER_PASSWORD)
    with pytest.raises(AuthorizationError):
        admin.autonomy_service.update_policy(
            "create_purchase_order", changes={"execution_mode": "AUTOMATIC"}
        )


# ---------------------------------------------------------------------------
# audit trail
# ---------------------------------------------------------------------------
def test_approvals_and_policies_are_audited(admin, business) -> None:
    _, approval_ref = _low_stock_workflow(admin, business)
    admin.autonomy_service.approve(approval_ref, note="Audit check")
    admin.autonomy_service.update_policy("generate_daily_report", changes={"maximum_amount": "900"})
    actions = {entry.action for entry in admin.audit_service.list_entries()}
    assert "APPROVAL_REQUESTED" in actions
    assert "APPROVAL_APPROVED" in actions
    assert "AUTONOMY_POLICY_UPDATED" in actions
    assert "WORKFLOW_COMPLETED" in actions
