"""UI tests: the Business Intelligence dashboard shows real analytics (test 15)."""

from __future__ import annotations

import pytest

from app.ui.main_window import MainWindow
from app.ui.pages.business_intelligence import BusinessIntelligencePage

from tests.conftest import completed_sale


def _close(widget) -> None:
    shutdown = getattr(widget, "shutdown", None)
    if callable(shutdown):
        shutdown()
    widget.close()
    widget.deleteLater()


def _page(admin) -> BusinessIntelligencePage:
    page = BusinessIntelligencePage(admin)
    page.wait_for_idle()
    return page


def test_page_is_registered_and_reachable(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("analytics")
        page = window.page_for("analytics")
        assert isinstance(page, BusinessIntelligencePage)
        assert "analytics" in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_dashboard_reflects_real_analytics(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=2)  # 300.00 revenue
    page = _page(admin)
    try:
        assert page.card_revenue.value_text == "300.00"
        assert page.card_cash.value_text == "0.00"  # invoiced but not collected
        assert page.card_receivables.value_text == "300.00"
        assert page.kpi_table.row_count() >= 15
        assert page.product_table.row_count() == 1
        assert page.segment_table.row_count() == 6
        assert page.risk_table.row_count() >= 5
        assert "revenue" in page.insights_text.toPlainText().lower()
    finally:
        _close(page)


def test_cards_match_the_service_output(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=3)
    bundle = admin.analytics_service.analyze("MONTHLY")
    page = _page(admin)
    try:
        assert page.card_revenue.value_text == f"{bundle.financial.revenue:,.2f}"
        assert page.card_expenses.value_text == f"{bundle.financial.operating_expenses:,.2f}"
        assert page.quality_label.text().startswith(bundle.period.label)
    finally:
        _close(page)


def test_forecast_tab_separates_estimates_from_actuals(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    page = _page(admin)
    try:
        outcome = admin.analytics_service.forecast("SALES", horizon=1)
        page._on_forecast(outcome)
        text = page.forecast_text.toPlainText()
        if outcome.status == "COMPLETED":
            assert "Forecast (estimates, not actual results)" in text
            assert "Measured error on validation" in text
        else:
            assert "INSUFFICIENT_HISTORICAL_DATA" in text
    finally:
        _close(page)


def test_simulation_tab_shows_the_hypothetical_label(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    page = _page(admin)
    try:
        outcome = admin.analytics_service.simulate("SALES_DECLINE", parameters={"percent": 10})
        page._on_simulation(outcome)
        assert page.simulation_table.row_count() >= 1
        assert "HYPOTHETICAL" in page.simulation_text.toPlainText()
    finally:
        _close(page)


def test_employee_cannot_see_the_bi_dashboard(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        assert "analytics" not in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_read_only_role_cannot_simulate_from_the_ui(qapp, admin) -> None:
    from tests.conftest import MANAGER_PASSWORD

    role = admin.role_service.create_role(
        {
            "role_name": "BI Reader",
            "description": "Read-only BI",
            "permission_keys": ["dashboard.view", "analytics.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "BI Reader",
            "email": "bireader@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("bireader@bizpilot.test", MANAGER_PASSWORD)

    page = _page(admin)
    try:
        assert page.simulate_button.isEnabled() is False
        assert page.ack_button.isEnabled() is False
        assert page.forecast_button.isEnabled() is True  # reading is allowed
    finally:
        _close(page)
