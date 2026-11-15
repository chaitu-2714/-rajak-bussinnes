"""First-launch setup wizard.

Runs only when the workspace has no business profile and no users. It creates
the business, the default roles/permissions, the first Super Admin account and
an authenticated session — then hands control to the main window.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWizard,
    QWizardPage,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.config import AppConfig
from app.core.constants import CURRENCIES, TIMEZONES
from app.core.exceptions import BizPilotError, ConflictError, ValidationError
from app.core.logging_config import get_logger
from app.ui.theme import load_icon
from app.utils.validators import validate_password_strength

logger = get_logger("ui.setup")


class SetupWizard(QWizard):
    """Three-step provisioning wizard."""

    setup_completed = Signal()

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._config: AppConfig = context.config

        self.setWindowTitle("BizPilot AI — Initial setup")
        self.setWizardStyle(QWizard.ClassicStyle)
        self.setOption(QWizard.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.HaveHelpButton, False)
        self.setMinimumSize(760, 560)
        self.setWindowIcon(load_icon(self._config, "app_icon"))

        self._build_pages()
        self.setButtonText(QWizard.NextButton, "Continue")
        self.setButtonText(QWizard.FinishButton, "Create workspace")

    # -- pages -------------------------------------------------------------
    def _build_pages(self) -> None:
        self.addPage(self._business_page())
        self.addPage(self._owner_page())
        self.addPage(self._security_page())

    def _business_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Your business")
        page.setSubTitle("This information appears on the dashboard and in reports.")

        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignLeft)

        self.business_name_input = QLineEdit()
        self.business_name_input.setPlaceholderText("e.g. Patnaik Traders")
        form.addRow("Business name *", self.business_name_input)

        self.currency_combo = QComboBox()
        self.currency_combo.addItems(CURRENCIES)
        form.addRow("Currency", self.currency_combo)

        self.timezone_combo = QComboBox()
        self.timezone_combo.addItems(TIMEZONES)
        form.addRow("Timezone", self.timezone_combo)

        self.financial_year_input = QLineEdit("04-01")
        self.financial_year_input.setPlaceholderText("MM-DD")
        form.addRow("Financial year starts", self.financial_year_input)

        layout.addLayout(form)
        layout.addStretch(1)

        note = QLabel(
            "Tip: Indian businesses usually keep INR, Asia/Kolkata and a 1 April "
            "financial year start."
        )
        note.setObjectName("Hint")
        note.setWordWrap(True)
        layout.addWidget(note)
        return page

    def _owner_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Owner account")
        page.setSubTitle("This account becomes the first Super Admin of the workspace.")

        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.setSpacing(10)

        self.owner_name_input = QLineEdit()
        self.owner_name_input.setPlaceholderText("Full name")
        form.addRow("Your name *", self.owner_name_input)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("you@business.com")
        form.addRow("Admin email *", self.email_input)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Optional")
        form.addRow("Phone", self.phone_input)

        layout.addLayout(form)
        layout.addStretch(1)

        note = QLabel("The email is your login identifier and must be unique.")
        note.setObjectName("Hint")
        layout.addWidget(note)
        return page

    def _security_page(self) -> QWizardPage:
        page = QWizardPage()
        page.setTitle("Secure your workspace")
        page.setSubTitle("There is no default password — choose a strong one now.")

        layout = QVBoxLayout(page)
        form = QFormLayout()
        form.setSpacing(10)

        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setPlaceholderText("At least 10 characters")
        form.addRow("Password *", self.password_input)

        self.confirm_input = QLineEdit()
        self.confirm_input.setEchoMode(QLineEdit.Password)
        self.confirm_input.setPlaceholderText("Repeat the password")
        form.addRow("Confirm password *", self.confirm_input)

        layout.addLayout(form)

        rules = QLabel(
            "Use at least 10 characters with uppercase and lowercase letters, "
            "a number and a special character."
        )
        rules.setObjectName("Hint")
        rules.setWordWrap(True)
        layout.addWidget(rules)

        layout.addSpacing(12)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("Muted")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        layout.addStretch(1)
        return page

    # -- navigation / validation ------------------------------------------
    def validateCurrentPage(self) -> bool:  # noqa: N802 (Qt override)
        page_id = self.currentId()
        if page_id == 0:
            if not self.business_name_input.text().strip():
                self._warn("Enter the business name.")
                return False
            year = self.financial_year_input.text().strip()
            parts = year.split("-")
            if len(parts) != 2 or not all(part.isdigit() for part in parts):
                self._warn("Financial year start must use MM-DD format.")
                return False
            return True

        if page_id == 1:
            if len(self.owner_name_input.text().strip()) < 2:
                self._warn("Enter the owner's full name.")
                return False
            email = self.email_input.text().strip()
            if "@" not in email or "." not in email.split("@")[-1]:
                self._warn("Enter a valid email address.")
                return False
            return True

        if page_id == 2:
            password = self.password_input.text()
            problems = validate_password_strength(password, 10)
            if problems:
                self._warn("\n".join(problems))
                return False
            if password != self.confirm_input.text():
                self._warn("The passwords do not match.")
                return False
            self.summary_label.setText(
                f"Ready to create <b>{self.business_name_input.text().strip()}</b> with "
                f"<b>{self.owner_name_input.text().strip()}</b> "
                f"({self.email_input.text().strip()}) as Super Admin."
            )
            return True
        return True

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Check your details", message)

    def accept(self) -> None:  # noqa: D102 (Qt override)
        payload = {
            "business_name": self.business_name_input.text().strip(),
            "owner_name": self.owner_name_input.text().strip(),
            "email": self.email_input.text().strip(),
            "phone": self.phone_input.text().strip() or None,
            "password": self.password_input.text(),
            "password_confirm": self.confirm_input.text(),
            "currency": self.currency_combo.currentText(),
            "timezone": self.timezone_combo.currentText(),
            "financial_year_start": self.financial_year_input.text().strip(),
        }
        try:
            self._context.auth_service.run_initial_setup(payload)
        except ConflictError as exc:
            QMessageBox.warning(self, "Already configured", exc.user_message)
            self.reject()
            return
        except ValidationError as exc:
            QMessageBox.warning(self, "Check your details", exc.user_message)
            return
        except BizPilotError as exc:
            QMessageBox.critical(self, "Setup failed", exc.user_message)
            logger.error("Setup failed: %s", exc.message)
            return
        except Exception:
            logger.exception("Unexpected setup failure")
            QMessageBox.critical(
                self,
                "Setup failed",
                "The workspace could not be created. Details were written to the application log.",
            )
            return

        logger.info("Workspace provisioned through the setup wizard")
        self.setup_completed.emit()
        super().accept()

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        return QSize(max(hint.width(), 760), max(hint.height(), 560))
