"""Date and time helpers.

All timestamps are stored as naive UTC datetimes so SQLite round-trips them
without timezone drift; presentation converts them to local time.
"""

from __future__ import annotations

from datetime import date, datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a naive datetime (the storage format)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def to_local(value: datetime | None) -> datetime | None:
    """Convert a stored naive UTC datetime to local naive time."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def format_datetime(value: datetime | None, fmt: str = "%d %b %Y, %I:%M %p") -> str:
    """Human readable local timestamp, or an em dash when empty."""
    local = to_local(value)
    return local.strftime(fmt) if local else "—"


def local_to_utc(value: datetime) -> datetime:
    """Convert a naive local datetime (as picked in the UI) to naive UTC."""
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def format_date(value: datetime | date | None, fmt: str = "%d %b %Y") -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        local = to_local(value)
        return local.strftime(fmt) if local else "—"
    return value.strftime(fmt)


def format_long_date(value: datetime | None = None) -> str:
    """e.g. 'Tuesday, 03 November 2026'."""
    local = to_local(value) if value else datetime.now()
    return local.strftime("%A, %d %B %Y")


def start_of_day(value: datetime | None = None) -> datetime:
    base = value or utcnow()
    return base.replace(hour=0, minute=0, second=0, microsecond=0)


def end_of_day(value: datetime | None = None) -> datetime:
    base = value or utcnow()
    return base.replace(hour=23, minute=59, second=59, microsecond=0)
