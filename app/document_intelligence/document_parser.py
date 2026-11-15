"""Document parsing: PDF, DOCX, XLSX, PPTX, CSV, TXT, Markdown and images.

Extraction never invents text. Pages that hold no extractable text are reported
as needing OCR instead of silently producing empty content.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger

logger = get_logger("document.parser")

TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".log", ".rst"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"}
SUPPORTED_EXTENSIONS = (
    {".pdf", ".docx", ".xlsx", ".xls", ".pptx", ".csv"}
    | TEXT_EXTENSIONS
    | IMAGE_EXTENSIONS
)
MAX_FILE_BYTES = 50 * 1024 * 1024
MIN_PAGE_CHARS = 20


class DocumentParseError(BizPilotError):
    default_user_message = "The document could not be read."


@dataclass
class ParsedPage:
    page_number: int
    text: str
    needs_ocr: bool = False


@dataclass
class ParsedDocument:
    file_type: str
    pages: list[ParsedPage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    needs_ocr_pages: list[int] = field(default_factory=list)
    ocr_applied: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n\n".join(page.text for page in self.pages if page.text.strip())

    @property
    def page_count(self) -> int:
        return len(self.pages) or 1

    @property
    def word_count(self) -> int:
        return len(re.findall(r"\w+", self.text))


class DocumentParser:
    """Turns a stored file into page-tagged text."""

    def __init__(self, ocr_service: Any | None = None) -> None:
        self._ocr = ocr_service

    def supported(self, suffix: str) -> bool:
        return suffix.lower() in SUPPORTED_EXTENSIONS

    def parse(self, path: Path, *, file_type: str | None = None) -> ParsedDocument:
        path = Path(path)
        suffix = (file_type or path.suffix).lower()
        if not suffix.startswith("."):
            suffix = f".{suffix}"
        if suffix not in SUPPORTED_EXTENSIONS:
            raise DocumentParseError(
                f"'{suffix}' is not a supported document type. Supported: "
                + ", ".join(sorted(SUPPORTED_EXTENSIONS))
            )
        if not path.exists():
            raise DocumentParseError(f"The file '{path.name}' is no longer on disk")

        if suffix == ".pdf":
            parsed = self._parse_pdf(path)
        elif suffix == ".docx":
            parsed = self._parse_docx(path)
        elif suffix in (".xlsx", ".xls"):
            parsed = self._parse_xlsx(path)
        elif suffix == ".pptx":
            parsed = self._parse_pptx(path)
        elif suffix == ".csv":
            parsed = self._parse_csv(path)
        elif suffix in TEXT_EXTENSIONS:
            parsed = self._parse_text(path)
        elif suffix in IMAGE_EXTENSIONS:
            parsed = self._parse_image(path)
        else:  # pragma: no cover - guarded above
            raise DocumentParseError(f"Unsupported document type '{suffix}'")

        parsed.file_type = suffix.lstrip(".")
        parsed.needs_ocr_pages = [page.page_number for page in parsed.pages if page.needs_ocr]
        if parsed.needs_ocr_pages and self._ocr is not None:
            self._apply_ocr(path, parsed)
        return parsed

    # -- per-format parsers ------------------------------------------------
    def _parse_pdf(self, path: Path) -> ParsedDocument:
        import pymupdf

        pages: list[ParsedPage] = []
        metadata: dict[str, Any] = {}
        with pymupdf.open(path) as document:
            metadata = dict(document.metadata or {})
            for index, page in enumerate(document, start=1):
                text = page.get_text("text") or ""
                cleaned = _clean(text)
                pages.append(
                    ParsedPage(
                        page_number=index,
                        text=cleaned,
                        needs_ocr=len(cleaned.strip()) < MIN_PAGE_CHARS,
                    )
                )
            metadata["page_count"] = document.page_count
        return ParsedDocument(file_type="pdf", pages=pages, metadata=metadata)

    def _parse_docx(self, path: Path) -> ParsedDocument:
        import docx

        document = docx.Document(str(path))
        blocks: list[str] = []
        for paragraph in document.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            style = (paragraph.style.name or "").lower()
            if style.startswith("heading"):
                blocks.append(f"# {text}")
            else:
                blocks.append(text)
        for table in document.tables:
            rows = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append("[TABLE]\n" + "\n".join(rows) + "\n[/TABLE]")
        text = "\n\n".join(blocks)
        return ParsedDocument(
            file_type="docx",
            pages=[ParsedPage(page_number=1, text=_clean(text))],
            metadata={"paragraphs": len(document.paragraphs), "tables": len(document.tables)},
        )

    def _parse_xlsx(self, path: Path) -> ParsedDocument:
        import openpyxl

        workbook = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
        pages: list[ParsedPage] = []
        for index, sheet in enumerate(workbook.worksheets, start=1):
            lines: list[str] = [f"Sheet: {sheet.title}"]
            header: list[str] | None = None
            for row_number, row in enumerate(sheet.iter_rows(values_only=True), start=1):
                values = ["" if cell is None else str(cell) for cell in row]
                if not any(value.strip() for value in values):
                    continue
                if header is None:
                    header = values
                    lines.append(" | ".join(values))
                    continue
                # Repeat the header so a row never loses its column meaning.
                lines.append(f"[ROW {row_number}] " + " | ".join(
                    f"{header[i] if i < len(header) else ''}={values[i]}"
                    for i in range(len(values))
                ))
            pages.append(ParsedPage(page_number=index, text=_clean("\n".join(lines))))
        workbook.close()
        return ParsedDocument(
            file_type="xlsx",
            pages=pages,
            metadata={"sheets": len(pages)},
        )

    def _parse_pptx(self, path: Path) -> ParsedDocument:
        from pptx import Presentation

        presentation = Presentation(str(path))
        pages: list[ParsedPage] = []
        for index, slide in enumerate(presentation.slides, start=1):
            blocks: list[str] = []
            for shape in slide.shapes:
                if shape.has_text_frame and shape.text_frame.text.strip():
                    blocks.append(shape.text_frame.text.strip())
                if getattr(shape, "has_table", False):
                    rows = [
                        " | ".join(cell.text.strip() for cell in row.cells)
                        for row in shape.table.rows
                    ]
                    blocks.append("[TABLE]\n" + "\n".join(rows) + "\n[/TABLE]")
            pages.append(
                ParsedPage(page_number=index, text=_clean("\n\n".join(blocks)))
            )
        return ParsedDocument(
            file_type="pptx", pages=pages, metadata={"slides": len(pages)}
        )

    def _parse_csv(self, path: Path) -> ParsedDocument:
        raw = path.read_text(encoding="utf-8", errors="replace")
        reader = csv.reader(io.StringIO(raw))
        rows = [row for row in reader if any(cell.strip() for cell in row)]
        if not rows:
            return ParsedDocument(
                file_type="csv", pages=[ParsedPage(page_number=1, text="")], metadata={"rows": 0}
            )
        header = rows[0]
        lines = [" | ".join(header)]
        for index, row in enumerate(rows[1:], start=2):
            lines.append(
                f"[ROW {index}] "
                + " | ".join(
                    f"{header[i] if i < len(header) else ''}={row[i]}"
                    for i in range(len(row))
                )
            )
        return ParsedDocument(
            file_type="csv",
            pages=[ParsedPage(page_number=1, text=_clean("\n".join(lines)))],
            metadata={"rows": len(rows) - 1, "columns": len(header)},
        )

    def _parse_text(self, path: Path) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        pages: list[ParsedPage] = []
        # Markdown/text is split on form feeds when present, otherwise one page.
        chunks = text.split("\f") if "\f" in text else [text]
        for index, chunk in enumerate(chunks, start=1):
            pages.append(ParsedPage(page_number=index, text=_clean(chunk)))
        return ParsedDocument(
            file_type=path.suffix.lstrip(".") or "txt",
            pages=pages,
            metadata={"characters": len(text)},
        )

    def _parse_image(self, path: Path) -> ParsedDocument:
        page = ParsedPage(page_number=1, text="", needs_ocr=True)
        return ParsedDocument(
            file_type=path.suffix.lstrip("."),
            pages=[page],
            metadata={"image": True},
            needs_ocr_pages=[1],
        )

    # -- OCR ---------------------------------------------------------------
    def _apply_ocr(self, path: Path, parsed: ParsedDocument) -> None:
        if self._ocr is None or not getattr(self._ocr, "available", False):
            parsed.warnings.append(
                "This document contains pages without a text layer and no local OCR "
                "engine is installed, so those pages have no content."
            )
            return
        for page in parsed.pages:
            if not page.needs_ocr:
                continue
            try:
                text = self._ocr.extract_page(path, page.page_number)
            except Exception as exc:  # noqa: BLE001 - OCR failure must be reported
                parsed.warnings.append(f"OCR failed on page {page.page_number}: {exc}")
                continue
            if text.strip():
                page.text = _clean(text)
                page.needs_ocr = False
                parsed.ocr_applied = True


def _clean(text: str) -> str:
    text = (text or "").replace("\u00a0", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
