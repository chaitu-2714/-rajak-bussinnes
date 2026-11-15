"""BizPilot AI desktop application entry point.

Run from source:      python main.py
Run from a bundle:    BizPilotAI.exe   (see deployment/build.spec)
"""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtWidgets import QApplication, QMessageBox

from app.core.application import ApplicationContext
from app.core.config import APP_NAME, APP_VERSION, load_config
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger, setup_logging
from app.ui.app_controller import AppController
from app.ui.theme import apply_theme

logger = get_logger("main")


def _install_exception_hook() -> None:
    """Log unexpected exceptions and show a friendly message instead of crashing."""

    def handler(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.critical(
            "Unhandled exception:\n%s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        QMessageBox.critical(
            None,
            "BizPilot AI",
            "An unexpected error occurred. The details were written to the "
            "application log so they can be investigated.",
        )

    sys.excepthook = handler


def main() -> int:
    """Start the desktop application."""
    config = load_config()
    setup_logging(config.log_dir, logging.INFO)
    logger.info("Starting %s %s", APP_NAME, APP_VERSION)
    logger.info("Data directory: %s", config.data_dir)

    app = QApplication(sys.argv)
    apply_theme(app, config)
    _install_exception_hook()

    try:
        context = ApplicationContext.build(config)
    except BizPilotError as exc:
        logger.error("Startup failed: %s", exc.message)
        QMessageBox.critical(None, APP_NAME, exc.user_message)
        return 1
    except Exception:
        logger.exception("Startup failed with an unexpected error")
        QMessageBox.critical(
            None,
            APP_NAME,
            "BizPilot AI could not start. The details were written to the application log.",
        )
        return 1

    controller = AppController(context)
    controller.start()

    exit_code = app.exec()
    context.database.dispose()
    logger.info("Application exited with code %s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
