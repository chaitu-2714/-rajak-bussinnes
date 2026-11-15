"""Convenience entry point for the application configuration.

The canonical implementation lives in :mod:`app.core.config`; this module
re-exports it so scripts, Alembic and packaging tools have a stable import.
"""

from app.core.config import (  # noqa: F401
    APP_NAME,
    APP_SLUG,
    APP_VERSION,
    ORGANISATION,
    AppConfig,
    SecuritySettings,
    data_root,
    is_frozen,
    load_config,
    resource_root,
)

__all__ = [
    "APP_NAME",
    "APP_SLUG",
    "APP_VERSION",
    "ORGANISATION",
    "AppConfig",
    "SecuritySettings",
    "data_root",
    "is_frozen",
    "load_config",
    "resource_root",
]
