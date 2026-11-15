"""Login window."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.config import APP_VERSION, AppConfig
from app.core.exceptions import (
    AccountInactiveError,
    AccountLockedError,
    BizPilotError,
    ValidationError,
)
from app.core.logging_config import get_logger
from app.ui.theme import load_icon, settings
from app.ui.ui_utils import primary_button
from app.utils.date_utils import format_datetime

logger = get_logger("ui.login")


class LoginWindow(QWidget):
    """Email + password sign-in for local accounts."""

    authenticated = Signal()

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._config: AppConfig = context.config
        self.setObjectName("AppRoot")
        self.setWindowTitle("BizPilot AI — Sign in")
        self.setMinimumSize(940, 600)
        self.resize(1040, 640)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._brand_panel(), 4)
        layout.addWidget(self._form_panel(), 5)

        self._prefill_remembered_email()

    # -- layout ------------------------------------------------------------
    def _brand_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("BrandPanel")
        panel.setMinimumWidth(380)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(40, 46, 40, 40)
        layout.setSpacing(16)

        mark = QLabel()
        mark.setPixmap(load_icon(self._config, "app_icon").pixmap(QSize(46, 46)))
        layout.addWidget(mark)

        title = QLabel("BizPilot AI")
        title.setObjectName("BrandHeadline")
        layout.addWidget(title)

        subtitle = QLabel("Business operations, run with confidence.")
        subtitle.setObjectName("BrandBody")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addSpacing(18)
        for line in (
            "Secure local authentication with Argon2id",
            "Role-based access for every module",
            "Complete audit trail of workspace activity",
            "Native Windows desktop application",
        ):
            bullet = QLabel(f"•  {line}")
            bullet.setObjectName("BrandBullet")
            bullet.setWordWrap(True)
            layout.addWidget(bullet)

        layout.addStretch(1)
        footer = QLabel(f"Version {APP_VERSION} · Local workspace")
        footer.setObjectName("BrandBody")
        layout.addWidget(footer)
        return panel

    def _form_panel(self) -> QWidget:
        wrapper = QWidget()
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(48, 40, 48, 40)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("LoginCard")
        card.setMaximumWidth(430)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 28, 30, 26)
        layout.setSpacing(10)

        heading = QLabel("Sign in to your workspace")
        heading.setObjectName("LoginTitle")
        layout.addWidget(heading)

        sub = QLabel("Use the account created during initial setup.")
        sub.setObjectName("LoginSubtitle")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        layout.addSpacing(8)

        email_label = QLabel("Email address")
        email_label.setObjectName("FieldLabel")
        layout.addWidget(email_label)
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("you@business.com")
        self.email_input.setClearButtonEnabled(True)
        self.email_input.returnPressed.connect(lambda: self.password_input.setFocus())
        layout.addWidget(self.email_input)

        password_label = QLabel("Password")
        password_label.setObjectName("FieldLabel")
        layout.addWidget(password_label)

        password_row = QHBoxLayout()
        password_row.setSpacing(8)
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Your password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self.attempt_login)
        password_row.addWidget(self.password_input, 1)

        self._toggle_password = QToolButton()
        self._toggle_password.setObjectName("HeaderButton")
        self._toggle_password.setText("Show")
        self._toggle_password.setCheckable(True)
        self._toggle_password.setCursor(Qt.PointingHandCursor)
        self._toggle_password.toggled.connect(self._on_toggle_password)
        password_row.addWidget(self._toggle_password)
        layout.addLayout(password_row)

        self.remember_checkbox = QCheckBox("Remember my email on this computer")
        layout.addWidget(self.remember_checkbox)
        layout.addSpacing(4)

        self.error_label = QLabel("")
        self.error_label.setObjectName("FormError")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        layout.addWidget(self.error_label)

        self.login_button = primary_button("Sign in")
        self.login_button.setMinimumHeight(38)
        self.login_button.clicked.connect(self.attempt_login)
        layout.addWidget(self.login_button)

        layout.addSpacing(6)
        hint = QLabel("Accounts lock temporarily after repeated failed sign-in attempts.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        outer.addWidget(card, 0, Qt.AlignHCenter)
        outer.addStretch(1)

        version = QLabel(f"BizPilot AI {APP_VERSION}")
        version.setObjectName("Hint")
        version.setAlignment(Qt.AlignCenter)
        outer.addWidget(version)
        return wrapper

    # -- behaviour ---------------------------------------------------------
    def _prefill_remembered_email(self) -> None:
        store = settings()
        remember = store.value("login/remember_email", False, type=bool)
        self.remember_checkbox.setChecked(bool(remember))
        if remember:
            self.email_input.setText(store.value("login/last_email", "", type=str) or "")
            self.password_input.setFocus()
        else:
            self.email_input.setFocus()

    def _on_toggle_password(self, shown: bool) -> None:
        self.password_input.setEchoMode(QLineEdit.Normal if shown else QLineEdit.Password)
        self._toggle_password.setText("Hide" if shown else "Show")

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(True)

    def _clear_error(self) -> None:
        self.error_label.clear()
        self.error_label.setVisible(False)

    def attempt_login(self) -> None:
        """Validate input and authenticate against the local database."""
        self._clear_error()
        email = self.email_input.text().strip()
        password = self.password_input.text()

        if not email:
            self._show_error("Enter your email address.")
            self.email_input.setFocus()
            return
        if not password:
            self._show_error("Enter your password.")
            self.password_input.setFocus()
            return

        self.login_button.setEnabled(False)
        self.login_button.setText("Signing in…")
        try:
            self._context.auth_service.login(email, password)
        except AccountLockedError as exc:
            self._show_error(
                "This account is temporarily locked after repeated failed attempts. "
                f"Try again after {format_datetime(exc.locked_until, '%I:%M %p')}."
            )
            self.password_input.clear()
            return
        except AccountInactiveError as exc:
            self._show_error(exc.user_message)
            return
        except ValidationError as exc:
            self._show_error(exc.user_message)
            return
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            logger.info("Login rejected: %s", exc.message)
            return
        except Exception:
            logger.exception("Unexpected login failure")
            self._show_error("Sign-in failed unexpectedly. Please try again.")
            return
        finally:
            self.login_button.setEnabled(True)
            self.login_button.setText("Sign in")

        store = settings()
        if self.remember_checkbox.isChecked():
            store.setValue("login/remember_email", True)
            store.setValue("login/last_email", email)
        else:
            store.setValue("login/remember_email", False)
            store.setValue("login/last_email", "")

        self.password_input.clear()
        self.authenticated.emit()

    def reset(self) -> None:
        """Clear the form when returning from a signed-out session."""
        self._clear_error()
        self.password_input.clear()
        self._prefill_remembered_email()
