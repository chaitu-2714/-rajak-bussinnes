"""Unit tests: exact Decimal money handling."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.database.types import ZERO, money_sum, to_money


def test_to_money_quantises_to_two_places() -> None:
    assert to_money("10.005") == Decimal("10.01")
    assert to_money(10) == Decimal("10.00")
    assert to_money(None) == ZERO


def test_money_arithmetic_is_exact() -> None:
    """The classic float trap: 0.1 + 0.2 must be exactly 0.30."""
    assert to_money("0.1") + to_money("0.2") == Decimal("0.30")
    assert money_sum(["0.1", "0.2", "0.3"]) == Decimal("0.60")


def test_money_sum_over_many_rows_has_no_drift() -> None:
    values = ["19.99"] * 1000
    assert money_sum(values) == Decimal("19990.00")


def test_invalid_amount_raises() -> None:
    with pytest.raises(ValueError):
        to_money("not-a-number")


def test_money_round_trips_through_database(business, admin) -> None:
    from app.database.models.finance import Expense

    expense = admin.finance_service.create_expense(
        {
            "expense_category": "OTHER",
            "description": "Rounding check",
            "amount": "1234.56",
            "payment_method": "CASH",
            "expense_date": "2026-11-01T10:00:00",
        }
    )
    assert expense.amount == Decimal("1234.56")

    with admin.database.session_factory() as db:
        row = db.get(Expense, expense.id)
        assert isinstance(row.amount, Decimal)
        assert row.amount == Decimal("1234.56")
