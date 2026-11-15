"""Alembic environment for BizPilot AI.

Works in two modes:

* programmatically from the application, where the caller injects the
  database URL through ``config.attributes['sqlalchemy_url']``;
* from the command line, where the URL is derived from
  :func:`app.core.config.load_config` (same persistent data directory the
  application uses).
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import load_config
from app.database.base import Base
import app.database.models  # noqa: F401  (registers every model)

config = context.config

if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    try:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    except Exception:  # pragma: no cover - logging config is optional
        pass

target_metadata = Base.metadata


def _database_url() -> str:
    injected = config.attributes.get("sqlalchemy_url")
    if injected:
        return str(injected)
    configured = config.get_main_option("sqlalchemy.url")
    if configured and configured.strip():
        return configured.strip()
    return load_config().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool, future=True)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
