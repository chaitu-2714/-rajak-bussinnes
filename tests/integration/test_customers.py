"""Customer tests: records, duplicates, history, segmentation, follow-ups."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.database.models.crm import Customer
from app.database.models.sales import SalesOrder
from app.utils.date_utils import utcnow

from tests.conftest import completed_sale


def test_create_customer_generates_code(admin) -> None:
    customer = admin.customer_service.create_customer(
        {"full_name": "Asha Rao", "email": "asha@example.com", "phone": "9876500001"}
    )
    assert customer.customer_code == "CUST-0001"
    assert customer.segment == "New"


def test_duplicate_email_rejected(admin) -> None:
    admin.customer_service.create_customer(
        {"full_name": "One", "email": "dup@example.com"}
    )
    with pytest.raises(ValidationError):
        admin.customer_service.create_customer(
            {"full_name": "Two", "email": "DUP@example.com"}
        )


def test_duplicate_phone_rejected(admin) -> None:
    admin.customer_service.create_customer({"full_name": "One", "phone": "9876500000"})
    with pytest.raises(ValidationError):
        admin.customer_service.create_customer({"full_name": "Two", "phone": "9876500000"})


def test_update_customer(admin, business) -> None:
    updated = admin.customer_service.update_customer(
        business["customer"].id,
        {
            "customer_code": business["customer"].customer_code,
            "full_name": "Test Customer Renamed",
            "email": "renamed@bizpilot.test",
            "phone": "9876500000",
            "city": "Cuttack",
            "customer_type": "WHOLESALE",
            "is_active": True,
        },
    )
    assert updated.full_name == "Test Customer Renamed"
    assert updated.city == "Cuttack"
    assert updated.customer_type == "WHOLESALE"


def test_search_and_filters(admin, business) -> None:
    admin.customer_service.create_customer(
        {"full_name": "Neha Sharma", "city": "Puri", "customer_type": "BUSINESS"}
    )
    assert [c.full_name for c in admin.customer_service.list_customers(search="neha")] == [
        "Neha Sharma"
    ]
    assert len(admin.customer_service.list_customers(customer_type="BUSINESS")) == 1
    assert len(admin.customer_service.list_customers(is_active=True)) == 2


def test_purchase_history_from_real_orders(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    profile = admin.customer_service.profile(business["customer"].id)

    assert profile.summary.order_count == 1
    assert profile.summary.total_purchase == Decimal("300.00")
    assert profile.invoices[0].total_amount == Decimal("300.00")
    assert profile.outstanding_amount == Decimal("300.00")
    assert profile.summary.last_purchase_at is not None


def test_payment_history_in_profile(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=1)
    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "50.00", "payment_method": "UPI"}
    )
    profile = admin.customer_service.profile(business["customer"].id)
    assert profile.payments[0].amount == Decimal("50.00")
    assert profile.outstanding_amount == Decimal("100.00")


def test_high_value_segment(admin) -> None:
    customer = admin.customer_service.create_customer({"full_name": "Big Buyer"})
    product = admin.inventory_service.create_product(
        {"product_name": "Bulk Pallet", "cost_price": "40000.00", "selling_price": "60000.00"}
    )
    admin.inventory_service.opening_stock(product.id, 2)
    order = admin.sales_service.create_order(
        {
            "customer_id": customer.id,
            "items": [{"product_id": product.id, "quantity": 1}],
        }
    )
    admin.sales_service.complete_order(order.id)
    summary = admin.customer_service.get_customer(customer.id)
    assert summary.segment == "High value"


def test_regular_segment_after_three_orders(admin, business) -> None:
    for _ in range(3):
        sale = completed_sale(admin, business, quantity=1)
        admin.sales_service.record_payment(
            {"invoice_id": sale["invoice"].id, "amount": "150.00"}
        )
    summary = admin.customer_service.get_customer(business["customer"].id)
    assert summary.order_count == 3
    assert summary.segment == "Regular"


def test_inactive_segment_when_last_purchase_is_old(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    with admin.database.session_factory() as db:
        order = db.query(SalesOrder).first()
        order.created_at = utcnow() - timedelta(days=200)
        db.commit()

    summary = admin.customer_service.get_customer(business["customer"].id)
    assert summary.segment == "Inactive"


def test_occasional_segment(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    with admin.database.session_factory() as db:
        customer = db.get(Customer, business["customer"].id)
        customer.created_at = utcnow() - timedelta(days=60)
        db.commit()
    summary = admin.customer_service.get_customer(business["customer"].id)
    assert summary.segment == "Occasional"


def test_dashboard_segments_and_totals(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    dashboard = admin.customer_service.dashboard()
    assert dashboard.total_customers == 1
    assert dashboard.active_customers == 1
    assert dashboard.total_purchase_value == Decimal("150.00")
    assert sum(dashboard.segments.values()) == 1
    assert dashboard.segmentation_rules


def test_deactivate_customer(admin, business) -> None:
    admin.customer_service.set_active(business["customer"].id, False)
    assert admin.customer_service.get_customer(business["customer"].id).is_active is False
    with pytest.raises(ValidationError):
        admin.sales_service.create_order(
            {
                "customer_id": business["customer"].id,
                "items": [{"product_id": business["tea"].id, "quantity": 1}],
            }
        )


def test_follow_up_lifecycle(admin, business) -> None:
    follow_up = admin.customer_service.create_follow_up(
        {
            "customer_id": business["customer"].id,
            "title": "Call about repeat order",
            "due_date": "2026-11-10T10:00:00",
        }
    )
    assert follow_up.status == "PENDING"
    assert follow_up.is_overdue is False

    pending = admin.customer_service.list_follow_ups(status="PENDING")
    assert len(pending) == 1

    completed = admin.customer_service.complete_follow_up(follow_up.id)
    assert completed.status == "COMPLETED"

    with pytest.raises(ConflictError):
        admin.customer_service.complete_follow_up(follow_up.id)


def test_overdue_follow_up_detection(admin, business) -> None:
    admin.customer_service.create_follow_up(
        {
            "customer_id": business["customer"].id,
            "title": "Overdue call",
            "due_date": "2020-01-01T10:00:00",
        }
    )
    overdue = admin.customer_service.list_follow_ups(overdue_only=True)
    assert len(overdue) == 1
    assert overdue[0].is_overdue is True


def test_unknown_customer_raises(admin) -> None:
    with pytest.raises(NotFoundError):
        admin.customer_service.profile(4242)


def test_customer_csv_export(admin, business) -> None:
    from pathlib import Path

    path = Path(admin.customer_service.export_customers_csv())
    assert path.exists()
    content = path.read_text(encoding="utf-8-sig")
    assert "Test Customer" in content
    assert "Segment" in content.splitlines()[0]
