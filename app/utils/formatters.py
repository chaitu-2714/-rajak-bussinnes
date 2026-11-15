"""Presentation helpers (currency, numbers, initials)."""

from __future__ import annotations

from decimal import Decimal

CURRENCY_SYMBOLS = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "AED": "AED ",
    "SGD": "S$",
    "AUD": "A$",
    "CAD": "C$",
}


def currency_symbol(code: str | None) -> str:
    return CURRENCY_SYMBOLS.get((code or "INR").upper(), f"{code or ''} ".strip() + " ")


def format_currency(amount: float | Decimal | None, code: str = "INR") -> str:
    """Indian digit grouping for INR, western grouping otherwise."""
    if amount is None:
        return "—"
    symbol = currency_symbol(code)
    value = float(amount)
    if (code or "INR").upper() == "INR":
        return f"{symbol}{_indian_grouping(value)}"
    return f"{symbol}{value:,.2f}"


def _indian_grouping(value: float) -> str:
    negative = value < 0
    whole, _, fraction = f"{abs(value):.2f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    text = f"{whole}.{fraction}"
    return f"-{text}" if negative else text


def format_number(value: int | float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


def initials(full_name: str | None) -> str:
    parts = [part for part in (full_name or "").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def title_case_key(value: str) -> str:
    """``users.create`` -> ``Create``."""
    tail = value.split(".")[-1]
    return tail.replace("_", " ").title()
