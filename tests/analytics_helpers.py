"""Analytics test helpers: historical records with controlled dates."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import text as sql_text

from app.utils.date_utils import utcnow


def backdate(context: Any, order_number: str, when) -> None:
    """Move one completed order (and its invoice and ledger entries) to a date."""
    with context.database.engine.begin() as conn:
        conn.execute(
            sql_text(
                "UPDATE sales_orders SET created_at = :when, updated_at = :when "
                "WHERE order_number = :ref"
            ),
            {"when": when, "ref": order_number},
        )
        conn.execute(
            sql_text(
                "UPDATE invoices SET invoice_date = :when, created_at = :when "
                "WHERE sales_order_id = (SELECT id FROM sales_orders WHERE order_number = :ref)"
            ),
            {"when": when, "ref": order_number},
        )
        conn.execute(
            sql_text(
                "UPDATE financial_transactions SET transaction_date = :when, created_at = :when "
                "WHERE reference_id = :ref"
            ),
            {"when": when, "ref": order_number},
        )


def seed_history(context: Any, business: dict, *, months: int = 4, per_month: int = 3) -> list[dict]:
    """Create completed sales spread over past months, each dated in its month."""
    created: list[dict] = []
    now = utcnow()
    # Make sure there is enough stock for the seeded sales.
    context.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": months * per_month * 2,
            "movement_type": "ADJUSTMENT",
            "reason": "Analytics test stock",
            "direction": 1,
        }
    )
    for month in range(months - 1, -1, -1):
        for index in range(per_month):
            when = now - timedelta(days=30 * month + index * 2)
            order = context.sales_service.create_order(
                {
                    "customer_id": business["customer"].id,
                    "items": [{"product_id": business["tea"].id, "quantity": 1}],
                }
            )
            done = context.sales_service.complete_order(order.id)
            invoice = context.sales_service.invoice_for_order(done.id)
            backdate(context, done.order_number, when)
            created.append({"order": done, "invoice": invoice, "when": when})
    return created


def record_expense(context: Any, *, amount: str, category: str = "RENT", when=None, description: str = "Test expense"):
    return context.finance_service.create_expense(
        {
            "expense_category": category,
            "description": description,
            "amount": amount,
            "payment_method": "CASH",
            "expense_date": (when or utcnow()).isoformat(),
        }
    )
