"""Top header: page title, notifications and the user menu."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.config import AppConfig
from app.security.authorization import Principal
from app.ui.theme import load_icon
from app.utils.formatters import initials


class Header(QWidget):
    """Application header bar with notification and profile controls."""

    profile_requested = Signal()
    password_requested = Signal()
    logout_requested = Signal()
    notifications_requested = Signal()

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self.setObjectName("Header")
        self.setFixedHeight(64)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(22, 10, 18, 10)
        layout.setSpacing(12)

        self._title = QLabel("Overview")
        self._title.setObjectName("HeaderTitle")
        layout.addWidget(self._title)
        layout.addStretch(1)

        self._business_label = QLabel("")
        self._business_label.setObjectName("Muted")
        layout.addWidget(self._business_label)

        divider = QFrame()
        divider.setObjectName("Divider")
        divider.setFixedSize(1, 24)
        layout.addWidget(divider)

        self._notification_button = QToolButton()
        self._notification_button.setObjectName("HeaderButton")
        self._notification_button.setIcon(load_icon(self._config, "bell"))
        self._notification_button.setIconSize(QSize(16, 16))
        self._notification_button.setText("Activity")
        self._notification_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._notification_button.setCursor(Qt.PointingHandCursor)
        self._notification_button.setToolTip("Recent workspace activity")
        self._notification_button.clicked.connect(self.notifications_requested.emit)
        layout.addWidget(self._notification_button)

        self._avatar = QLabel("?")
        self._avatar.setObjectName("Avatar")
        self._avatar.setAlignment(Qt.AlignCenter)
        self._avatar.setFixedSize(32, 32)
        layout.addWidget(self._avatar)

        identity = QVBoxLayout()
        identity.setSpacing(0)
        identity.setContentsMargins(0, 0, 0, 0)
        self._name = QLabel("")
        self._name.setObjectName("UserName")
        self._role = QLabel("")
        self._role.setObjectName("UserRole")
        identity.addWidget(self._name)
        identity.addWidget(self._role)
        layout.addLayout(identity)

        self._menu_button = QToolButton()
        self._menu_button.setObjectName("HeaderButton")
        self._menu_button.setText("▾")
        self._menu_button.setCursor(Qt.PointingHandCursor)
        self._menu_button.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self)
        menu.addAction("My profile", self.profile_requested.emit)
        menu.addAction("Change password", self.password_requested.emit)
        menu.addSeparator()
        menu.addAction("Sign out", self.logout_requested.emit)
        self._menu_button.setMenu(menu)
        layout.addWidget(self._menu_button)

    # -- context -----------------------------------------------------------
    def set_context(self, principal: Principal, business_name: str) -> None:
        self._name.setText(principal.full_name)
        self._role.setText(principal.primary_role)
        self._avatar.setText(initials(principal.full_name))
        self._business_label.setText(business_name)

    def set_page_title(self, title: str) -> None:
        self._title.setText(title)

    def set_notification_count(self, count: int) -> None:
        self._notification_button.setText(f"Activity ({count})" if count else "Activity")

    def notification_button(self) -> QToolButton:
        return self._notification_button
