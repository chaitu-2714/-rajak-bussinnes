"""Sales tests: order lifecycle, stock, invoices, payments and cancellation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError, NotFoundError, ValidationError

from tests.conftest import completed_sale, seed_business


def test_create_draft_order_with_multiple_products(admin, business) -> None:
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [
                {"product_id": business["tea"].id, "quantity": 2},
                {"product_id": business["coffee"].id, "quantity": 3},
            ],
            "notes": "Deliver on Friday",
        }
    )
    assert order.order_status == "DRAFT"
    assert order.item_count == 2
    assert order.subtotal == Decimal("540.00")  # 2*150 + 3*80
    assert order.total_amount == Decimal("540.00")
    # A draft does not move stock or money.
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10
    assert admin.finance_service.summary().revenue == Decimal("0.00")


def test_order_totals_apply_discount_and_tax(admin, business) -> None:
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [
                {
                    "product_id": business["tea"].id,
                    "quantity": 2,
                    "discount_amount": "50.00",
                    "tax_amount": "27.00",
                }
            ],
            "discount_amount": "10.00",
        }
    )
    assert order.subtotal == Decimal("300.00")
    assert order.discount_amount == Decimal("60.00")
    assert order.tax_amount == Decimal("27.00")
    assert order.total_amount == Decimal("267.00")


def test_discount_cannot_exceed_line_value(admin, business) -> None:
    with pytest.raises(ValidationError):
        admin.sales_service.create_order(
            {
                "customer_id": business["customer"].id,
                "items": [
                    {
                        "product_id": business["tea"].id,
                        "quantity": 1,
                        "discount_amount": "999.00",
                    }
                ],
            }
        )


def test_inactive_customer_rejected(admin, business) -> None:
    admin.customer_service.set_active(business["customer"].id, False)
    with pytest.raises(ValidationError):
        admin.sales_service.create_order(
            {
                "customer_id": business["customer"].id,
                "items": [{"product_id": business["tea"].id, "quantity": 1}],
            }
        )


def test_confirm_then_complete_deducts_stock_and_invoices(admin, business) -> None:
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [{"product_id": business["tea"].id, "quantity": 2}],
        }
    )
    admin.sales_service.confirm_order(order.id)
    completed = admin.sales_service.complete_order(order.id)

    assert completed.order_status == "COMPLETED"
    assert completed.invoice_number is not None
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 8

    invoice = admin.sales_service.invoice_for_order(order.id)
    assert invoice.total_amount == Decimal("300.00")
    assert invoice.status == "UNPAID"
    assert invoice.outstanding_amount == Decimal("300.00")


def test_completion_writes_stock_movement(admin, business) -> None:
    completed_sale(admin, business, quantity=3)
    movements = admin.inventory_service.movements(product_id=business["tea"].id)
    sale = [m for m in movements if m.movement_type == "SALE"]
    assert len(sale) == 1
    assert sale[0].quantity == 3
    assert sale[0].previous_quantity == 10
    assert sale[0].new_quantity == 7
    assert sale[0].reference_type == "SALES_ORDER"


def test_insufficient_stock_blocks_completion(admin, business) -> None:
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [{"product_id": business["tea"].id, "quantity": 999}],
        }
    )
    with pytest.raises(ConflictError):
        admin.sales_service.complete_order(order.id)

    # Nothing partially applied: stock, invoice and revenue untouched.
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10
    assert admin.sales_service.invoice_for_order(order.id) is None
    assert admin.finance_service.summary().revenue == Decimal("0.00")
    assert admin.sales_service.get_order(order.id).order_status == "DRAFT"


def test_confirm_checks_stock(admin, business) -> None:
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [{"product_id": business["coffee"].id, "quantity": 100}],
        }
    )
    with pytest.raises(ConflictError):
        admin.sales_service.confirm_order(order.id)


def test_duplicate_completion_rejected(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=1)
    with pytest.raises(ConflictError):
        admin.sales_service.complete_order(sale["order"].id)
    # Stock and revenue posted exactly once.
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 9
    assert admin.finance_service.summary().revenue == Decimal("150.00")


def test_partial_payment_updates_status(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=2)
    invoice = admin.sales_service.record_payment(
        {
            "invoice_id": sale["invoice"].id,
            "amount": "100.00",
            "payment_method": "UPI",
        }
    )
    assert invoice.status == "PARTIALLY_PAID"
    assert invoice.paid_amount == Decimal("100.00")
    assert invoice.outstanding_amount == Decimal("200.00")

    order = admin.sales_service.get_order(sale["order"].id)
    assert order.payment_status == "PARTIALLY_PAID"
    assert order.paid_amount == Decimal("100.00")


def test_full_payment_marks_invoice_paid(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=1)
    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "150.00", "payment_method": "CASH"}
    )
    invoice = admin.sales_service.invoice(sale["invoice"].id)
    assert invoice.status == "PAID"
    assert invoice.outstanding_amount == Decimal("0.00")


def test_overpayment_rejected(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=1)
    with pytest.raises(ValidationError):
        admin.sales_service.record_payment(
            {"invoice_id": sale["invoice"].id, "amount": "500.00"}
        )
    assert admin.sales_service.invoice(sale["invoice"].id).outstanding_amount == Decimal("150.00")


def test_cancellation_reverses_stock_invoice_and_revenue(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=4)
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 6

    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "200.00"}
    )
    summary_before = admin.finance_service.summary()
    assert summary_before.revenue == Decimal("600.00")

    cancelled = admin.sales_service.cancel_order(sale["order"].id, "Customer returned goods")
    assert cancelled.order_status == "CANCELLED"
    assert cancelled.payment_status == "REFUNDED"

    # Stock is returned and the movement ledger shows it.
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10
    returns = [m for m in admin.inventory_service.movements() if m.movement_type == "RETURN"]
    assert returns and returns[0].quantity == 4

    summary_after = admin.finance_service.summary()
    assert summary_after.revenue == Decimal("0.00")
    assert summary_after.refunds_paid == Decimal("200.00")
    assert summary_after.outstanding_receivables == Decimal("0.00")

    invoice = admin.sales_service.invoice(sale["invoice"].id)
    assert invoice.status == "CANCELLED"


def test_double_cancellation_rejected(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=1)
    admin.sales_service.cancel_order(sale["order"].id, "First cancellation")
    with pytest.raises(ConflictError):
        admin.sales_service.cancel_order(sale["order"].id, "Second cancellation")
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10


def test_cancelled_invoice_rejects_payment(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=1)
    admin.sales_service.cancel_order(sale["order"].id, "No longer needed")
    with pytest.raises(ConflictError):
        admin.sales_service.record_payment(
            {"invoice_id": sale["invoice"].id, "amount": "10.00"}
        )


def test_draft_cancellation_needs_no_reversal(admin, business) -> None:
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [{"product_id": business["tea"].id, "quantity": 1}],
        }
    )
    cancelled = admin.sales_service.cancel_order(order.id, "Duplicate order")
    assert cancelled.order_status == "CANCELLED"
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10


def test_cancellation_requires_reason(admin, business) -> None:
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [{"product_id": business["tea"].id, "quantity": 1}],
        }
    )
    with pytest.raises(ValidationError):
        admin.sales_service.cancel_order(order.id, "")


def test_sales_dashboard_totals(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=2)
    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "100.00"}
    )
    dashboard = admin.sales_service.dashboard()
    assert dashboard.total_orders == 1
    assert dashboard.completed_orders == 1
    assert dashboard.total_sales_value == Decimal("300.00")
    assert dashboard.paid_total == Decimal("100.00")
    assert dashboard.outstanding_total == Decimal("200.00")
    assert dashboard.top_products[0]["product"] == "Test Tea"


def test_unknown_order_raises(admin) -> None:
    with pytest.raises(NotFoundError):
        admin.sales_service.get_order(9999)


def test_sales_csv_export(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    from pathlib import Path

    path = Path(admin.sales_service.export_sales_csv())
    assert path.exists()
    content = path.read_text(encoding="utf-8-sig")
    assert "Order" in content.splitlines()[0]
    assert "Test Customer" in content
