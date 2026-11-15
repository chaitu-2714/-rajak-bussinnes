"""UI tests: the Security Center reflects real records."""

from __future__ import annotations

import pytest

from app.ui.main_window import MainWindow
from app.ui.pages.security_center import SecurityCenterPage

from tests.conftest import completed_sale


def _close(widget) -> None:
    shutdown = getattr(widget, "shutdown", None)
    if callable(shutdown):
        shutdown()
    widget.close()
    widget.deleteLater()


def _page(admin) -> SecurityCenterPage:
    page = SecurityCenterPage(admin)
    page.wait_for_idle()
    return page


def test_page_is_registered_and_reachable(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("security")
        page = window.page_for("security")
        assert isinstance(page, SecurityCenterPage)
        assert "security" in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_overview_shows_real_values(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    page = _page(admin)
    try:
        assert page.card_sessions.value_text != "0"
        assert "Audit chain" in page.integrity_label.text()
        assert page.users_table.row_count() >= 1
    finally:
        _close(page)


def test_agent_and_governance_tables_are_populated(qapp, admin) -> None:
    page = _page(admin)
    try:
        assert page.agent_table.row_count() >= 5
        assert page.governance_table.row_count() >= 8
    finally:
        _close(page)


def test_audit_chain_verification_from_the_ui(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    page = _page(admin)
    try:
        page._verify_chain()
        page.wait_for_idle()
        assert "Chain intact" in page.integrity_text.toPlainText()
    finally:
        _close(page)


def test_employee_cannot_see_the_security_center(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        assert "security" not in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_backup_can_be_created_from_the_ui(qapp, admin) -> None:
    page = _page(admin)
    try:
        page._create_backup()
        page.wait_for_idle()
        text = page.backup_detail.toPlainText()
        assert "VERIFIED" in text or "bak-" in text
        # The page refreshes itself; wait for that refresh to land.
        page.refresh()
        page.wait_for_idle()
        assert page.backup_table.row_count() >= 1
    finally:
        _close(page)
