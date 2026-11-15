"""Left navigation sidebar with permission-aware entries."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config import APP_VERSION, AppConfig
from app.core.logging_config import get_logger
from app.security.authorization import Principal
from app.ui.navigation import NAV_ITEMS, SECTION_ORDER, NavItem
from app.ui.theme import load_icon

logger = get_logger("ui.sidebar")


class Sidebar(QWidget):
    """Vertical navigation; hides modules the signed-in user cannot view."""

    navigate = Signal(str)

    def __init__(self, config: AppConfig, principal: Principal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._principal = principal
        self._buttons: dict[str, QToolButton] = {}
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        self.setObjectName("Sidebar")
        self.setFixedWidth(248)
        self._build()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._brand())
        layout.addWidget(self._navigation_area(), 1)
        layout.addWidget(self._footer())

    def _brand(self) -> QWidget:
        brand = QWidget()
        brand.setObjectName("SidebarBrand")
        row = QHBoxLayout(brand)
        row.setContentsMargins(16, 16, 16, 14)
        row.setSpacing(10)

        mark = QLabel()
        mark.setPixmap(load_icon(self._config, "app_icon").pixmap(QSize(30, 30)))
        mark.setFixedSize(30, 30)

        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel("BizPilot AI")
        name.setObjectName("BrandName")
        tag = QLabel("BUSINESS OPERATIONS")
        tag.setObjectName("BrandTag")
        text.addWidget(name)
        text.addWidget(tag)

        row.addWidget(mark)
        row.addLayout(text)
        row.addStretch(1)
        return brand

    def _navigation_area(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 4, 0, 8)
        column.setSpacing(1)

        visible = [item for item in NAV_ITEMS if self._can_view(item)]
        for section in SECTION_ORDER:
            section_items = [item for item in visible if item.section == section]
            if not section_items:
                continue
            header = QLabel(section.upper())
            header.setObjectName("SidebarSection")
            column.addWidget(header)
            for item in section_items:
                column.addWidget(self._nav_row(item))
        column.addStretch(1)

        scroll.setWidget(container)
        return scroll

    def _nav_row(self, item: NavItem) -> QWidget:
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(0)

        button = QToolButton()
        button.setObjectName("NavButton")
        button.setText(item.label)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIcon(load_icon(self._config, item.icon))
        button.setIconSize(QSize(17, 17))
        button.setCheckable(True)
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        button.setToolTip(
            f"{item.label} — {item.phase} (not yet implemented)"
            if item.coming_soon
            else item.label
        )
        button.clicked.connect(lambda _=False, key=item.key: self.navigate.emit(key))

        self._group.addButton(button)
        self._buttons[item.key] = button
        layout.addWidget(button, 1)

        if item.coming_soon:
            badge = QLabel("Soon")
            badge.setObjectName("SoonBadge")
            badge.setAlignment(Qt.AlignCenter)
            layout.addWidget(badge)
        return row

    def _footer(self) -> QWidget:
        footer = QWidget()
        layout = QVBoxLayout(footer)
        layout.setContentsMargins(16, 10, 16, 14)
        layout.setSpacing(2)

        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        layout.addWidget(line)

        version = QLabel(f"Version {APP_VERSION}")
        version.setObjectName("Hint")
        layout.addWidget(version)

        mode = QLabel("Local desktop · SQLite")
        mode.setObjectName("Hint")
        layout.addWidget(mode)
        return footer

    # -- behaviour ---------------------------------------------------------
    def _can_view(self, item: NavItem) -> bool:
        return self._principal.has(item.permission)

    def set_active(self, key: str) -> None:
        button = self._buttons.get(key)
        if button is not None and not button.isChecked():
            button.setChecked(True)

    def visible_keys(self) -> list[str]:
        return list(self._buttons.keys())

    def has_item(self, key: str) -> bool:
        return key in self._buttons
