"""Document lifecycle: versions, archive, retention and deletion."""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import DocumentStatus
from app.core.logging_config import get_logger
from app.database.models.knowledge import (
    DocumentChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from app.utils.date_utils import utcnow

logger = get_logger("knowledge.lifecycle")


class KnowledgeLifecycleService:
    """Keeps every version, and removes retrievable content on deletion."""

    def __init__(self, *, retention_days: int = 365) -> None:
        self._retention_days = retention_days

    # -- versions ----------------------------------------------------------
    def add_version(
        self,
        db: Session,
        document: KnowledgeDocument,
        *,
        version: int,
        file_name: str,
        storage_path: str,
        content_hash: str,
        file_size: int,
        page_count: int,
        note: str | None,
        uploaded_by: int | None,
    ) -> KnowledgeDocumentVersion:
        record = KnowledgeDocumentVersion(
            document_id=document.id,
            version=version,
            file_name=file_name,
            storage_path=storage_path,
            content_hash=content_hash,
            file_size=file_size,
            page_count=page_count,
            chunk_count=0,
            note=note,
            uploaded_by=uploaded_by,
        )
        db.add(record)
        db.flush()
        return record

    def history(self, db: Session, document: KnowledgeDocument) -> list[dict]:
        rows = db.scalars(
            select(KnowledgeDocumentVersion)
            .where(KnowledgeDocumentVersion.document_id == document.id)
            .order_by(KnowledgeDocumentVersion.version.desc())
        ).all()
        return [
            {
                "version": row.version,
                "file_name": row.file_name,
                "content_hash": row.content_hash,
                "file_size": row.file_size,
                "page_count": row.page_count,
                "chunk_count": row.chunk_count,
                "note": row.note,
                "created_at": row.created_at,
                "is_current": row.version == document.current_version,
            }
            for row in rows
        ]

    # -- archive -----------------------------------------------------------
    def archive(self, db: Session, document: KnowledgeDocument) -> None:
        document.is_archived = True
        document.status = DocumentStatus.ARCHIVED
        db.flush()

    # -- deletion ----------------------------------------------------------
    def delete(
        self,
        db: Session,
        document: KnowledgeDocument,
        *,
        vector_store,
        purge_files: bool = True,
    ) -> dict:
        """Remove retrievable content; keep the row for the audit trail."""
        removed_chunks = db.scalars(
            select(DocumentChunk).where(DocumentChunk.document_id == document.id)
        ).all()
        for chunk in removed_chunks:
            db.delete(chunk)
        vectors_removed = vector_store.delete_document_vectors(document.id)

        document.status = DocumentStatus.DELETED
        document.is_deleted = True
        document.is_archived = True
        document.index_status = "NOT_INDEXED"
        document.chunk_count = 0
        document.extracted_text = None
        document.summary = None
        document.updated_at = utcnow()
        db.flush()

        files_removed = 0
        if purge_files:
            directory = Path(document.storage_path).parent
            try:
                if directory.exists() and directory.is_dir():
                    shutil.rmtree(directory)
                    files_removed = 1
            except OSError as exc:  # noqa: BLE001
                logger.warning("Could not remove files for %s: %s", document.document_ref, exc)

        return {
            "document_ref": document.document_ref,
            "chunks_removed": len(removed_chunks),
            "vectors_removed": vectors_removed,
            "files_removed": files_removed,
            "retention_days": self._retention_days,
            "note": "The document row is kept for the audit trail; its content is no "
            "longer retrievable.",
        }

    def retention_policy(self) -> dict:
        return {
            "retention_days": self._retention_days,
            "description": "Deleted documents keep their metadata row for audit; files and "
            "vectors are removed immediately unless retention is configured otherwise.",
        }
