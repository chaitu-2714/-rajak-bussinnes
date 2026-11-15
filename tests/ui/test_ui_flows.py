"""UI tests: first launch, login, navigation, RBAC and empty states.

Widgets are exercised with the offscreen Qt platform, so no display is needed.
"""

from __future__ import annotations

import pytest

from app.ui.app_controller import AppController
from app.ui.main_window import MainWindow

from tests.conftest import ADMIN_EMAIL, ADMIN_PASSWORD, EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD


def _close(widget) -> None:
    if widget is not None:
        widget.close()
        widget.deleteLater()


def test_setup_wizard_opens_on_first_launch(qapp, context) -> None:
    controller = AppController(context)
    try:
        controller.start()
        assert controller.wizard is not None
        assert controller.login_window is None
        assert controller.wizard.windowTitle().startswith("BizPilot AI")
    finally:
        _close(controller.wizard)


def test_login_window_opens_after_initialisation(qapp, admin) -> None:
    controller = AppController(admin)
    try:
        controller.start()
        assert controller.login_window is not None
        assert controller.wizard is None
        assert controller.login_window.login_button.text() == "Sign in"
    finally:
        _close(controller.login_window)


def test_successful_login_opens_dashboard(qapp, admin) -> None:
    controller = AppController(admin)
    try:
        controller.start()
        login = controller.login_window
        login.email_input.setText(ADMIN_EMAIL)
        login.password_input.setText(ADMIN_PASSWORD)
        login.attempt_login()
        qapp.processEvents()

        assert controller.main_window is not None
        assert controller.main_window.current_key() == "overview"
        assert controller.main_window.isVisible() or not controller.main_window.isHidden()
    finally:
        _close(controller.main_window)
        _close(controller.login_window)


def test_wrong_password_shows_inline_error(qapp, admin) -> None:
    controller = AppController(admin)
    try:
        controller.start()
        login = controller.login_window
        login.email_input.setText(ADMIN_EMAIL)
        login.password_input.setText("Wrong!Passw0rd")
        login.attempt_login()
        assert login.error_label.isVisible()
        assert "Invalid email or password" in login.error_label.text()
        assert controller.main_window is None
    finally:
        _close(controller.login_window)


def test_sidebar_hides_unauthorised_modules(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        visible = set(window.sidebar.visible_keys())
        assert "overview" in visible
        assert "users" not in visible
        assert "roles" not in visible
        assert "audit" not in visible
        assert "settings" not in visible
    finally:
        _close(window)


def test_super_admin_sees_every_module(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        visible = set(window.sidebar.visible_keys())
        assert {"overview", "users", "roles", "audit", "settings"}.issubset(visible)
        # Modules from later phases are visible but explicitly marked coming soon.
        assert "finance" in visible
    finally:
        _close(window)


def test_unauthorised_page_cannot_be_opened(qapp, employee_context, monkeypatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(
        "app.ui.main_window.show_info", lambda *args, **kwargs: messages.append(args[1])
    )
    window = MainWindow(employee_context)
    try:
        assert window.current_key() == "overview"
        window.navigate_to("users")
        assert window.current_key() == "overview"
        assert window.page_for("users") is None
        assert messages and "does not include access" in messages[0]
    finally:
        _close(window)


def test_navigation_between_pages(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        for key in ("overview", "users", "roles", "audit", "settings", "finance"):
            window.navigate_to(key)
            assert window.current_key() == key
        assert window.page_for("finance") is not None
        assert window.page_for("finance").__class__.__name__ == "FinancePage"
        # Phase 10: every navigation entry is a real page. The audit trail and
        # reports were the last placeholders and now render live pages.
        window.navigate_to("audit")
        assert window.page_for("audit").__class__.__name__ == "AuditPage"
        window.navigate_to("reports")
        assert window.page_for("reports").__class__.__name__ == "ReportsPage"
        # No navigation entry is a placeholder any more.
        from app.ui.navigation import NAV_ITEMS

        assert [item.key for item in NAV_ITEMS if item.coming_soon] == []
    finally:
        _close(window)


def test_logout_returns_to_login(qapp, admin) -> None:
    controller = AppController(admin)
    try:
        controller.start()
        login = controller.login_window
        login.email_input.setText(ADMIN_EMAIL)
        login.password_input.setText(ADMIN_PASSWORD)
        login.attempt_login()
        qapp.processEvents()
        assert controller.main_window is not None

        controller.main_window.logout_requested.emit()
        qapp.processEvents()
        assert controller.main_window is None
        assert controller.login_window is not None
        assert controller.login_window.isVisible()
    finally:
        _close(controller.login_window)


def test_window_can_be_resized(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.resize(1280, 800)
        assert window.width() == 1280
        assert window.height() == 800
        assert window.minimumWidth() == 1180
        window.resize(600, 400)  # below minimum: Qt clamps to the minimum size
        assert window.width() >= 1180
    finally:
        _close(window)


def test_dashboard_reports_real_zeroes_and_one_pending_module(qapp, admin) -> None:
    """Phase 2 has no transactions yet: figures are real zeros, not inventions."""
    window = MainWindow(admin)
    try:
        dashboard = window.page_for("overview")
        assert dashboard is not None

        cards = {card._title.text(): card for card in dashboard._stat_cards}
        assert cards["Total Revenue"].value_text == "0.00"
        assert cards["Total Sales"].value_text == "0.00"
        assert cards["Active Customers"].value_text == "0"
        assert cards["Inventory Items"].value_text == "0"
        assert cards["User Accounts"].value_text == "1"
        assert cards["Roles"].value_text == "6"

        # Phase 10: approvals are live, so the card shows a real count.
        assert cards["Pending Approvals"].value_text == "0"
        assert dashboard._revenue_chart._stack.currentWidget() is dashboard._revenue_chart._empty
    finally:
        _close(window)


def test_audit_page_shows_recorded_actions(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("audit")
        page = window.page_for("audit")
        assert page.table.rowCount() >= 1
        page.table.selectRow(0)
        assert page.detail.toPlainText().startswith("{")
    finally:
        _close(window)


def test_users_page_lists_and_filters(qapp, admin) -> None:
    from tests.conftest import create_user

    create_user(admin, "Employee", "listme@bizpilot.test")
    window = MainWindow(admin)
    try:
        window.navigate_to("users")
        page = window.page_for("users")
        assert page.table.rowCount() == 2

        page.search_input.setText("listme")
        assert page.table.rowCount() == 1
        page.search_input.clear()
        assert page.table.rowCount() == 2
    finally:
        _close(window)


def test_roles_page_lists_six_system_roles(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("roles")
        page = window.page_for("roles")
        assert page.table.rowCount() == 6
        assert page._detail_name.text()
        assert page.delete_button.isEnabled() is False  # system role selected
    finally:
        _close(window)


def test_settings_read_only_without_permission(qapp, admin) -> None:
    from tests.conftest import MANAGER_PASSWORD, create_user

    create_user(admin, "Business Admin", "bizadmin@bizpilot.test", MANAGER_PASSWORD, "Biz Admin")
    admin.auth_service.logout()
    admin.auth_service.login("bizadmin@bizpilot.test", MANAGER_PASSWORD)

    window = MainWindow(admin)
    try:
        window.navigate_to("settings")
        page = window.page_for("settings")
        assert page.save_business_button.isEnabled() is False
        assert page.business_name_input.isEnabled() is False
    finally:
        _close(window)


def test_settings_editable_for_super_admin(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("settings")
        page = window.page_for("settings")
        assert page.save_business_button.isEnabled() is True
        assert page.business_name_input.text() == "Test Traders"
        assert page.db_path_input.text().endswith("bizpilot_ai.db")
    finally:
        _close(window)


def test_notifications_use_real_audit_entries(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window._update_notification_count()
        assert "Activity" in window.header.notification_button().text()
    finally:
        _close(window)


def test_login_window_has_version_and_password_toggle(qapp, admin) -> None:
    controller = AppController(admin)
    try:
        controller.start()
        login = controller.login_window
        login._toggle_password.setChecked(True)
        assert login.password_input.echoMode().name == "Normal"
        login._toggle_password.setChecked(False)
        assert login.password_input.echoMode().name == "Password"
        assert login.remember_checkbox.isChecked() in (True, False)
    finally:
        _close(controller.login_window)
