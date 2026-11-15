"""Shared pytest fixtures.

Every test runs against an isolated temporary data directory and its own
database, so the real user database is never touched.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Qt must run headless in CI / this environment.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.core.application import ApplicationContext  # noqa: E402
from app.core.config import AppConfig, SecuritySettings  # noqa: E402
from app.core.database import Database  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ADMIN_EMAIL = "admin@bizpilot.test"
ADMIN_PASSWORD = "Adm1n!Passw0rd"
EMPLOYEE_EMAIL = "employee@bizpilot.test"
EMPLOYEE_PASSWORD = "Empl0yee!Passw0rd"
MANAGER_PASSWORD = "Manag3r!Passw0rd"

ADMIN_PAYLOAD = {
    "business_name": "Test Traders",
    "owner_name": "Test Admin",
    "email": ADMIN_EMAIL,
    "phone": "+91 90000 00000",
    "password": ADMIN_PASSWORD,
    "password_confirm": ADMIN_PASSWORD,
    "currency": "INR",
    "timezone": "Asia/Kolkata",
    "financial_year_start": "04-01",
}


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    """Isolated configuration pointing at a temporary data directory."""
    cfg = AppConfig(
        data_dir=tmp_path / "data",
        resources_dir=PROJECT_ROOT / "resources",
        migrations_dir=PROJECT_ROOT / "migrations",
        environment="testing",
        security=SecuritySettings(),
    )
    cfg.ensure_directories()
    return cfg


@pytest.fixture()
def database(config: AppConfig):
    """Initialised database with migrations applied."""
    db = Database(config)
    db.initialize()
    yield db
    db.dispose()


@pytest.fixture()
def context(database: Database, config: AppConfig) -> ApplicationContext:
    """Fully wired application context on an empty database."""
    return ApplicationContext.build(config, database)


@pytest.fixture()
def admin(context: ApplicationContext) -> ApplicationContext:
    """Context with the workspace provisioned and signed in as Super Admin."""
    context.auth_service.run_initial_setup(ADMIN_PAYLOAD)
    return context


def create_user(
    context: ApplicationContext,
    role_name: str,
    email: str,
    password: str = EMPLOYEE_PASSWORD,
    full_name: str = "Test User",
) -> int:
    """Helper: create a user holding a single named role; returns the id."""
    roles = {role.role_name: role for role in context.role_service.list_roles()}
    user = context.user_service.create_user(
        {
            "full_name": full_name,
            "email": email,
            "phone": None,
            "password": password,
            "password_confirm": password,
            "role_ids": [roles[role_name].id],
            "is_active": True,
        }
    )
    return user.id


@pytest.fixture()
def employee_context(admin: ApplicationContext) -> ApplicationContext:
    """Signed in as an Employee account."""
    create_user(admin, "Employee", EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD, "Employee User")
    admin.auth_service.logout()
    admin.auth_service.login(EMPLOYEE_EMAIL, EMPLOYEE_PASSWORD)
    return admin


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole UI test session (offscreen)."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Phase 2 fixtures: a small but realistic business dataset
# ---------------------------------------------------------------------------
def seed_business(context: ApplicationContext) -> dict:
    """Create categories, products with stock, a customer and a supplier."""
    category = context.inventory_service.create_category({"category_name": "Test Category"})
    tea = context.inventory_service.create_product(
        {
            "product_name": "Test Tea",
            "category_id": category.id,
            "unit": "pack",
            "cost_price": "100.00",
            "selling_price": "150.00",
            "minimum_stock": 5,
        }
    )
    coffee = context.inventory_service.create_product(
        {
            "product_name": "Test Coffee",
            "category_id": category.id,
            "cost_price": "50.00",
            "selling_price": "80.00",
            "minimum_stock": 3,
        }
    )
    context.inventory_service.opening_stock(tea.id, 10, "Opening stock")
    context.inventory_service.opening_stock(coffee.id, 20, "Opening stock")

    customer = context.customer_service.create_customer(
        {
            "full_name": "Test Customer",
            "email": "customer@bizpilot.test",
            "phone": "9876500000",
            "city": "Bhubaneswar",
        }
    )
    supplier = context.purchasing_service.create_supplier(
        {"supplier_name": "Test Supplier", "phone": "9000011111"}
    )
    return {
        "category": category,
        "tea": tea,
        "coffee": coffee,
        "customer": customer,
        "supplier": supplier,
    }


@pytest.fixture()
def business(admin: ApplicationContext) -> dict:
    """Signed-in Super Admin with a small catalogue, customer and supplier."""
    return seed_business(admin)


def completed_sale(context: ApplicationContext, data: dict, *, quantity: int = 2) -> dict:
    """Create, complete and invoice a sale of ``quantity`` tea."""
    order = context.sales_service.create_order(
        {
            "customer_id": data["customer"].id,
            "items": [{"product_id": data["tea"].id, "quantity": quantity}],
        }
    )
    order = context.sales_service.complete_order(order.id)
    invoice = context.sales_service.invoice_for_order(order.id)
    return {"order": order, "invoice": invoice}


# ---------------------------------------------------------------------------
# Phase 3 fixtures: AI orchestration
# ---------------------------------------------------------------------------
@pytest.fixture()
def conversation(admin: ApplicationContext) -> int:
    """An empty AI conversation owned by the signed-in Super Admin."""
    return admin.ai_service.create_conversation("Test conversation").id


@pytest.fixture()
def seeded_conversation(admin: ApplicationContext, business: dict) -> int:
    """Conversation plus a small catalogue, customer and supplier."""
    return admin.ai_service.create_conversation("Seeded conversation").id
