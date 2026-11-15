"""Business knowledge graph: entity resolution and relationships.

Entities found in documents are matched to real business records. A weak match is
flagged for review instead of being assumed, and no business entity is ever
duplicated by this service.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging_config import get_logger
from app.database.models.knowledge import DocumentEntity, KnowledgeDocument

logger = get_logger("knowledge.graph")

MATCH_THRESHOLD = 0.82
REVIEW_THRESHOLD = 0.62


class EntityResolutionService:
    """Matches names in documents to suppliers, customers and products."""

    def __init__(self, services: Any) -> None:
        self._services = services

    def resolve(
        self, *, pages: list, business_id: int | None, db: Session
    ) -> list[dict[str, Any]]:
        text = "\n".join(getattr(page, "text", "") or "" for page in pages)
        if not text.strip():
            return []
        candidates = self._candidates()
        found: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        lowered = text.lower()
        for entity_type, records in candidates.items():
            for record_id, name in records:
                if not name or len(name) < 3:
                    continue
                if name.lower() not in lowered:
                    # Try a fuzzy pass on capitalised phrases.
                    if self._fuzzy_present(name, text) < REVIEW_THRESHOLD:
                        continue
                    confidence = self._fuzzy_present(name, text)
                    needs_review = confidence < MATCH_THRESHOLD
                else:
                    confidence = 1.0
                    needs_review = False
                key = (entity_type, record_id)
                if key in seen:
                    continue
                seen.add(key)
                found.append(
                    {
                        "entity_type": entity_type,
                        "entity_value": name,
                        "resolved_entity_id": record_id,
                        "match_confidence": round(confidence, 2),
                        "needs_review": needs_review,
                        "page_number": self._page_of(name, pages),
                    }
                )
        return found

    def _candidates(self) -> dict[str, list[tuple[int, str]]]:
        candidates: dict[str, list[tuple[int, str]]] = {
            "SUPPLIER": [],
            "CUSTOMER": [],
            "PRODUCT": [],
        }
        try:
            candidates["SUPPLIER"] = [
                (supplier.id, supplier.supplier_name)
                for supplier in self._services.purchasing_service.list_suppliers()
            ]
        except Exception:  # noqa: BLE001 - permissions or empty data
            pass
        try:
            candidates["CUSTOMER"] = [
                (customer.id, customer.full_name)
                for customer in self._services.customer_service.list_customers()
            ]
        except Exception:  # noqa: BLE001
            pass
        try:
            candidates["PRODUCT"] = [
                (product.id, product.product_name)
                for product in self._services.inventory_service.list_products()
            ]
        except Exception:  # noqa: BLE001
            pass
        return candidates

    def _fuzzy_present(self, name: str, text: str) -> float:
        best = 0.0
        for phrase in re.findall(r"[A-Z][A-Za-z0-9&.\- ]{3,60}", text):
            score = SequenceMatcher(None, name.lower(), phrase.strip().lower()).ratio()
            best = max(best, score)
        return best

    def _page_of(self, name: str, pages: list) -> int | None:
        for page in pages:
            if name.lower() in (getattr(page, "text", "") or "").lower():
                return getattr(page, "page_number", None)
        return None


class BusinessKnowledgeGraph:
    """Relationships between documents and the records they mention."""

    def __init__(self, services: Any) -> None:
        self._services = services

    def document_relationships(self, db: Session, document_ref: str) -> dict[str, Any]:
        document = db.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.document_ref == document_ref)
        ).first()
        if document is None:
            return {"document_ref": document_ref, "entities": [], "records": []}
        entities = db.scalars(
            select(DocumentEntity).where(DocumentEntity.document_id == document.id)
        ).all()
        records: list[dict[str, Any]] = []
        for entity in entities:
            if entity.resolved_entity_id is None:
                continue
            if entity.entity_type == "SUPPLIER":
                records.extend(self._supplier_records(entity.resolved_entity_id))
            elif entity.entity_type == "CUSTOMER":
                records.extend(self._customer_records(entity.resolved_entity_id))
        return {
            "document_ref": document_ref,
            "title": document.title,
            "entities": [
                {
                    "type": entity.entity_type,
                    "value": entity.entity_value,
                    "resolved_id": entity.resolved_entity_id,
                    "confidence": entity.match_confidence,
                    "needs_review": entity.needs_review,
                }
                for entity in entities
            ],
            "records": records,
        }

    def _supplier_records(self, supplier_id: int) -> list[dict[str, Any]]:
        try:
            orders = self._services.purchasing_service.list_purchase_orders()
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "type": "PURCHASE_ORDER",
                "reference": order.purchase_order_number,
                "status": order.status,
                "total": str(order.total_amount),
            }
            for order in orders
            if order.supplier_id == supplier_id
        ]

    def _customer_records(self, customer_id: int) -> list[dict[str, Any]]:
        try:
            orders = self._services.sales_service.list_orders(customer_id=customer_id)
        except Exception:  # noqa: BLE001
            return []
        return [
            {
                "type": "SALES_ORDER",
                "reference": order.order_number,
                "status": order.order_status,
                "total": str(order.total_amount),
            }
            for order in orders[:20]
        ]
