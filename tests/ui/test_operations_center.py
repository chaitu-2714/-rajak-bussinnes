"""UI tests: the Autonomous Operations Center."""

from __future__ import annotations

import pytest

from app.ui.main_window import MainWindow
from app.ui.pages.operations_center import OperationsCenterPage

from tests.conftest import completed_sale


def _close(widget) -> None:
    shutdown = getattr(widget, "shutdown", None)
    if callable(shutdown):
        shutdown()
    widget.close()
    widget.deleteLater()


def _seed(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    admin.finance_service.create_expense(
        {
            "expense_category": "RENT",
            "description": "Shop rent",
            "amount": "5000.00",
            "payment_method": "CASH",
            "expense_date": "2026-11-02T10:00:00",
        }
    )
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 9,
            "movement_type": "ADJUSTMENT",
            "reason": "Breakage",
            "direction": -1,
        }
    )
    view = admin.autonomy_service.create_workflow(
        "LOW_STOCK_REPLENISHMENT",
        payload={
            "product_id": business["tea"].id,
            "supplier_id": business["supplier"].id,
            "items": [
                {"product_id": business["tea"].id, "ordered_quantity": 10, "unit_cost": "180.00"}
            ],
        },
    )
    admin.autonomy_service.start_workflow(view.workflow_ref)


def test_page_is_registered_and_reachable(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("automation")
        page = window.page_for("automation")
        assert isinstance(page, OperationsCenterPage)
        assert "automation" in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_dashboard_reflects_real_records(qapp, admin, business) -> None:
    _seed(admin, business)
    page = OperationsCenterPage(admin)
    try:
        assert page.workflows_table.row_count() == 1
        assert page.card_total.value_text == "1"
        assert page.card_approvals.value_text == "1"
        page.workflows_table.table.selectRow(0)
        page._show_workflow(page._workflows and next(iter(page._workflows)))
        text = page.detail_text.toPlainText()
        assert "WAITING_APPROVAL" in text
        assert "create_purchase_order" in text
        assert page.tasks_table.row_count() >= 8
    finally:
        _close(page)


def test_approval_center_lists_pending_requests(qapp, admin, business) -> None:
    _seed(admin, business)
    page = OperationsCenterPage(admin)
    try:
        assert page.approvals_table.row_count() == 1
        page.approvals_table.table.selectRow(0)
        page._show_approval_details()
        details = page.approval_details.toPlainText()
        assert "create_purchase_order" in details
        assert "Financial impact" in details
        assert "PENDING" in details
    finally:
        _close(page)


def test_autonomy_tab_lists_every_policy(qapp, admin) -> None:
    page = OperationsCenterPage(admin)
    try:
        from app.ai.autonomy.actions import ACTION_REGISTRY

        assert page.policies_table.row_count() == len(ACTION_REGISTRY)
        assert page.schedules_table.row_count() >= 3
        assert page.start_button.isEnabled() is True
        assert page.approve_button.isEnabled() is True
    finally:
        _close(page)


def test_read_only_role_cannot_act(qapp, admin) -> None:
    from tests.conftest import MANAGER_PASSWORD

    role = admin.role_service.create_role(
        {
            "role_name": "Ops Reader",
            "description": "Read-only operations view",
            "permission_keys": ["dashboard.view", "automation.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Ops Reader",
            "email": "opsreader@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("opsreader@bizpilot.test", MANAGER_PASSWORD)

    page = OperationsCenterPage(admin)
    try:
        assert page.start_button.isEnabled() is False
        assert page.approve_button.isEnabled() is False
        assert page.save_policy_button.isEnabled() is False
        assert page.process_events_button.isEnabled() is False
    finally:
        _close(page)


def test_employee_cannot_see_the_operations_center(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        assert "automation" not in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_policy_editor_reflects_the_selected_policy(qapp, admin) -> None:
    page = OperationsCenterPage(admin)
    try:
        for row in range(page.policies_table.row_count()):
            item = page.policies_table.table.item(row, 0)
            if item is not None and item.text() == "create_purchase_order":
                page.policies_table.table.selectRow(row)
                page._show_policy_editor()
                break
        assert page.mode_combo.currentData() == "APPROVAL"
    finally:
        _close(page)
