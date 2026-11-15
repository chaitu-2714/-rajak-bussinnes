"""Document-level access control for the knowledge base."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.database.models.knowledge import KnowledgeAccessPolicy, KnowledgeDocument

logger = get_logger("knowledge.permissions")


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str


class KnowledgePermissionService:
    """Decides whether a user may see a document.

    Rules, in order: business isolation, then an explicit restricted flag, then a
    category policy, then the plain ``knowledge.view`` permission.
    """

    def can_view(
        self,
        db: Session,
        document: KnowledgeDocument,
        *,
        user_id: int | None,
        roles: list[str],
        permissions: set[str],
        business_id: int | None,
        is_superuser: bool = False,
    ) -> AccessDecision:
        if document.is_deleted:
            return AccessDecision(False, "The document was deleted")

        # 1. Business isolation is absolute — not even a superuser crosses it.
        if document.business_id is not None and business_id is not None:
            if document.business_id != business_id:
                return AccessDecision(False, "The document belongs to another business")

        if is_superuser:
            return AccessDecision(True, "Super administrator")

        if "knowledge.view" not in permissions and "knowledge.manage" not in permissions:
            return AccessDecision(False, "Missing knowledge.view")

        # 2. Explicit per-document restriction.
        if document.is_restricted:
            allowed_users = set(document.allowed_user_ids or [])
            allowed_roles = set(document.allowed_roles or [])
            if "knowledge.manage" in permissions:
                return AccessDecision(True, "Knowledge manager")
            if user_id is not None and user_id in allowed_users:
                return AccessDecision(True, "Named user")
            if allowed_roles & set(roles):
                return AccessDecision(True, "Allowed role")
            return AccessDecision(False, "The document is restricted")

        # 3. Category policy.
        policy = self._category_policy(db, document)
        if policy is not None:
            if policy.restricted:
                allowed_roles = set(policy.allowed_roles or [])
                if "knowledge.manage" in permissions or (allowed_roles & set(roles)):
                    return AccessDecision(True, "Category policy allows this role")
                return AccessDecision(False, "The document category is restricted")
            allowed_roles = set(policy.allowed_roles or [])
            if allowed_roles and not (allowed_roles & set(roles)):
                if "knowledge.manage" not in permissions:
                    return AccessDecision(False, "Category policy excludes this role")

        return AccessDecision(True, "Permitted")

    def _category_policy(
        self, db: Session, document: KnowledgeDocument
    ) -> KnowledgeAccessPolicy | None:
        return db.scalars(
            select(KnowledgeAccessPolicy).where(
                KnowledgeAccessPolicy.scope == "CATEGORY",
                KnowledgeAccessPolicy.scope_value == document.category,
                KnowledgeAccessPolicy.business_id == document.business_id,
            )
        ).first()

    def visible_document_ids(
        self,
        db: Session,
        documents: list[KnowledgeDocument],
        *,
        user_id: int | None,
        roles: list[str],
        permissions: set[str],
        business_id: int | None,
        is_superuser: bool = False,
    ) -> set[int]:
        visible: set[int] = set()
        for document in documents:
            decision = self.can_view(
                db,
                document,
                user_id=user_id,
                roles=roles,
                permissions=permissions,
                business_id=business_id,
                is_superuser=is_superuser,
            )
            if decision.allowed:
                visible.add(document.id)
        return visible
