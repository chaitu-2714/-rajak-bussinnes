"""User management page."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.schemas.user_schema import UserSummary
from app.ui.components.confirmation_dialog import confirm
from app.ui.dialogs.password_dialog import PasswordResetDialog
from app.ui.dialogs.user_dialog import UserDialog
from app.ui.ui_utils import (
    danger_button,
    primary_button,
    secondary_button,
    show_info,
)
from app.utils.date_utils import format_datetime

logger = get_logger("ui.users")

COLUMNS = ("Name", "Email", "Phone", "Roles", "Status", "Created", "Last sign-in")


class UsersPage(QWidget):
    """List, search, create, edit and deactivate user accounts."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._users: list[UserSummary] = []
        self.setObjectName("PageSurface")
        self._build()
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 24)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchInput")
        self.search_input.setPlaceholderText("Search by name, email or phone…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(260)
        self.search_input.textChanged.connect(lambda _: self.refresh())
        toolbar.addWidget(self.search_input)

        self.role_combo = QComboBox()
        self.role_combo.setMinimumWidth(160)
        self.role_combo.currentIndexChanged.connect(lambda _: self.refresh())
        toolbar.addWidget(self.role_combo)

        self.status_combo = QComboBox()
        self.status_combo.addItem("All statuses", None)
        self.status_combo.addItem("Active", True)
        self.status_combo.addItem("Inactive", False)
        self.status_combo.currentIndexChanged.connect(lambda _: self.refresh())
        toolbar.addWidget(self.status_combo)

        toolbar.addStretch(1)

        principal = self._context.auth_context.principal
        self._can_create = bool(principal and principal.has("users.create"))
        self._can_update = bool(principal and principal.has("users.update"))
        self._can_deactivate = bool(principal and principal.has("users.deactivate"))
        self._can_reset = bool(principal and principal.has("users.reset_password"))

        refresh_button = secondary_button("Refresh")
        refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_button)

        self.new_button = primary_button("New user")
        self.new_button.setEnabled(self._can_create)
        self.new_button.clicked.connect(self._create_user)
        toolbar.addWidget(self.new_button)
        layout.addLayout(toolbar)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._update_action_state)
        self.table.doubleClicked.connect(lambda _: self._edit_user())
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._count_label = QLabel("")
        self._count_label.setObjectName("Muted")
        actions.addWidget(self._count_label)
        actions.addStretch(1)

        self.edit_button = secondary_button("Edit")
        self.edit_button.clicked.connect(self._edit_user)
        actions.addWidget(self.edit_button)

        self.reset_button = secondary_button("Reset password")
        self.reset_button.setEnabled(self._can_reset)
        self.reset_button.clicked.connect(self._reset_password)
        actions.addWidget(self.reset_button)

        self.toggle_button = danger_button("Deactivate")
        self.toggle_button.setEnabled(self._can_deactivate)
        self.toggle_button.clicked.connect(self._toggle_active)
        actions.addWidget(self.toggle_button)
        layout.addLayout(actions)

        self._update_action_state()

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._error.setVisible(False)
        self._load_role_filter()

        role_id = self.role_combo.currentData()
        is_active = self.status_combo.currentData()
        search = self.search_input.text().strip() or None
        try:
            users = self._context.user_service.list_users(
                search=search, role_id=role_id, is_active=is_active
            )
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return

        self._users = users
        self._render(users)

    def _load_role_filter(self) -> None:
        current = self.role_combo.currentData()
        self.role_combo.blockSignals(True)
        self.role_combo.clear()
        self.role_combo.addItem("All roles", None)
        try:
            for role in self._context.role_service.list_roles():
                self.role_combo.addItem(role.role_name, role.id)
        except BizPilotError:
            logger.debug("Role filter unavailable for this user")
        index = self.role_combo.findData(current)
        self.role_combo.setCurrentIndex(index if index >= 0 else 0)
        self.role_combo.blockSignals(False)

    def _render(self, users: list[UserSummary]) -> None:
        self.table.setRowCount(0)
        for row, user in enumerate(users):
            self.table.insertRow(row)
            values = (
                user.full_name,
                user.email,
                user.phone or "—",
                ", ".join(user.roles) or "—",
                "Active" if user.is_active else "Inactive",
                format_datetime(user.created_at, "%d %b %Y"),
                format_datetime(user.last_login_at, "%d %b %Y, %I:%M %p"),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                if column == 0:
                    item.setData(Qt.UserRole, user.id)
                if column == 4:
                    item.setForeground(QBrush(QColor("#15803D" if user.is_active else "#B91C1C")))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(row, column, item)

        self._count_label.setText(f"{len(users)} user(s)")
        self._update_action_state()

    def selected_user(self) -> UserSummary | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._users):
            return None
        return self._users[row]

    def _update_action_state(self) -> None:
        user = self.selected_user()
        has_selection = user is not None
        self.edit_button.setEnabled(has_selection and self._can_update)
        self.reset_button.setEnabled(has_selection and self._can_reset)
        self.toggle_button.setEnabled(has_selection and self._can_deactivate)
        if user is not None:
            self.toggle_button.setText("Deactivate" if user.is_active else "Activate")

    # -- actions -----------------------------------------------------------
    def _create_user(self) -> None:
        dialog = UserDialog(self._context, None, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The user account was created.", "User created")

    def _edit_user(self) -> None:
        user = self.selected_user()
        if user is None:
            return
        dialog = UserDialog(self._context, user, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The user account was updated.", "User updated")

    def _reset_password(self) -> None:
        user = self.selected_user()
        if user is None:
            return
        dialog = PasswordResetDialog(self._context, user.full_name, user.id, self)
        if dialog.exec():
            show_info(
                self,
                f"The password for {user.full_name} was reset and their sessions were revoked.",
                "Password reset",
            )

    def _toggle_active(self) -> None:
        user = self.selected_user()
        if user is None:
            return
        activating = not user.is_active
        if not activating:
            confirmed = confirm(
                self,
                title="Deactivate user",
                message=(
                    f"{user.full_name} will be signed out and blocked from signing in. "
                    "Their records and audit history are preserved."
                ),
                confirm_text="Deactivate user",
                destructive=True,
            )
            if not confirmed:
                return
        try:
            self._context.user_service.set_active(user.id, activating)
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return
        self.refresh()
