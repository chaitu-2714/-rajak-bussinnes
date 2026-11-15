"""Dashboard statistic card.

A card shows a real value, or an explicit "not available yet" state instead of
inventing numbers for modules that do not exist in Phase 1.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QVBoxLayout, QWidget


class StatCard(QFrame):
    """Rounded card with title, value and caption."""

    def __init__(
        self,
        title: str,
        value: str | None = None,
        caption: str = "",
        available: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setProperty("available", "true" if available else "false")
        self.setMinimumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        self._title = QLabel(title)
        self._title.setObjectName("StatTitle")

        self._value = QLabel()
        self._value.setObjectName("StatValue")
        self._value.setProperty("available", "true" if available else "false")

        self._caption = QLabel()
        self._caption.setObjectName("StatCaption")
        self._caption.setProperty("available", "true" if available else "false")
        self._caption.setWordWrap(True)

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._caption)
        layout.addStretch(1)

        self.set_value(value, available, caption)

    def set_value(self, value: str | None, available: bool = True, caption: str | None = None) -> None:
        self._value.setText(value if value is not None else "—")
        if caption is not None:
            self._caption.setText(caption)
        self.setProperty("available", "true" if available else "false")
        self._value.setProperty("available", "true" if available else "false")
        self._caption.setProperty("available", "true" if available else "false")
        self._value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        for widget in (self, self._value, self._caption):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

    @property
    def value_text(self) -> str:
        return self._value.text()
