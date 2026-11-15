"""Knowledge service: RBAC, storage, search, RAG and provider settings."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.providers.hybrid_ai_router import HybridAIModelRouter
from app.core.constants import MODULE_KNOWLEDGE, AuditAction, KnowledgeCategory
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.knowledge import (
    DocumentExtractionResult,
    KnowledgeAccessPolicy,
    KnowledgeDocument,
    KnowledgeSearchHistory,
)
from app.knowledge.knowledge_manager import BusinessKnowledgeManager, SearchResult
from app.knowledge.knowledge_permissions import KnowledgePermissionService
from app.knowledge_graph.business_knowledge_graph import BusinessKnowledgeGraph
from app.rag.rag_pipeline import RagAnswer, RagPipeline
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService

logger = get_logger("services.knowledge")


class KnowledgeService(BaseService):
    """The UI and AI tools reach documents through this service."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        manager: BusinessKnowledgeManager,
        permissions: KnowledgePermissionService,
        rag: RagPipeline,
        graph: BusinessKnowledgeGraph,
        hybrid_router: HybridAIModelRouter,
        audit_service: AuditService,
        storage_root: Path,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._manager = manager
        self._permissions = permissions
        self._rag = rag
        self._graph = graph
        self._router = hybrid_router
        self._audit = audit_service
        self._storage_root = Path(storage_root)

    # -- helpers -----------------------------------------------------------
    def _actor(self, db: Session) -> dict[str, Any]:
        user = self._current_user(db)
        roles = [role.role_name for role in getattr(user, "roles", [])]
        permissions = set(self._principal_permissions())
        return {
            "user_id": user.id,
            "roles": roles,
            "permissions": permissions,
            "is_superuser": bool(getattr(user, "is_superuser", False)),
            "business_id": self._business_id(db),
        }

    def _business_id(self, db: Session) -> int | None:
        """The workspace's business id (one business per installation)."""
        from app.database.models.business import Business

        return db.scalars(select(Business.id).order_by(Business.id)).first()

    def _principal_permissions(self) -> list[str]:
        principal = self._auth_context.principal
        return list(principal.permissions) if principal else []

    def _visible_documents(self, db: Session, actor: dict[str, Any]) -> list[KnowledgeDocument]:
        documents = self._manager.list_documents(
            db, business_id=actor["business_id"], limit=500
        )
        visible_ids = self._permissions.visible_document_ids(
            db,
            documents,
            user_id=actor["user_id"],
            roles=actor["roles"],
            permissions=actor["permissions"],
            business_id=actor["business_id"],
            is_superuser=actor["is_superuser"],
        )
        return [document for document in documents if document.id in visible_ids]

    # -- documents ---------------------------------------------------------
    def upload_document(
        self,
        file_path: str | Path,
        *,
        title: str | None = None,
        category: str | None = None,
        is_restricted: bool = False,
        allowed_roles: list[str] | None = None,
        collection_key: str | None = None,
        note: str | None = None,
        process: bool = True,
    ) -> dict[str, Any]:
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.upload")
            actor_id = user.id
            business_id = self._business_id(db)
        if category and category not in KnowledgeCategory.ALL:
            raise ValidationError(f"'{category}' is not a knowledge category")
        try:
            document = self._manager.import_document(
                Path(file_path),
                title=title,
                category=category,
                business_id=business_id,
                uploaded_by=actor_id,
                is_restricted=is_restricted,
                allowed_roles=allowed_roles,
                collection_key=collection_key,
                note=note,
                process=process,
            )
        except Exception as exc:
            with self.unit_of_work() as db:
                self._audit.record(
                    db,
                    actor_id=actor_id,
                    action=AuditAction.DOCUMENT_FAILED,
                    module=MODULE_KNOWLEDGE,
                    entity_type="KnowledgeDocument",
                    entity_id=str(Path(file_path).name),
                    new_values={"error": str(exc)[:300]},
                )
            raise
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor_id,
                action=AuditAction.DOCUMENT_UPLOADED,
                module=MODULE_KNOWLEDGE,
                entity_type="KnowledgeDocument",
                entity_id=document.document_ref,
                new_values={"title": document.title, "status": document.status},
            )
            return self._document_row(db, document)

    def upload_bytes(
        self,
        content: bytes,
        file_name: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Convenience for the UI, which holds bytes rather than a path."""
        suffix = Path(file_name).suffix or ".txt"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        try:
            return self.upload_document(temp_path, title=kwargs.pop("title", Path(file_name).stem), **kwargs)
        finally:
            temp_path.unlink(missing_ok=True)

    def list_documents(self, *, category: str | None = None, include_archived: bool = False) -> list[dict]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
            actor = self._actor(db)
            documents = self._manager.list_documents(
                db,
                business_id=actor["business_id"],
                category=category,
                include_archived=include_archived,
            )
            visible_ids = self._permissions.visible_document_ids(
                db,
                documents,
                user_id=actor["user_id"],
                roles=actor["roles"],
                permissions=actor["permissions"],
                business_id=actor["business_id"],
                is_superuser=actor["is_superuser"],
            )
            return [
                self._document_row(db, document)
                for document in documents
                if document.id in visible_ids
            ]

    def statistics(self) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
            actor = self._actor(db)
            stats = self._manager.statistics(db, business_id=actor["business_id"])
            stats["vector_index"] = self._manager._vectors.validate_vector_index()  # noqa: SLF001
            stats["embedding_model"] = self._manager._embeddings.model_info()  # noqa: SLF001
            stats["ocr"] = getattr(self._manager._parser._ocr, "info", lambda: {"available": False})()  # noqa: SLF001
            return stats

    def get_document(self, document_ref: str) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
            actor = self._actor(db)
            allowed = self._manager.verify_document_access(
                db,
                document_ref,
                user_id=actor["user_id"],
                roles=actor["roles"],
                permissions=actor["permissions"],
                business_id=actor["business_id"],
                is_superuser=actor["is_superuser"],
            )
            if not allowed:
                self._audit.record(
                    db,
                    actor_id=actor["user_id"],
                    action=AuditAction.DOCUMENT_ACCESS_DENIED,
                    module=MODULE_KNOWLEDGE,
                    entity_type="KnowledgeDocument",
                    entity_id=document_ref,
                )
                raise AuthorizationError("You do not have access to this document")
            details = self._manager.get_document_details(db, document_ref)
            details["relationships"] = self._graph.document_relationships(db, document_ref)
            return details

    def preview_document(self, document_ref: str, *, limit: int = 4000) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
            actor = self._actor(db)
            if not self._manager.verify_document_access(
                db, document_ref,
                user_id=actor["user_id"], roles=actor["roles"],
                permissions=actor["permissions"], business_id=actor["business_id"],
                is_superuser=actor["is_superuser"],
            ):
                raise AuthorizationError("You do not have access to this document")
            document = self._manager.get_document_by_ref(db, document_ref)
            return {
                "document_ref": document.document_ref,
                "title": document.title,
                "text": (document.extracted_text or "")[:limit],
                "truncated": len(document.extracted_text or "") > limit,
            }

    def verify_field(self, document_ref: str, field_name: str, *, status: str = "VERIFIED") -> dict:
        if status not in ("VERIFIED", "REJECTED", "UNVERIFIED"):
            raise ValidationError("A verification status must be VERIFIED, REJECTED or UNVERIFIED")
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.manage")
            document = self._manager.get_document_by_ref(db, document_ref)
            row = db.scalars(
                select(DocumentExtractionResult).where(
                    DocumentExtractionResult.document_id == document.id,
                    DocumentExtractionResult.field_name == field_name,
                )
            ).first()
            if row is None:
                raise NotFoundError(f"No extracted field '{field_name}' on this document")
            row.validation_status = status
            row.verified_by = user.id
            from app.utils.date_utils import utcnow

            row.verified_at = utcnow()
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.EXTRACTION_VERIFIED,
                module=MODULE_KNOWLEDGE,
                entity_type="DocumentExtractionResult",
                entity_id=f"{document_ref}:{field_name}",
                new_values={"status": status},
            )
            return {"document_ref": document_ref, "field": field_name, "status": status}

    def update_document(self, document_ref: str, file_path: str | Path, *, note: str | None = None) -> dict:
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.manage")
            actor_id = user.id
        result = self._manager.update_document(document_ref, Path(file_path), note=note, uploaded_by=actor_id)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor_id,
                action=AuditAction.DOCUMENT_VERSION_ADDED,
                module=MODULE_KNOWLEDGE,
                entity_type="KnowledgeDocument",
                entity_id=document_ref,
                new_values={"version": result.get("version")},
            )
        return result

    def reprocess_document(self, document_ref: str) -> dict:
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.manage")
            actor_id = user.id
        result = self._manager.reprocess_document(document_ref)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor_id,
                action=AuditAction.DOCUMENT_INDEXED,
                module=MODULE_KNOWLEDGE,
                entity_type="KnowledgeDocument",
                entity_id=document_ref,
                new_values={"chunks": result.get("chunks")},
            )
        return result

    def archive_document(self, document_ref: str) -> dict:
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.manage")
            actor_id = user.id
        result = self._manager.archive_document(document_ref)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor_id,
                action=AuditAction.DOCUMENT_ARCHIVED,
                module=MODULE_KNOWLEDGE,
                entity_type="KnowledgeDocument",
                entity_id=document_ref,
            )
        return result

    def delete_document(self, document_ref: str) -> dict:
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.manage")
            actor_id = user.id
        result = self._manager.delete_document(document_ref)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor_id,
                action=AuditAction.DOCUMENT_DELETED,
                module=MODULE_KNOWLEDGE,
                entity_type="KnowledgeDocument",
                entity_id=document_ref,
                new_values=result,
            )
        return result

    # -- search ------------------------------------------------------------
    def search(self, query: str, *, mode: str = "HYBRID", category: str | None = None, top_k: int = 8) -> dict:
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.view")
            actor = self._actor(db)
            documents = self._manager.list_documents(db, business_id=actor["business_id"], limit=500)
            visible_ids = self._permissions.visible_document_ids(
                db, documents,
                user_id=actor["user_id"], roles=actor["roles"],
                permissions=actor["permissions"], business_id=actor["business_id"],
                is_superuser=actor["is_superuser"],
            )
            result: SearchResult = self._manager.search_knowledge(
                db,
                query,
                mode=mode,
                business_id=actor["business_id"],
                visible_document_ids=visible_ids,
                categories=[category] if category else None,
                top_k=top_k,
            )
            db.add(
                KnowledgeSearchHistory(
                    business_id=actor["business_id"],
                    query=query,
                    mode=result.mode,
                    result_count=result.count,
                    filters={"category": category} if category else {},
                    user_id=user.id,
                )
            )
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.KNOWLEDGE_SEARCHED,
                module=MODULE_KNOWLEDGE,
                entity_type="KnowledgeSearch",
                entity_id=query[:100],
                new_values={"results": result.count, "mode": result.mode},
            )
            return {
                "query": result.query,
                "mode": result.mode,
                "count": result.count,
                "documents_searched": result.documents_searched,
                "note": result.note,
                "hits": [
                    {
                        "chunk_id": hit.chunk_id,
                        "document_ref": hit.document_ref,
                        "title": hit.title,
                        "category": hit.category,
                        "page_number": hit.page_number,
                        "section_heading": hit.section_heading,
                        "excerpt": " ".join(hit.content.split())[:400],
                        "score": hit.score,
                        "match_type": hit.match_type,
                    }
                    for hit in result.hits
                ],
            }

    def search_history(self, limit: int = 20) -> list[dict]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
            rows = db.scalars(
                select(KnowledgeSearchHistory)
                .order_by(KnowledgeSearchHistory.id.desc())
                .limit(limit)
            ).all()
            return [
                {
                    "query": row.query,
                    "mode": row.mode,
                    "results": row.result_count,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    # -- RAG ---------------------------------------------------------------
    def ask(self, question: str, *, mode: str = "DOCUMENT", top_k: int = 6) -> RagAnswer:
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.ask")
            actor = self._actor(db)
            documents = self._manager.list_documents(db, business_id=actor["business_id"], limit=500)
            visible_ids = self._permissions.visible_document_ids(
                db, documents,
                user_id=actor["user_id"], roles=actor["roles"],
                permissions=actor["permissions"], business_id=actor["business_id"],
                is_superuser=actor["is_superuser"],
            )
            answer = self._rag.process_query(
                db,
                question,
                business_id=actor["business_id"],
                visible_document_ids=visible_ids,
                mode=mode,
                user_id=user.id,
                top_k=top_k,
            )
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.RAG_ANSWER_GENERATED,
                module=MODULE_KNOWLEDGE,
                entity_type="RagQuery",
                entity_id=answer.query_ref,
                new_values={
                    "grounded": answer.grounded,
                    "provider": answer.provider,
                    "sources": len(answer.sources),
                },
            )
            return answer

    def ask_history(self, limit: int = 20) -> list[dict]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
            return self._rag.history(db, limit=limit)

    # -- maintenance -------------------------------------------------------
    def recover_jobs(self) -> int:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.manage")
        return self._manager.recover_interrupted_jobs()

    def reindex_all(self) -> dict:
        with self.unit_of_work() as db:
            user = self._authorize(db, "knowledge.manage")
            actor_id = user.id
        result = self._manager.reindex_all()
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor_id,
                action=AuditAction.DOCUMENT_INDEXED,
                module=MODULE_KNOWLEDGE,
                entity_type="VectorIndex",
                entity_id=result["model"],
                new_values={"rebuilt": result["rebuilt"], "failed": len(result["failed"])},
            )
        return result

    def validate_index(self) -> dict:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
        return self._manager._vectors.validate_vector_index()  # noqa: SLF001

    # -- AI provider settings ---------------------------------------------
    def provider_configuration(self) -> dict:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
            return self._router.configuration()

    def configure_providers(
        self,
        *,
        policy: str | None = None,
        offline_mode: bool | None = None,
        cloud_sharing_enabled: bool | None = None,
    ) -> dict:
        with self.unit_of_work() as db:
            user = self._authorize(db, "agents.configure")
            actor_id = user.id
        self._router.configure(
            policy=policy, offline_mode=offline_mode, cloud_sharing_enabled=cloud_sharing_enabled
        )
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor_id,
                action="AI_PROVIDER_CONFIGURED",
                module=MODULE_KNOWLEDGE,
                entity_type="HybridAIModelRouter",
                entity_id=policy or "unchanged",
                new_values={
                    "policy": policy,
                    "offline_mode": offline_mode,
                    "cloud_sharing_enabled": cloud_sharing_enabled,
                },
            )
        return self._router.configuration()

    def provider_usage(self, limit: int = 20) -> list[dict]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "knowledge.view")
        return self._router.usage_summary(limit=limit)

    # -- helpers -----------------------------------------------------------
    def _document_row(self, db: Session, document: KnowledgeDocument) -> dict[str, Any]:
        return {
            "document_ref": document.document_ref,
            "title": document.title,
            "file_name": document.file_name,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "category": document.category,
            "status": document.status,
            "processing_stage": document.processing_stage,
            "ocr_status": document.ocr_status,
            "index_status": document.index_status,
            "page_count": document.page_count,
            "chunk_count": document.chunk_count,
            "current_version": document.current_version,
            "embedding_model": document.embedding_model,
            "is_restricted": document.is_restricted,
            "is_archived": document.is_archived,
            "error": document.error_message,
            "created_at": document.created_at,
            "processed_at": document.processed_at,
        }
