"""Audit log viewer with user, action, module and date filters."""

from __future__ import annotations

import json
from datetime import datetime, time

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.services.audit_service import AuditEntryView
from app.ui.ui_utils import muted_label, secondary_button
from app.utils.date_utils import format_datetime, local_to_utc

COLUMNS = ("Time", "User", "Action", "Module", "Entity", "Status")
PAGE_LIMIT = 300


class AuditPage(QWidget):
    """Read-only audit trail; entries cannot be edited or deleted."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._entries: list[AuditEntryView] = []
        self.setObjectName("PageSurface")
        self._build()
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(12)

        filters = QHBoxLayout()
        filters.setSpacing(8)

        self.user_combo = QComboBox()
        self.user_combo.setMinimumWidth(150)
        self.user_combo.currentIndexChanged.connect(lambda _: self.refresh())
        filters.addWidget(self.user_combo)

        self.action_combo = QComboBox()
        self.action_combo.setMinimumWidth(160)
        self.action_combo.currentIndexChanged.connect(lambda _: self.refresh())
        filters.addWidget(self.action_combo)

        self.module_input = QLineEdit()
        self.module_input.setPlaceholderText("Module contains…")
        self.module_input.setClearButtonEnabled(True)
        self.module_input.returnPressed.connect(self.refresh)
        filters.addWidget(self.module_input)

        self.date_checkbox = QCheckBox("Date range")
        self.date_checkbox.toggled.connect(self._toggle_dates)
        filters.addWidget(self.date_checkbox)

        self.from_date = QDateEdit(QDate.currentDate().addDays(-30))
        self.from_date.setCalendarPopup(True)
        self.from_date.setDisplayFormat("dd MMM yyyy")
        self.from_date.setButtonSymbols(QDateEdit.NoButtons)
        self.from_date.setEnabled(False)
        self.from_date.dateChanged.connect(lambda _: self.refresh())
        filters.addWidget(self.from_date)

        self.to_date = QDateEdit(QDate.currentDate())
        self.to_date.setCalendarPopup(True)
        self.to_date.setDisplayFormat("dd MMM yyyy")
        self.to_date.setButtonSymbols(QDateEdit.NoButtons)
        self.to_date.setEnabled(False)
        self.to_date.dateChanged.connect(lambda _: self.refresh())
        filters.addWidget(self.to_date)

        filters.addStretch(1)
        refresh_button = secondary_button("Refresh")
        refresh_button.clicked.connect(self.refresh)
        filters.addWidget(refresh_button)

        reset_button = secondary_button("Reset filters")
        reset_button.clicked.connect(self._reset_filters)
        filters.addWidget(reset_button)
        layout.addLayout(filters)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setVisible(False)
        layout.addWidget(self._error)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._show_detail)
        splitter.addWidget(self.table)

        detail_widget = QWidget()
        detail_layout = QVBoxLayout(detail_widget)
        detail_layout.setContentsMargins(0, 6, 0, 0)
        detail_layout.setSpacing(4)
        detail_layout.addWidget(muted_label("Entry detail"))
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select an audit entry to inspect its recorded values.")
        detail_layout.addWidget(self.detail, 1)
        splitter.addWidget(detail_widget)
        splitter.setSizes([420, 170])
        layout.addWidget(splitter, 1)

        self._count_label = QLabel("")
        self._count_label.setObjectName("Muted")
        layout.addWidget(self._count_label)

    def _toggle_dates(self, enabled: bool) -> None:
        self.from_date.setEnabled(enabled)
        self.to_date.setEnabled(enabled)
        self.refresh()

    def _reset_filters(self) -> None:
        self.user_combo.blockSignals(True)
        self.action_combo.blockSignals(True)
        self.user_combo.setCurrentIndex(0)
        self.action_combo.setCurrentIndex(0)
        self.user_combo.blockSignals(False)
        self.action_combo.blockSignals(False)
        self.module_input.clear()
        self.date_checkbox.setChecked(False)
        self.refresh()

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._error.setVisible(False)
        self._load_filter_options()

        date_from = date_to = None
        if self.date_checkbox.isChecked():
            date_from = local_to_utc(
                datetime.combine(self.from_date.date().toPython(), time.min)
            )
            date_to = local_to_utc(
                datetime.combine(self.to_date.date().toPython(), time.max)
            )

        try:
            entries = self._context.audit_service.list_entries(
                user_id=self.user_combo.currentData(),
                action=self.action_combo.currentData(),
                module=self.module_input.text().strip() or None,
                date_from=date_from,
                date_to=date_to,
                limit=PAGE_LIMIT,
            )
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return

        self._entries = entries
        self._render(entries)

    def _load_filter_options(self) -> None:
        if self.user_combo.count() == 0:
            try:
                self.user_combo.blockSignals(True)
                self.user_combo.addItem("All users", None)
                for user_id, name in self._context.audit_service.filter_users():
                    self.user_combo.addItem(name, user_id)
                self.action_combo.blockSignals(True)
                self.action_combo.addItem("All actions", None)
                for action in self._context.audit_service.available_actions():
                    self.action_combo.addItem(action.replace("_", " ").title(), action)
            except BizPilotError:
                return
            finally:
                self.user_combo.blockSignals(False)
                self.action_combo.blockSignals(False)

    def _render(self, entries: list[AuditEntryView]) -> None:
        self.table.setRowCount(0)
        for row, entry in enumerate(entries):
            self.table.insertRow(row)
            values = (
                format_datetime(entry.created_at),
                entry.user_name,
                entry.action.replace("_", " ").title(),
                entry.module,
                f"{entry.entity_type or '—'}"
                + (f" #{entry.entity_id}" if entry.entity_id else ""),
                entry.status.title(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if column == 5:
                    item.setForeground(
                        QBrush(QColor("#15803D" if entry.status == "SUCCESS" else "#B91C1C"))
                    )
                self.table.setItem(row, column, item)

        self._count_label.setText(
            f"Showing {len(entries)} most recent entries (limit {PAGE_LIMIT}). "
            "Audit records are append-only."
        )
        self.detail.clear()

    def _show_detail(self) -> None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._entries):
            self.detail.clear()
            return
        entry = self._entries[row]
        payload = {
            "id": entry.id,
            "timestamp": format_datetime(entry.created_at, "%d %b %Y, %I:%M:%S %p"),
            "user": entry.user_name,
            "action": entry.action,
            "module": entry.module,
            "entity": f"{entry.entity_type or '—'}"
            + (f" #{entry.entity_id}" if entry.entity_id else ""),
            "status": entry.status,
            "device": entry.device,
            "old_values": entry.old_values,
            "new_values": entry.new_values,
        }
        self.detail.setPlainText(json.dumps(payload, indent=2, default=str))
