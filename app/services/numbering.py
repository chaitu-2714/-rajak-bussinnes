"""Document numbering helper.

Numbers look like ``SO-2026-0001``. The maximum existing suffix is scanned
inside the caller's transaction and the unique index on the column is the final
guard against a duplicate, which is sufficient for a single-user desktop app.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.utils.date_utils import utcnow


def next_document_number(
    db: Session,
    model: type,
    column_name: str,
    prefix: str,
    *,
    with_year: bool = True,
    width: int = 4,
) -> str:
    """Return the next free document number for ``model.column_name``."""
    column = getattr(model, column_name)
    pattern = f"{prefix}-{utcnow().year}-%" if with_year else f"{prefix}-%"
    existing = db.scalars(select(column).where(column.like(pattern))).all()

    highest = 0
    for value in existing:
        if not value:
            continue
        tail = str(value).rsplit("-", 1)[-1]
        if tail.isdigit():
            highest = max(highest, int(tail))

    sequence = f"{highest + 1:0{width}d}"
    if with_year:
        return f"{prefix}-{utcnow().year}-{sequence}"
    return f"{prefix}-{sequence}"
