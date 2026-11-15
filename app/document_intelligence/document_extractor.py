"""Document classification and structured extraction.

Classification and extraction are deterministic (filename and content rules), so
they work offline and their results can be re-checked. Every extracted field
records its page, its evidence and its confidence, and starts life UNVERIFIED.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from app.core.constants import KnowledgeCategory
from app.core.logging_config import get_logger

logger = get_logger("document.intelligence")

CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        KnowledgeCategory.SUPPLIER_AGREEMENT,
        ("supplier agreement", "supply agreement", "vendor agreement", "contract with supplier",
         "supply contract", "agreement with supplier"),
    ),
    (
        KnowledgeCategory.CUSTOMER_AGREEMENT,
        ("customer agreement", "client agreement", "service agreement", "customer contract"),
    ),
    (
        KnowledgeCategory.BUSINESS_POLICY,
        ("policy", "policies", "procedure", "guidelines", "code of conduct"),
    ),
    (
        KnowledgeCategory.INVOICE,
        ("invoice", "tax invoice", "bill", "receipt"),
    ),
    (
        KnowledgeCategory.PURCHASE_ORDER,
        ("purchase order", "po number", "goods received note"),
    ),
    (
        KnowledgeCategory.PRODUCT_CATALOGUE,
        ("catalogue", "catalog", "price list", "product list"),
    ),
    (
        KnowledgeCategory.FINANCIAL_DOCUMENT,
        ("balance sheet", "profit and loss", "ledger", "financial statement", "bank statement"),
    ),
    (
        KnowledgeCategory.SALES_DOCUMENT,
        ("sales report", "sales summary", "quotation", "quote"),
    ),
    (
        KnowledgeCategory.INVENTORY_DOCUMENT,
        ("stock report", "inventory report", "warehouse", "stock movement"),
    ),
    (
        KnowledgeCategory.MANAGEMENT_REPORT,
        ("management report", "monthly report", "performance report", "board report"),
    ),
    (
        KnowledgeCategory.EMPLOYEE_PROCEDURE,
        ("employee handbook", "onboarding", "standard operating procedure", "sop"),
    ),
    (
        KnowledgeCategory.RESEARCH_REFERENCE,
        ("research", "study", "whitepaper", "reference"),
    ),
)

FILENAME_HINTS: tuple[tuple[str, str], ...] = (
    ("agreement", KnowledgeCategory.SUPPLIER_AGREEMENT),
    ("contract", KnowledgeCategory.SUPPLIER_AGREEMENT),
    ("invoice", KnowledgeCategory.INVOICE),
    ("policy", KnowledgeCategory.BUSINESS_POLICY),
    ("catalog", KnowledgeCategory.PRODUCT_CATALOGUE),
    ("report", KnowledgeCategory.MANAGEMENT_REPORT),
    ("sop", KnowledgeCategory.EMPLOYEE_PROCEDURE),
)

DATE_RE = re.compile(
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4})",
    re.IGNORECASE,
)
MONEY_RE = re.compile(r"(?:INR|Rs\.?|₹|\$)?\s?([0-9][0-9,]*\.?[0-9]{0,2})")
DAYS_RE = re.compile(r"(\d{1,3})\s*(?:calendar\s+)?days", re.IGNORECASE)


@dataclass
class ExtractedField:
    field_name: str
    field_value: str | None
    page_number: int | None = None
    location: str | None = None
    confidence: float | None = None
    evidence: str | None = None


@dataclass
class ExtractionResult:
    document_type: str
    fields: list[ExtractedField] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class DocumentClassifier:
    """Assigns a knowledge category from the filename and content."""

    def classify(self, *, file_name: str, text: str) -> tuple[str, float, str]:
        name = (file_name or "").lower()
        haystack = f"{name}\n{(text or '')[:6000]}".lower()

        best_category = KnowledgeCategory.OTHER
        best_score = 0
        for category, phrases in CATEGORY_RULES:
            score = sum(haystack.count(phrase) for phrase in phrases)
            if score > best_score:
                best_score = score
                best_category = category

        if best_score == 0:
            for hint, category in FILENAME_HINTS:
                if hint in name:
                    return category, 0.45, f"filename contains '{hint}'"
            return KnowledgeCategory.OTHER, 0.2, "no category keywords matched"

        confidence = min(0.95, 0.55 + 0.08 * best_score)
        return best_category, round(confidence, 2), f"{best_score} keyword match(es)"


class DocumentIntelligenceService:
    """Extracts structured fields for the supported document types."""

    def extract(self, *, category: str, pages: list) -> ExtractionResult:
        text_by_page = [(page.page_number, page.text or "") for page in pages]
        full_text = "\n".join(text for _, text in text_by_page)
        if category == KnowledgeCategory.SUPPLIER_AGREEMENT:
            return self._supplier_agreement(text_by_page, full_text)
        if category == KnowledgeCategory.INVOICE:
            return self._invoice(text_by_page, full_text)
        if category == KnowledgeCategory.PURCHASE_ORDER:
            return self._purchase_order(text_by_page, full_text)
        if category == KnowledgeCategory.BUSINESS_POLICY:
            return self._policy(text_by_page, full_text)
        return ExtractionResult(
            document_type="GENERAL",
            notes=["No structured extraction template exists for this category."],
        )

    # -- helpers -----------------------------------------------------------
    def _find(
        self, pages: list[tuple[int, str]], patterns: tuple[str, ...]
    ) -> tuple[str, int, str] | None:
        for pattern in patterns:
            regex = re.compile(pattern, re.IGNORECASE)
            for page_number, text in pages:
                match = regex.search(text)
                if match:
                    value = match.group(1) if match.groups() else match.group(0)
                    line_start = text.rfind("\n", 0, match.start()) + 1
                    line_end = text.find("\n", match.end())
                    evidence = text[line_start: line_end if line_end != -1 else None].strip()
                    return value.strip(), page_number, evidence[:300]
        return None

    def _field(
        self,
        pages: list[tuple[int, str]],
        name: str,
        patterns: tuple[str, ...],
        *,
        confidence: float = 0.8,
    ) -> ExtractedField | None:
        found = self._find(pages, patterns)
        if found is None:
            return None
        value, page_number, evidence = found
        return ExtractedField(
            field_name=name,
            field_value=value,
            page_number=page_number,
            location=f"page {page_number}",
            confidence=confidence,
            evidence=evidence,
        )

    # -- templates ---------------------------------------------------------
    def _supplier_agreement(self, pages, full_text: str) -> ExtractionResult:
        fields = [
            self._field(pages, "supplier_name", (
                r"(?:between|with)\s+([A-Z][A-Za-z&.\s]{2,60}(?:Pvt|Private|Ltd|Limited|LLP)?)",
                r"supplier(?:\s+name)?\s*[:\-]\s*([A-Za-z0-9&.\s]{2,60})",
            )),
            self._field(pages, "agreement_date", (r"agreement date\s*[:\-]\s*(" + DATE_RE.pattern + ")",)),
            self._field(pages, "effective_date", (r"effective(?: from)?\s*(?:date)?\s*[:\-]\s*(" + DATE_RE.pattern + ")",)),
            self._field(pages, "expiry_date", (
                r"(?:expir(?:y|es|ation)(?:\s+date)?|valid until|valid till)\s*[:\-]?\s*(" + DATE_RE.pattern + ")",
            )),
            self._field(pages, "payment_terms", (
                r"payment terms?\s*[:\-]?\s*([^\n.]{3,120})",
                r"payment(?:\s+shall be made)?\s+within\s*(\d{1,3}\s*(?:calendar\s+)?days)",
            )),
            self._field(pages, "delivery_terms", (
                r"delivery terms?\s*[:\-]?\s*([^\n.]{3,120})",
                r"deliver(?:y|ed)?\s+within\s*(\d{1,3}\s*days)",
            )),
            self._field(pages, "contract_duration", (
                r"(?:contract|agreement)\s+(?:duration|term|period)\s*[:\-]?\s*([^\n.]{3,80})",
            )),
            self._field(pages, "renewal", (
                r"renewal\s*[:\-]?\s*([^\n.]{3,160})",
            )),
            self._field(pages, "penalty_clause", (
                r"(?:late delivery\s+)?penalt(?:y|ies)\s*[:\-]?\s*([^\n.]{3,200})",
            )),
            self._field(pages, "termination", (
                r"termination\s*[:\-]?\s*([^\n.]{3,200})",
            )),
        ]
        return ExtractionResult(
            document_type="SUPPLIER_AGREEMENT",
            fields=[field for field in fields if field is not None],
            notes=["Extracted values are unverified until a human confirms them."],
        )

    def _invoice(self, pages, full_text: str) -> ExtractionResult:
        fields = [
            self._field(pages, "invoice_number", (
                r"invoice\s*(?:no\.?|number|#)\s*[:\-]?\s*([A-Za-z0-9/\-]{3,30})",
            ), confidence=0.9),
            self._field(pages, "invoice_date", (
                r"invoice date\s*[:\-]?\s*(" + DATE_RE.pattern + ")",
            )),
            self._field(pages, "due_date", (
                r"due date\s*[:\-]?\s*(" + DATE_RE.pattern + ")",
            )),
            self._field(pages, "supplier_name", (
                r"(?:from|supplier|vendor)\s*[:\-]\s*([A-Za-z0-9&.\s]{2,60})",
            )),
            self._field(pages, "total_amount", (
                r"(?:grand\s+total|total\s+amount|amount\s+due|total)\s*[:\-]?\s*[A-Za-z₹$]*\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            ), confidence=0.85),
            self._field(pages, "tax_amount", (
                r"(?:gst|tax|vat)\s*(?:@\s*[0-9.]+%?)?\s*[:\-]?\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            ), confidence=0.75),
        ]
        result = ExtractionResult(
            document_type="INVOICE",
            fields=[field for field in fields if field is not None],
            notes=[
                "Invoice values are extracted from the document only; they are not "
                "recorded as financial transactions.",
            ],
        )
        status = self._find(pages, (r"(?:payment\s+status|status)\s*[:\-]\s*(paid|unpaid|partially paid)",))
        if status:
            value, page_number, evidence = status
            result.fields.append(
                ExtractedField(
                    field_name="payment_status",
                    field_value=value.lower(),
                    page_number=page_number,
                    location=f"page {page_number}",
                    confidence=0.7,
                    evidence=evidence,
                )
            )
        else:
            result.notes.append(
                "Payment status was not stated in the document, so it was not extracted."
            )
        return result

    def _purchase_order(self, pages, full_text: str) -> ExtractionResult:
        fields = [
            self._field(pages, "purchase_order_number", (
                r"(?:purchase\s+order|po)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([A-Za-z0-9/\-]{3,30})",
            ), confidence=0.9),
            self._field(pages, "supplier_name", (
                r"supplier\s*[:\-]\s*([A-Za-z0-9&.\s]{2,60})",
            )),
            self._field(pages, "order_date", (
                r"(?:order|po)\s+date\s*[:\-]?\s*(" + DATE_RE.pattern + ")",
            )),
            self._field(pages, "expected_delivery_date", (
                r"(?:expected\s+delivery|delivery\s+date)\s*[:\-]?\s*(" + DATE_RE.pattern + ")",
            )),
            self._field(pages, "total_amount", (
                r"(?:total|order\s+value)\s*[:\-]?\s*[A-Za-z₹$]*\s*([0-9][0-9,]*\.?[0-9]{0,2})",
            )),
        ]
        return ExtractionResult(
            document_type="PURCHASE_ORDER",
            fields=[field for field in fields if field is not None],
        )

    def _policy(self, pages, full_text: str) -> ExtractionResult:
        title = None
        for page_number, text in pages:
            for line in text.splitlines():
                candidate = line.strip().lstrip("#").strip()
                if 3 < len(candidate) < 120 and (
                    "policy" in candidate.lower() or "procedure" in candidate.lower()
                ):
                    title = ExtractedField(
                        field_name="policy_name",
                        field_value=candidate,
                        page_number=page_number,
                        location=f"page {page_number}",
                        confidence=0.8,
                        evidence=candidate,
                    )
                    break
            if title:
                break
        fields = [title] if title else []
        scope = self._field(pages, "scope", (r"scope\s*[:\-]?\s*([^\n.]{3,200})",))
        if scope:
            fields.append(scope)
        responsibilities = self._field(
            pages, "responsibilities", (r"responsibilit(?:y|ies)\s*[:\-]?\s*([^\n.]{3,200})",)
        )
        if responsibilities:
            fields.append(responsibilities)
        approval = self._field(
            pages, "approval_requirement",
            (r"approval(?:\s+requirements?)?\s*[:\-]?\s*([^\n.]{3,200})",),
        )
        if approval:
            fields.append(approval)
        effective = self._field(
            pages, "effective_date",
            (r"effective\s*(?:from|date)?\s*[:\-]?\s*(" + DATE_RE.pattern + ")",),
        )
        if effective:
            fields.append(effective)
        exceptions = self._field(pages, "exceptions", (r"exceptions?\s*[:\-]?\s*([^\n.]{3,200})",))
        if exceptions:
            fields.append(exceptions)
        return ExtractionResult(document_type="BUSINESS_POLICY", fields=fields)


def to_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(value.replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
