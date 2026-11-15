"""Security tests: role-based access control at the service layer."""

from __future__ import annotations

import pytest

from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    ProtectedRecordError,
)
from app.security.authorization import get_user_permissions, has_permission
from app.database.models.user import User

from tests.conftest import (
    ADMIN_EMAIL,
    ADMIN_PASSWORD,
    EMPLOYEE_EMAIL,
    EMPLOYEE_PASSWORD,
    MANAGER_PASSWORD,
    create_user,
)


def _login_as(admin, role_name: str, email: str, password: str = MANAGER_PASSWORD) -> None:
    create_user(admin, role_name, email, password, f"{role_name} User")
    admin.auth_service.logout()
    admin.auth_service.login(email, password)


def test_super_admin_holds_every_permission(admin) -> None:
    with admin.database.session_factory() as db:
        user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        permissions = get_user_permissions(db, user)
    catalogue = {p.key for p in admin.permission_service.list_all()}
    assert permissions == catalogue


def test_business_admin_can_manage_users_but_not_settings(admin) -> None:
    _login_as(admin, "Business Admin", "bizadmin@bizpilot.test")
    assert admin.user_service.list_users()
    assert admin.role_service.list_roles()
    with pytest.raises(AuthorizationError):
        admin.business_service.update_business(
            {
                "business_name": "Hacked",
                "owner_name": "Hacker Name",
                "email": "x@example.com",
                "currency": "INR",
                "timezone": "Asia/Kolkata",
                "financial_year_start": "04-01",
            }
        )


def test_finance_manager_cannot_manage_users(admin) -> None:
    _login_as(admin, "Finance Manager", "finance@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.user_service.list_users()
    with pytest.raises(AuthorizationError):
        admin.user_service.create_user(
            {
                "full_name": "Nope",
                "email": "nope@bizpilot.test",
                "password": "Empl0yee!Passw0rd",
                "password_confirm": "Empl0yee!Passw0rd",
                "role_ids": [1],
            }
        )


def test_sales_manager_cannot_read_audit_or_create_roles(admin) -> None:
    _login_as(admin, "Sales Manager", "sales@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.audit_service.list_entries()
    with pytest.raises(AuthorizationError):
        admin.role_service.create_role(
            {"role_name": "Sneaky", "description": "", "permission_keys": ["dashboard.view"]}
        )


def test_inventory_manager_cannot_approve_finance(admin) -> None:
    _login_as(admin, "Inventory Manager", "inventory@bizpilot.test")
    with admin.database.session_factory() as db:
        user = db.query(User).filter(User.email == "inventory@bizpilot.test").first()
        assert has_permission(db, user, "inventory.view") is True
        assert has_permission(db, user, "finance.approve") is False
        assert has_permission(db, user, "users.create") is False


def test_employee_has_minimal_access(employee_context) -> None:
    assert employee_context.auth_context.principal.permissions == frozenset(
        {"dashboard.view", "auth.change_password"}
    )
    with pytest.raises(AuthorizationError):
        employee_context.user_service.list_users()
    with pytest.raises(AuthorizationError):
        employee_context.audit_service.list_entries()
    with pytest.raises(AuthorizationError):
        employee_context.role_service.list_roles()


def test_employee_can_still_use_the_dashboard(employee_context) -> None:
    summary = employee_context.dashboard_service.get_summary()
    assert summary.user_name == "Employee User"
    assert summary.system_status.database_connected is True


def test_permission_change_takes_effect_immediately(admin) -> None:
    create_user(admin, "Employee", EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD, "Employee User")
    employee_role = next(
        role for role in admin.role_service.list_roles() if role.role_name == "Employee"
    )
    admin.role_service.update_role(
        employee_role.id,
        {
            "role_name": "Employee",
            "description": employee_role.description,
            "permission_keys": ["dashboard.view", "auth.change_password", "users.view"],
        },
    )

    admin.auth_service.logout()
    admin.auth_service.login(EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD)
    assert "users.view" in admin.auth_context.principal.permissions
    assert admin.user_service.list_users()


def test_role_assignment_requires_permission(admin) -> None:
    user_id = create_user(admin, "Employee", "assign@bizpilot.test")
    _login_as(admin, "Finance Manager", "finance2@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.user_service.assign_roles(user_id, [1])


def test_non_superuser_cannot_grant_roles_they_do_not_hold(admin) -> None:
    super_admin_role = next(
        role for role in admin.role_service.list_roles() if role.role_name == "Super Admin"
    )
    _login_as(admin, "Business Admin", "bizadmin2@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.user_service.create_user(
            {
                "full_name": "Escalation Attempt",
                "email": "escalate@bizpilot.test",
                "password": "Empl0yee!Passw0rd",
                "password_confirm": "Empl0yee!Passw0rd",
                "role_ids": [super_admin_role.id],
            }
        )


def test_system_roles_are_protected(admin) -> None:
    employee_role = next(
        role for role in admin.role_service.list_roles() if role.role_name == "Employee"
    )
    with pytest.raises(ProtectedRecordError):
        admin.role_service.delete_role(employee_role.id)

    with pytest.raises(ProtectedRecordError):
        admin.role_service.update_role(
            employee_role.id,
            {
                "role_name": "Renamed Employee",
                "description": "x",
                "permission_keys": ["dashboard.view"],
            },
        )


def test_super_admin_role_always_keeps_all_permissions(admin) -> None:
    super_admin_role = next(
        role for role in admin.role_service.list_roles() if role.role_name == "Super Admin"
    )
    updated = admin.role_service.update_role(
        super_admin_role.id,
        {
            "role_name": "Super Admin",
            "description": super_admin_role.description,
            "permission_keys": ["dashboard.view"],
        },
    )
    assert len(updated.permission_keys) == len(admin.permission_service.list_all())


def test_custom_role_can_be_created_and_deleted(admin) -> None:
    role = admin.role_service.create_role(
        {
            "role_name": "Report Viewer",
            "description": "Read-only reports",
            "permission_keys": ["dashboard.view", "reports.view"],
        }
    )
    assert role.is_system_role is False
    assert set(role.permission_keys) == {"dashboard.view", "reports.view"}

    admin.role_service.delete_role(role.id)
    names = {item.role_name for item in admin.role_service.list_roles()}
    assert "Report Viewer" not in names


def test_cannot_delete_role_assigned_to_users(admin) -> None:
    role = admin.role_service.create_role(
        {
            "role_name": "Temp Role",
            "description": "",
            "permission_keys": ["dashboard.view"],
        }
    )
    admin.user_service.create_user(
        {
            "full_name": "Temp User",
            "email": "temp@bizpilot.test",
            "password": "Empl0yee!Passw0rd",
            "password_confirm": "Empl0yee!Passw0rd",
            "role_ids": [role.id],
        }
    )
    with pytest.raises(ConflictError):
        admin.role_service.delete_role(role.id)


def test_last_super_admin_cannot_be_deactivated(admin) -> None:
    with admin.database.session_factory() as db:
        admin_user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        admin_id = admin_user.id

    # Another Super Admin may deactivate this account...
    create_user(admin, "Super Admin", "super2@bizpilot.test", MANAGER_PASSWORD, "Second Admin")
    admin.auth_service.logout()
    admin.auth_service.login("super2@bizpilot.test", MANAGER_PASSWORD)
    admin.user_service.set_active(admin_id, False)

    # ...but the last remaining one cannot be removed.
    with admin.database.session_factory() as db:
        second = db.query(User).filter(User.email == "super2@bizpilot.test").first()
        second_id = second.id
    with pytest.raises(ProtectedRecordError):
        admin.user_service.set_active(second_id, False)


def test_last_super_admin_cannot_lose_the_super_admin_role(admin) -> None:
    employee_role = next(
        role for role in admin.role_service.list_roles() if role.role_name == "Employee"
    )
    with admin.database.session_factory() as db:
        admin_user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        admin_id = admin_user.id

    with pytest.raises(ProtectedRecordError):
        admin.user_service.assign_roles(admin_id, [employee_role.id])


def test_admin_cannot_deactivate_self(admin) -> None:
    with admin.database.session_factory() as db:
        admin_user = db.query(User).filter(User.email == ADMIN_EMAIL).first()
        admin_id = admin_user.id
    with pytest.raises(ProtectedRecordError):
        admin.user_service.set_active(admin_id, False)


def test_admin_cannot_reset_another_super_admins_password_without_being_superuser(admin) -> None:
    create_user(admin, "Super Admin", "super3@bizpilot.test", MANAGER_PASSWORD, "Third Admin")
    with admin.database.session_factory() as db:
        third = db.query(User).filter(User.email == "super3@bizpilot.test").first()
        third_id = third.id

    _login_as(admin, "Business Admin", "bizadmin3@bizpilot.test")
    with pytest.raises(AuthorizationError):
        admin.user_service.reset_password(third_id, "An0ther!Passw0rd", "An0ther!Passw0rd")
