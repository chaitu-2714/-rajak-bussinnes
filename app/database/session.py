"""SQLAlchemy engine and session construction for SQLite.

Foreign keys are enforced per connection, WAL journaling is enabled for
concurrency, and a busy timeout avoids spurious "database is locked" errors.
The engine is created from a URL so a PostgreSQL URL can be substituted in a
later phase without touching repositories.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppConfig

logger = logging.getLogger("bizpilot.database")


def _apply_sqlite_pragmas(dbapi_connection: Any, _connection_record: Any) -> None:
    """Configure every new SQLite connection."""
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=5000")
    finally:
        cursor.close()


def create_engine_for(config: AppConfig, *, echo: bool = False) -> Engine:
    """Create a configured engine for the application database."""
    engine = create_engine(
        config.database_url,
        echo=echo,
        future=True,
        pool_pre_ping=True,
        connect_args={"timeout": 15, "check_same_thread": False},
    )
    event.listen(engine, "connect", _apply_sqlite_pragmas)
    logger.debug("Engine created for %s", config.db_path)
    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the session factory used by repositories and services."""
    return sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
        future=True,
    )
