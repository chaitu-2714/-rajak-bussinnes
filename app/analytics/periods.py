"""Reporting period resolution in the business timezone."""

from __future__ import annotations

from datetime import datetime, timedelta

from app.analytics.schemas import AnalyticsPeriod
from app.utils.date_utils import local_to_utc, to_local, utcnow

GRANULARITIES = ("DAILY", "WEEKLY", "MONTHLY", "QUARTERLY", "YEARLY", "CUSTOM")


def _bounds(start: datetime, end: datetime, granularity: str) -> AnalyticsPeriod:
    local_start = start
    local_end = end
    label = _label(local_start, local_end, granularity)
    return AnalyticsPeriod(
        label=label,
        granularity=granularity,
        start=local_to_utc(local_start),
        end=local_to_utc(local_end),
        local_start=local_start,
        local_end=local_end,
        days=max(1, (local_end.date() - local_start.date()).days + 1),
    )


def _label(start: datetime, end: datetime, granularity: str) -> str:
    if granularity == "DAILY":
        return start.strftime("%d %b %Y")
    if granularity == "WEEKLY":
        return f"{start.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
    if granularity == "MONTHLY":
        return start.strftime("%B %Y")
    if granularity == "QUARTERLY":
        quarter = (start.month - 1) // 3 + 1
        return f"Q{quarter} {start.year}"
    if granularity == "YEARLY":
        return f"FY {start.year}"
    return f"{start.strftime('%d %b %Y')} – {end.strftime('%d %b %Y')}"


def resolve_period(
    granularity: str = "MONTHLY",
    *,
    reference: datetime | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> AnalyticsPeriod:
    """Resolve a calendar period. All boundaries are local, converted to UTC."""
    granularity = (granularity or "MONTHLY").upper()
    if granularity not in GRANULARITIES:
        raise ValueError(f"'{granularity}' is not a supported reporting granularity")

    if granularity == "CUSTOM":
        if start is None or end is None:
            raise ValueError("A custom period needs both a start and an end date")
        local_start = to_local(start) if start.tzinfo else start
        local_end = to_local(end) if end.tzinfo else end
        local_start = local_start.replace(hour=0, minute=0, second=0, microsecond=0)
        local_end = local_end.replace(hour=23, minute=59, second=59, microsecond=0)
        if local_end < local_start:
            raise ValueError("The custom period ends before it starts")
        return _bounds(local_start, local_end, "CUSTOM")

    now = to_local(reference or utcnow())
    if granularity == "DAILY":
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return _bounds(day, day.replace(hour=23, minute=59, second=59), "DAILY")
    if granularity == "WEEKLY":
        monday = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return _bounds(monday, monday + timedelta(days=6, hours=23, minutes=59, seconds=59), "WEEKLY")
    if granularity == "MONTHLY":
        first = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (first + timedelta(days=32)).replace(day=1)
        last = next_month - timedelta(seconds=1)
        return _bounds(first, last, "MONTHLY")
    if granularity == "QUARTERLY":
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        first = now.replace(
            month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        next_quarter = (first + timedelta(days=95)).replace(day=1)
        last = next_quarter - timedelta(seconds=1)
        return _bounds(first, last, "QUARTERLY")
    first = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    last = now.replace(month=12, day=31, hour=23, minute=59, second=59, microsecond=0)
    return _bounds(first, last, "YEARLY")


def previous_period(period: AnalyticsPeriod) -> AnalyticsPeriod:
    """The immediately preceding period of the same length and granularity."""
    if period.granularity == "CUSTOM":
        length = period.local_end - period.local_start
        local_end = period.local_start - timedelta(seconds=1)
        local_start = local_end - length
        return _bounds(local_start, local_end, "CUSTOM")
    shift_days = period.days
    local_end = period.local_start - timedelta(seconds=1)
    local_start = local_end - timedelta(days=shift_days - 1)
    local_start = local_start.replace(hour=0, minute=0, second=0, microsecond=0)
    if period.granularity == "MONTHLY":
        first = (period.local_start.replace(day=1) - timedelta(days=1)).replace(day=1)
        last = period.local_start - timedelta(seconds=1)
        return _bounds(first, last, "MONTHLY")
    if period.granularity == "QUARTERLY":
        first = (period.local_start.replace(day=1) - timedelta(days=1)).replace(day=1)
        first = (first - timedelta(days=92)).replace(day=1)
        last = period.local_start - timedelta(seconds=1)
        return _bounds(first, last, "QUARTERLY")
    if period.granularity == "YEARLY":
        first = period.local_start.replace(year=period.local_start.year - 1)
        last = period.local_end.replace(year=period.local_end.year - 1)
        return _bounds(first, last, "YEARLY")
    return _bounds(local_start, local_end, period.granularity)


def year_ago(period: AnalyticsPeriod) -> AnalyticsPeriod | None:
    """The same period one year earlier (used only when data allows)."""
    try:
        local_start = period.local_start.replace(year=period.local_start.year - 1)
        local_end = period.local_end.replace(year=period.local_end.year - 1)
    except ValueError:  # 29 February
        return None
    return _bounds(local_start, local_end, period.granularity)


def monthly_buckets(period: AnalyticsPeriod) -> list[tuple[str, datetime, datetime]]:
    """Split a period into month buckets: (label, local start, local end)."""
    buckets: list[tuple[str, datetime, datetime]] = []
    cursor = period.local_start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while cursor <= period.local_end:
        next_month = (cursor + timedelta(days=32)).replace(day=1)
        end = min(next_month - timedelta(seconds=1), period.local_end)
        buckets.append((cursor.strftime("%b %Y"), cursor, end))
        cursor = next_month
    return buckets


def daily_buckets(period: AnalyticsPeriod) -> list[tuple[str, datetime, datetime]]:
    buckets: list[tuple[str, datetime, datetime]] = []
    cursor = period.local_start
    while cursor <= period.local_end:
        end = cursor.replace(hour=23, minute=59, second=59, microsecond=0)
        buckets.append((cursor.strftime("%d %b"), cursor, min(end, period.local_end)))
        cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return buckets


def week_buckets(period: AnalyticsPeriod) -> list[tuple[str, datetime, datetime]]:
    buckets: list[tuple[str, datetime, datetime]] = []
    cursor = period.local_start - timedelta(days=period.local_start.weekday())
    cursor = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
    while cursor <= period.local_end:
        end = cursor + timedelta(days=6, hours=23, minutes=59, seconds=59)
        buckets.append(
            (f"W{cursor.isocalendar().week}", cursor, min(end, period.local_end))
        )
        cursor = cursor + timedelta(days=7)
    return buckets


def buckets_for(period: AnalyticsPeriod, granularity: str | None = None) -> list[tuple[str, datetime, datetime]]:
    granularity = (granularity or period.granularity).upper()
    if granularity == "DAILY":
        return daily_buckets(period)
    if granularity == "WEEKLY":
        return week_buckets(period)
    return monthly_buckets(period)
