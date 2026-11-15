"""Window orchestration: setup wizard → login → main window → logout."""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.login_window import LoginWindow
from app.ui.main_window import MainWindow
from app.ui.setup_wizard import SetupWizard
from app.ui.ui_utils import show_error

logger = get_logger("ui.controller")


class AppController(QObject):
    """Owns the top-level windows and the sign-in state machine."""

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__()
        self._context = context
        self._login_window: LoginWindow | None = None
        self._main_window: MainWindow | None = None
        self._wizard: SetupWizard | None = None

    # -- entry -------------------------------------------------------------
    def start(self) -> None:
        """Show the wizard on a fresh workspace, otherwise the login screen."""
        try:
            needs_setup = self._context.auth_service.needs_initial_setup()
        except BizPilotError as exc:
            logger.error("Could not determine setup state: %s", exc.message)
            show_error(None, exc.user_message, "Database problem")
            return

        if needs_setup:
            logger.info("Fresh workspace detected - opening setup wizard")
            self.show_setup()
        else:
            self.show_login()

    # -- windows -----------------------------------------------------------
    def show_setup(self) -> None:
        wizard = SetupWizard(self._context)
        wizard.setup_completed.connect(self._on_setup_completed)
        wizard.rejected.connect(self._on_setup_cancelled)
        self._wizard = wizard
        wizard.show()

    def show_login(self) -> None:
        if self._login_window is None:
            login = LoginWindow(self._context)
            login.authenticated.connect(self._on_authenticated)
            self._login_window = login
        else:
            self._login_window.reset()
        self._login_window.show()
        self._login_window.raise_()
        self._login_window.activateWindow()

    def _open_main_window(self) -> None:
        self._main_window = MainWindow(self._context)
        self._main_window.logout_requested.connect(self.logout)
        self._main_window.show()
        logger.info("Main window opened")

    # -- state transitions -------------------------------------------------
    def _on_setup_completed(self) -> None:
        if self._wizard is not None:
            self._wizard.close()
            self._wizard = None
        self._open_main_window()

    def _on_setup_cancelled(self) -> None:
        logger.info("Setup wizard cancelled by the user")
        self._wizard = None

    def _on_authenticated(self) -> None:
        if self._login_window is not None:
            self._login_window.hide()
        self._open_main_window()

    def logout(self) -> None:
        """Sign out, close the workspace and return to the login screen."""
        try:
            self._context.auth_service.logout()
        except BizPilotError as exc:  # pragma: no cover - defensive
            logger.warning("Logout error: %s", exc.message)

        if self._main_window is not None:
            self._main_window.close()
            self._main_window.deleteLater()
            self._main_window = None
        self.show_login()
        logger.info("Signed out")

    # -- accessors used by tests -------------------------------------------
    @property
    def main_window(self) -> MainWindow | None:
        return self._main_window

    @property
    def login_window(self) -> LoginWindow | None:
        return self._login_window

    @property
    def wizard(self) -> SetupWizard | None:
        return self._wizard
