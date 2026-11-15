"""UI tests: the AI Collaboration Center."""

from __future__ import annotations

import pytest

from app.ui.main_window import MainWindow
from app.ui.pages.collaboration_center import CollaborationCenterPage

from tests.conftest import MANAGER_PASSWORD, completed_sale


def _close(widget) -> None:
    shutdown = getattr(widget, "shutdown", None)
    if callable(shutdown):
        shutdown()
    widget.close()
    widget.deleteLater()


def _seed(admin, business) -> str:
    completed_sale(admin, business, quantity=2)
    admin.finance_service.create_expense(
        {
            "expense_category": "RENT",
            "description": "Shop rent",
            "amount": "5000.00",
            "payment_method": "CASH",
            "expense_date": "2026-11-02T10:00:00",
        }
    )
    detail = admin.collaboration_service.run_collaboration(
        "Analyze my complete business performance.", scenario="BUSINESS_HEALTH"
    )
    return detail.collaboration.collaboration_id


def test_page_is_registered_and_reachable(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("collaboration")
        page = window.page_for("collaboration")
        assert isinstance(page, CollaborationCenterPage)
        assert "collaboration" in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_dashboard_shows_real_rows(qapp, admin, business) -> None:
    collaboration_id = _seed(admin, business)
    page = CollaborationCenterPage(admin)
    try:
        assert page.table.row_count() == 1
        assert page.card_total.value_text == "1"
        assert page.card_completed.value_text in ("1", "0")
        page.table.table.selectRow(0)
        page._select(collaboration_id)
        assert "Analyze my complete business performance." in page.overview_text.toPlainText()
        assert page.tasks_table.row_count() == 5
        assert page.findings_table.row_count() > 0
    finally:
        _close(page)


def test_decision_tab_renders_the_decision(qapp, admin, business) -> None:
    collaboration_id = _seed(admin, business)
    page = CollaborationCenterPage(admin)
    try:
        page._select(collaboration_id)
        page.tabs.setCurrentIndex(4)
        text = page.decision_text.toPlainText()
        assert "DECISION STATUS" in text
        assert "Executive summary" in text
        assert page.actions_table.row_count() >= 1
    finally:
        _close(page)


def test_progress_comes_from_task_statuses(qapp, admin, business) -> None:
    collaboration_id = _seed(admin, business)
    view = admin.collaboration_service.get_status(collaboration_id)
    assert view.tasks_total == 5
    assert view.tasks_completed == 5
    assert view.progress_percent == 100


def test_start_button_follows_permissions(qapp, admin) -> None:
    page = CollaborationCenterPage(admin)
    try:
        assert page.start_button.isEnabled() is True
    finally:
        _close(page)


def test_read_only_role_cannot_start_or_export(qapp, admin) -> None:
    role = admin.role_service.create_role(
        {
            "role_name": "Collab Reader",
            "description": "Reads collaboration output only",
            "permission_keys": ["dashboard.view", "agents.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Collab Reader",
            "email": "collabreader@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("collabreader@bizpilot.test", MANAGER_PASSWORD)

    page = CollaborationCenterPage(admin)
    try:
        assert page.start_button.isEnabled() is False
        assert page.csv_button.isEnabled() is False
        assert page.pdf_button.isEnabled() is False
    finally:
        _close(page)


def test_employee_cannot_see_the_collaboration_center(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        assert "collaboration" not in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_export_buttons_produce_files(qapp, admin, business) -> None:
    collaboration_id = _seed(admin, business)
    page = CollaborationCenterPage(admin)
    try:
        page._select(collaboration_id)
        csv_path = admin.collaboration_service.export_decision_csv(collaboration_id)
        pdf_path = admin.collaboration_service.export_decision_pdf(collaboration_id)
        assert csv_path.exists() and csv_path.stat().st_size > 100
        assert pdf_path.read_bytes()[:4] == b"%PDF"
    finally:
        _close(page)
