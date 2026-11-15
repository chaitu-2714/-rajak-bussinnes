"""Role and permission management page."""

from __future__ import annotations

from collections import OrderedDict

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.schemas.role_schema import RoleSummary
from app.ui.components.confirmation_dialog import confirm
from app.ui.dialogs.role_dialog import RoleDialog
from app.ui.ui_utils import (
    danger_button,
    muted_label,
    primary_button,
    secondary_button,
    show_info,
)


class RolesPage(QWidget):
    """List roles, inspect permissions and manage custom roles."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._roles: list[RoleSummary] = []
        self._permission_index: "OrderedDict[str, list[tuple[str, str]]] | None" = None
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
        toolbar.addWidget(
            muted_label("Roles bundle permissions. Service calls check these permissions.")
        )
        toolbar.addStretch(1)

        principal = self._context.auth_context.principal
        self._can_create = bool(principal and principal.has("roles.create"))
        self._can_update = bool(principal and principal.has("roles.update"))

        refresh_button = secondary_button("Refresh")
        refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_button)

        self.new_button = primary_button("New role")
        self.new_button.setEnabled(self._can_create)
        self.new_button.clicked.connect(self._create_role)
        toolbar.addWidget(self.new_button)
        layout.addLayout(toolbar)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setVisible(False)
        layout.addWidget(self._error)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Role", "Type", "Users"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.itemSelectionChanged.connect(self._show_selected)
        left_layout.addWidget(self.table, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.edit_button = secondary_button("Edit role")
        self.edit_button.clicked.connect(self._edit_role)
        buttons.addWidget(self.edit_button)
        self.delete_button = danger_button("Delete role")
        self.delete_button.clicked.connect(self._delete_role)
        buttons.addWidget(self.delete_button)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        splitter.addWidget(self._build_detail_panel())
        splitter.setSizes([520, 420])
        layout.addWidget(splitter, 1)

    def _build_detail_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("DetailPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(8)

        header = QHBoxLayout()
        self._detail_name = QLabel("Select a role")
        self._detail_name.setObjectName("SectionTitle")
        header.addWidget(self._detail_name)
        header.addStretch(1)
        self._detail_badge = QLabel("")
        self._detail_badge.setObjectName("Badge")
        self._detail_badge.setVisible(False)
        header.addWidget(self._detail_badge)
        layout.addLayout(header)

        self._detail_description = QLabel("")
        self._detail_description.setObjectName("Muted")
        self._detail_description.setWordWrap(True)
        layout.addWidget(self._detail_description)

        self._detail_meta = QLabel("")
        self._detail_meta.setObjectName("Hint")
        layout.addWidget(self._detail_meta)

        layout.addWidget(muted_label("Granted permissions"))
        self._permission_list = QListWidget()
        self._permission_list.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self._permission_list, 1)

        self._user_hint = QLabel("")
        self._user_hint.setObjectName("Hint")
        self._user_hint.setWordWrap(True)
        layout.addWidget(self._user_hint)
        return panel

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._error.setVisible(False)
        try:
            self._roles = self._context.role_service.list_roles()
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return

        self.table.setRowCount(0)
        for row, role in enumerate(self._roles):
            self.table.insertRow(row)
            values = (
                role.role_name,
                "System" if role.is_system_role else "Custom",
                str(role.user_count),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if column == 0:
                    item.setData(Qt.UserRole, role.id)
                self.table.setItem(row, column, item)

        if self._roles:
            self.table.selectRow(0)
        else:
            self._clear_detail()
        self._update_buttons()

    def selected_role(self) -> RoleSummary | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self._roles):
            return None
        return self._roles[row]

    def _show_selected(self) -> None:
        role = self.selected_role()
        self._update_buttons()
        if role is None:
            self._clear_detail()
            return

        self._detail_name.setText(role.role_name)
        self._detail_badge.setText("System role" if role.is_system_role else "Custom role")
        self._detail_badge.setObjectName(
            "BadgeSystem" if role.is_system_role else "Badge"
        )
        self._detail_badge.style().unpolish(self._detail_badge)
        self._detail_badge.style().polish(self._detail_badge)
        self._detail_badge.setVisible(True)
        self._detail_description.setText(role.description or "No description provided.")
        self._detail_meta.setText(
            f"{len(role.permission_keys)} permissions · {role.user_count} user(s) assigned"
        )

        self._render_permissions(role)

        if role.is_system_role:
            self._user_hint.setText(
                "System roles cannot be deleted. Names are fixed so the security "
                "model stays predictable."
            )
        else:
            self._user_hint.setText(
                "Custom role: rename, re-scope or delete it (only while no users hold it)."
            )

    def _permission_lookup(self) -> "OrderedDict[str, list[tuple[str, str]]]":
        """Permission catalogue grouped by module (cached)."""
        if self._permission_index is None:
            index: OrderedDict[str, list[tuple[str, str]]] = OrderedDict()
            try:
                for module, permissions in self._context.permission_service.grouped().items():
                    index[module] = [(item.key, item.name) for item in permissions]
            except BizPilotError:
                index = OrderedDict()
            self._permission_index = index
        return self._permission_index

    def _render_permissions(self, role: RoleSummary) -> None:
        """Show granted permissions grouped by module, with readable names."""
        self._permission_list.clear()
        granted = set(role.permission_keys)
        lookup = self._permission_lookup()
        catalogued: set[str] = set()

        for module, permissions in lookup.items():
            module_permissions = [
                (key, name) for key, name in permissions if key in granted
            ]
            if not module_permissions:
                continue
            header = QListWidgetItem(module)
            header.setFlags(Qt.NoItemFlags)
            font = header.font()
            font.setBold(True)
            header.setFont(font)
            header.setForeground(QBrush(QColor("#64748B")))
            self._permission_list.addItem(header)
            for key, name in module_permissions:
                item = QListWidgetItem(f"{name}  ·  {key}")
                item.setFlags(Qt.ItemIsEnabled)
                self._permission_list.addItem(item)
                catalogued.add(key)

        for key in sorted(granted - catalogued):
            self._permission_list.addItem(QListWidgetItem(key))

    def _clear_detail(self) -> None:
        self._detail_name.setText("Select a role")
        self._detail_badge.setVisible(False)
        self._detail_description.setText("")
        self._detail_meta.setText("")
        self._permission_list.clear()
        self._user_hint.setText("")

    def _update_buttons(self) -> None:
        role = self.selected_role()
        self.edit_button.setEnabled(role is not None and self._can_update)
        self.delete_button.setEnabled(
            role is not None and self._can_update and not role.is_system_role
        )

    # -- actions -----------------------------------------------------------
    def _create_role(self) -> None:
        dialog = RoleDialog(self._context, None, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The role was created.", "Role created")

    def _edit_role(self) -> None:
        role = self.selected_role()
        if role is None:
            return
        dialog = RoleDialog(self._context, role, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The role was updated.", "Role updated")

    def _delete_role(self) -> None:
        role = self.selected_role()
        if role is None:
            return
        if not confirm(
            self,
            title="Delete role",
            message=(
                f"Delete the custom role '{role.role_name}'? This cannot be undone. "
                "Roles assigned to users cannot be deleted."
            ),
            confirm_text="Delete role",
            destructive=True,
        ):
            return
        try:
            self._context.role_service.delete_role(role.id)
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return
        self.refresh()
