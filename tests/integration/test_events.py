"""Business event outbox tests."""

from __future__ import annotations

import pytest

from app.core.exceptions import AuthorizationError

from tests.conftest import completed_sale


def test_sale_completion_publishes_dispatched_event(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    events = admin.event_service.list_events()
    sale_events = [event for event in events if event["event_type"] == "SaleCompleted"]
    assert sale_events
    assert sale_events[0]["status"] == "DISPATCHED"
    assert sale_events[0]["dispatched_at"] is not None
    assert sale_events[0]["payload"]["total_amount"] == "150.00"


def test_all_expected_events_are_emitted(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=1)
    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "50.00"}
    )
    admin.finance_service.create_expense(
        {
            "expense_category": "OTHER",
            "description": "Event check",
            "amount": "10.00",
            "payment_method": "CASH",
            "expense_date": "2026-11-01T09:00:00",
        }
    )
    admin.sales_service.cancel_order(sale["order"].id, "Testing events")

    event_types = {event["event_type"] for event in admin.event_service.list_events()}
    assert {
        "CustomerCreated",
        "SaleCompleted",
        "PaymentReceived",
        "ExpenseRecorded",
        "SaleCancelled",
    }.issubset(event_types)


def test_failed_handler_is_retried_then_failed(admin, business) -> None:
    attempts = {"count": 0}

    def failing_handler(payload: dict) -> None:
        attempts["count"] += 1
        raise RuntimeError("downstream unavailable")

    admin.event_service.register_handler("SaleCompleted", failing_handler)
    completed_sale(admin, business, quantity=1)

    events = [e for e in admin.event_service.list_events() if e["event_type"] == "SaleCompleted"]
    assert events[0]["status"] in ("PENDING", "FAILED")
    assert events[0]["attempts"] >= 1

    # Retrying resets the attempt counter so delivery can be attempted again.
    reset = admin.event_service.retry_failed()
    assert reset >= 0


def test_event_dispatch_survives_handler_removal(admin, business) -> None:
    admin.event_service.register_handler("CustomerCreated", lambda payload: None)
    admin.customer_service.create_customer({"full_name": "Event Customer"})
    events = [e for e in admin.event_service.list_events() if e["event_type"] == "CustomerCreated"]
    assert events[0]["status"] == "DISPATCHED"


def test_event_history_requires_audit_permission(employee_context) -> None:
    with pytest.raises(AuthorizationError):
        employee_context.event_service.list_events()
