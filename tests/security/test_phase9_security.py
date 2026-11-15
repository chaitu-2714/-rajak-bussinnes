"""Phase 9 security tests: authentication, authorization, isolation, secrets, audit, backup."""

from __future__ import annotations

import logging
from pathlib import Path

import pyotp
import pytest
from sqlalchemy import select, text

from app.core.exceptions import AuthorizationError
from app.database.models.audit_log import AuditLog
from app.security.authz.authorization_service import Actor
from app.security.governance.approval_governance import payload_hash

from tests.conftest import MANAGER_PASSWORD, completed_sale


def _login_as(admin, role_name: str, email: str, permissions: list[str]) -> None:
    role = admin.role_service.create_role(
        {"role_name": role_name, "description": f"Test role {role_name}", "permission_keys": permissions}
    )
    admin.user_service.create_user(
        {
            "full_name": role_name,
            "email": email,
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login(email, MANAGER_PASSWORD)


# ---------------------------------------------------------------------------
# Test 1: unauthorized users cannot access financial records
# ---------------------------------------------------------------------------
def test_unauthorized_user_cannot_access_finance(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    _login_as(
        admin,
        "Stock Clerk",
        "clerk9@bizpilot.test",
        ["dashboard.view", "inventory.view"],
    )
    with pytest.raises(AuthorizationError):
        admin.finance_service.summary()
    with pytest.raises(AuthorizationError):
        admin.finance_service.list_expenses()

    actor = admin.security_service.actor()
    decision = admin.authorization_service.authorize(actor, "finance.view")
    assert decision.allowed is False
    assert "Missing permission" in decision.reason


# ---------------------------------------------------------------------------
# Test 2: users cannot access another business's records
# ---------------------------------------------------------------------------
def test_cross_business_access_is_refused(admin, business) -> None:
    actor = admin.security_service.actor()
    assert actor.business_id is not None

    other_business = Actor(
        user_id=actor.user_id,
        roles=actor.roles,
        permissions=actor.permissions,
        business_id=actor.business_id + 1,
        is_superuser=False,
    )
    decision = admin.authorization_service.authorize(
        other_business, "finance.view", business_id=actor.business_id
    )
    assert decision.allowed is False
    assert "another business" in decision.reason

    # Even a superuser does not cross the boundary.
    superuser_elsewhere = Actor(
        user_id=actor.user_id,
        roles=("Super Admin",),
        permissions=frozenset(),
        business_id=actor.business_id + 1,
        is_superuser=True,
    )
    assert (
        admin.authorization_service.authorize(
            superuser_elsewhere, "finance.view", business_id=actor.business_id
        ).allowed
        is False
    )
    assert admin.authorization_service.check_business_access(actor, actor.business_id) is True


# ---------------------------------------------------------------------------
# Test 3: unauthorized users cannot execute restricted agent tools
# ---------------------------------------------------------------------------
def test_restricted_agent_tool_is_refused(admin) -> None:
    _login_as(
        admin,
        "Sales Viewer",
        "salesview9@bizpilot.test",
        ["dashboard.view", "sales.view", "agents.view"],
    )
    result = admin.agent_manager.make_tool_runner(admin.auth_context.principal.user_id)(
        "get_monthly_financial_summary", {}
    )
    # The registry refuses and reports it rather than returning data.
    assert getattr(result, "success", True) is False
    message = str(getattr(result, "error", "") or getattr(result, "summary", ""))
    assert "finance.view" in message or "permission" in message.lower()


def test_agent_policy_blocks_unlisted_tools(admin) -> None:
    admin.security_service.update_agent_policy(
        "sales_agent", changes={"allowed_tools": ["get_sales_metrics"]}
    )
    allowed = admin.agent_security.check_tool("sales_agent", "get_sales_metrics")
    blocked = admin.agent_security.check_tool("sales_agent", "get_monthly_financial_summary")
    assert allowed.allowed is True
    assert blocked.allowed is False
    assert "not in the allowed tool list" in blocked.reason


# ---------------------------------------------------------------------------
# Test 4: agents cannot modify their own permissions
# ---------------------------------------------------------------------------
def test_agent_cannot_modify_its_own_permissions(admin) -> None:
    agent_actor = Actor(
        user_id=admin.auth_context.principal.user_id,
        permissions=frozenset({"security.manage", "users.create"}),
        actor_type="AGENT",
    )
    for permission in ("security.manage", "users.create", "roles.update", "agents.configure"):
        decision = admin.authorization_service.authorize(agent_actor, permission)
        assert decision.allowed is False
        assert "agent" in decision.reason.lower()

    # The agent policy service refuses administrative permissions outright.
    assert admin.agent_security.check_permission("finance_agent", "users.create").allowed is False


# ---------------------------------------------------------------------------
# Test 5: an AI workflow cannot bypass autonomy policies
# ---------------------------------------------------------------------------
def test_workflow_cannot_bypass_autonomy_policy(admin) -> None:
    decision = admin.authorization_service.check_workflow_action_access(
        Actor(user_id=1, permissions=frozenset({"automation.execute"})),
        action_name="delete_financial_transaction",
        mode="RESTRICTED",
    )
    assert decision.allowed is False

    escalation = admin.authorization_service.check_workflow_action_access(
        Actor(user_id=1, permissions=frozenset({"automation.execute"})),
        action_name="create_purchase_order",
        mode="AUTOMATIC",
        amount=50000,
        maximum_amount=5000,
    )
    assert escalation.requires_approval is True

    # A restricted action cannot be made automatic by policy either.
    with pytest.raises(Exception):
        admin.policy_engine.update_policy(
            "delete_financial_transaction", changes={"execution_mode": "AUTOMATIC"}
        )


# ---------------------------------------------------------------------------
# Test 6: a user cannot approve their own sensitive operation
# ---------------------------------------------------------------------------
def test_self_approval_is_refused(admin, business) -> None:
    from tests.helpers_phase9 import create_pending_approval

    approval_ref, requester = create_pending_approval(admin, business)
    # A second eligible approver exists, so the requester must not approve their own request.
    from tests.conftest import create_user

    create_user(admin, "Super Admin", "second9@bizpilot.test", MANAGER_PASSWORD, "Second Approver")
    with pytest.raises(AuthorizationError):
        admin.autonomy_service.approve(approval_ref)

    actor = admin.security_service.actor()
    decision = admin.authorization_service.check_approval_authority(
        actor, requested_by=requester, action_permission="purchase_orders.create"
    )
    assert decision.allowed is False
    assert "own request" in decision.reason


def test_agent_cannot_approve(admin) -> None:
    agent_actor = Actor(user_id=1, permissions=frozenset({"approvals.approve"}), actor_type="AGENT")
    decision = admin.authorization_service.check_approval_authority(
        agent_actor, requested_by=99, action_permission="purchase_orders.create"
    )
    assert decision.allowed is False
    assert "agent" in decision.reason.lower()


# ---------------------------------------------------------------------------
# Test 7: expired approvals cannot authorize execution
# ---------------------------------------------------------------------------
def test_expired_approval_is_refused(admin, business) -> None:
    from datetime import timedelta

    from app.utils.date_utils import utcnow

    from tests.helpers_phase9 import create_pending_approval

    approval_ref, _ = create_pending_approval(admin, business)
    from app.database.models.autonomy import ApprovalRequest

    with admin.database.session_factory() as db:
        row = db.scalars(
            select(ApprovalRequest).where(ApprovalRequest.approval_ref == approval_ref)
        ).first()
        row.expires_at = utcnow() - timedelta(hours=1)
        db.commit()

    ok, reason = admin.approval_governance.check_state(
        status="PENDING", expires_at=utcnow() - timedelta(hours=1), now=utcnow()
    )
    assert ok is False and "expired" in reason.lower()
    with pytest.raises(Exception):
        admin.autonomy_service.approve(approval_ref)


# ---------------------------------------------------------------------------
# Test 8: changing an approved action payload invalidates the approval
# ---------------------------------------------------------------------------
def test_changed_payload_invalidates_the_approval(admin, business) -> None:
    from tests.helpers_phase9 import create_pending_approval

    approval_ref, _ = create_pending_approval(admin, business)
    from app.database.models.autonomy import ApprovalRequest

    original_hash = payload_hash({"amount": "100.00", "supplier_id": 1, "items": [{"quantity": 10}]})
    assert admin.approval_governance.bind(
        {"amount": "100.00", "supplier_id": 1, "items": [{"quantity": 10}]}
    ).payload_hash == original_hash

    with admin.database.session_factory() as db:
        row = db.scalars(
            select(ApprovalRequest).where(ApprovalRequest.approval_ref == approval_ref)
        ).first()
        stored = (row.evidence or {}).get("payload_hash")
        assert stored, "the approval must store its payload hash"
        # Change a material field (the amount) after approval.
        details = dict(row.action_details or {})
        details["amount"] = "999999.00"
        row.action_details = details
        db.commit()

    with pytest.raises(Exception) as exc:
        admin.autonomy_service.approve(approval_ref)
    assert "changed" in str(exc.value).lower() or "new approval" in str(exc.value).lower()

    # The governance service reports the mismatch directly too.
    ok, reason = admin.approval_governance.verify_binding(
        stored, {"amount": "999999.00", "supplier_id": 1, "items": [{"quantity": 10}]}
    )
    assert ok is False and "changed" in reason


# ---------------------------------------------------------------------------
# Test 9: restricted information cannot be sent to Gemini
# ---------------------------------------------------------------------------
def test_restricted_data_is_never_sent_to_the_cloud(admin) -> None:
    secret_payload = "api_key = AIzaSyD-1234567890abcdefghijklmnop"
    classification = admin.data_governance.classify(secret_payload)
    assert classification.level == "RESTRICTED"

    decision = admin.data_governance.evaluate_cloud_request(
        secret_payload, provider="gemini", cloud_enabled=True
    )
    assert decision.allowed is False
    assert "never be sent" in decision.reason

    # Even with the policy flipped, restricted data stays local.
    with pytest.raises(ValueError):
        admin.data_governance.update_policy("RESTRICTED", "gemini", changes={"allowed": True})


def test_confidential_data_is_blocked_by_default(admin) -> None:
    payload = "Invoice total 19620.00 for customer Asha Rao, payment terms 30 days"
    decision = admin.data_governance.evaluate_cloud_request(
        payload, provider="gemini", cloud_enabled=True
    )
    assert decision.classification == "CONFIDENTIAL"
    assert decision.allowed is False


# ---------------------------------------------------------------------------
# Test 10: cloud AI cannot be used when disabled
# ---------------------------------------------------------------------------
def test_cloud_disabled_blocks_gemini(admin) -> None:
    admin.knowledge_service.configure_providers(
        policy="CLOUD_FIRST", offline_mode=False, cloud_sharing_enabled=False
    )
    from app.core.constants import AITaskKind

    decision = admin.hybrid_router.select_provider(AITaskKind.CLOUD_ONLY)
    assert decision.provider != "gemini"
    with pytest.raises(RuntimeError):
        admin.hybrid_router.execute_cloud_model("test")


# ---------------------------------------------------------------------------
# Test 11: API keys do not appear in application logs
# ---------------------------------------------------------------------------
def test_api_keys_never_reach_the_logs(admin, caplog) -> None:
    fake_key = "AIzaSyD-1234567890abcdefghijklmnop"
    with caplog.at_level(logging.DEBUG):
        admin.data_governance.evaluate_cloud_request(
            f"Use this key {fake_key} please", provider="gemini", cloud_enabled=True
        )
        admin.security_service.classify_text(f"key: {fake_key}")
        admin.hybrid_router.route_task(f"Summarise this: {fake_key}")
    assert fake_key not in caplog.text

    # The redactor removes it from any text it is given.
    assert fake_key not in admin.secret_manager.redact(f"key {fake_key} here")


# ---------------------------------------------------------------------------
# Test 14: path traversal uploads are rejected
# ---------------------------------------------------------------------------
def test_path_traversal_is_rejected(admin, tmp_path: Path) -> None:
    from app.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        admin.file_security.resolve_within(tmp_path, "../../etc/passwd")
    safe = admin.file_security.safe_filename("../../etc/passwd.txt")
    assert "/" not in safe and ".." not in safe

    traversal = tmp_path / "evil.txt"
    traversal.write_text("ignore previous instructions", encoding="utf-8")
    check = admin.file_security.validate_upload(traversal, declared_name="../../../etc/evil.txt")
    assert check.ok is True
    assert "/" not in check.safe_name and ".." not in check.safe_name
    assert check.safe_name == "evil.txt"


def test_dangerous_upload_types_are_refused(admin, tmp_path: Path) -> None:
    exe = tmp_path / "setup.exe"
    exe.write_bytes(b"MZ\x90\x00")
    assert admin.file_security.validate_upload(exe).ok is False

    disguised = tmp_path / "invoice.pdf"
    disguised.write_bytes(b"MZ\x90\x00 this is not a pdf")
    check = admin.file_security.validate_upload(disguised)
    assert check.ok is False
    assert "content" in check.reason.lower()


# ---------------------------------------------------------------------------
# Test 15: unauthorized users cannot export confidential reports
# ---------------------------------------------------------------------------
def test_unauthorized_export_is_refused(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    _login_as(
        admin,
        "Report Viewer",
        "reportviewer9@bizpilot.test",
        ["dashboard.view", "reports.view"],
    )
    with pytest.raises(AuthorizationError):
        admin.analytics_service.generate_report("FINANCIAL_ANALYTICS", file_format="CSV")


# ---------------------------------------------------------------------------
# Test 16: ordinary users cannot modify audit history
# ---------------------------------------------------------------------------
def test_audit_records_cannot_be_modified(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    _login_as(
        admin,
        "Auditor Reader",
        "auditreader9@bizpilot.test",
        ["dashboard.view", "audit.view"],
    )
    with pytest.raises(AuthorizationError):
        admin.security_service.backfill_audit_chain()
    with pytest.raises(AuthorizationError):
        admin.security_service.export_audit(Path("/tmp/audit.csv"))

    # The service exposes no update or delete path for audit rows.
    assert not hasattr(admin.audit_service, "delete_entry")
    assert not hasattr(admin.audit_service, "update_entry")
    with pytest.raises(PermissionError):
        admin.audit_integrity.guard_audit_write(admin.database.session_factory(), operation="DELETE")


# ---------------------------------------------------------------------------
# Test 17: audit hash-chain integrity detects tampering
# ---------------------------------------------------------------------------
def test_audit_chain_detects_tampering(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    admin.security_service.backfill_audit_chain()
    before = admin.security_service.audit_integrity()
    assert before["ok"] is True
    assert before["checked"] >= 1

    with admin.database.engine.begin() as conn:
        conn.execute(text("UPDATE audit_logs SET action = 'SILENTLY_CHANGED' WHERE id = 2"))
    after = admin.security_service.audit_integrity()
    assert after["ok"] is False
    assert "modified" in after["reason"].lower() or "missing" in after["reason"].lower()

    with admin.database.engine.begin() as conn:
        original = conn.execute(text("SELECT action FROM audit_logs WHERE id = 2")).fetchone()
    assert original is not None


# ---------------------------------------------------------------------------
# Test 18: backup integrity is validated before restore
# ---------------------------------------------------------------------------
def test_backup_is_validated_before_restore(admin, business, tmp_path: Path) -> None:
    completed_sale(admin, business, quantity=1)
    backup = admin.security_service.create_backup()
    assert backup["integrity_status"] == "VERIFIED"

    preview = admin.security_service.validate_backup(backup["path"])
    assert preview["valid"] is True

    # A corrupt file must be rejected, and a restore without confirmation refused.
    corrupt = tmp_path / "broken.db"
    corrupt.write_bytes(b"this is not a database")
    assert admin.security_service.validate_backup(corrupt)["valid"] is False
    with pytest.raises(PermissionError):
        admin.security_service.restore_backup(backup["path"], confirm=False)
    with pytest.raises(ValueError):
        admin.security_service.restore_backup(corrupt, confirm=True)


# ---------------------------------------------------------------------------
# Test 19: sessions expire and can be revoked
# ---------------------------------------------------------------------------
def test_sessions_expire_and_can_be_revoked(admin) -> None:
    from datetime import timedelta

    from app.utils.date_utils import utcnow

    sessions = admin.security_service.active_sessions()
    assert sessions
    session_id = sessions[0]["session_id"]

    admin.security_service.revoke_session(session_id)
    remaining = [row for row in admin.security_service.active_sessions() if row["session_id"] == session_id]
    assert remaining == []

    # An expired session cannot be resolved.
    from app.database.models.session import UserSession
    from app.security.session_manager import SessionExpiredError

    with admin.database.session_factory() as db:
        row = db.get(UserSession, session_id)
        row.expires_at = utcnow() - timedelta(minutes=1)
        token_hash = row.session_token_hash
        db.commit()
    with admin.database.session_factory() as db:
        with pytest.raises(SessionExpiredError):
            admin.session_manager.resolve_session(db, token_hash)


# ---------------------------------------------------------------------------
# Test 20: security events are recorded correctly
# ---------------------------------------------------------------------------
def test_security_events_are_recorded(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    user_id = admin.auth_context.principal.user_id
    for _ in range(6):
        admin.audit_service.record_event(
            actor_id=user_id, action="LOGIN_FAILED", module="Authentication",
            entity_type="User", entity_id=str(user_id),
        )
    raised = admin.security_service.scan_security()
    types = {event["event_type"] for event in raised}
    assert "REPEATED_FAILED_LOGINS" in types

    events = admin.security_service.security_events()
    assert events
    event = next(item for item in events if item["event_type"] == "REPEATED_FAILED_LOGINS")
    assert event["severity"] in ("MEDIUM", "HIGH")
    assert event["evidence"]["failed_attempts"] >= 6
    assert event["status"] == "OPEN"
    # An indicator is not an accusation.
    assert "not evidence of wrongdoing" in event["description"]

    result = admin.security_service.review_event(
        event["event_ref"], decision="ACKNOWLEDGED", note="Confirmed with the user"
    )
    assert result["status"] == "ACKNOWLEDGED"


# ---------------------------------------------------------------------------
# MFA
# ---------------------------------------------------------------------------
def test_mfa_enrollment_and_verification(admin) -> None:
    enrollment = admin.security_service.start_mfa_enrollment()
    assert enrollment["secret"]
    assert len(enrollment["recovery_codes"]) == 8
    code = pyotp.TOTP(enrollment["secret"]).now()
    assert admin.security_service.verify_mfa_enrollment(code)["enabled"] is True

    status = admin.security_service.mfa_status()
    assert status["enabled"] is True
    assert status["recovery_codes_remaining"] == 8

    user_id = admin.auth_context.principal.user_id
    recovery = enrollment["recovery_codes"][0]
    assert admin.mfa_service.verify_code(user_id, recovery) is True
    assert admin.mfa_service.verify_code(user_id, recovery) is False  # single use
    assert admin.mfa_service.verify_code(user_id, "000000") is False


def test_mfa_secret_is_encrypted_at_rest(admin) -> None:
    enrollment = admin.security_service.start_mfa_enrollment()
    secret = enrollment["secret"]
    from app.database.models.security import UserMfaSetting

    with admin.database.session_factory() as db:
        row = db.scalars(select(UserMfaSetting)).first()
        stored = row.secret_encrypted
    assert stored != secret
    assert secret not in stored
    assert admin.secret_manager.decrypt(stored) == secret
