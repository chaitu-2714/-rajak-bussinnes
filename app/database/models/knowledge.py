"""Phase 8 models: knowledge documents, chunks, extraction, RAG history, vectors."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.constants import DocumentStatus, KnowledgeCategory
from app.database.base import Base
from app.utils.date_utils import utcnow


class KnowledgeCollection(Base):
    """A named grouping of documents inside one business."""

    __tablename__ = "knowledge_collections"
    __table_args__ = (UniqueConstraint("collection_key", name="uq_knowledge_collections_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    collection_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class KnowledgeDocument(Base):
    """One business document (the current version's metadata)."""

    __tablename__ = "knowledge_documents"
    __table_args__ = (UniqueConstraint("document_ref", name="uq_knowledge_documents_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[str] = mapped_column(
        String(40), nullable=False, default=KnowledgeCategory.OTHER, index=True
    )
    category_source: Mapped[str] = mapped_column(String(20), nullable=False, default="AUTO")
    collection_key: Mapped[str | None] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=DocumentStatus.PENDING, index=True,
        server_default=text("'PENDING'"),
    )
    processing_stage: Mapped[str | None] = mapped_column(String(40))
    ocr_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_REQUIRED")
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="NOT_INDEXED")
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    version_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_roles: Mapped[list[Any] | None] = mapped_column(JSON)
    allowed_user_ids: Mapped[list[Any] | None] = mapped_column(JSON)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    error_message: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    embedding_model: Mapped[str | None] = mapped_column(String(80))
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )

    versions: Mapped[list["KnowledgeDocumentVersion"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["DocumentChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KnowledgeDocumentVersion(Base):
    """An immutable record of one stored version of a document."""

    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "version", name="uq_knowledge_document_versions"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="versions")


class DocumentChunk(Base):
    """A retrievable chunk of a document, with its page and heading."""

    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("chunk_id", name="uq_document_chunks_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chunk_id: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    document_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_heading: Mapped[str | None] = mapped_column(String(200))
    source_file: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    document: Mapped["KnowledgeDocument"] = relationship(back_populates="chunks")


class DocumentExtractionResult(Base):
    """A structured field extracted from a document."""

    __tablename__ = "document_extraction_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_type: Mapped[str] = mapped_column(String(40), nullable=False, default="GENERAL")
    field_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    field_value: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    location: Mapped[str | None] = mapped_column(String(120))
    confidence: Mapped[float | None] = mapped_column(Float)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNVERIFIED")
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    evidence: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class DocumentEntity(Base):
    """An entity mentioned in a document, resolved against business records."""

    __tablename__ = "document_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    entity_value: Mapped[str] = mapped_column(String(200), nullable=False)
    resolved_entity_id: Mapped[int | None] = mapped_column(Integer)
    match_confidence: Mapped[float | None] = mapped_column(Float)
    needs_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class KnowledgeAccessPolicy(Base):
    """Per-document or per-category access rule."""

    __tablename__ = "knowledge_access_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="CATEGORY")
    scope_value: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    allowed_roles: Mapped[list[Any] | None] = mapped_column(JSON)
    restricted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class KnowledgeSearchHistory(Base):
    """A search performed in the Knowledge Search Center."""

    __tablename__ = "knowledge_search_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="SEMANTIC")
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class RagQueryHistory(Base):
    """One RAG question and the answer it produced."""

    __tablename__ = "rag_query_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(30), nullable=False, default="DOCUMENT")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    grounded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_status: Mapped[str] = mapped_column(String(20), nullable=False, default="SUFFICIENT")
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    chunks_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    business_records: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    limitations: Mapped[list[Any] | None] = mapped_column(JSON)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)

    sources: Mapped[list["RagSourceReference"]] = relationship(
        back_populates="query", cascade="all, delete-orphan"
    )


class RagSourceReference(Base):
    """A citation for one retrieved chunk used in an answer."""

    __tablename__ = "rag_source_references"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    query_id: Mapped[int] = mapped_column(
        ForeignKey("rag_query_history.id", ondelete="CASCADE"), nullable=False, index=True
    )
    document_ref: Mapped[str] = mapped_column(String(40), nullable=False)
    document_title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    chunk_id: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_heading: Mapped[str | None] = mapped_column(String(200))
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    similarity: Mapped[float | None] = mapped_column(Float)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="DOCUMENT")

    query: Mapped["RagQueryHistory"] = relationship(back_populates="sources")


class EmbeddingModelRegistry(Base):
    """Which embedding model produced which index."""

    __tablename__ = "embedding_model_registry"
    __table_args__ = (UniqueConstraint("model_id", name="uq_embedding_model_registry_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[str] = mapped_column(String(120), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="local")
    dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    indexed_chunks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    registered_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class KnowledgeProcessingJob(Base):
    """A persistent document-processing job (survives restarts)."""

    __tablename__ = "knowledge_processing_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    document_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True
    )
    job_type: Mapped[str] = mapped_column(String(30), nullable=False, default="PROCESS")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="QUEUED", index=True)
    stage: Mapped[str | None] = mapped_column(String(40))
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class HybridAIUsage(Base):
    """Recorded provider selection and usage for each AI request."""

    __tablename__ = "hybrid_ai_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    policy: Mapped[str] = mapped_column(String(30), nullable=False, default="LOCAL_FIRST")
    provider: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    model: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fallback_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
