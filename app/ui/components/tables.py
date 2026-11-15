"""Reusable data table with sorting, row identity and an empty state."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QStackedLayout,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

ID_ROLE = Qt.UserRole
SORT_ROLE = Qt.UserRole + 1


class SortableItem(QTableWidgetItem):
    """Table cell that sorts on an explicit key (number, date or text)."""

    def __lt__(self, other: QTableWidgetItem) -> bool:  # noqa: D105
        # Note: calling super().__lt__() here recurses back into this override,
        # so the comparison is implemented entirely in Python.
        mine = self.data(SORT_ROLE)
        theirs = other.data(SORT_ROLE) if hasattr(other, "data") else None
        if mine is None or theirs is None:
            return self.text() < getattr(other, "text", lambda: "")()
        try:
            return mine < theirs
        except TypeError:
            return str(mine) < str(theirs)


class DataTable(QWidget):
    """Thin wrapper that keeps table setup consistent across pages."""

    def __init__(
        self,
        columns: list[str],
        *,
        empty_title: str = "Nothing here yet",
        empty_body: str = "Records will appear once you add them.",
        stretch_columns: tuple[int, ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._columns = columns

        self.table = QTableWidget(0, len(columns))
        self.table.setHorizontalHeaderLabels(columns)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSortingEnabled(True)
        header = self.table.horizontalHeader()
        for index in range(len(columns)):
            if index in stretch_columns:
                header.setSectionResizeMode(index, QHeaderView.Stretch)
            else:
                header.setSectionResizeMode(index, QHeaderView.ResizeToContents)
        if not stretch_columns:
            header.setStretchLastSection(True)

        self._empty = QWidget()
        from PySide6.QtWidgets import QVBoxLayout

        empty_box = QVBoxLayout(self._empty)
        empty_box.setContentsMargins(0, 0, 0, 0)
        empty_box.addStretch(1)
        title = QLabel(empty_title)
        title.setObjectName("EmptyTitle")
        title.setAlignment(Qt.AlignCenter)
        body = QLabel(empty_body)
        body.setObjectName("EmptyBody")
        body.setAlignment(Qt.AlignCenter)
        body.setWordWrap(True)
        empty_box.addWidget(title)
        empty_box.addWidget(body)
        empty_box.addStretch(1)

        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self.table)
        self._stack.addWidget(self._empty)

    # -- data --------------------------------------------------------------
    def set_rows(
        self,
        rows: list[list[Any]],
        *,
        row_ids: list[int] | None = None,
        sort_keys: dict[int, list[Any]] | None = None,
        empty_body: str | None = None,
    ) -> None:
        """Replace the contents.

        ``rows`` holds display strings; ``sort_keys`` optionally maps a column
        index to the raw values used for sorting that column.
        """
        was_sorting = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)

        for row_index, row in enumerate(rows):
            self.table.insertRow(row_index)
            for column, value in enumerate(row):
                item = SortableItem("" if value is None else str(value))
                if column == 0 and row_ids is not None and row_index < len(row_ids):
                    item.setData(ID_ROLE, row_ids[row_index])
                if sort_keys and column in sort_keys:
                    keys = sort_keys[column]
                    if row_index < len(keys):
                        item.setData(SORT_ROLE, keys[row_index])
                self.table.setItem(row_index, column, item)

        self.table.setSortingEnabled(was_sorting)
        if rows:
            # Size columns to their content, then cap very wide cells so the
            # remaining columns stay visible instead of being squeezed.
            self.table.resizeColumnsToContents()
            for column in range(self.table.columnCount()):
                if self.table.columnWidth(column) > 260:
                    self.table.setColumnWidth(column, 260)
        self._stack.setCurrentWidget(self.table if rows else self._empty)
        if empty_body is not None:
            labels = self._empty.findChildren(QLabel)
            if len(labels) >= 2:
                labels[1].setText(empty_body)

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(ID_ROLE) if item else None

    def selected_row_text(self, column: int) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, column)
        return item.text() if item else None

    def row_count(self) -> int:
        return self.table.rowCount()

    def clear_selection(self) -> None:
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
