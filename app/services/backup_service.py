"""Backup and restore service (SQLite online backup API)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import MODULE_SETTINGS, AuditAction
from app.core.database import Database
from app.core.exceptions import BackupError
from app.core.logging_config import get_logger
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService

logger = get_logger("services.backup")


@dataclass(frozen=True)
class BackupFile:
    path: Path
    size_bytes: int
    created_at: datetime

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_label(self) -> str:
        size = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"


class BackupService(BaseService):
    """Create and restore verified database backups."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        database: Database,
        audit_service: AuditService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._database = database
        self._audit = audit_service

    @property
    def default_directory(self) -> Path:
        return self._database.config.backup_dir

    def list_backups(self) -> list[BackupFile]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "settings.update")
            directory = self.default_directory
            if not directory.exists():
                return []
            files = [
                BackupFile(
                    path=path,
                    size_bytes=path.stat().st_size,
                    created_at=datetime.fromtimestamp(path.stat().st_mtime),
                )
                for path in directory.glob("*.db")
                if path.is_file()
            ]
            return sorted(files, key=lambda item: item.created_at, reverse=True)

    def create_backup(self, destination: Path | None = None) -> BackupFile:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "settings.update")
            try:
                path = self._database.backup(destination)
            except BackupError:
                raise
            except Exception as exc:
                raise BackupError(f"Backup failed: {exc}") from exc
            stat = path.stat()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_BACKUP,
                module=MODULE_SETTINGS,
                entity_type="Database",
                entity_id=path.name,
                new_values={"path": str(path), "size_bytes": stat.st_size},
            )
            return BackupFile(
                path=path,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime),
            )

    def restore_backup(self, source: Path) -> BackupFile | None:
        """Restore a verified backup, keeping a safety copy of the current data."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "settings.update")
            safety_path = self._database.restore(Path(source))
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.RESTORE_BACKUP,
                module=MODULE_SETTINGS,
                entity_type="Database",
                entity_id=Path(source).name,
                new_values={
                    "source": str(source),
                    "safety_backup": str(safety_path) if safety_path else None,
                },
            )
            if safety_path is None:
                return None
            stat = safety_path.stat()
            return BackupFile(
                path=safety_path,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime),
            )
