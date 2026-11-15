"""Database lifecycle: engine creation, migrations, integrity checks, backup.

Safety rules implemented here:

* an existing database file is never deleted or recreated on error;
* schema changes go through Alembic, never ``drop_all``;
* backups and restores use SQLite's online backup API rather than a raw file
  copy, so a running transaction cannot produce a corrupt backup.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import AppConfig
from app.core.exceptions import BackupError, DatabaseError, MigrationError
from app.core.logging_config import get_logger
from app.database.base import Base
from app.database.session import create_engine_for, create_session_factory

logger = get_logger("database")

_REQUIRED_TABLES = ("users", "roles", "permissions", "user_roles", "role_permissions", "sessions", "business", "audit_logs")


class Database:
    """Owns the engine, the session factory and schema lifecycle."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None

    # -- lifecycle ---------------------------------------------------------
    @property
    def config(self) -> AppConfig:
        return self._config

    @property
    def is_initialized(self) -> bool:
        """True once the engine has been opened."""
        return self._engine is not None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise DatabaseError("Database engine is not initialised")
        return self._engine

    @property
    def session_factory(self) -> sessionmaker[Session]:
        if self._session_factory is None:
            raise DatabaseError("Database session factory is not initialised")
        return self._session_factory

    def initialize(self) -> None:
        """Create directories, open the engine, migrate and verify."""
        self._config.ensure_directories()
        self._open_engine()
        self._apply_migrations()
        ok, detail = self.integrity_check()
        if not ok:
            raise DatabaseError(f"Database integrity check failed: {detail}")
        logger.info("Database ready at %s", self._config.db_path)

    def _open_engine(self) -> None:
        try:
            self._engine = create_engine_for(self._config)
            self._session_factory = create_session_factory(self._engine)
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - environment failure
            raise DatabaseError(f"Unable to open the database: {exc}") from exc

    def _apply_migrations(self) -> None:
        """Upgrade the schema to head using Alembic."""
        migrations_dir = self._config.migrations_dir
        if not migrations_dir.exists():
            # Frozen builds always bundle migrations; this guards against a
            # missing resource without ever destroying existing data.
            logger.warning(
                "Migrations directory %s not found - falling back to metadata create_all",
                migrations_dir,
            )
            try:
                Base.metadata.create_all(self.engine)
            except Exception as exc:
                raise MigrationError(f"Schema creation failed: {exc}") from exc
            return

        alembic_config = Config()
        alembic_config.set_main_option("script_location", str(migrations_dir))
        alembic_config.set_main_option("sqlalchemy.url", self._config.database_url)
        alembic_config.set_main_option("prepend_sys_path", ".")
        try:
            command.upgrade(alembic_config, "head")
        except Exception as exc:
            raise MigrationError(f"Database migration failed: {exc}") from exc

    def dispose(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
        self._engine = None
        self._session_factory = None

    def reopen(self) -> None:
        """Reopen the engine after a restore."""
        self.dispose()
        self._open_engine()

    # -- diagnostics -------------------------------------------------------
    def check_connection(self) -> tuple[bool, str]:
        """Return (ok, human readable detail) for the connection."""
        try:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True, f"Connected to {self._config.db_path.name}"
        except Exception as exc:  # pragma: no cover - environment failure
            logger.error("Database connection check failed: %s", exc)
            return False, "Database unavailable"

    def integrity_check(self) -> tuple[bool, str]:
        """Run SQLite's integrity check plus a foreign-key check."""
        try:
            with self.engine.connect() as connection:
                integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar()
                foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
            if integrity != "ok":
                return False, f"integrity_check reported {integrity!r}"
            if foreign_keys:
                return False, f"{len(foreign_keys)} foreign key violation(s)"
            return True, "ok"
        except Exception as exc:
            return False, str(exc)

    def table_names(self) -> list[str]:
        with self.engine.connect() as connection:
            rows = connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).all()
        return [row[0] for row in rows]

    def schema_version(self) -> str:
        try:
            with self.engine.connect() as connection:
                version = connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).scalar()
            return str(version or "unknown")
        except Exception:
            return "unmanaged"

    # -- backup / restore --------------------------------------------------
    def backup(self, destination: Path | None = None) -> Path:
        """Create a consistent backup using SQLite's online backup API."""
        self._config.backup_dir.mkdir(parents=True, exist_ok=True)
        if destination is None:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            destination = self._config.backup_dir / f"bizpilot_backup_{stamp}.db"
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == self._config.db_path.resolve():
            raise BackupError("A backup cannot overwrite the live database file")

        raw = self.engine.raw_connection()
        try:
            driver_connection = raw.driver_connection
            target = sqlite3.connect(str(destination))
            try:
                driver_connection.backup(target)
                target.commit()
            finally:
                target.close()
        except Exception as exc:
            raise BackupError(f"Backup failed: {exc}") from exc
        finally:
            raw.close()

        ok, detail = self._verify_backup_file(destination)
        if not ok:
            destination.unlink(missing_ok=True)
            raise BackupError(f"Backup verification failed: {detail}")
        logger.info("Database backup written to %s", destination)
        return destination

    @staticmethod
    def _verify_backup_file(path: Path) -> tuple[bool, str]:
        if not path.exists() or path.stat().st_size == 0:
            return False, "backup file is empty"
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
            finally:
                connection.close()
        except sqlite3.Error as exc:
            return False, str(exc)
        if not integrity or integrity[0] != "ok":
            return False, "integrity check failed"
        missing = [table for table in _REQUIRED_TABLES if table not in tables]
        if missing:
            return False, f"missing tables: {', '.join(missing)}"
        return True, "ok"

    def restore(self, source: Path, *, safety_backup: bool = True) -> Path | None:
        """Replace the live database with a verified backup.

        A safety backup of the current database is taken first by default.
        """
        source = Path(source)
        if not source.exists():
            raise BackupError("The selected backup file does not exist")
        ok, detail = self._verify_backup_file(source)
        if not ok:
            raise BackupError(f"The selected file is not a valid BizPilot backup: {detail}")

        safety_path: Path | None = None
        if safety_backup:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safety_path = self._config.backup_dir / f"pre_restore_{stamp}.db"
            safety_path = self.backup(safety_path)

        raw = self.engine.raw_connection()
        try:
            driver_connection = raw.driver_connection
            origin = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
            try:
                origin.backup(driver_connection)
                driver_connection.commit()
            finally:
                origin.close()
        except Exception as exc:
            raise BackupError(f"Restore failed: {exc}") from exc
        finally:
            raw.close()

        self.reopen()
        ok, detail = self.integrity_check()
        if not ok:
            raise BackupError(f"Restored database failed its integrity check: {detail}")
        logger.info("Database restored from %s", source)
        return safety_path
