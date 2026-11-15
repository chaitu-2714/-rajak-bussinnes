"""Small UI helpers shared by pages and dialogs."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QMessageBox, QPushButton, QWidget

from app.core.exceptions import BizPilotError, ValidationError
from app.core.logging_config import get_logger

logger = get_logger("ui")


def primary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", "primary")
    button.setCursor(Qt.PointingHandCursor)
    return button


def secondary_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setCursor(Qt.PointingHandCursor)
    return button


def danger_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", "danger")
    button.setCursor(Qt.PointingHandCursor)
    return button


def ghost_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("variant", "ghost")
    button.setCursor(Qt.PointingHandCursor)
    return button


def field_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("FieldLabel")
    return label


def muted_label(text: str = "") -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    return label


def section_title(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def show_error(
    parent: QWidget | None, message: str | Exception, title: str = "Something went wrong"
) -> None:
    """Show an error dialog; exceptions are reduced to their user-safe message."""
    if not isinstance(message, str):
        message = getattr(message, "user_message", None) or str(message)
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStandardButtons(QMessageBox.Ok)
    box.exec()


def show_info(parent: QWidget | None, message: str, title: str = "BizPilot AI") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Information)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStandardButtons(QMessageBox.Ok)
    box.exec()


def run_action(
    parent: QWidget | None,
    action: Callable[[], Any],
    *,
    success_message: str | None = None,
    success_title: str = "Done",
) -> tuple[bool, Any]:
    """Execute a service call, converting errors into friendly dialogs.

    Returns ``(ok, result)``. Expected :class:`BizPilotError` cases show their
    safe user message; anything unexpected is logged and reported generically.
    """
    try:
        result = action()
    except ValidationError as exc:
        show_error(parent, exc.user_message, "Please check your input")
        return False, exc
    except BizPilotError as exc:
        logger.warning("Handled application error: %s", exc.message)
        show_error(parent, exc.user_message)
        return False, exc
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("Unexpected UI action failure")
        show_error(
            parent,
            "An unexpected error occurred. The details were written to the application log.",
        )
        return False, exc
    if success_message:
        show_info(parent, success_message, success_title)
    return True, result
