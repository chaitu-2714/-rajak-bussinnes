"""Recent-activity panel shown from the header bell button."""

from __future__ import annotations

from PySide6.QtWidgets import QMenu, QWidget

from app.services.audit_service import AuditEntryView
from app.utils.date_utils import format_datetime


class NotificationPanel(QMenu):
    """Menu listing real audit entries (never placeholder notifications)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(340)
        self.populate([])

    def populate(self, entries: list[AuditEntryView]) -> None:
        self.clear()
        header = self.addAction("Recent activity")
        header.setEnabled(False)
        self.addSeparator()

        if not entries:
            empty = self.addAction("No activity recorded yet")
            empty.setEnabled(False)
            return

        for entry in entries:
            label = f"{entry.action.replace('_', ' ').title()} · {entry.user_name}"
            action = self.addAction(label)
            action.setToolTip(
                f"{entry.module} · {format_datetime(entry.created_at)} · {entry.status}"
            )
            action.setEnabled(False)
