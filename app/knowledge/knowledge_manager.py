"""Business knowledge management: import, process, index, search, retrieve."""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import DocumentStatus, KnowledgeCategory
from app.core.exceptions import BizPilotError, ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.knowledge import (
    DocumentChunk,
    DocumentEntity,
    DocumentExtractionResult,
    EmbeddingModelRegistry,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeProcessingJob,
)
from app.document_intelligence.document_chunker import DocumentChunker
from app.document_intelligence.document_extractor import (
    DocumentClassifier,
    DocumentIntelligenceService,
)
from app.document_intelligence.document_parser import (
    MAX_FILE_BYTES,
    SUPPORTED_EXTENSIONS,
    DocumentParser,
)
from app.embeddings.embedding_service import EmbeddingService
from app.knowledge.knowledge_lifecycle import KnowledgeLifecycleService
from app.knowledge.knowledge_permissions import KnowledgePermissionService
from app.vector_store.vector_store_service import LocalVectorStore, VectorRecord
from app.utils.date_utils import utcnow

logger = get_logger("knowledge.manager")

SEARCH_MODES = ("SEMANTIC", "KEYWORD", "HYBRID")


class KnowledgeError(BizPilotError):
    default_user_message = "The knowledge operation could not be completed."


@dataclass
class SearchHit:
    chunk_id: str
    document_id: int
    document_ref: str
    title: str
    category: str
    page_number: int | None
    section_heading: str | None
    content: str
    score: float
    match_type: str


@dataclass
class SearchResult:
    query: str
    mode: str
    hits: list[SearchHit] = field(default_factory=list)
    documents_searched: int = 0
    note: str | None = None

    @property
    def count(self) -> int:
        return len(self.hits)


class BusinessKnowledgeManager:
    """The single entry point for document knowledge."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        storage_root: Path,
        vector_store: LocalVectorStore,
        embedding_service: EmbeddingService,
        parser: DocumentParser,
        chunker: DocumentChunker,
        classifier: DocumentClassifier,
        intelligence: DocumentIntelligenceService,
        permissions: KnowledgePermissionService,
        lifecycle: KnowledgeLifecycleService,
        entity_resolver: Any | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage_root = Path(storage_root)
        self._storage_root.mkdir(parents=True, exist_ok=True)
        self._vectors = vector_store
        self._embeddings = embedding_service
        self._parser = parser
        self._chunker = chunker
        self._classifier = classifier
        self._intelligence = intelligence
        self._permissions = permissions
        self._lifecycle = lifecycle
        self._resolver = entity_resolver

    # ------------------------------------------------------------------
    # import and validation
    # ------------------------------------------------------------------
    def validate_document(self, path: Path, *, file_name: str | None = None) -> dict[str, Any]:
        path = Path(path)
        name = file_name or path.name
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValidationError(
                f"'{suffix or name}' is not a supported document type. Supported: "
                + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            )
        if not path.exists():
            raise ValidationError(f"The file '{name}' was not found")
        size = path.stat().st_size
        if size == 0:
            raise ValidationError("The file is empty")
        if size > MAX_FILE_BYTES:
            raise ValidationError(
                f"The file is {size / 1024 / 1024:.1f} MB, above the "
                f"{MAX_FILE_BYTES / 1024 / 1024:.0f} MB limit"
            )
        return {
            "file_name": name,
            "file_type": suffix.lstrip("."),
            "file_size": size,
            "content_hash": self._hash_file(path),
            "valid": True,
        }

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return digest.hexdigest()

    def import_document(
        self,
        source_path: Path,
        *,
        title: str | None = None,
        category: str | None = None,
        business_id: int | None = None,
        uploaded_by: int | None = None,
        is_restricted: bool = False,
        allowed_roles: list[str] | None = None,
        allowed_user_ids: list[int] | None = None,
        collection_key: str | None = None,
        note: str | None = None,
        process: bool = True,
    ) -> KnowledgeDocument:
        """Copy a file into knowledge storage and index it."""
        info = self.validate_document(source_path)
        content_hash = info["content_hash"]

        with self._session_factory() as db:
            duplicate = db.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.content_hash == content_hash,
                    KnowledgeDocument.is_deleted.is_(False),
                )
            ).first()
            if duplicate is not None:
                raise ConflictError(
                    f"This file was already imported as '{duplicate.title}' "
                    f"({duplicate.document_ref})."
                )

            document_ref = f"doc-{uuid.uuid4().hex[:12]}"
            directory = self._document_directory(business_id, document_ref)
            directory.mkdir(parents=True, exist_ok=True)
            stored_path = directory / f"v1_{Path(info['file_name']).name}"
            shutil.copy2(source_path, stored_path)

            document = KnowledgeDocument(
                document_ref=document_ref,
                business_id=business_id,
                title=title or Path(info["file_name"]).stem.replace("_", " ").title(),
                file_name=info["file_name"],
                file_type=info["file_type"],
                file_size=info["file_size"],
                content_hash=content_hash,
                storage_path=str(stored_path),
                category=category or KnowledgeCategory.OTHER,
                category_source="MANUAL" if category else "AUTO",
                collection_key=collection_key,
                status=DocumentStatus.PENDING,
                processing_stage="IMPORTED",
                is_restricted=is_restricted,
                allowed_roles=allowed_roles or [],
                allowed_user_ids=allowed_user_ids or [],
                uploaded_by=uploaded_by,
                embedding_model=self._embeddings.model_id,
            )
            db.add(document)
            db.flush()
            self._lifecycle.add_version(
                db,
                document,
                version=1,
                file_name=info["file_name"],
                storage_path=str(stored_path),
                content_hash=content_hash,
                file_size=info["file_size"],
                page_count=0,
                note=note or "Initial import",
                uploaded_by=uploaded_by,
            )
            db.add(
                KnowledgeProcessingJob(
                    job_ref=f"job-{uuid.uuid4().hex[:10]}",
                    document_id=document.id,
                    job_type="PROCESS",
                    status="QUEUED",
                    stage="QUEUED",
                    requested_by=uploaded_by,
                )
            )
            db.commit()
            document_id = document.id

        if process:
            self.process_document(document_id)
        with self._session_factory() as db:
            return self.get_document(db, document_id)

    def _document_directory(self, business_id: int | None, document_ref: str) -> Path:
        business = f"business_{business_id}" if business_id is not None else "business_default"
        return self._storage_root / business / document_ref

    # ------------------------------------------------------------------
    # processing
    # ------------------------------------------------------------------
    def process_document(self, document_id: int, *, force: bool = False) -> dict[str, Any]:
        """Extract, classify, chunk, embed and index one document."""
        with self._session_factory() as db:
            document = self.get_document(db, document_id)
            if document.is_deleted:
                raise ConflictError("This document was deleted and cannot be processed")
            document.status = DocumentStatus.PROCESSING
            document.processing_stage = "EXTRACTING"
            document.error_message = None
            path = Path(document.storage_path)
            file_type = document.file_type
            business_id = document.business_id
            document_ref = document.document_ref
            version = document.current_version
            forced_category = document.category if document.category_source == "MANUAL" else None
            db.commit()

        job_id = self._start_job(document_id, "PROCESS")
        try:
            parsed = self._parser.parse(path, file_type=file_type)
        except Exception as exc:  # noqa: BLE001 - real error must surface
            self._fail(document_id, job_id, f"Extraction failed: {exc}")
            raise KnowledgeError(f"Extraction failed: {exc}") from exc

        if not parsed.text.strip():
            reason = (
                "No extractable text was found. "
                + (" ".join(parsed.warnings) if parsed.warnings else "The file may be a scan.")
            )
            self._fail(document_id, job_id, reason)
            raise KnowledgeError(reason)

        with self._session_factory() as db:
            document = self.get_document(db, document_id)
            document.processing_stage = "CLASSIFYING"
            db.commit()

        category, confidence, reason = self._classifier.classify(
            file_name=path.name, text=parsed.text
        )
        if forced_category:
            category = forced_category
            confidence, reason = 1.0, "category set manually"

        chunks = self._chunker.chunk_pages(parsed.pages, category=category)
        if not chunks:
            self._fail(document_id, job_id, "The document produced no usable chunks")
            raise KnowledgeError("The document produced no usable chunks")

        with self._session_factory() as db:
            document = self.get_document(db, document_id)
            document.processing_stage = "EMBEDDING"
            document.category = category
            db.commit()

        try:
            vectors = self._embeddings.embed_texts([chunk.content for chunk in chunks])
        except Exception as exc:  # noqa: BLE001
            self._fail(document_id, job_id, f"Embedding failed: {exc}")
            raise KnowledgeError(f"Embedding failed: {exc}") from exc

        with self._session_factory() as db:
            document = self.get_document(db, document_id)
            document.processing_stage = "INDEXING"
            document.status = DocumentStatus.INDEXING
            # Replace previous chunks of this version.
            for existing in db.scalars(
                select(DocumentChunk).where(DocumentChunk.document_id == document.id)
            ).all():
                db.delete(existing)
            db.flush()

            chunk_rows: list[DocumentChunk] = []
            for chunk, vector in zip(chunks, vectors):
                chunk_id = f"{document_ref}-v{version}-c{chunk.chunk_index}"
                row = DocumentChunk(
                    chunk_id=chunk_id,
                    document_id=document.id,
                    business_id=document.business_id,
                    document_version=version,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    section_heading=chunk.section_heading,
                    source_file=document.file_name,
                    content_hash=chunk.content_hash,
                    token_count=chunk.token_estimate,
                )
                db.add(row)
                chunk_rows.append(row)
            db.flush()

            self._vectors.delete_document_vectors(document.id)
            self._vectors.add_embeddings(
                [
                    VectorRecord(
                        chunk_id=row.chunk_id,
                        document_id=document.id,
                        document_ref=document.document_ref,
                        business_id=document.business_id,
                        category=document.category,
                        document_version=version,
                        page_number=row.page_number,
                        section_heading=row.section_heading,
                        source_file=document.file_name,
                        model_id=self._embeddings.model_id,
                        content=row.content,
                        content_hash=row.content_hash,
                        vector=vector,
                    )
                    for row, vector in zip(chunk_rows, vectors)
                ]
            )

            document.status = DocumentStatus.INDEXED
            document.processing_stage = "COMPLETED"
            document.index_status = "INDEXED"
            document.ocr_status = (
                "APPLIED" if parsed.ocr_applied else ("UNAVAILABLE" if parsed.needs_ocr_pages else "NOT_REQUIRED")
            )
            document.page_count = parsed.page_count
            document.word_count = parsed.word_count
            document.chunk_count = len(chunk_rows)
            document.extracted_text = parsed.text[:200000]
            document.summary = self._summarise(parsed.text)
            document.embedding_model = self._embeddings.model_id
            document.metadata_json = {
                "category_confidence": confidence,
                "category_reason": reason,
                "parser_warnings": parsed.warnings,
                "pages": parsed.page_count,
                "file_metadata": {k: str(v) for k, v in (parsed.metadata or {}).items()},
            }
            document.processed_at = utcnow()
            document.error_message = None

            version_row = db.scalars(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == document.id,
                    KnowledgeDocumentVersion.version == version,
                )
            ).first()
            if version_row is not None:
                version_row.chunk_count = len(chunk_rows)
                version_row.page_count = parsed.page_count

            self._store_extraction(db, document, parsed.pages, category)
            self._store_entities(db, document, parsed.pages)
            db.commit()
            indexed_chunks = len(chunk_rows)

        self._finish_job(job_id, "COMPLETED", chunks=indexed_chunks)
        self._update_model_registry()
        logger.info(
            "Indexed %s (%s chunks, %s)", document_ref, indexed_chunks, self._embeddings.model_id
        )
        return {
            "document_ref": document_ref,
            "status": DocumentStatus.INDEXED,
            "category": category,
            "category_confidence": confidence,
            "chunks": indexed_chunks,
            "pages": parsed.page_count,
            "embedding_model": self._embeddings.model_id,
            "ocr_applied": parsed.ocr_applied,
            "warnings": parsed.warnings,
        }

    def _store_extraction(self, db: Session, document: KnowledgeDocument, pages, category: str) -> None:
        for row in db.scalars(
            select(DocumentExtractionResult).where(
                DocumentExtractionResult.document_id == document.id
            )
        ).all():
            db.delete(row)
        db.flush()
        result = self._intelligence.extract(category=category, pages=pages)
        for field in result.fields:
            db.add(
                DocumentExtractionResult(
                    document_id=document.id,
                    document_type=result.document_type,
                    field_name=field.field_name,
                    field_value=field.field_value,
                    page_number=field.page_number,
                    location=field.location,
                    confidence=field.confidence,
                    validation_status="UNVERIFIED",
                    evidence=field.evidence,
                )
            )

    def _store_entities(self, db: Session, document: KnowledgeDocument, pages) -> None:
        for row in db.scalars(
            select(DocumentEntity).where(DocumentEntity.document_id == document.id)
        ).all():
            db.delete(row)
        db.flush()
        if self._resolver is None:
            return
        try:
            entities = self._resolver.resolve(
                pages=pages, business_id=document.business_id, db=db
            )
        except Exception:  # noqa: BLE001 - entity resolution must not fail ingestion
            logger.exception("Entity resolution failed for %s", document.document_ref)
            return
        for entity in entities:
            db.add(
                DocumentEntity(
                    document_id=document.id,
                    entity_type=entity["entity_type"],
                    entity_value=entity["entity_value"],
                    resolved_entity_id=entity.get("resolved_entity_id"),
                    match_confidence=entity.get("match_confidence"),
                    needs_review=entity.get("needs_review", False),
                    page_number=entity.get("page_number"),
                )
            )

    def _summarise(self, text: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        summary = " ".join(sentence.strip() for sentence in sentences[:3] if sentence.strip())
        return summary[:500]

    # -- job helpers -------------------------------------------------------
    def _start_job(self, document_id: int, job_type: str) -> int:
        with self._session_factory() as db:
            job = KnowledgeProcessingJob(
                job_ref=f"job-{uuid.uuid4().hex[:10]}",
                document_id=document_id,
                job_type=job_type,
                status="RUNNING",
                stage="STARTED",
                attempts=1,
                started_at=utcnow(),
            )
            db.add(job)
            db.commit()
            return job.id

    def _finish_job(self, job_id: int, status: str, *, chunks: int = 0) -> None:
        with self._session_factory() as db:
            job = db.get(KnowledgeProcessingJob, job_id)
            if job is None:
                return
            job.status = status
            job.stage = "COMPLETED" if status == "COMPLETED" else "FAILED"
            job.progress = 100 if status == "COMPLETED" else job.progress
            job.completed_at = utcnow()
            db.commit()

    def _fail(self, document_id: int, job_id: int, message: str) -> None:
        with self._session_factory() as db:
            document = db.get(KnowledgeDocument, document_id)
            if document is not None:
                document.status = DocumentStatus.FAILED
                document.processing_stage = "FAILED"
                document.index_status = "FAILED"
                document.error_message = message[:1000]
            job = db.get(KnowledgeProcessingJob, job_id)
            if job is not None:
                job.status = "FAILED"
                job.error_message = message[:1000]
                job.completed_at = utcnow()
            db.commit()

    def _update_model_registry(self) -> None:
        with self._session_factory() as db:
            row = db.scalars(
                select(EmbeddingModelRegistry).where(
                    EmbeddingModelRegistry.model_id == self._embeddings.model_id
                )
            ).first()
            if row is not None:
                row.indexed_chunks = self._vectors.count()
                db.commit()

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------
    def get_document(self, db: Session, document_id: int) -> KnowledgeDocument:
        document = db.get(KnowledgeDocument, document_id)
        if document is None:
            raise NotFoundError(f"Document #{document_id} was not found")
        return document

    def get_document_by_ref(self, db: Session, document_ref: str) -> KnowledgeDocument:
        document = db.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.document_ref == document_ref)
        ).first()
        if document is None:
            raise NotFoundError(f"Document '{document_ref}' was not found")
        return document

    def get_document_details(self, db: Session, document_ref: str) -> dict[str, Any]:
        document = self.get_document_by_ref(db, document_ref)
        extraction = db.scalars(
            select(DocumentExtractionResult)
            .where(DocumentExtractionResult.document_id == document.id)
            .order_by(DocumentExtractionResult.id)
        ).all()
        entities = db.scalars(
            select(DocumentEntity).where(DocumentEntity.document_id == document.id)
        ).all()
        return {
            "document_ref": document.document_ref,
            "title": document.title,
            "file_name": document.file_name,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "category": document.category,
            "category_source": document.category_source,
            "status": document.status,
            "processing_stage": document.processing_stage,
            "ocr_status": document.ocr_status,
            "index_status": document.index_status,
            "page_count": document.page_count,
            "word_count": document.word_count,
            "chunk_count": document.chunk_count,
            "current_version": document.current_version,
            "embedding_model": document.embedding_model,
            "is_restricted": document.is_restricted,
            "is_archived": document.is_archived,
            "error": document.error_message,
            "summary": document.summary,
            "created_at": document.created_at,
            "processed_at": document.processed_at,
            "metadata": document.metadata_json or {},
            "extraction": [
                {
                    "field": row.field_name,
                    "value": row.field_value,
                    "page": row.page_number,
                    "confidence": row.confidence,
                    "status": row.validation_status,
                    "evidence": row.evidence,
                }
                for row in extraction
            ],
            "entities": [
                {
                    "type": row.entity_type,
                    "value": row.entity_value,
                    "resolved_id": row.resolved_entity_id,
                    "confidence": row.match_confidence,
                    "needs_review": row.needs_review,
                }
                for row in entities
            ],
            "versions": self._lifecycle.history(db, document),
        }

    def get_document_history(self, db: Session, document_ref: str) -> list[dict]:
        document = self.get_document_by_ref(db, document_ref)
        return self._lifecycle.history(db, document)

    def list_documents(
        self,
        db: Session,
        *,
        business_id: int | None = None,
        category: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        limit: int = 200,
    ) -> list[KnowledgeDocument]:
        query = select(KnowledgeDocument).where(KnowledgeDocument.is_deleted.is_(False))
        if business_id is not None:
            query = query.where(KnowledgeDocument.business_id == business_id)
        if category:
            query = query.where(KnowledgeDocument.category == category)
        if status:
            query = query.where(KnowledgeDocument.status == status)
        if not include_archived:
            query = query.where(KnowledgeDocument.is_archived.is_(False))
        query = query.order_by(KnowledgeDocument.id.desc()).limit(limit)
        return list(db.scalars(query).all())

    def statistics(self, db: Session, *, business_id: int | None = None) -> dict[str, Any]:
        base = select(func.count(KnowledgeDocument.id)).where(
            KnowledgeDocument.is_deleted.is_(False)
        )
        if business_id is not None:
            base = base.where(KnowledgeDocument.business_id == business_id)
        total = db.scalar(base) or 0
        indexed = db.scalar(base.where(KnowledgeDocument.status == DocumentStatus.INDEXED)) or 0
        failed = db.scalar(base.where(KnowledgeDocument.status == DocumentStatus.FAILED)) or 0
        processing = db.scalar(
            base.where(KnowledgeDocument.status.in_(DocumentStatus.ACTIVE))
        ) or 0
        bytes_used = db.scalar(
            select(func.coalesce(func.sum(KnowledgeDocument.file_size), 0)).where(
                KnowledgeDocument.is_deleted.is_(False)
            )
        )
        categories = {
            row[0]: row[1]
            for row in db.execute(
                select(KnowledgeDocument.category, func.count(KnowledgeDocument.id))
                .where(KnowledgeDocument.is_deleted.is_(False))
                .group_by(KnowledgeDocument.category)
            ).all()
        }
        return {
            "total_documents": int(total),
            "indexed": int(indexed),
            "processing": int(processing),
            "failed": int(failed),
            "storage_bytes": int(bytes_used or 0),
            "chunks": self._vectors.count(business_id=business_id),
            "categories": categories,
        }

    # ------------------------------------------------------------------
    # search and retrieval
    # ------------------------------------------------------------------
    def search_knowledge(
        self,
        db: Session,
        query: str,
        *,
        mode: str = "HYBRID",
        business_id: int | None = None,
        visible_document_ids: set[int] | None = None,
        categories: list[str] | None = None,
        top_k: int = 8,
        min_similarity: float = 0.05,
    ) -> SearchResult:
        query = (query or "").strip()
        if not query:
            raise ValidationError("Enter something to search for")
        mode = (mode or "HYBRID").upper()
        if mode not in SEARCH_MODES:
            raise ValidationError(f"Unknown search mode '{mode}'")

        documents = {
            document.id: document
            for document in self.list_documents(db, business_id=business_id, limit=500)
            if document.status == DocumentStatus.INDEXED
        }
        if visible_document_ids is not None:
            documents = {
                doc_id: document
                for doc_id, document in documents.items()
                if doc_id in visible_document_ids
            }
        if not documents:
            return SearchResult(query=query, mode=mode, note="No indexed documents are visible to you.")

        allowed_ids = list(documents)
        hits: dict[str, SearchHit] = {}

        if mode in ("SEMANTIC", "HYBRID"):
            vector = self._embeddings.embed_query(query)
            for match in self._vectors.search_similar_chunks(
                vector,
                top_k=top_k * 2,
                business_id=business_id,
                document_ids=allowed_ids,
                categories=categories,
                min_similarity=min_similarity,
            ):
                document = documents.get(match.document_id)
                if document is None:
                    continue
                hits[match.chunk_id] = SearchHit(
                    chunk_id=match.chunk_id,
                    document_id=match.document_id,
                    document_ref=match.document_ref,
                    title=document.title,
                    category=document.category,
                    page_number=match.page_number,
                    section_heading=match.section_heading,
                    content=match.content,
                    score=float(match.score),
                    match_type="SEMANTIC",
                )

        if mode in ("KEYWORD", "HYBRID"):
            for hit in self._keyword_search(
                db,
                query,
                allowed_ids=allowed_ids,
                categories=categories,
                limit=top_k * 2,
            ):
                existing = hits.get(hit.chunk_id)
                if existing is not None:
                    existing.score = round(existing.score + hit.score, 6)
                    existing.match_type = "HYBRID"
                else:
                    hits[hit.chunk_id] = hit

        ordered = sorted(hits.values(), key=lambda hit: hit.score, reverse=True)[:top_k]
        return SearchResult(
            query=query,
            mode=mode,
            hits=ordered,
            documents_searched=len(documents),
            note=None if ordered else "No passage matched this query.",
        )

    def _keyword_search(
        self,
        db: Session,
        query: str,
        *,
        allowed_ids: list[int],
        categories: list[str] | None,
        limit: int,
    ) -> list[SearchHit]:
        terms = [
            term.lower()
            for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-/\.]{1,}", query)
            if len(term) > 1
        ]
        # Drop filler words so coverage measures real subject matter.
        stop = {"the", "and", "for", "with", "what", "are", "our", "this", "that", "from",
                "have", "has", "does", "did", "was", "were", "you", "your", "how", "much",
                "many", "any", "all", "about", "into", "their", "there", "when", "which"}
        terms = [term for term in terms if term not in stop]
        if not terms:
            return []
        required = max(1, (len(terms) + 1) // 2)
        stmt = select(DocumentChunk, KnowledgeDocument).join(
            KnowledgeDocument, KnowledgeDocument.id == DocumentChunk.document_id
        ).where(DocumentChunk.document_id.in_(allowed_ids))
        if categories:
            stmt = stmt.where(DocumentChunk.business_id.is_not(None) | DocumentChunk.business_id.is_(None))
            stmt = stmt.where(KnowledgeDocument.category.in_(categories))
        rows = db.execute(stmt.limit(2000)).all()

        scored: list[SearchHit] = []
        lowered_terms = [term.lower() for term in terms]
        for chunk, document in rows:
            content = (chunk.content or "").lower()
            score = 0.0
            matched = 0
            for term in lowered_terms:
                occurrences = content.count(term)
                if occurrences:
                    matched += 1
                    score += 1.0 + min(occurrences, 5) * 0.2
            # A chunk must cover at least half the query terms to count as a match.
            if matched < required:
                continue
            # Reward chunks that contain every term (exact identifiers matter).
            if matched == len(lowered_terms):
                score += 3.0
            # Exact phrase matches (invoice numbers, "payment terms") rank highest.
            if len(query.strip()) > 4 and query.strip().lower() in content:
                score += 4.0
            scored.append(
                SearchHit(
                    chunk_id=chunk.chunk_id,
                    document_id=chunk.document_id,
                    document_ref=document.document_ref,
                    title=document.title,
                    category=document.category,
                    page_number=chunk.page_number,
                    section_heading=chunk.section_heading,
                    content=chunk.content,
                    score=round(score / 10, 6),
                    match_type="KEYWORD",
                )
            )
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:limit]

    def retrieve_knowledge(self, db: Session, chunk_ids: list[str]) -> list[dict[str, Any]]:
        if not chunk_ids:
            return []
        rows = db.scalars(
            select(DocumentChunk).where(DocumentChunk.chunk_id.in_(chunk_ids))
        ).all()
        return [
            {
                "chunk_id": row.chunk_id,
                "document_id": row.document_id,
                "content": row.content,
                "page_number": row.page_number,
                "section_heading": row.section_heading,
                "source_file": row.source_file,
            }
            for row in rows
        ]

    # ------------------------------------------------------------------
    # lifecycle operations
    # ------------------------------------------------------------------
    def update_document(
        self,
        document_ref: str,
        source_path: Path,
        *,
        note: str | None = None,
        uploaded_by: int | None = None,
    ) -> dict[str, Any]:
        """Store a new version of an existing document and re-index it."""
        info = self.validate_document(source_path)
        with self._session_factory() as db:
            document = self.get_document_by_ref(db, document_ref)
            version = document.current_version + 1
            directory = Path(document.storage_path).parent
            directory.mkdir(parents=True, exist_ok=True)
            stored_path = directory / f"v{version}_{Path(info['file_name']).name}"
            shutil.copy2(source_path, stored_path)

            document.current_version = version
            document.version_count = version
            document.file_name = info["file_name"]
            document.file_size = info["file_size"]
            document.content_hash = info["content_hash"]
            document.storage_path = str(stored_path)
            document.status = DocumentStatus.PENDING
            document.processing_stage = "VERSION_ADDED"
            self._lifecycle.add_version(
                db,
                document,
                version=version,
                file_name=info["file_name"],
                storage_path=str(stored_path),
                content_hash=info["content_hash"],
                file_size=info["file_size"],
                page_count=0,
                note=note or f"Version {version}",
                uploaded_by=uploaded_by,
            )
            db.commit()
            document_id = document.id
        result = self.process_document(document_id)
        result["version"] = version
        return result

    def reprocess_document(self, document_ref: str) -> dict[str, Any]:
        with self._session_factory() as db:
            document = self.get_document_by_ref(db, document_ref)
            document_id = document.id
        return self.process_document(document_id, force=True)

    def archive_document(self, document_ref: str) -> dict[str, Any]:
        with self._session_factory() as db:
            document = self.get_document_by_ref(db, document_ref)
            self._lifecycle.archive(db, document)
            db.commit()
            return {"document_ref": document_ref, "status": document.status}

    def delete_document(self, document_ref: str) -> dict[str, Any]:
        with self._session_factory() as db:
            document = self.get_document_by_ref(db, document_ref)
            result = self._lifecycle.delete(db, document, vector_store=self._vectors)
            db.commit()
        self._update_model_registry()
        return result

    def verify_document_access(
        self,
        db: Session,
        document_ref: str,
        *,
        user_id: int | None,
        roles: list[str],
        permissions: set[str],
        business_id: int | None,
        is_superuser: bool = False,
    ) -> bool:
        document = self.get_document_by_ref(db, document_ref)
        decision = self._permissions.can_view(
            db,
            document,
            user_id=user_id,
            roles=roles,
            permissions=permissions,
            business_id=business_id,
            is_superuser=is_superuser,
        )
        return decision.allowed

    # ------------------------------------------------------------------
    # maintenance
    # ------------------------------------------------------------------
    def recover_interrupted_jobs(self) -> int:
        """Processing jobs left RUNNING by a crash are marked for retry."""
        with self._session_factory() as db:
            jobs = db.scalars(
                select(KnowledgeProcessingJob).where(
                    KnowledgeProcessingJob.status.in_(("RUNNING", "QUEUED"))
                )
            ).all()
            for job in jobs:
                job.status = "INTERRUPTED"
                job.error_message = (
                    "Interrupted by an application restart; the document can be reprocessed."
                )
                if job.document_id:
                    document = db.get(KnowledgeDocument, job.document_id)
                    if document is not None and document.status in DocumentStatus.ACTIVE:
                        document.status = DocumentStatus.FAILED
                        document.processing_stage = "INTERRUPTED"
                        document.error_message = job.error_message
            db.commit()
            return len(jobs)

    def reindex_all(self) -> dict[str, Any]:
        """Rebuild the vector index from stored documents (after a model change)."""
        rebuilt = 0
        failed: list[str] = []
        with self._session_factory() as db:
            documents = db.scalars(
                select(KnowledgeDocument).where(
                    KnowledgeDocument.is_deleted.is_(False),
                    KnowledgeDocument.status == DocumentStatus.INDEXED,
                )
            ).all()
            refs = [(document.id, document.document_ref) for document in documents]
        for document_id, document_ref in refs:
            try:
                self.process_document(document_id, force=True)
                rebuilt += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("Re-index failed for %s: %s", document_ref, exc)
                failed.append(f"{document_ref}: {exc}")
        return {"rebuilt": rebuilt, "failed": failed, "model": self._embeddings.model_id}
