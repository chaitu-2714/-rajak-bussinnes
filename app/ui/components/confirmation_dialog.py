"""Confirmation dialogs for destructive or irreversible actions."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.ui.ui_utils import danger_button, primary_button, secondary_button


class ConfirmationDialog(QDialog):
    """Modal confirmation with an optional typed challenge phrase."""

    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        message: str,
        confirm_text: str = "Confirm",
        destructive: bool = False,
        challenge: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(440)
        self._challenge = challenge
        self._challenge_input: QLineEdit | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)

        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)

        body = QLabel(message)
        body.setWordWrap(True)
        body.setObjectName("Muted")
        layout.addWidget(body)

        if challenge:
            prompt = QLabel(f"Type <b>{challenge}</b> to continue")
            prompt.setObjectName("FieldLabel")
            layout.addWidget(prompt)
            self._challenge_input = QLineEdit()
            self._challenge_input.setPlaceholderText(challenge)
            self._challenge_input.textChanged.connect(self._validate)
            layout.addWidget(self._challenge_input)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.reject)
        self._confirm = danger_button(confirm_text) if destructive else primary_button(confirm_text)
        self._confirm.clicked.connect(self.accept)
        self._confirm.setDefault(True)
        buttons.addWidget(cancel)
        buttons.addWidget(self._confirm)
        layout.addLayout(buttons)

        if challenge:
            self._confirm.setEnabled(False)

    def _validate(self, text: str) -> None:
        self._confirm.setEnabled(bool(self._challenge) and text.strip() == self._challenge)


def confirm(
    parent: QWidget | None,
    *,
    title: str,
    message: str,
    confirm_text: str = "Confirm",
    destructive: bool = False,
    challenge: str | None = None,
) -> bool:
    """Show a confirmation dialog and return True when the user accepts."""
    dialog = ConfirmationDialog(
        parent,
        title=title,
        message=message,
        confirm_text=confirm_text,
        destructive=destructive,
        challenge=challenge,
    )
    return dialog.exec() == QDialog.Accepted
