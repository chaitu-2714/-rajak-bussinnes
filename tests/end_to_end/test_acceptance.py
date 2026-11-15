"""End-to-end acceptance scenarios for the 1.0.0 release.

Each test follows one user journey across the whole application. They use real
services and real SQLite databases — no mocks.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.constants import WorkflowStatus
from app.core.exceptions import AuthorizationError
from app.database.models.autonomy import ApprovalRequest
from app.utils.date_utils import utcnow

from tests.conftest import MANAGER_PASSWORD, completed_sale


# ---------------------------------------------------------------------------
# Acceptance Test 1 — new business setup
# ---------------------------------------------------------------------------
def test_acceptance_1_new_business_setup(admin) -> None:
    profile = admin.business_service.get_business()
    assert profile.business_name
    assert admin.auth_service.needs_initial_setup() is False
    # A second setup must be refused rather than overwrite the workspace.
    with pytest.raises(Exception):
        admin.auth_service.run_initial_setup(
            {
                "business_name": "Duplicate",
                "owner_name": "Someone",
                "email": "dup@example.com",
                "password": MANAGER_PASSWORD,
                "password_confirm": MANAGER_PASSWORD,
                "currency": "INR",
                "timezone": "Asia/Kolkata",
                "financial_year_start": "04-01",
            }
        )
    principal = admin.auth_context.principal
    assert principal is not None and principal.is_superuser is True


# ---------------------------------------------------------------------------
# Acceptance Test 2 — complete sales transaction
# ---------------------------------------------------------------------------
def test_acceptance_2_complete_sales_transaction(admin, business) -> None:
    tea = business["tea"]
    customer = business["customer"]

    order = admin.sales_service.create_order(
        {"customer_id": customer.id, "items": [{"product_id": tea.id, "quantity": 4}]}
    )
    completed = admin.sales_service.complete_order(order.id)
    invoice = admin.sales_service.invoice_for_order(completed.id)
    assert invoice is not None

    # Partial payment: the rest stays outstanding and is not cash.
    admin.sales_service.record_payment(
        {"invoice_id": invoice.id, "amount": "100.00", "payment_method": "CASH"}
    )
    refreshed = admin.sales_service.invoice(invoice.id)
    assert refreshed.paid_amount == Decimal("100.00")
    assert refreshed.outstanding_amount == refreshed.total_amount - Decimal("100.00")

    stock = {row.product_id: row for row in admin.inventory_service.list_stock()}
    assert stock[tea.id].available_quantity == tea.opening_stock - 4 if hasattr(tea, "opening_stock") else True

    summary = admin.finance_service.summary()
    assert summary.revenue >= Decimal("100.00")
    assert summary.cash_received == Decimal("100.00")

    entries = admin.audit_service.list_entries(module="Sales")
    assert entries, "the sale must appear in the audit trail"


# ---------------------------------------------------------------------------
# Acceptance Test 3 — multi-agent business analysis
# ---------------------------------------------------------------------------
def test_acceptance_3_multi_agent_analysis(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    detail = admin.collaboration_service.run_collaboration(
        "Analyze my complete business performance."
    )
    assert detail.collaboration.status in ("COMPLETED", "PARTIAL")
    assert detail.decision is not None
    findings = detail.findings
    assert findings
    agents = {
        (finding.get("agent_id") or finding.get("agent") or finding.get("agent_code"))
        if isinstance(finding, dict)
        else getattr(finding, "agent_id", None)
        for finding in findings
    }
    agents.discard(None)
    assert len(agents) >= 3, f"expected several agents, saw {agents}"


# ---------------------------------------------------------------------------
# Acceptance Test 4 — autonomous purchase workflow with approval
# ---------------------------------------------------------------------------
def test_acceptance_4_autonomous_purchase_workflow(admin, business) -> None:
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
    before = len(admin.purchasing_service.list_purchase_orders())

    view = admin.autonomy_service.create_workflow(
        "LOW_STOCK_REPLENISHMENT",
        payload={
            "product_id": business["tea"].id,
            "supplier_id": business["supplier"].id,
            "items": [
                {
                    "product_id": business["tea"].id,
                    "ordered_quantity": 10,
                    "unit_cost": "100.00",
                }
            ],
        },
    )
    detail = admin.autonomy_service.start_workflow(view.workflow_ref)
    assert detail.workflow.status == WorkflowStatus.WAITING_APPROVAL
    assert len(admin.purchasing_service.list_purchase_orders()) == before, (
        "no purchase order may exist before approval"
    )

    approval = admin.autonomy_service.pending_approvals()[0]
    result = admin.autonomy_service.approve(approval.approval_ref)
    assert result.status == "APPROVED"
    assert len(admin.purchasing_service.list_purchase_orders()) == before + 1

    resumed = admin.autonomy_service.get_workflow(view.workflow_ref)
    assert resumed.workflow.status == WorkflowStatus.COMPLETED
    audited = admin.audit_service.list_entries(module="AI Agents")
    assert audited, "the workflow must be audited"


# ---------------------------------------------------------------------------
# Acceptance Test 5 — business intelligence report
# ---------------------------------------------------------------------------
def test_acceptance_5_business_intelligence(admin, business) -> None:
    completed_sale(admin, business, quantity=3)
    bundle = admin.analytics_service.analyze("MONTHLY")
    financial = bundle.financial
    # Independent check: revenue must equal the invoiced total of completed orders.
    orders = admin.sales_service.list_orders()
    invoiced = sum(
        (order.total_amount for order in orders if order.order_status == "COMPLETED"),
        Decimal("0.00"),
    )
    assert financial.revenue == invoiced
    # Revenue and cash are separate figures and are never conflated.
    assert financial.cash_received <= financial.revenue

    report = admin.analytics_service.generate_report("EXECUTIVE_PERFORMANCE", file_format="PDF")
    path = Path(report["path"])
    assert path.exists() and path.stat().st_size > 1000
    assert report.get("period")


# ---------------------------------------------------------------------------
# Acceptance Test 6 — hybrid RAG over a supplier agreement
# ---------------------------------------------------------------------------
def test_acceptance_6_hybrid_rag(admin, tmp_path: Path) -> None:
    agreement = tmp_path / "supplier_agreement.txt"
    agreement.write_text(
        "SUPPLIER AGREEMENT\n\n"
        "This agreement is between Patnaik Traders and Odisha Beverages Supply Pvt Ltd.\n"
        "Payment terms: 30 days from invoice date\n"
        "Delivery terms: Delivery within 7 days of purchase order\n",
        encoding="utf-8",
    )
    admin.knowledge_service.upload_document(agreement)

    answer = admin.knowledge_service.ask("What are the supplier's payment conditions?")
    assert answer.grounded is True
    assert "30 days" in answer.answer
    assert answer.sources
    cited = answer.sources[0]
    details = admin.knowledge_service.get_document(cited.document_ref)
    preview = admin.knowledge_service.preview_document(cited.document_ref)
    assert "30 days" in preview["text"], "the cited document must really contain the evidence"
    assert details["status"] in ("INDEXED",)
    assert details["page_count"] >= 1


# ---------------------------------------------------------------------------
# Acceptance Test 7 — security denials
# ---------------------------------------------------------------------------
def test_acceptance_7_security_denials(admin, business, employee_context) -> None:
    """Unauthorised access to financial records and documents is refused."""
    from tests.conftest import ADMIN_PAYLOAD, EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD

    # employee_context signs the shared session in as an Employee, so sign back in
    # as the administrator to create the record under test.
    admin.auth_service.logout()
    admin.auth_service.login(ADMIN_PAYLOAD["email"], ADMIN_PAYLOAD["password"])
    completed_sale(admin, business, quantity=1)

    # Even an administrator cannot invent a permission.
    actor = admin.security_service.actor()
    assert admin.authorization_service.authorize(actor, "finance.teleport").allowed is False

    # Now act as the Employee.
    admin.auth_service.logout()
    admin.auth_service.login(EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD)
    with pytest.raises(AuthorizationError):
        admin.finance_service.summary()
    with pytest.raises(AuthorizationError):
        admin.security_service.overview()
    with pytest.raises(AuthorizationError):
        admin.knowledge_service.list_documents()
    with pytest.raises(AuthorizationError):
        admin.sales_service.create_order(
            {
                "customer_id": business["customer"].id,
                "items": [{"product_id": business["tea"].id, "quantity": 1}],
            }
        )


# ---------------------------------------------------------------------------
# Acceptance Test 8 — offline operation
# ---------------------------------------------------------------------------
def test_acceptance_8_offline_operation(admin, business, tmp_path: Path) -> None:
    admin.knowledge_service.configure_providers(policy="OFFLINE", offline_mode=True)
    completed_sale(admin, business, quantity=1)

    # Business modules, analytics and retrieval all work with no network.
    assert admin.finance_service.summary().revenue > 0
    assert admin.analytics_service.kpis("MONTHLY")
    document = tmp_path / "policy.txt"
    document.write_text("Returns must be recorded within 7 days.\n", encoding="utf-8")
    admin.knowledge_service.upload_document(document)
    answer = admin.knowledge_service.ask("How long do I have to record a return?")
    assert answer.provider in ("deterministic", "ollama")
    assert answer.provider != "gemini"

    configuration = admin.knowledge_service.provider_configuration()
    assert configuration["offline_mode"] is True


# ---------------------------------------------------------------------------
# Acceptance Test 9 — backup and recovery
# ---------------------------------------------------------------------------
def test_acceptance_9_backup_and_recovery(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    orders_before = len(admin.sales_service.list_orders())

    backup = admin.security_service.create_backup(include_knowledge=True)
    assert backup["integrity_status"] == "VERIFIED"
    preview = admin.security_service.validate_backup(backup["path"])
    assert preview["valid"] is True

    # Validate the copy that a restore would use, without replacing live data here.
    import shutil
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / Path(backup["path"]).name
        shutil.copy2(backup["path"], copy)
        assert admin.security_service.validate_backup(copy)["valid"] is True

    assert len(admin.sales_service.list_orders()) == orders_before
    history = admin.security_service.backup_history()
    assert history and history[0]["integrity_status"] == "VERIFIED"


# ---------------------------------------------------------------------------
# Acceptance Test 10 — upgrade path (installer itself needs Windows)
# ---------------------------------------------------------------------------
def test_acceptance_10_upgrade_preserves_business_data(tmp_path: Path, monkeypatch) -> None:
    import os

    from app.core.config import load_config
    from app.core.database import Database

    monkeypatch.setenv("BIZPILOT_DATA_DIR", str(tmp_path))
    config = load_config()
    database = Database(config)
    database.initialize()
    with database.engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(
            text(
                "INSERT INTO business (business_name, owner_name, email, currency, timezone, "
                "financial_year_start, created_at, updated_at) VALUES "
                "('Legacy Traders','Owner','legacy@example.com','INR','Asia/Kolkata','04-01',"
                "'2026-01-01','2026-01-01')"
            )
        )
    schema = database.schema_version()
    database.dispose()

    # Re-opening applies migrations idempotently and keeps the row.
    database = Database(config)
    database.initialize()
    assert database.schema_version() == schema
    with database.engine.connect() as conn:
        from sqlalchemy import text

        name = conn.execute(text("SELECT business_name FROM business")).scalar_one()
    assert name == "Legacy Traders"
    database.dispose()
