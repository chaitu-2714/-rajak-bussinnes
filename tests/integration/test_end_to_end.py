"""End-to-end workflow test across all five Phase 2 modules.

Customer → product → opening stock → complete sale → stock reduced → invoice →
payment → financial transactions → audit log, plus the purchasing chain.
"""

from __future__ import annotations

from decimal import Decimal

from app.database.models.audit_log import AuditLog
from app.database.models.finance import FinancialTransaction
from app.database.models.sales import Invoice, Payment
from sqlalchemy import select

from tests.conftest import completed_sale


def test_full_sales_and_finance_workflow(admin, business) -> None:
    # 1. Sale of two products in one order.
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [
                {"product_id": business["tea"].id, "quantity": 2},
                {"product_id": business["coffee"].id, "quantity": 4},
            ],
        }
    )
    assert order.total_amount == Decimal("620.00")  # 300 + 320

    # 2. Complete: stock out, invoice, revenue — atomically.
    completed = admin.sales_service.complete_order(order.id)
    assert completed.order_status == "COMPLETED"
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 8
    assert admin.inventory_service.stock_for_product(business["coffee"].id) == 16

    # 3. Invoice exists and is unpaid.
    invoice = admin.sales_service.invoice_for_order(order.id)
    assert invoice.status == "UNPAID"
    assert invoice.outstanding_amount == Decimal("620.00")

    # 4. Partial payment.
    admin.sales_service.record_payment(
        {"invoice_id": invoice.id, "amount": "400.00", "payment_method": "UPI"}
    )
    invoice = admin.sales_service.invoice(invoice.id)
    assert invoice.status == "PARTIALLY_PAID"
    assert invoice.outstanding_amount == Decimal("220.00")

    # 5. Finance reflects revenue and cash separately.
    summary = admin.finance_service.summary()
    assert summary.revenue == Decimal("620.00")
    assert summary.cash_received == Decimal("400.00")
    assert summary.outstanding_receivables == Decimal("220.00")
    assert summary.cogs == Decimal("400.00")  # 2*100 + 4*50
    assert summary.gross_profit == Decimal("220.00")

    # 6. Ledger has exactly one revenue row and one cash row.
    with admin.database.session_factory() as db:
        transactions = db.scalars(select(FinancialTransaction)).all()
        categories = [t.category for t in transactions]
        assert categories.count("SALES_REVENUE") == 1
        assert categories.count("PAYMENT_RECEIVED") == 1
        assert len(db.scalars(select(Payment)).all()) == 1
        assert len(db.scalars(select(Invoice)).all()) == 1

    # 7. Audit trail covers the whole chain.
    actions = {entry.action for entry in admin.audit_service.list_entries()}
    assert {
        "CREATE_SALES_ORDER",
        "COMPLETE_SALES_ORDER",
        "CREATE_INVOICE",
        "RECORD_PAYMENT",
        "STOCK_ADJUSTMENT",
        "CREATE_CUSTOMER",
        "CREATE_PRODUCT",
    }.issubset(actions)

    # 8. Customer history is derived from the sale.
    profile = admin.customer_service.profile(business["customer"].id)
    assert profile.summary.total_purchase == Decimal("620.00")
    assert profile.outstanding_amount == Decimal("220.00")

    # 9. Dashboard shows the same figures.
    dashboard = admin.dashboard_service.get_summary()
    cards = {card.title: card.value for card in dashboard.stat_cards}
    assert cards["Total Revenue"] == "620.00"
    assert cards["Total Sales"] == "620.00"
    assert cards["Active Customers"] == "1"
    assert cards["Inventory Items"] == "2"


def test_purchase_to_sale_workflow(admin, business) -> None:
    """Buy stock from a supplier, receive it, then sell it."""
    po = admin.purchasing_service.create_purchase_order(
        {
            "supplier_id": business["supplier"].id,
            "items": [
                {"product_id": business["tea"].id, "ordered_quantity": 30, "unit_cost": "95.00"}
            ],
        }
    )
    po = admin.purchasing_service.approve_purchase_order(po.id)
    admin.purchasing_service.receive_goods(
        {
            "purchase_order_id": po.id,
            "items": [{"purchase_order_item_id": po.lines[0].id, "quantity": 30}],
        }
    )
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 40

    # Selling keeps using the recorded cost price for COGS.
    completed_sale(admin, business, quantity=5)
    summary = admin.finance_service.summary()
    assert summary.cogs == Decimal("500.00")  # 5 × 100 cost, not 95 purchase cost
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 35


def test_audit_log_records_business_modules(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    with admin.database.session_factory() as db:
        modules = {row.module for row in db.scalars(select(AuditLog)).all()}
    assert {"Sales", "Inventory", "Customers"}.issubset(modules)


def test_stock_movements_trace_every_change(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    movements = admin.inventory_service.movements(product_id=business["tea"].id)
    sequence = [(m.movement_type, m.previous_quantity, m.new_quantity) for m in reversed(movements)]
    assert sequence == [
        ("OPENING_STOCK", 0, 10),
        ("SALE", 10, 8),
    ]
