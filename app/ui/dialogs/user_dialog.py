"""Create / edit user dialog."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.schemas.user_schema import UserSummary
from app.ui.ui_utils import (
    field_label,
    muted_label,
    primary_button,
    secondary_button,
    show_error,
)
from app.utils.validators import validate_password_strength


class UserDialog(QDialog):
    """Modal form for creating or editing a user account."""

    def __init__(
        self,
        context: ApplicationContext,
        user: UserSummary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._context = context
        self._user = user
        self._role_checks: dict[int, QCheckBox] = {}
        self._is_edit = user is not None

        self.setWindowTitle("Edit user" if self._is_edit else "New user")
        self.setModal(True)
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(12)

        heading = QLabel("Edit user account" if self._is_edit else "Create a user account")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(
            muted_label(
                "Roles decide what this user can do. Permissions are enforced by the "
                "service layer, not just by the interface."
            )
        )

        self._error = QLabel("")
        self._error.setObjectName("FormError")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        layout.addWidget(field_label("Full name *"))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Asha Rao")
        layout.addWidget(self.name_input)

        layout.addWidget(field_label("Email address *"))
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("name@business.com")
        layout.addWidget(self.email_input)

        layout.addWidget(field_label("Phone"))
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Optional")
        layout.addWidget(self.phone_input)

        if not self._is_edit:
            layout.addWidget(field_label("Temporary password *"))
            self.password_input = QLineEdit()
            self.password_input.setEchoMode(QLineEdit.Password)
            self.password_input.setPlaceholderText("At least 10 characters")
            layout.addWidget(self.password_input)

            layout.addWidget(field_label("Confirm password *"))
            self.confirm_input = QLineEdit()
            self.confirm_input.setEchoMode(QLineEdit.Password)
            layout.addWidget(self.confirm_input)

            hint = QLabel(
                "Must include uppercase, lowercase, a number and a special character. "
                "Share it with the user and ask them to change it after first sign-in."
            )
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            layout.addWidget(hint)
        else:
            self.password_input = None
            self.confirm_input = None

        layout.addWidget(field_label("Roles *"))
        layout.addWidget(self._roles_widget(), 1)

        self.active_checkbox = QCheckBox("Account is active")
        self.active_checkbox.setChecked(True if not self._is_edit else user.is_active)
        if self._is_edit:
            self.active_checkbox.setVisible(False)
        layout.addWidget(self.active_checkbox)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.reject)
        self._save = primary_button("Save changes" if self._is_edit else "Create user")
        self._save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(self._save)
        layout.addLayout(buttons)

        self._load()

    # -- construction ------------------------------------------------------
    def _roles_widget(self) -> QWidget:
        container = QFrame()
        container.setObjectName("CardMuted")
        outer = QVBoxLayout(container)
        outer.setContentsMargins(12, 10, 12, 10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(130)
        scroll.setMaximumHeight(180)
        scroll.setFrameShape(QFrame.NoFrame)

        inner = QWidget()
        self._roles_layout = QVBoxLayout(inner)
        self._roles_layout.setContentsMargins(0, 0, 0, 0)
        self._roles_layout.setSpacing(6)
        scroll.setWidget(inner)
        outer.addWidget(scroll)
        return container

    def _load(self) -> None:
        try:
            roles = self._context.role_service.list_roles()
        except BizPilotError as exc:
            show_error(self, exc.user_message)
            roles = []

        if not roles:
            note = QLabel("No roles are available. Ask an administrator to configure roles.")
            note.setObjectName("Hint")
            self._roles_layout.addWidget(note)
            return

        selected = set(self._user.role_ids) if self._user else set()
        for role in roles:
            check = QCheckBox(f"{role.role_name} — {role.description or 'No description'}")
            check.setProperty("role_id", role.id)
            if self._user and not self._user.is_superuser and role.role_name == "Super Admin":
                # Only a Super Admin may grant the Super Admin role.
                principal = self._context.auth_context.principal
                if principal and not principal.is_superuser:
                    check.setEnabled(False)
            if role.id in selected:
                check.setChecked(True)
            self._role_checks[role.id] = check
            self._roles_layout.addWidget(check)
        self._roles_layout.addStretch(1)

        if self._user:
            self.name_input.setText(self._user.full_name)
            self.email_input.setText(self._user.email)
            self.phone_input.setText(self._user.phone or "")

    # -- validation --------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def selected_role_ids(self) -> list[int]:
        return [role_id for role_id, check in self._role_checks.items() if check.isChecked()]

    def payload(self) -> dict:
        data = {
            "full_name": self.name_input.text().strip(),
            "email": self.email_input.text().strip(),
            "phone": self.phone_input.text().strip() or None,
            "role_ids": self.selected_role_ids(),
        }
        if not self._is_edit:
            data["password"] = self.password_input.text()
            data["password_confirm"] = self.confirm_input.text()
            data["is_active"] = self.active_checkbox.isChecked()
        return data

    def _validate(self) -> bool:
        if len(self.name_input.text().strip()) < 2:
            self._show_error("Enter the user's full name.")
            return False
        if "@" not in self.email_input.text():
            self._show_error("Enter a valid email address.")
            return False
        if not self.selected_role_ids():
            self._show_error("Select at least one role.")
            return False
        if not self._is_edit:
            problems = validate_password_strength(self.password_input.text(), 10)
            if problems:
                self._show_error(" ".join(problems))
                return False
            if self.password_input.text() != self.confirm_input.text():
                self._show_error("The passwords do not match.")
                return False
        return True

    def _submit(self) -> None:
        self._error.setVisible(False)
        if not self._validate():
            return

        payload = self.payload()
        try:
            if self._is_edit and self._user is not None:
                self._context.user_service.update_user(self._user.id, payload)
            else:
                self._context.user_service.create_user(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        except Exception:
            self._show_error("The user could not be saved. Please try again.")
            return
        self.accept()
