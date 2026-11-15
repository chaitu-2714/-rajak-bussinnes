"""Profile dialog for the signed-in user."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.ui.ui_utils import (
    field_label,
    muted_label,
    primary_button,
    secondary_button,
)


class ProfileDialog(QDialog):
    """View account details and edit name/phone."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.setWindowTitle("My profile")
        self.setModal(True)
        self.setMinimumWidth(460)

        principal = context.auth_context.principal
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("My profile")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        layout.addWidget(field_label("Email address"))
        email = QLineEdit(principal.email if principal else "")
        email.setReadOnly(True)
        layout.addWidget(email)

        layout.addWidget(field_label("Roles"))
        roles = QLineEdit(", ".join(principal.roles) if principal else "")
        roles.setReadOnly(True)
        layout.addWidget(roles)

        layout.addWidget(field_label("Full name *"))
        self.name_input = QLineEdit(principal.full_name if principal else "")
        layout.addWidget(self.name_input)

        layout.addWidget(field_label("Phone"))
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Optional")
        layout.addWidget(self.phone_input)

        layout.addWidget(
            muted_label("Email address and roles can only be changed by an administrator.")
        )

        self._error = QLabel("")
        self._error.setObjectName("FormError")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button("Close")
        cancel.clicked.connect(self.reject)
        save = primary_button("Save changes")
        save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._load_phone()

    def _load_phone(self) -> None:
        try:
            principal = self._context.auth_context.principal
            if principal is None:
                return
            user = self._context.user_service.get_user(principal.user_id)
            self.phone_input.setText(user.phone or "")
        except BizPilotError:
            # A user without users.view still sees their own name; phone stays empty.
            self.phone_input.setText("")

    def _submit(self) -> None:
        self._error.setVisible(False)
        if len(self.name_input.text().strip()) < 2:
            self._error.setText("Enter your full name.")
            self._error.setVisible(True)
            return
        try:
            self._context.user_service.update_own_profile(
                {
                    "full_name": self.name_input.text().strip(),
                    "phone": self.phone_input.text().strip() or None,
                }
            )
        except BizPilotError as exc:
            self._error.setText(exc.user_message)
            self._error.setVisible(True)
            return
        self.accept()
