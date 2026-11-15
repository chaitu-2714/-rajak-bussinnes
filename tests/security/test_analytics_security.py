"""Security tests for the analytics layer (test 18)."""

from __future__ import annotations

import pytest

from app.core.exceptions import AuthorizationError, ValidationError

from tests.conftest import MANAGER_PASSWORD, completed_sale


def test_employee_cannot_access_analytics(employee_context) -> None:
    with pytest.raises(AuthorizationError):
        employee_context.analytics_service.analyze("MONTHLY")
    with pytest.raises(AuthorizationError):
        employee_context.analytics_service.list_anomalies()


def test_employee_cannot_forecast_or_simulate(employee_context) -> None:
    with pytest.raises(AuthorizationError):
        employee_context.analytics_service.forecast("SALES")
    with pytest.raises(AuthorizationError):
        employee_context.analytics_service.simulate("SALES_DECLINE", parameters={"percent": 5})


def test_view_only_role_cannot_review_or_simulate(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    role = admin.role_service.create_role(
        {
            "role_name": "BI Viewer",
            "description": "Read-only business intelligence",
            "permission_keys": [
                "dashboard.view",
                "analytics.view",
                "sales.view",
                "finance.view",
                "inventory.view",
                "customers.view",
                "purchase_orders.view",
                "suppliers.view",
            ],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "BI Viewer",
            "email": "biviewer@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("biviewer@bizpilot.test", MANAGER_PASSWORD)

    bundle = admin.analytics_service.analyze("MONTHLY")
    assert bundle.period.label  # reading analytics is allowed
    with pytest.raises(AuthorizationError):
        admin.analytics_service.simulate("SALES_DECLINE", parameters={"percent": 5})
    with pytest.raises(AuthorizationError):
        admin.analytics_service.review_anomaly("anm-unknown", decision="ACKNOWLEDGED")
    with pytest.raises(AuthorizationError):
        admin.analytics_service.generate_report("EXECUTIVE_PERFORMANCE")


def test_analytics_inherit_the_users_module_permissions(admin, business) -> None:
    """Analytics aggregates modules, so it needs their read permissions too."""
    completed_sale(admin, business, quantity=1)
    role = admin.role_service.create_role(
        {
            "role_name": "Sales Analyst",
            "description": "Sales analytics without finance access",
            "permission_keys": [
                "dashboard.view",
                "analytics.view",
                "analytics.manage",
                "sales.view",
            ],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Sales Analyst",
            "email": "salesanalyst@bizpilot.test",
            "password": MANAGER_PASSWORD,
            "password_confirm": MANAGER_PASSWORD,
            "role_ids": [role.id],
        }
    )
    admin.auth_service.logout()
    admin.auth_service.login("salesanalyst@bizpilot.test", MANAGER_PASSWORD)

    # The finance collector raises AuthorizationError, so no financial figure leaks.
    with pytest.raises(AuthorizationError):
        admin.analytics_service.analyze("MONTHLY")


def test_unknown_report_type_is_rejected(admin, business) -> None:
    with pytest.raises((ValueError, ValidationError)):
        admin.analytics_service.generate_report("DROP_TABLE")


def test_unknown_forecast_target_is_rejected(admin, business) -> None:
    with pytest.raises(ValidationError):
        admin.analytics_service.forecast("PROFIT")


def test_invalid_forecast_horizon_is_rejected(admin, business) -> None:
    with pytest.raises(ValidationError):
        admin.analytics_service.forecast("SALES", horizon=99)


def test_invalid_anomaly_review_decision_is_rejected(admin, business) -> None:
    with pytest.raises(ValidationError):
        admin.analytics_service.review_anomaly("anm-1", decision="IGNORE")


def test_analytics_never_modify_business_records(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    orders_before = len(admin.sales_service.list_orders())
    expenses_before = len(admin.finance_service.list_expenses())
    stock_before = [(row.sku, row.available_quantity) for row in admin.inventory_service.list_stock()]

    admin.analytics_service.analyze("MONTHLY")
    admin.analytics_service.forecast("SALES", horizon=1)
    admin.analytics_service.simulate("PRICE_INCREASE", parameters={"percent": 5})
    admin.analytics_service.generate_report("EXECUTIVE_PERFORMANCE")

    assert len(admin.sales_service.list_orders()) == orders_before
    assert len(admin.finance_service.list_expenses()) == expenses_before
    assert [
        (row.sku, row.available_quantity) for row in admin.inventory_service.list_stock()
    ] == stock_before


def test_report_generation_is_audited(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    admin.analytics_service.generate_report("FINANCIAL_ANALYTICS", file_format="CSV")
    actions = {entry.action for entry in admin.audit_service.list_entries()}
    assert "ANALYTICS_REPORT_GENERATED" in actions


def test_anomaly_review_is_audited(admin, business) -> None:
    from tests.analytics_helpers import record_expense

    for amount in ("1000.00", "1100.00", "950.00"):
        record_expense(admin, amount=amount, category="RENT")
    record_expense(admin, amount="60000.00", category="RENT")
    rows = admin.analytics_service.list_anomalies() if admin.analytics_service.anomalies("MONTHLY") else []
    if rows:
        admin.analytics_service.review_anomaly(rows[0]["anomaly_id"], decision="DISMISSED")
    actions = {entry.action for entry in admin.audit_service.list_entries()}
    assert "ANOMALY_REVIEWED" in actions
