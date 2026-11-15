"""Configuration layer for BizPilot AI.

Resolves every filesystem location the application needs (database, logs,
backups, exports, Qt resources and Alembic migrations) in a way that works
both from source and from a frozen PyInstaller executable.

The database is never stored next to the executable: it lives in the
per-user application data directory so that upgrades never destroy data.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "BizPilot AI"
APP_SLUG = "BizPilotAI"
APP_VERSION = "1.0.0"
APP_BUILD = "1000"
APP_RELEASE_DATE = "2026-11-05"
ORGANISATION = "BizPilot AI"
DB_FILENAME = "bizpilot_ai.db"


def is_frozen() -> bool:
    """Return True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def _default_data_root() -> Path:
    """Per-user writable application data directory."""
    if sys.platform.startswith("win"):
        root = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        base = Path(root) if root else Path.home() / "AppData" / "Local"
        return base / APP_SLUG
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_SLUG
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_SLUG


def _default_resource_root() -> Path:
    """Directory that holds bundled read-only resources."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    # app/core/config.py -> app/core -> app -> project root
    return Path(__file__).resolve().parents[2]


def data_root() -> Path:
    override = os.environ.get("BIZPILOT_DATA_DIR")
    return Path(override).expanduser().resolve() if override else _default_data_root()


def resource_root() -> Path:
    override = os.environ.get("BIZPILOT_RESOURCE_ROOT")
    return Path(override).expanduser().resolve() if override else _default_resource_root()


@dataclass(frozen=True)
class SecuritySettings:
    """Security policy values. Kept in one place so tests can tighten them."""

    max_failed_attempts: int = 5
    lockout_minutes: int = 15
    session_hours: int = 8
    idle_timeout_minutes: int = 180
    min_password_length: int = 10


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration."""

    data_dir: Path
    resources_dir: Path
    migrations_dir: Path
    environment: str = "production"
    security: SecuritySettings = field(default_factory=SecuritySettings)

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_FILENAME

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def export_dir(self) -> Path:
        return self.data_dir / "exports"

    @property
    def document_dir(self) -> Path:
        """Uploaded knowledge documents (never inside the install directory)."""
        return self.data_dir / "documents"

    @property
    def vector_dir(self) -> Path:
        return self.data_dir / "vector_store"

    @property
    def config_dir(self) -> Path:
        return self.data_dir / "config"

    @property
    def database_url(self) -> str:
        return f"sqlite+pysqlite:///{self.db_path.as_posix()}"

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"development", "dev", "testing", "test"}

    def ensure_directories(self) -> None:
        """Create every writable directory the application depends on."""
        for directory in (
            self.data_dir,
            self.log_dir,
            self.backup_dir,
            self.export_dir,
            self.document_dir,
            self.vector_dir,
            self.config_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def style_path(self, filename: str) -> Path:
        return self.resources_dir / "styles" / filename


def load_config() -> AppConfig:
    """Build the runtime configuration from environment variables."""
    config = AppConfig(
        data_dir=data_root(),
        resources_dir=Path(
            os.environ.get("BIZPILOT_RESOURCES_DIR") or resource_root() / "resources"
        ),
        migrations_dir=Path(
            os.environ.get("BIZPILOT_MIGRATIONS_DIR") or resource_root() / "migrations"
        ),
        environment=os.environ.get("BIZPILOT_ENV", "production"),
    )
    config.ensure_directories()
    return config
