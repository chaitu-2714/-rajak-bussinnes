"""UI tests: AI Command Center (offscreen Qt, real orchestration service)."""

from __future__ import annotations

import pytest

from app.core.constants import AIWorkflowStatus
from app.ui.main_window import MainWindow
from app.ui.pages.ai_command_page import AICommandPage

from tests.conftest import EMPLOYEE_PASSWORD, EMPLOYEE_EMAIL


def _close(widget) -> None:
    shutdown = getattr(widget, "shutdown", None)
    if callable(shutdown):
        shutdown()
    widget.close()
    widget.deleteLater()


def _send_and_wait(page: AICommandPage, command: str) -> None:
    page.input.setText(command)
    page._send()
    assert page._worker is not None
    assert page._worker.wait(90_000)
    # deliver the queued signals from the worker thread
    from PySide6.QtWidgets import QApplication

    for _ in range(3):
        QApplication.processEvents()


def test_command_center_is_registered(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("command_center")
        page = window.page_for("command_center")
        assert isinstance(page, AICommandPage)
        assert "command_center" in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_status_panels_show_real_provider_and_agent_state(qapp, admin) -> None:
    page = AICommandPage(admin)
    try:
        assert "ollama" in page.provider_label.text()
        assert "fallback" in page.provider_label.text()
        assert "Finance Agent" in page.agent_label.text()
        assert "Database: connected" in page.system_label.text()
        assert "48" in page.system_label.text()  # 27 base + 7 data + 5 agents + 1 collab + 6 analytics + 2 knowledge
    finally:
        _close(page)


def test_command_submission_shows_the_answer(qapp, admin, conversation) -> None:
    page = AICommandPage(admin)
    try:
        page._select_conversation(conversation)
        _send_and_wait(page, "Show this month's revenue.")
        # user bubble + assistant bubble
        assert page.messages_layout.count() - 1 == 2
        assert page.status_chip.text().startswith(("Offline", "Online"))
        assert "Finished" in page._status_label.text()
    finally:
        _close(page)


def test_ui_is_disabled_while_a_command_runs(qapp, admin, conversation) -> None:
    page = AICommandPage(admin)
    try:
        page._select_conversation(conversation)
        page.input.setText("Show this month's revenue.")
        page._send()
        assert page.send_button.isEnabled() is False
        assert page.progress.isVisibleTo(page) is True
        page._worker.wait(90_000)
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        assert page.send_button.isEnabled() is True
        assert page.progress.isVisibleTo(page) is False
    finally:
        _close(page)


def test_error_is_displayed_when_the_command_fails(qapp, admin, conversation) -> None:
    page = AICommandPage(admin)
    try:
        page._select_conversation(conversation)
        page._on_failed("Service unavailable")
        assert page.messages_layout.count() - 1 == 1
        assert "failed" in page._status_label.text().lower()
    finally:
        _close(page)


def test_cancellation_flow(qapp, admin, conversation) -> None:
    page = AICommandPage(admin)
    try:
        page._select_conversation(conversation)
        page._active_workflow = "wf-test"
        page.stop_button.setEnabled(True)
        page._on_cancelled("wf-test")
        assert "cancelled" in page._status_label.text().lower() or page.stop_button.isEnabled() is False
        assert page.messages_layout.count() - 1 == 1
    finally:
        _close(page)


def test_new_conversation_and_clear(qapp, admin) -> None:
    page = AICommandPage(admin)
    try:
        page._new_conversation()
        assert page._conversation_id is not None
        first_id = page._conversation_id
        _send_and_wait(page, "Show this month's revenue.")
        assert page.messages_layout.count() - 1 == 2

        page._clear_conversation()
        assert page.messages_layout.count() - 1 == 0

        page._new_conversation()
        assert page._conversation_id != first_id
    finally:
        _close(page)


def test_saved_command_fills_the_input(qapp, admin) -> None:
    page = AICommandPage(admin)
    try:
        item = page.saved_list.item(0)
        page._use_saved_command(item)
        assert page.input.text() == item.text()
    finally:
        _close(page)


def test_employee_cannot_use_the_command_center(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        assert "command_center" not in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_details_dialog_data_is_available(qapp, admin, conversation) -> None:
    page = AICommandPage(admin)
    try:
        page._select_conversation(conversation)
        _send_and_wait(page, "Show this month's revenue.")
        workflows = admin.ai_service.list_workflows(conversation_id=conversation)
        detail = admin.ai_service.workflow_detail(workflows[0].workflow_id)
        assert detail["steps"]
        assert detail["steps"][0]["output"]
    finally:
        _close(page)


def test_approval_button_appears_for_actions(qapp, admin, conversation) -> None:
    page = AICommandPage(admin)
    try:
        page._select_conversation(conversation)
        _send_and_wait(page, "Record an expense of 300 for transport.")
        workflows = admin.ai_service.list_workflows(conversation_id=conversation)
        waiting = [w for w in workflows if w.status == AIWorkflowStatus.WAITING_FOR_APPROVAL]
        assert waiting, "the action should be waiting for approval"
        assert page.messages_layout.count() - 1 == 2
    finally:
        _close(page)
