"""UI tests for the Phase 2 business pages (offscreen Qt)."""

from __future__ import annotations

import pytest

from app.ui.main_window import MainWindow

from tests.conftest import completed_sale


def _close(widget) -> None:
    if widget is not None:
        widget.close()
        widget.deleteLater()


def test_business_pages_render_real_rows(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    window = MainWindow(admin)
    try:
        window.navigate_to("sales")
        sales = window.page_for("sales")
        assert sales.table.row_count() == 1

        window.navigate_to("inventory")
        inventory = window.page_for("inventory")
        assert inventory.products_table.row_count() == 2
        assert inventory.stock_table.row_count() == 2
        assert inventory.movements_table.row_count() >= 3  # 2 openings + 1 sale

        window.navigate_to("customers")
        customers = window.page_for("customers")
        assert customers.table.row_count() == 1

        window.navigate_to("suppliers")
        suppliers = window.page_for("suppliers")
        assert suppliers.table.row_count() == 1

        window.navigate_to("finance")
        finance = window.page_for("finance")
        assert finance.transaction_table.row_count() >= 1
        assert finance.report_table.row_count() >= 1
    finally:
        _close(window)


def test_dashboard_reflects_a_completed_sale(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    window = MainWindow(admin)
    try:
        dashboard = window.page_for("overview")
        cards = {card._title.text(): card for card in dashboard._stat_cards}
        assert cards["Total Revenue"].value_text == "300.00"
        assert cards["Total Sales"].value_text == "300.00"
        assert cards["Inventory Items"].value_text == "2"
        # The revenue chart now has data and shows the plot, not the empty state.
        assert (
            dashboard._revenue_chart._stack.currentWidget()
            is dashboard._revenue_chart._plot
        )
    finally:
        _close(window)


def test_employee_sidebar_hides_business_modules(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        visible = set(window.sidebar.visible_keys())
        assert "overview" in visible
        for module in ("finance", "sales", "customers", "inventory", "suppliers"):
            assert module not in visible
    finally:
        _close(window)


def test_sales_actions_disabled_without_selection(qapp, admin, business) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("sales")
        page = window.page_for("sales")
        page.table.clear_selection()
        page._update_actions()
        assert page.complete_button.isEnabled() is False
        assert page.cancel_button.isEnabled() is False
        assert page.payment_button.isEnabled() is False
        # Creating an order is always available to a permitted user.
        assert page.new_button.isEnabled() is True
    finally:
        _close(window)


def test_finance_page_has_all_tabs(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("finance")
        page = window.page_for("finance")
        labels = [page.tabs.tabText(index) for index in range(page.tabs.count())]
        assert labels == ["Overview", "Expenses", "Transactions", "Reports"]
    finally:
        _close(window)


def test_inventory_tabs_and_low_stock_list(qapp, admin, business) -> None:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 6,
            "movement_type": "ADJUSTMENT",
            "reason": "Dropped below minimum",
            "direction": -1,
        }
    )
    window = MainWindow(admin)
    try:
        window.navigate_to("inventory")
        page = window.page_for("inventory")
        assert page.low_table.row_count() == 1
        assert page.card_low.value_text == "1"
    finally:
        _close(window)


def test_customer_profile_panel_populates(qapp, admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    window = MainWindow(admin)
    try:
        window.navigate_to("customers")
        page = window.page_for("customers")
        page.table.table.selectRow(0)
        assert "Test Customer" in page.profile_name.text()
        assert "Outstanding" in page.profile_stats.text()
        assert page.invoice_list.count() == 1
    finally:
        _close(window)


def test_supplier_purchase_orders_tab(qapp, admin, business) -> None:
    po = admin.purchasing_service.create_purchase_order(
        {
            "supplier_id": business["supplier"].id,
            "items": [
                {"product_id": business["tea"].id, "ordered_quantity": 10, "unit_cost": "90.00"}
            ],
        }
    )
    admin.purchasing_service.approve_purchase_order(po.id)
    window = MainWindow(admin)
    try:
        window.navigate_to("suppliers")
        page = window.page_for("suppliers")
        assert page.orders_table.row_count() == 1
        page.orders_table.table.selectRow(0)
        assert page.receive_button.isEnabled() is True
        assert page.approve_button.isEnabled() is False
    finally:
        _close(window)


def test_read_only_role_disables_mutating_buttons(qapp, admin, business) -> None:
    from tests.conftest import MANAGER_PASSWORD, create_user

    create_user(admin, "Finance Manager", "fin@bizpilot.test", MANAGER_PASSWORD, "Finance User")
    admin.auth_service.logout()
    admin.auth_service.login("fin@bizpilot.test", MANAGER_PASSWORD)

    window = MainWindow(admin)
    try:
        window.navigate_to("finance")
        page = window.page_for("finance")
        assert page.add_expense_button.isEnabled() is True  # finance.create
        assert page.reverse_button.isEnabled() is True  # finance.approve
        # Sales page is visible to a finance manager but cannot create orders.
        window.navigate_to("sales")
        sales = window.page_for("sales")
        assert sales.new_button.isEnabled() is False
    finally:
        _close(window)
