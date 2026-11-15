"""Purchasing tests: suppliers, purchase orders and goods receipts."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError, ValidationError


def _po(admin, business, quantity: int = 20) -> dict:
    return admin.purchasing_service.create_purchase_order(
        {
            "supplier_id": business["supplier"].id,
            "items": [
                {
                    "product_id": business["tea"].id,
                    "ordered_quantity": quantity,
                    "unit_cost": "95.00",
                }
            ],
            "tax_amount": "0.00",
        }
    )


def test_create_supplier_and_duplicate_name(admin) -> None:
    supplier = admin.purchasing_service.create_supplier(
        {"supplier_name": "Acme Supplies", "phone": "9000011111"}
    )
    assert supplier.supplier_code == "SUP-0001"
    with pytest.raises(ValidationError):
        admin.purchasing_service.create_supplier({"supplier_name": "acme supplies"})


def test_update_supplier(admin, business) -> None:
    updated = admin.purchasing_service.update_supplier(
        business["supplier"].id,
        {
            "supplier_code": business["supplier"].supplier_code,
            "supplier_name": "Test Supplier Renamed",
            "contact_person": "Ravi",
            "tax_identifier": "21ABCDE1234F1Z5",
            "is_active": True,
        },
    )
    assert updated.supplier_name == "Test Supplier Renamed"
    assert updated.tax_identifier == "21ABCDE1234F1Z5"


def test_purchase_order_creation_does_not_change_stock(admin, business) -> None:
    po = _po(admin, business, quantity=20)
    assert po.status == "DRAFT"
    assert po.total_amount == Decimal("1900.00")
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10


def test_approve_and_mark_ordered(admin, business) -> None:
    po = _po(admin, business)
    po = admin.purchasing_service.approve_purchase_order(po.id)
    assert po.status == "APPROVED"
    po = admin.purchasing_service.mark_ordered(po.id)
    assert po.status == "ORDERED"
    with pytest.raises(ConflictError):
        admin.purchasing_service.approve_purchase_order(po.id)


def test_receiving_requires_an_approved_order(admin, business) -> None:
    po = _po(admin, business)
    with pytest.raises(ConflictError):
        admin.purchasing_service.receive_goods(
            {
                "purchase_order_id": po.id,
                "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": 5}],
            }
        )


def test_partial_receipt_updates_stock_and_status(admin, business) -> None:
    po = _po(admin, business, quantity=20)
    po = admin.purchasing_service.approve_purchase_order(po.id)

    receipt = admin.purchasing_service.receive_goods(
        {
            "purchase_order_id": po.id,
            "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": 12}],
            "notes": "First delivery",
        }
    )
    assert receipt.receipt_number.startswith("GRN-")
    assert receipt.total_quantity == 12

    po = admin.purchasing_service.get_purchase_order(po.id)
    assert po.status == "PARTIALLY_RECEIVED"
    assert po.received_quantity == 12
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 22

    movements = admin.inventory_service.movements(product_id=business["tea"].id)
    purchase = [m for m in movements if m.movement_type == "PURCHASE"]
    assert purchase and purchase[0].quantity == 12
    assert purchase[0].reference_type == "GOODS_RECEIPT"


def test_over_receipt_rejected(admin, business) -> None:
    po = _po(admin, business, quantity=5)
    po = admin.purchasing_service.approve_purchase_order(po.id)
    with pytest.raises(ValidationError):
        admin.purchasing_service.receive_goods(
            {
                "purchase_order_id": po.id,
                "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": 6}],
            }
        )
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10


def test_full_receipt_marks_order_received(admin, business) -> None:
    po = _po(admin, business, quantity=8)
    po = admin.purchasing_service.approve_purchase_order(po.id)
    admin.purchasing_service.receive_goods(
        {
            "purchase_order_id": po.id,
            "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": 8}],
        }
    )
    po = admin.purchasing_service.get_purchase_order(po.id)
    assert po.status == "RECEIVED"
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 18


def test_two_partial_receipts_reach_received(admin, business) -> None:
    po = _po(admin, business, quantity=10)
    po = admin.purchasing_service.approve_purchase_order(po.id)
    for quantity in (4, 6):
        admin.purchasing_service.receive_goods(
            {
                "purchase_order_id": po.id,
                "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": quantity}],
            }
        )
    po = admin.purchasing_service.get_purchase_order(po.id)
    assert po.status == "RECEIVED"
    assert po.receipt_count == 2
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 20


def test_cannot_cancel_after_receipt(admin, business) -> None:
    po = _po(admin, business, quantity=10)
    po = admin.purchasing_service.approve_purchase_order(po.id)
    admin.purchasing_service.receive_goods(
        {
            "purchase_order_id": po.id,
            "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": 2}],
        }
    )
    with pytest.raises(ConflictError):
        admin.purchasing_service.cancel_purchase_order(po.id, "Changed plans")


def test_cancel_draft_purchase_order(admin, business) -> None:
    po = _po(admin, business)
    cancelled = admin.purchasing_service.cancel_purchase_order(po.id, "Not needed")
    assert cancelled.status == "CANCELLED"
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10


def test_supplier_purchase_history(admin, business) -> None:
    po = _po(admin, business, quantity=10)
    po = admin.purchasing_service.approve_purchase_order(po.id)
    admin.purchasing_service.receive_goods(
        {
            "purchase_order_id": po.id,
            "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": 5}],
        }
    )
    supplier = admin.purchasing_service.get_supplier(business["supplier"].id)
    assert supplier.order_count == 1
    assert supplier.total_order_value == Decimal("950.00")
    assert supplier.received_value == Decimal("475.00")


def test_inactive_supplier_cannot_be_used(admin, business) -> None:
    admin.purchasing_service.set_supplier_active(business["supplier"].id, False)
    with pytest.raises(ValidationError):
        _po(admin, business)


def test_purchase_order_listing_and_filters(admin, business) -> None:
    po = _po(admin, business)
    admin.purchasing_service.approve_purchase_order(po.id)
    assert len(admin.purchasing_service.list_purchase_orders()) == 1
    assert len(admin.purchasing_service.list_purchase_orders(status="APPROVED")) == 1
    assert len(admin.purchasing_service.list_purchase_orders(status="DRAFT")) == 0
    assert admin.purchasing_service.list_receipts() == []
