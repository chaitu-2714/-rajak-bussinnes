"""Phase 8 knowledge tools: document search and grounded answers for the AI."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas.tool_schema import ToolContext, ToolDefinition
from app.core.constants import AIRiskLevel
from app.core.exceptions import NotFoundError

SearchMode = Literal["HYBRID", "SEMANTIC", "KEYWORD"]
AnswerMode = Literal["DOCUMENT", "HYBRID", "BUSINESS"]


class KnowledgeSearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=300)
    mode: SearchMode = "HYBRID"
    category: str | None = None
    top_k: int = Field(default=6, ge=1, le=20)


class DocumentQuestionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=3, max_length=400)
    mode: AnswerMode = "DOCUMENT"


def _service(context: ToolContext):
    service = getattr(context.services, "knowledge_service", None)
    if service is None:
        raise NotFoundError("The knowledge service is not available")
    return service


def _run_search(context: ToolContext, args: KnowledgeSearchArgs) -> dict:
    result = _service(context).search(
        args.query, mode=args.mode, category=args.category, top_k=args.top_k
    )
    return {
        "query": result["query"],
        "mode": result["mode"],
        "count": result["count"],
        "note": result["note"],
        "results": [
            {
                "document": hit["title"],
                "page": hit["page_number"],
                "section": hit["section_heading"],
                "score": hit["score"],
                "match_type": hit["match_type"],
                "excerpt": hit["excerpt"],
            }
            for hit in result["hits"]
        ],
        "summary": (
            f"{result['count']} passage(s) found in {result['documents_searched']} document(s)."
            if result["count"]
            else result["note"] or "No passage matched."
        ),
    }


def _run_answer(context: ToolContext, args: DocumentQuestionArgs) -> dict:
    answer = _service(context).ask(args.question, mode=args.mode)
    return {
        "question": answer.question,
        "answer": answer.answer,
        "grounded": answer.grounded,
        "evidence_status": answer.evidence_status,
        "provider": answer.provider,
        "model": answer.model,
        "citations": answer.citations,
        "sources": [
            {
                "document": source.title,
                "page": source.page_number,
                "section": source.section_heading,
                "type": source.source_type,
                "similarity": source.similarity,
            }
            for source in answer.sources
        ],
        "business_records": answer.business_records,
        "limitations": answer.limitations,
        "summary": answer.answer[:400],
    }


def build_knowledge_tools() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="search_business_documents",
            description=(
                "Search uploaded business documents (contracts, policies, invoices) "
                "by meaning or exact keyword, returning passages with page numbers"
            ),
            category="knowledge",
            input_model=KnowledgeSearchArgs,
            required_permission="knowledge.view",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=120.0,
            handler=_run_search,
        ),
        ToolDefinition(
            name="ask_business_documents",
            description=(
                "Answer a question from uploaded documents, optionally combined with "
                "business records, with citations and an explicit evidence status"
            ),
            category="knowledge",
            input_model=DocumentQuestionArgs,
            required_permission="knowledge.ask",
            risk_level=AIRiskLevel.READ_ONLY,
            timeout_seconds=180.0,
            handler=_run_answer,
        ),
    ]
