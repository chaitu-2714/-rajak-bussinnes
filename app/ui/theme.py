"""Theme loading and application-wide look and feel."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication

from app.core.config import APP_VERSION, AppConfig
from app.core.logging_config import get_logger

logger = get_logger("ui.theme")

SETTINGS_ORG = "BizPilotAI"
SETTINGS_APP = "BizPilot AI"

STYLE_FILES = ("light_theme.qss", "components.qss")


def settings() -> QSettings:
    """Persistent UI preferences (remembered email, theme, window state)."""
    return QSettings(SETTINGS_ORG, SETTINGS_APP)


def icon_path(config: AppConfig, name: str) -> Path:
    return config.resources_dir / "icons" / f"{name}.svg"


def load_icon(config: AppConfig, name: str) -> QIcon:
    path = icon_path(config, name)
    if path.exists():
        return QIcon(str(path))
    return QIcon()


def _read_styles(config: AppConfig) -> str:
    chunks: list[str] = []
    for filename in STYLE_FILES:
        path = config.style_path(filename)
        if path.exists():
            chunks.append(path.read_text(encoding="utf-8"))
        else:
            logger.warning("Stylesheet not found: %s", path)
    return "\n".join(chunks)


def create_light_palette() -> QPalette:
    """Explicit light palette so Windows/system dark mode doesn't turn backgrounds black."""
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#F5F7FA"))
    palette.setColor(QPalette.WindowText, QColor("#1F2937"))
    palette.setColor(QPalette.Base, QColor("#FFFFFF"))
    palette.setColor(QPalette.AlternateBase, QColor("#F8FAFC"))
    palette.setColor(QPalette.ToolTipBase, QColor("#0F172A"))
    palette.setColor(QPalette.ToolTipText, QColor("#F8FAFC"))
    palette.setColor(QPalette.Text, QColor("#1F2937"))
    palette.setColor(QPalette.Button, QColor("#F1F5F9"))
    palette.setColor(QPalette.ButtonText, QColor("#1F2937"))
    palette.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Link, QColor("#2563EB"))
    palette.setColor(QPalette.Highlight, QColor("#2563EB"))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    palette.setColor(QPalette.Mid, QColor("#D7DEE8"))
    palette.setColor(QPalette.Dark, QColor("#94A3B8"))
    palette.setColor(QPalette.Light, QColor("#FFFFFF"))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor("#94A3B8"))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor("#94A3B8"))
    palette.setColor(QPalette.Disabled, QPalette.WindowText, QColor("#94A3B8"))
    palette.setColor(QPalette.Disabled, QPalette.Base, QColor("#F8FAFC"))
    return palette


def apply_theme(app: QApplication, config: AppConfig) -> None:
    """Apply the light enterprise theme and the application icon."""
    app.setStyle("Fusion")
    app.setPalette(create_light_palette())

    stylesheet = _read_styles(config)
    if stylesheet:
        app.setStyleSheet(stylesheet)

    app.setApplicationName("BizPilot AI")
    app.setOrganizationName(SETTINGS_ORG)
    app.setApplicationVersion(APP_VERSION)

    icon_file = config.resources_dir / "icons" / "app_icon.svg"
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))
