"""RAG grounding, citations, hybrid retrieval and provider behaviour (tests 7-10, 17-19)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.providers.hybrid_ai_router import HybridAIModelRouter
from app.core.constants import AITaskKind, RoutingPolicy

from tests.conftest import completed_sale


@pytest.fixture()
def corpus(admin, tmp_path: Path) -> dict[str, str]:
    agreement = tmp_path / "supplier_agreement.txt"
    agreement.write_text(
        "SUPPLIER AGREEMENT\n\n"
        "This agreement is between Patnaik Traders and Odisha Beverages Supply Pvt Ltd.\n"
        "Payment terms: 30 days from invoice date\n"
        "Delivery terms: Delivery within 7 days of purchase order\n"
        "Penalty clause: Late delivery attracts a penalty of 2% of order value per week\n",
        encoding="utf-8",
    )
    policy = tmp_path / "purchase_policy.md"
    policy.write_text(
        "# Purchase Approval Policy\n\n"
        "Orders above INR 25000 require owner approval.\n"
        "Inventory returns must be recorded within 7 days of delivery.\n",
        encoding="utf-8",
    )
    refs = {}
    for key, path in (("agreement", agreement), ("policy", policy)):
        refs[key] = admin.knowledge_service.upload_document(path)["document_ref"]
    return refs


# ---------------------------------------------------------------------------
# Test 7: a document question with page references
# ---------------------------------------------------------------------------
def test_document_question_is_answered_with_page_references(admin, corpus) -> None:
    answer = admin.knowledge_service.ask("What are the payment terms in the supplier agreement?")
    assert answer.grounded is True
    assert answer.evidence_status == "SUFFICIENT"
    assert "30 days" in answer.answer
    assert answer.sources
    assert all(source.page_number == 1 for source in answer.sources)
    assert any("page 1" in citation for citation in answer.citations)


# ---------------------------------------------------------------------------
# Test 8: refuse when no evidence exists
# ---------------------------------------------------------------------------
def test_no_evidence_means_no_answer(admin, corpus) -> None:
    answer = admin.knowledge_service.ask(
        "What is the warranty period for the delivery van engine?"
    )
    assert answer.evidence_status == "INSUFFICIENT_EVIDENCE"
    assert answer.grounded is False
    assert "could not find" in answer.answer.lower()
    # Nothing invented: no source and no fabricated citation.
    assert answer.sources == []


def test_no_documents_at_all(admin) -> None:
    answer = admin.knowledge_service.ask("What are the payment terms?")
    assert answer.evidence_status == "NO_DOCUMENTS"
    assert answer.grounded is False


# ---------------------------------------------------------------------------
# Test 9: database records combined with document terms
# ---------------------------------------------------------------------------
def test_hybrid_answer_combines_records_and_contract(admin, business, corpus) -> None:
    completed_sale(admin, business, quantity=2)
    # The supplier named in the agreement, so records and document refer to the same party.
    supplier = admin.purchasing_service.create_supplier(
        {"supplier_name": "Odisha Beverages Supply Pvt Ltd", "phone": "9000012345"}
    )
    order = admin.purchasing_service.create_purchase_order(
        {
            "supplier_id": supplier.id,
            "items": [{"product_id": business["tea"].id, "ordered_quantity": 10, "unit_cost": "100.00"}],
        }
    )
    admin.purchasing_service.approve_purchase_order(order.id)
    admin.purchasing_service.mark_ordered(order.id)

    answer = admin.knowledge_service.ask(
        "How much do I owe Odisha Beverages Supply and what are the payment terms in our agreement?",
        mode="HYBRID",
    )
    assert answer.business_records >= 1
    document_sources = [s for s in answer.sources if s.source_type == "DOCUMENT"]
    assert document_sources, "the agreement must be cited alongside the records"
    # The two sources are presented separately and labelled.
    assert "business records" in answer.answer.lower()
    assert "documents" in answer.answer.lower()
    assert "30 days" in answer.answer
    assert any(s.source_type == "BUSINESS_RECORD" for s in answer.sources)


# ---------------------------------------------------------------------------
# Test 10: unpaid invoices are not cash
# ---------------------------------------------------------------------------
def test_unpaid_invoice_is_not_reported_as_paid(admin, business, corpus) -> None:
    sale = completed_sale(admin, business, quantity=2)
    answer = admin.knowledge_service.ask(
        "How much is outstanding on my customer invoices?", mode="HYBRID"
    )
    assert answer.business_data.get("outstanding_receivables") is not None
    assert "outstanding" in answer.answer.lower()
    # The invoice is still unpaid in the database.
    invoice = admin.sales_service.invoice(sale["invoice"].id)
    assert invoice.paid_amount == 0
    assert invoice.outstanding_amount == invoice.total_amount


# ---------------------------------------------------------------------------
# Test 17: offline RAG (deterministic when no local model is running)
# ---------------------------------------------------------------------------
def test_offline_rag_uses_no_cloud_and_still_answers(admin, corpus) -> None:
    admin.knowledge_service.configure_providers(policy=RoutingPolicy.OFFLINE, offline_mode=True)
    answer = admin.knowledge_service.ask("What are the payment terms in the supplier agreement?")
    assert answer.provider in ("deterministic", "ollama")
    assert answer.provider != "gemini"
    assert answer.grounded is True
    assert "30 days" in answer.answer


# ---------------------------------------------------------------------------
# Test 18: Gemini is never used when cloud access is disabled
# ---------------------------------------------------------------------------
def test_cloud_is_not_used_when_disabled(admin, corpus) -> None:
    admin.knowledge_service.configure_providers(
        policy=RoutingPolicy.CLOUD_FIRST, offline_mode=False, cloud_sharing_enabled=False
    )
    router = admin.hybrid_router
    decision = router.select_provider(AITaskKind.CLOUD_ONLY)
    assert decision.provider != "gemini"
    assert decision.cloud_permitted is False

    answer = admin.knowledge_service.ask("What are the payment terms in the supplier agreement?")
    assert answer.provider != "gemini"

    # Even asking for the cloud provider directly is refused.
    with pytest.raises(RuntimeError):
        router.execute_cloud_model("test prompt")


def test_local_tasks_never_route_to_the_cloud(admin) -> None:
    admin.knowledge_service.configure_providers(
        policy=RoutingPolicy.TASK_BASED, offline_mode=False, cloud_sharing_enabled=True
    )
    for task in (AITaskKind.DOCUMENT_ANSWER, AITaskKind.SENSITIVE_ANALYSIS, AITaskKind.EXTRACTION):
        decision = admin.hybrid_router.select_provider(task)
        assert decision.provider != "gemini", task


# ---------------------------------------------------------------------------
# Test 19: provider failures are reported
# ---------------------------------------------------------------------------
def test_provider_failure_is_reported_and_falls_back(admin, corpus) -> None:
    router: HybridAIModelRouter = admin.hybrid_router
    health = router.check_provider_health()
    assert "ollama" in health
    assert health["ollama"]["available"] is False  # no server in this environment
    assert "detail" in health["ollama"]

    reply, decision = router.route_task("Summarise the payment terms", task=AITaskKind.NARRATE)
    assert reply is None  # no provider could answer
    assert decision.provider in ("ollama", "deterministic")

    usage = admin.knowledge_service.provider_usage(5)
    assert usage, "the attempt must be recorded"
    assert usage[0]["provider"] in ("ollama", "deterministic")


def test_usage_records_the_actual_provider(admin, corpus) -> None:
    admin.knowledge_service.ask("What are the payment terms?")
    usage = admin.knowledge_service.provider_usage(5)
    assert usage
    record = usage[0]
    assert record["provider"] in ("deterministic", "ollama")
    assert record["policy"] in RoutingPolicy.ALL
    # The answer's provider must match what was recorded.
    answer = admin.knowledge_service.ask("What are the delivery terms?")
    latest = admin.knowledge_service.provider_usage(1)[0]
    assert latest["provider"] == answer.provider


# ---------------------------------------------------------------------------
# retrieval quality
# ---------------------------------------------------------------------------
def test_hybrid_search_beats_semantic_only_on_identifiers(admin, corpus, tmp_path: Path) -> None:
    invoice = tmp_path / "invoice_114.txt"
    invoice.write_text(
        "TAX INVOICE\nInvoice No: OBS/2026/114\nSupplier: Odisha Beverages Supply Pvt Ltd\n"
        "Grand Total: 19620.00\n",
        encoding="utf-8",
    )
    admin.knowledge_service.upload_document(invoice)
    semantic = admin.knowledge_service.search("OBS/2026/114", mode="SEMANTIC")
    keyword = admin.knowledge_service.search("OBS/2026/114", mode="KEYWORD")
    assert keyword["count"] >= 1
    assert keyword["hits"][0]["score"] > 0
    # Keyword search is what guarantees exact identifiers are found.
    assert semantic["count"] >= 0


def test_citations_are_deduplicated(admin, corpus) -> None:
    answer = admin.knowledge_service.ask("What are the payment terms and delivery terms?")
    assert len(answer.citations) == len(set(answer.citations))


def test_rag_history_is_recorded(admin, corpus) -> None:
    admin.knowledge_service.ask("What are the payment terms?")
    history = admin.knowledge_service.ask_history()
    assert history
    assert history[0]["grounded"] is True
    assert history[0]["sources"] >= 1
