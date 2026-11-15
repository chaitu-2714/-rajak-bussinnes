"""UI tests: the AI Agents monitoring dashboard."""

from __future__ import annotations

import pytest

from app.ui.main_window import MainWindow
from app.ui.pages.agents_page import AgentsPage

from tests.conftest import completed_sale


def _close(widget) -> None:
    shutdown = getattr(widget, "shutdown", None)
    if callable(shutdown):
        shutdown()
    widget.close()
    widget.deleteLater()


def _seed(admin, business) -> None:
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
    admin.agent_manager.run_agent("finance_agent", period="this_month")
    admin.agent_manager.run_agent("inventory_agent")


def test_agents_page_is_registered(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("agents")
        page = window.page_for("agents")
        assert isinstance(page, AgentsPage)
        assert "agents" in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_five_agent_cards_render(qapp, admin, business) -> None:
    _seed(admin, business)
    page = AgentsPage(admin)
    try:
        assert page.cards_grid.count() == 5
        assert page._agents
        assert {agent["info"]["agent_code"] for agent in page._agents} == {
            "finance_agent",
            "sales_agent",
            "customer_agent",
            "inventory_agent",
            "business_intelligence_agent",
        }
    finally:
        _close(page)


def test_selecting_an_agent_shows_its_history(qapp, admin, business) -> None:
    _seed(admin, business)
    page = AgentsPage(admin)
    try:
        page._select("finance_agent")
        assert "Finance Agent" in page.overview_title.text()
        assert page.findings_table.row_count() >= 1
        assert page.executions_table.row_count() == 1
        assert "Executions: 1" in page.overview_body.toPlainText()
    finally:
        _close(page)


def test_run_button_follows_permissions(qapp, admin) -> None:
    page = AgentsPage(admin)
    try:
        page._select("finance_agent")
        assert page.run_button.isEnabled() is True
    finally:
        _close(page)


def test_read_only_role_cannot_run_agents(qapp, admin) -> None:
    from tests.conftest import MANAGER_PASSWORD, create_user

    role = admin.role_service.create_role(
        {
            "role_name": "Agent Reader",
            "description": "Views agent output only",
            "permission_keys": ["dashboard.view", "agents.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Agent Reader",
            "email": "reader@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("reader@bizpilot.test", MANAGER_PASSWORD)

    page = AgentsPage(admin)
    try:
        page._select("finance_agent")
        assert page.run_button.isEnabled() is False
        assert page.accept_button.isEnabled() is False
    finally:
        _close(page)


def test_recommendation_status_updates_from_the_page(qapp, admin, business) -> None:
    _seed(admin, business)
    page = AgentsPage(admin)
    try:
        page._select("finance_agent")
        if page.recommendations_table.row_count() == 0:
            pytest.skip("no recommendations for this dataset")
        page.recommendations_table.table.selectRow(0)
        recommendation_id = page.recommendations_table.selected_id()
        page._set_status("ACCEPTED")
        page._select("finance_agent")
        statuses = [
            page.recommendations_table.table.item(row, 2).text()
            for row in range(page.recommendations_table.row_count())
        ]
        assert "ACCEPTED" in statuses
        assert recommendation_id is not None
    finally:
        _close(page)


def test_employee_does_not_see_the_agents_module(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        assert "agents" not in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_command_center_shows_agent_answer(qapp, admin, business) -> None:
    from PySide6.QtWidgets import QApplication

    _seed(admin, business)
    window = MainWindow(admin)
    try:
        window.navigate_to("command_center")
        page = window.page_for("command_center")
        page._new_conversation()
        page.input.setText("Analyze my monthly finances.")
        page._send()
        assert page._worker.wait(120_000)
        for _ in range(4):
            QApplication.processEvents()
        assert page.messages_layout.count() - 1 == 2
        workflows = admin.ai_service.list_workflows(limit=1)
        detail = admin.ai_service.workflow_detail(workflows[0].workflow_id)
        assert detail["steps"][0]["output"]["findings"]
    finally:
        _close(window)
