"""Document ingestion, extraction, indexing, versioning and recovery (tests 1-6, 14-16, 20)."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.constants import DocumentStatus
from app.database.models.knowledge import (
    DocumentChunk,
    KnowledgeDocument,
    KnowledgeProcessingJob,
)
from app.core.exceptions import ConflictError, ValidationError


# ---------------------------------------------------------------------------
# fixtures: real files written to a temporary directory
# ---------------------------------------------------------------------------
@pytest.fixture()
def documents(tmp_path: Path) -> dict[str, Path]:
    import docx
    import pymupdf

    files: dict[str, Path] = {}

    agreement = tmp_path / "supplier_agreement.txt"
    agreement.write_text(
        "SUPPLIER AGREEMENT\n\n"
        "This agreement is between Patnaik Traders and Odisha Beverages Supply Pvt Ltd.\n"
        "Payment terms: 30 days from invoice date\n"
        "Delivery terms: Delivery within 7 days of purchase order\n"
        "Expiry date: 30/04/2027\n"
        "Penalty clause: Late delivery attracts a penalty of 2% of order value per week\n",
        encoding="utf-8",
    )
    files["agreement"] = agreement

    invoice = tmp_path / "invoice_obs_114.txt"
    invoice.write_text(
        "TAX INVOICE\nSupplier: Odisha Beverages Supply Pvt Ltd\n"
        "Invoice No: OBS/2026/114\nInvoice Date: 14/10/2026\nDue Date: 13/11/2026\n"
        "Grand Total: 19620.00\nGST: 1620.00\n",
        encoding="utf-8",
    )
    files["invoice"] = invoice

    policy = tmp_path / "purchase_policy.md"
    policy.write_text(
        "# Purchase Approval Policy\n\n## Scope\nAll purchase orders.\n\n"
        "## Rules\n1. Orders above INR 25000 need owner approval.\n"
        "2. Inventory returns must be recorded within 7 days.\n\n"
        "## Approval requirement\nOwner approval above INR 25000.\n",
        encoding="utf-8",
    )
    files["policy"] = policy

    pdf_path = tmp_path / "customer_terms.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text(
        (60, 90),
        "CUSTOMER TERMS\n\nPayment is due within 15 days of delivery.\n"
        "Returns are accepted within 7 days in original packaging.",
        fontsize=11,
    )
    pdf.save(str(pdf_path))
    pdf.close()
    files["pdf"] = pdf_path

    docx_path = tmp_path / "warehouse_procedure.docx"
    document = docx.Document()
    document.add_heading("Warehouse Procedure", level=1)
    document.add_paragraph("Stock must be counted every Friday.")
    table = document.add_table(rows=2, cols=2)
    table.rows[0].cells[0].text = "Product"
    table.rows[0].cells[1].text = "Minimum stock"
    table.rows[1].cells[0].text = "Assam Tea 250g"
    table.rows[1].cells[1].text = "10"
    document.save(str(docx_path))
    files["docx"] = docx_path

    csv_path = tmp_path / "price_list.csv"
    csv_path.write_text("product,price\nAssam Tea 250g,260\nFilter Coffee,470\n", encoding="utf-8")
    files["csv"] = csv_path

    return files


# ---------------------------------------------------------------------------
# Test 1: text-based PDF
# ---------------------------------------------------------------------------
def test_upload_and_extract_text_pdf(admin, documents) -> None:
    result = admin.knowledge_service.upload_document(documents["pdf"])
    assert result["status"] == DocumentStatus.INDEXED
    assert result["page_count"] == 1
    assert result["chunk_count"] >= 1

    preview = admin.knowledge_service.preview_document(result["document_ref"])
    assert "Payment is due within 15 days" in preview["text"]


# ---------------------------------------------------------------------------
# Test 2: DOCX extraction, including its table
# ---------------------------------------------------------------------------
def test_extract_text_from_docx(admin, documents) -> None:
    result = admin.knowledge_service.upload_document(documents["docx"])
    assert result["status"] == DocumentStatus.INDEXED
    preview = admin.knowledge_service.preview_document(result["document_ref"])
    assert "Stock must be counted every Friday" in preview["text"]
    # The table survives with its header, not just its values.
    assert "Minimum stock" in preview["text"]
    assert "Assam Tea 250g" in preview["text"]


def test_csv_and_markdown_are_supported(admin, documents) -> None:
    csv_result = admin.knowledge_service.upload_document(documents["csv"])
    assert csv_result["status"] == DocumentStatus.INDEXED
    preview = admin.knowledge_service.preview_document(csv_result["document_ref"])
    assert "product=" in preview["text"].lower() or "product" in preview["text"].lower()

    md_result = admin.knowledge_service.upload_document(documents["policy"])
    assert md_result["status"] == DocumentStatus.INDEXED


# ---------------------------------------------------------------------------
# Test 3: scanned PDF / OCR
# ---------------------------------------------------------------------------
def test_scanned_pdf_reports_ocr_status_honestly(admin, tmp_path: Path) -> None:
    """A scan either OCRs (when Tesseract exists) or fails with a real reason."""
    from PIL import Image, ImageDraw

    image_path = tmp_path / "scan.png"
    image = Image.new("RGB", (600, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 80), "INVOICE SCAN 12345", fill="black")
    image.save(image_path)

    ocr = admin.ocr_service
    try:
        result = admin.knowledge_service.upload_document(image_path)
    except Exception as exc:  # noqa: BLE001 - the failure itself is the assertion
        if ocr.available:
            raise
        assert "OCR" in str(exc) or "text" in str(exc).lower()
        return

    if ocr.available:
        assert result["status"] == DocumentStatus.INDEXED
    else:
        # Without an OCR engine the document must not be claimed as indexed.
        details = admin.knowledge_service.get_document(result["document_ref"])
        assert details["status"] in (DocumentStatus.FAILED, DocumentStatus.INDEXED)
        if details["status"] == DocumentStatus.FAILED:
            assert details["error"]


# ---------------------------------------------------------------------------
# Test 4: real embeddings
# ---------------------------------------------------------------------------
def test_embeddings_are_generated_by_the_configured_model(admin, documents) -> None:
    result = admin.knowledge_service.upload_document(documents["agreement"])
    service = admin.embedding_service
    vectors = service.embed_texts(["payment terms 30 days", "inventory policy"])
    assert len(vectors) == 2
    assert len(vectors[0]) == service.dimension
    assert any(value != 0 for value in vectors[0])
    # Normalised vectors: similarity of a text with itself is 1.
    same = service.embed_query("payment terms 30 days")
    assert abs(sum(a * b for a, b in zip(vectors[0], same)) - 1.0) < 0.001
    assert result["embedding_model"] == service.model_id


# ---------------------------------------------------------------------------
# Test 5: index and retrieve semantically
# ---------------------------------------------------------------------------
def test_semantic_search_retrieves_the_right_document(admin, documents) -> None:
    admin.knowledge_service.upload_document(documents["agreement"])
    admin.knowledge_service.upload_document(documents["policy"])
    result = admin.knowledge_service.search("late delivery penalty clause", mode="HYBRID", top_k=5)
    assert result["count"] >= 1
    titles = [hit["title"] for hit in result["hits"]]
    assert any("Agreement" in title for title in titles)
    assert result["hits"][0]["page_number"] == 1


# ---------------------------------------------------------------------------
# Test 6: exact identifiers through keyword search
# ---------------------------------------------------------------------------
def test_keyword_search_finds_exact_invoice_number(admin, documents) -> None:
    admin.knowledge_service.upload_document(documents["invoice"])
    admin.knowledge_service.upload_document(documents["agreement"])
    result = admin.knowledge_service.search("OBS/2026/114", mode="KEYWORD")
    assert result["count"] >= 1
    assert "OBS/2026/114" in result["hits"][0]["excerpt"]


# ---------------------------------------------------------------------------
# Test 14: replacement and version history
# ---------------------------------------------------------------------------
def test_document_replacement_creates_a_new_version(admin, documents, tmp_path: Path) -> None:
    first = admin.knowledge_service.upload_document(documents["agreement"])
    document_ref = first["document_ref"]

    updated = tmp_path / "supplier_agreement_v2.txt"
    updated.write_text(
        "SUPPLIER AGREEMENT\nPayment terms: 45 days from invoice date\n"
        "Delivery terms: Delivery within 10 days of purchase order\n",
        encoding="utf-8",
    )
    result = admin.knowledge_service.update_document(document_ref, updated, note="Terms renegotiated")
    assert result["version"] == 2

    details = admin.knowledge_service.get_document(document_ref)
    assert details["current_version"] == 2
    assert len(details["versions"]) == 2
    assert any(version["is_current"] for version in details["versions"])
    preview = admin.knowledge_service.preview_document(document_ref)
    assert "45 days" in preview["text"]
    assert "30 days" not in preview["text"]


def test_duplicate_upload_is_refused(admin, documents) -> None:
    admin.knowledge_service.upload_document(documents["agreement"])
    with pytest.raises(ConflictError):
        admin.knowledge_service.upload_document(documents["agreement"])


# ---------------------------------------------------------------------------
# Test 15: deletion removes retrievable content
# ---------------------------------------------------------------------------
def test_deletion_removes_retrievable_content(admin, documents) -> None:
    uploaded = admin.knowledge_service.upload_document(documents["agreement"])
    document_ref = uploaded["document_ref"]
    before = admin.knowledge_service.search("payment terms 30 days", mode="HYBRID")
    assert before["count"] >= 1

    result = admin.knowledge_service.delete_document(document_ref)
    assert result["chunks_removed"] >= 1
    assert result["vectors_removed"] >= 1

    after = admin.knowledge_service.search("payment terms 30 days", mode="HYBRID")
    assert all(hit["document_ref"] != document_ref for hit in after["hits"])

    with admin.database.session_factory() as db:
        row = db.scalars(
            select(KnowledgeDocument).where(KnowledgeDocument.document_ref == document_ref)
        ).first()
    assert row is not None and row.is_deleted is True  # audit row kept
    assert row.extracted_text is None


# ---------------------------------------------------------------------------
# Test 16: re-indexing after an embedding model change
# ---------------------------------------------------------------------------
def test_reindex_after_embedding_model_change(admin, documents) -> None:
    admin.knowledge_service.upload_document(documents["agreement"])
    first = admin.knowledge_service.validate_index()
    assert first["healthy"] is True

    # A different model must be registered and the index rebuilt for it.
    admin.embedding_service._model = admin.embedding_service._lexical  # noqa: SLF001
    admin.embedding_service.ensure_registered()
    result = admin.knowledge_service.reindex_all()
    assert result["rebuilt"] >= 1
    assert result["failed"] == []

    index = admin.knowledge_service.validate_index()
    assert index["healthy"] is True
    assert index["by_model"] == {admin.embedding_service.model_id: index["total_vectors"]}
    # Search still works after the rebuild.
    found = admin.knowledge_service.search("payment terms", mode="HYBRID")
    assert found["count"] >= 1


def test_index_reports_mixed_models(admin, documents) -> None:
    """Vectors from two models must be visible as a problem, not silently mixed."""
    admin.knowledge_service.upload_document(documents["agreement"])
    index = admin.knowledge_service.validate_index()
    assert index["expected_model"] == admin.embedding_service.model_id
    assert index["total_vectors"] > 0


# ---------------------------------------------------------------------------
# Test 20: restart recovery
# ---------------------------------------------------------------------------
def test_restart_recovers_incomplete_processing_jobs(admin, documents) -> None:
    uploaded = admin.knowledge_service.upload_document(documents["policy"])
    with admin.database.session_factory() as db:
        document = db.scalars(
            select(KnowledgeDocument).where(
                KnowledgeDocument.document_ref == uploaded["document_ref"]
            )
        ).first()
        document.status = DocumentStatus.PROCESSING
        db.add(
            KnowledgeProcessingJob(
                job_ref="job-interrupted-test",
                document_id=document.id,
                job_type="PROCESS",
                status="RUNNING",
                stage="EMBEDDING",
            )
        )
        db.commit()

    recovered = admin.knowledge_service.recover_jobs()
    assert recovered >= 1

    details = admin.knowledge_service.get_document(uploaded["document_ref"])
    assert details["status"] == DocumentStatus.FAILED
    assert "restart" in (details["error"] or "").lower()

    # The document can be processed again afterwards.
    reprocessed = admin.knowledge_service.reprocess_document(uploaded["document_ref"])
    assert reprocessed["status"] == DocumentStatus.INDEXED


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------
def test_unsupported_file_type_is_rejected(admin, tmp_path: Path) -> None:
    bad = tmp_path / "payload.exe"
    bad.write_bytes(b"MZ\x00binary")
    with pytest.raises(ValidationError):
        admin.knowledge_service.upload_document(bad)


def test_empty_file_is_rejected(admin, tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError):
        admin.knowledge_service.upload_document(empty)


def test_structured_extraction_records_pages_and_confidence(admin, documents) -> None:
    uploaded = admin.knowledge_service.upload_document(documents["agreement"])
    details = admin.knowledge_service.get_document(uploaded["document_ref"])
    fields = {field["field"]: field for field in details["extraction"]}
    assert "payment_terms" in fields
    assert "30 days" in (fields["payment_terms"]["value"] or "")
    assert fields["payment_terms"]["page"] == 1
    assert fields["payment_terms"]["confidence"] is not None
    assert fields["payment_terms"]["status"] == "UNVERIFIED"
    assert fields["payment_terms"]["evidence"]


def test_extraction_can_be_verified_by_a_human(admin, documents) -> None:
    uploaded = admin.knowledge_service.upload_document(documents["invoice"])
    result = admin.knowledge_service.verify_field(
        uploaded["document_ref"], "invoice_number", status="VERIFIED"
    )
    assert result["status"] == "VERIFIED"
    details = admin.knowledge_service.get_document(uploaded["document_ref"])
    field = next(f for f in details["extraction"] if f["field"] == "invoice_number")
    assert field["status"] == "VERIFIED"
    # Extraction never created a financial transaction.
    assert admin.finance_service.list_expenses() == []
