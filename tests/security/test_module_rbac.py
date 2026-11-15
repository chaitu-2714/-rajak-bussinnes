"""Security tests for the Phase 2 modules (service-level RBAC)."""

from __future__ import annotations

import pytest

from app.core.exceptions import AuthorizationError

from tests.conftest import MANAGER_PASSWORD, create_user, seed_business


def _login_as(admin, role: str, email: str) -> None:
    create_user(admin, role, email, MANAGER_PASSWORD, f"{role} User")
    admin.auth_service.logout()
    admin.auth_service.login(email, MANAGER_PASSWORD)


def test_employee_cannot_touch_business_modules(employee_context) -> None:
    with pytest.raises(AuthorizationError):
        employee_context.finance_service.summary()
    with pytest.raises(AuthorizationError):
        employee_context.sales_service.list_orders()
    with pytest.raises(AuthorizationError):
        employee_context.customer_service.list_customers()
    with pytest.raises(AuthorizationError):
        employee_context.inventory_service.list_products()
    with pytest.raises(AuthorizationError):
        employee_context.purchasing_service.list_suppliers()


def test_employee_cannot_create_an_expense(employee_context) -> None:
    with pytest.raises(AuthorizationError):
        employee_context.finance_service.create_expense(
            {
                "expense_category": "OTHER",
                "description": "Sneaky",
                "amount": "10.00",
                "payment_method": "CASH",
                "expense_date": "2026-11-01T09:00:00",
            }
        )


def test_finance_manager_cannot_create_sales(admin, business) -> None:
    _login_as(admin, "Finance Manager", "finance@bizpilot.test")
    assert admin.finance_service.summary()  # allowed
    with pytest.raises(AuthorizationError):
        admin.sales_service.create_order(
            {
                "customer_id": business["customer"].id,
                "items": [{"product_id": business["tea"].id, "quantity": 1}],
            }
        )


def test_finance_manager_cannot_adjust_stock(admin, business) -> None:
    _login_as(admin, "Finance Manager", "finance2@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.inventory_service.adjust_stock(
            {
                "product_id": business["tea"].id,
                "quantity": 1,
                "movement_type": "ADJUSTMENT",
                "reason": "Not allowed",
            }
        )


def test_finance_manager_cannot_export_customers(admin, business) -> None:
    _login_as(admin, "Finance Manager", "finance3@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.customer_service.export_customers_csv()


def test_inventory_manager_cannot_approve_purchase_orders(admin, business) -> None:
    po = admin.purchasing_service.create_purchase_order(
        {
            "supplier_id": business["supplier"].id,
            "items": [
                {"product_id": business["tea"].id, "ordered_quantity": 5, "unit_cost": "90.00"}
            ],
        }
    )
    _login_as(admin, "Inventory Manager", "inventory@bizpilot.test")
    assert admin.purchasing_service.list_purchase_orders()
    with pytest.raises(AuthorizationError):
        admin.purchasing_service.approve_purchase_order(po.id)


def test_inventory_manager_cannot_view_finance(admin) -> None:
    _login_as(admin, "Inventory Manager", "inventory2@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.finance_service.summary()


def test_sales_manager_cannot_cancel_without_permission(admin, business) -> None:
    """A custom role without sales.cancel cannot cancel, even with sales.view."""
    role = admin.role_service.create_role(
        {
            "role_name": "Order Viewer",
            "description": "Can see orders but not change them",
            "permission_keys": ["dashboard.view", "sales.view", "customers.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Viewer User",
            "email": "viewer@bizpilot.test",
            "password": "Viewer!Passw0rd1",
            "password_confirm": "Viewer!Passw0rd1",
            "role_ids": [role.id],
        }
    )
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [{"product_id": business["tea"].id, "quantity": 1}],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("viewer@bizpilot.test", "Viewer!Passw0rd1")

    assert admin.sales_service.list_orders()
    with pytest.raises(AuthorizationError):
        admin.sales_service.cancel_order(order.id, "Not permitted")


def test_business_admin_cannot_receive_goods(admin, business) -> None:
    po = admin.purchasing_service.create_purchase_order(
        {
            "supplier_id": business["supplier"].id,
            "items": [
                {"product_id": business["tea"].id, "ordered_quantity": 5, "unit_cost": "90.00"}
            ],
        }
    )
    admin.purchasing_service.approve_purchase_order(po.id)
    _login_as(admin, "Business Admin", "bizadmin@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.purchasing_service.receive_goods(
            {
                "purchase_order_id": po.id,
                "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": 1}],
            }
        )


def test_business_admin_cannot_create_products(admin) -> None:
    _login_as(admin, "Business Admin", "bizadmin2@bizpilot.test")
    assert admin.inventory_service.list_products() == []
    with pytest.raises(AuthorizationError):
        admin.inventory_service.create_product({"product_name": "Nope"})


def test_sales_manager_can_sell_but_not_reverse_expenses(admin, business) -> None:
    _login_as(admin, "Sales Manager", "sales@bizpilot.test")
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [{"product_id": business["tea"].id, "quantity": 1}],
        }
    )
    assert order.order_status == "DRAFT"
    with pytest.raises(AuthorizationError):
        admin.finance_service.reverse_expense(1, "Not allowed")
