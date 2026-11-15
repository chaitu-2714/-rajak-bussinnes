"""Coming-soon page for modules delivered in later phases.

It states clearly that the module is not implemented yet rather than showing
inactive buttons or fabricated data.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from app.ui.navigation import NavItem


class ComingSoonPage(QWidget):
    """Explicit placeholder that never pretends to be operational."""

    def __init__(self, item: NavItem, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PageSurface")
        self._item = item

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 22, 24, 24)
        outer.setSpacing(14)

        card = QFrame()
        card.setObjectName("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 34, 30, 34)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignTop)

        glyph = QFrame()
        glyph.setObjectName("ComingSoonIcon")
        glyph.setFixedSize(44, 44)
        glyph_layout = QVBoxLayout(glyph)
        glyph_layout.setContentsMargins(0, 0, 0, 0)
        symbol = QLabel("◆")
        symbol.setObjectName("ComingSoonGlyph")
        symbol.setAlignment(Qt.AlignCenter)
        glyph_layout.addWidget(symbol)
        layout.addWidget(glyph)

        title = QLabel(f"{item.label} arrives in {item.phase or 'a later phase'}")
        title.setObjectName("PageTitle")
        layout.addWidget(title)

        description = QLabel(item.description or "This module is planned for a later phase.")
        description.setObjectName("Muted")
        description.setWordWrap(True)
        layout.addWidget(description)

        note = QLabel(
            "Phase 1 delivers the foundation only: authentication, role-based access "
            "control, user management, settings and audit logging. This screen is "
            "intentionally empty so no unfinished feature is presented as working."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)

        badge = QLabel(f"Planned · {item.phase or 'TBD'}")
        badge.setObjectName("PhaseBadge")
        layout.addWidget(badge, 0, Qt.AlignLeft)

        outer.addWidget(card)
        outer.addStretch(1)

    def refresh(self) -> None:
        """No data to refresh for an unimplemented module."""
        return
