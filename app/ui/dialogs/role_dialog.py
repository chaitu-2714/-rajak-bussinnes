"""Create / edit role dialog with grouped permission selection."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import ROLE_SUPER_ADMIN
from app.core.exceptions import BizPilotError
from app.schemas.role_schema import RoleSummary
from app.ui.ui_utils import (
    field_label,
    muted_label,
    primary_button,
    secondary_button,
    show_error,
)

_KEY_ROLE = Qt.UserRole + 1


class RoleDialog(QDialog):
    """Create or edit a role and its permissions."""

    def __init__(
        self,
        context: ApplicationContext,
        role: RoleSummary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._context = context
        self._role = role
        self._is_edit = role is not None
        self._is_super_admin = bool(role and role.role_name == ROLE_SUPER_ADMIN)

        self.setWindowTitle("Edit role" if self._is_edit else "New role")
        self.setModal(True)
        self.setMinimumSize(600, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Edit role" if self._is_edit else "Create a custom role")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        subtitle = (
            "System role names are fixed. Permissions you change here apply to every "
            "user holding this role."
            if self._is_edit
            else "Group permissions by module. Users receive these capabilities through this role."
        )
        layout.addWidget(muted_label(subtitle))

        self._error = QLabel("")
        self._error.setObjectName("FormError")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        layout.addWidget(field_label("Role name *"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Warehouse Supervisor")
        if self._is_edit and role and role.is_system_role:
            self.name_input.setReadOnly(True)
            self.name_input.setToolTip("System role names cannot be changed")
        layout.addWidget(self.name_input)

        layout.addWidget(field_label("Description"))
        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("What is this role responsible for?")
        layout.addWidget(self.description_input)

        layout.addWidget(field_label("Permissions *"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)
        layout.addWidget(self.tree, 1)

        tools = QHBoxLayout()
        select_all = secondary_button("Select all")
        select_all.clicked.connect(lambda: self._set_all(True))
        clear_all = secondary_button("Clear all")
        clear_all.clicked.connect(lambda: self._set_all(False))
        tools.addWidget(select_all)
        tools.addWidget(clear_all)
        tools.addStretch(1)
        if self._is_super_admin:
            lock_note = QLabel("Super Admin always holds every permission.")
            lock_note.setObjectName("Hint")
            tools.addWidget(lock_note)
        layout.addLayout(tools)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.reject)
        self._save = primary_button("Save role")
        self._save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(self._save)
        layout.addLayout(buttons)

        self._load()

    # -- construction ------------------------------------------------------
    def _load(self) -> None:
        selected = set(self._role.permission_keys) if self._role else set()
        try:
            grouped = self._context.permission_service.grouped()
        except BizPilotError as exc:
            show_error(self, exc.user_message)
            grouped = {}

        for module, permissions in grouped.items():
            parent = QTreeWidgetItem(self.tree, [module])
            parent.setFlags(Qt.ItemIsEnabled)
            parent.setExpanded(True)
            for permission in permissions:
                child = QTreeWidgetItem(parent, [f"{permission.name}  ·  {permission.key}"])
                child.setFlags(
                    Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable
                )
                child.setData(0, _KEY_ROLE, permission.key)
                checked = permission.key in selected or self._is_super_admin
                child.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)
                if self._is_super_admin:
                    child.setFlags(Qt.ItemIsEnabled)

        if self._role:
            self.name_input.setText(self._role.role_name)
            self.description_input.setText(self._role.description or "")

    def _set_all(self, checked: bool) -> None:
        if self._is_super_admin:
            return
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                child.setCheckState(0, Qt.Checked if checked else Qt.Unchecked)

    def permission_keys(self) -> list[str]:
        keys: list[str] = []
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                if child.checkState(0) == Qt.Checked:
                    key = child.data(0, _KEY_ROLE)
                    if key:
                        keys.append(str(key))
        return keys

    def payload(self) -> dict:
        return {
            "role_name": self.name_input.text().strip(),
            "description": self.description_input.text().strip() or None,
            "permission_keys": self.permission_keys(),
        }

    # -- actions -----------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _submit(self) -> None:
        self._error.setVisible(False)
        if len(self.name_input.text().strip()) < 3:
            self._show_error("Role name must be at least 3 characters.")
            return
        if not self.permission_keys():
            self._show_error("Select at least one permission.")
            return

        try:
            if self._is_edit and self._role is not None:
                self._context.role_service.update_role(self._role.id, self.payload())
            else:
                self._context.role_service.create_role(self.payload())
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        except Exception:
            self._show_error("The role could not be saved. Please try again.")
            return
        self.accept()
