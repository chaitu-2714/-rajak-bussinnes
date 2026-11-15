"""Exact money handling.

Money is stored in SQLite as ``NUMERIC(14, 2)`` and always handled as
:class:`decimal.Decimal` in Python. Values are quantised to two decimal places
on the way in and on the way out, so floating point artefacts can never leak
into an invoice total, a payment or a report.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Numeric
from sqlalchemy.types import TypeDecorator

TWO_PLACES = Decimal("0.01")
ZERO = Decimal("0.00")


def to_money(value: Any) -> Decimal:
    """Convert a value to a 2-decimal Decimal (banker-safe rounding)."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid monetary amount: {value!r}") from exc


def money_sum(values: Any) -> Decimal:
    """Sum an iterable of money values exactly, as Decimal."""
    total = ZERO
    for value in values:
        total += to_money(value)
    return total


class Money(TypeDecorator):
    """NUMERIC column that always yields a quantised Decimal."""

    impl = Numeric(14, 2)
    cache_ok = True

    def process_bind_param(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return to_money(value)

    def process_result_value(self, value: Any, dialect: Any) -> Decimal | None:
        if value is None:
            return None
        return to_money(value)
