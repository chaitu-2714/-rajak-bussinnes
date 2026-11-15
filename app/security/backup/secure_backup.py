"""Secure backup and recovery on top of the Phase 1 SQLite backup service."""

from __future__ import annotations

import hashlib
import shutil
import sqlite3
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging_config import get_logger
from app.database.models.security import BackupHistory
from app.utils.date_utils import utcnow

logger = get_logger("security.backup")


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    detail: str
    tables: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "detail": self.detail, "tables": self.tables}


class SecureBackupService:
    """Creates, validates and restores backups with a recorded history."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        base_service: Any,
        *,
        knowledge_root: Path | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._base = base_service
        self._knowledge_root = Path(knowledge_root) if knowledge_root else None

    # -- helpers -----------------------------------------------------------
    def _hash(self, path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()

    def validate_backup(self, path: Path) -> ValidationResult:
        """Open the backup read-only and check it is a sound SQLite database.

        A knowledge backup is a zip archive; the database inside it is what gets
        validated, so a corrupt archive is rejected rather than trusted.
        """
        path = Path(path)
        if not path.exists():
            return ValidationResult(False, "The backup file does not exist")
        if path.suffix.lower() == ".zip":
            return self._validate_archive(path)
        if path.stat().st_size == 0:
            return ValidationResult(False, "The backup file is empty")
        try:
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                tables = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
                users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            finally:
                connection.close()
        except sqlite3.DatabaseError as exc:
            return ValidationResult(False, f"The backup is not a readable database: {exc}")
        if integrity != "ok":
            return ValidationResult(False, f"Integrity check failed: {integrity}", tables)
        if tables < 5:
            return ValidationResult(
                False, f"Only {tables} tables found; this does not look like a BizPilot backup", tables
            )
        return ValidationResult(
            True, f"Integrity check passed with {tables} tables and {users} user(s)", tables
        )

    def _validate_archive(self, path: Path) -> ValidationResult:
        """Extract the database from a backup archive and validate that."""
        import tempfile

        try:
            with zipfile.ZipFile(path) as archive:
                members = [name for name in archive.namelist() if name.endswith(".db")]
                if not members:
                    return ValidationResult(False, "The archive contains no database file")
                with tempfile.TemporaryDirectory() as tmp:
                    extracted = archive.extract(members[0], tmp)
                    return self.validate_backup(Path(extracted))
        except zipfile.BadZipFile:
            return ValidationResult(False, "The backup archive is corrupt")

    # -- create ------------------------------------------------------------
    def create_backup(
        self,
        *,
        performed_by: int | None = None,
        backup_type: str = "MANUAL",
        include_knowledge: bool = False,
        destination: Path | None = None,
    ) -> dict[str, Any]:
        backup_file = self._base.create_backup(destination)
        path = Path(getattr(backup_file, "path", backup_file))
        validation = self.validate_backup(path)

        archive_path = path
        if include_knowledge and self._knowledge_root and self._knowledge_root.exists():
            archive_path = path.with_suffix(".zip")
            with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(path, arcname=path.name)
                for item in self._knowledge_root.rglob("*"):
                    if item.is_file():
                        zf.write(item, arcname=str(Path("knowledge") / item.relative_to(self._knowledge_root)))

        record = {
            "backup_ref": f"bak-{utcnow().strftime('%Y%m%d%H%M%S')}",
            "backup_type": backup_type,
            "file_name": archive_path.name,
            "file_size": archive_path.stat().st_size,
            "content_hash": self._hash(archive_path),
            "includes_knowledge": include_knowledge,
            "integrity_status": "VERIFIED" if validation.ok else "FAILED",
            "validation_detail": validation.detail,
            "operation": "BACKUP",
            "performed_by": performed_by,
            "path": str(archive_path),
        }
        with self._session_factory() as db:
            db.add(
                BackupHistory(
                    backup_ref=record["backup_ref"],
                    backup_type=backup_type,
                    file_name=record["file_name"],
                    file_size=record["file_size"],
                    content_hash=record["content_hash"],
                    includes_knowledge=include_knowledge,
                    integrity_status=record["integrity_status"],
                    validation_detail=validation.detail,
                    operation="BACKUP",
                    performed_by=performed_by,
                )
            )
            db.commit()
        return record

    # -- restore -----------------------------------------------------------
    def preview_restore(self, path: Path) -> dict[str, Any]:
        validation = self.validate_backup(path)
        return {
            "path": str(path),
            "valid": validation.ok,
            "detail": validation.detail,
            "tables": validation.tables,
            "note": "Restoring replaces the active database. A safety copy of the current "
            "data is taken first.",
        }

    def restore_backup(
        self, path: Path, *, performed_by: int | None = None, confirm: bool = False
    ) -> dict[str, Any]:
        if not confirm:
            raise PermissionError("A restore must be explicitly confirmed")
        validation = self.validate_backup(path)
        if not validation.ok:
            with self._session_factory() as db:
                db.add(
                    BackupHistory(
                        backup_ref=f"res-{utcnow().strftime('%Y%m%d%H%M%S')}",
                        file_name=Path(path).name,
                        operation="RESTORE",
                        integrity_status="REJECTED",
                        validation_detail=validation.detail,
                        performed_by=performed_by,
                    )
                )
                db.commit()
            raise ValueError(f"The backup was rejected: {validation.detail}")

        # A copy of the current database is taken before anything is replaced.
        safety = self._base.create_backup()
        self._base.restore_backup(Path(path))
        with self._session_factory() as db:
            db.add(
                BackupHistory(
                    backup_ref=f"res-{utcnow().strftime('%Y%m%d%H%M%S')}",
                    file_name=Path(path).name,
                    operation="RESTORE",
                    integrity_status="VERIFIED",
                    validation_detail=validation.detail,
                    performed_by=performed_by,
                )
            )
            db.commit()
        return {
            "restored": Path(path).name,
            "safety_backup": str(getattr(safety, "path", safety)),
            "validation": validation.detail,
        }

    # -- history -----------------------------------------------------------
    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(BackupHistory).order_by(BackupHistory.id.desc()).limit(limit)
            ).all()
            return [
                {
                    "backup_ref": row.backup_ref,
                    "backup_type": row.backup_type,
                    "file_name": row.file_name,
                    "file_size": row.file_size,
                    "operation": row.operation,
                    "integrity_status": row.integrity_status,
                    "validation_detail": row.validation_detail,
                    "includes_knowledge": row.includes_knowledge,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
