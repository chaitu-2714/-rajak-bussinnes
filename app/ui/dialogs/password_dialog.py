"""Password dialogs: self-service change and administrative reset."""

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
from app.utils.validators import validate_password_strength


class PasswordChangeDialog(QDialog):
    """Change the signed-in user's own password."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.setWindowTitle("Change password")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        heading = QLabel("Change your password")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(
            muted_label(
                "Changing your password signs out your other active sessions on this computer."
            )
        )

        self._error = QLabel("")
        self._error.setObjectName("FormError")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        layout.addWidget(field_label("Current password *"))
        self.current_input = QLineEdit()
        self.current_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.current_input)

        layout.addWidget(field_label("New password *"))
        self.new_input = QLineEdit()
        self.new_input.setEchoMode(QLineEdit.Password)
        self.new_input.setPlaceholderText("At least 10 characters")
        layout.addWidget(self.new_input)

        layout.addWidget(field_label("Confirm new password *"))
        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.confirm_input)

        hint = QLabel(
            "Use uppercase and lowercase letters, a number and a special character."
        )
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.reject)
        save = primary_button("Update password")
        save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _submit(self) -> None:
        self._error.setVisible(False)
        if not self.current_input.text():
            self._show_error("Enter your current password.")
            return
        problems = validate_password_strength(self.new_input.text(), 10)
        if problems:
            self._show_error(" ".join(problems))
            return
        if self.new_input.text() != self.confirm_input.text():
            self._show_error("The new passwords do not match.")
            return
        try:
            self._context.auth_service.change_password(
                self.current_input.text(),
                self.new_input.text(),
                self.confirm_input.text(),
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        except Exception:
            self._show_error("The password could not be updated. Please try again.")
            return
        self.accept()


class PasswordResetDialog(QDialog):
    """Administrator setting a temporary password for another user."""

    def __init__(
        self, context: ApplicationContext, user_name: str, user_id: int, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._context = context
        self._user_id = user_id
        self.setWindowTitle("Reset password")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)

        heading = QLabel(f"Reset password for {user_name}")
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(
            muted_label(
                "The user is signed out everywhere and must use this temporary "
                "password at their next sign-in. The action is written to the audit log."
            )
        )

        self._error = QLabel("")
        self._error.setObjectName("FormError")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        layout.addWidget(field_label("Temporary password *"))
        self.new_input = QLineEdit()
        self.new_input.setEchoMode(QLineEdit.Password)
        self.new_input.setPlaceholderText("At least 10 characters")
        layout.addWidget(self.new_input)

        layout.addWidget(field_label("Confirm password *"))
        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.confirm_input)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.reject)
        save = primary_button("Reset password")
        save.clicked.connect(self._submit)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _submit(self) -> None:
        self._error.setVisible(False)
        problems = validate_password_strength(self.new_input.text(), 10)
        if problems:
            self._show_error(" ".join(problems))
            return
        if self.new_input.text() != self.confirm_input.text():
            self._show_error("The passwords do not match.")
            return
        try:
            self._context.user_service.reset_password(
                self._user_id, self.new_input.text(), self.confirm_input.text()
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        except Exception:
            self._show_error("The password could not be reset. Please try again.")
            return
        self.accept()
