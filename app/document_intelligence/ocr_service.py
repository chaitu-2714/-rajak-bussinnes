"""OCR for scanned pages.

Tesseract is used when it is installed. When it is not, the service reports
itself as unavailable and says why — it never returns invented text.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from app.core.logging_config import get_logger

logger = get_logger("document.ocr")


@dataclass
class OcrService:
    """Local OCR, available only when the engine really is installed."""

    language: str = "eng"
    dpi: int = 200

    def __post_init__(self) -> None:
        self._pytesseract = None
        self._reason: str | None = None
        try:
            import pytesseract  # type: ignore

            self._pytesseract = pytesseract
        except Exception as exc:  # noqa: BLE001
            self._reason = (
                "pytesseract is not installed, so scanned pages cannot be read."
                f" ({type(exc).__name__})"
            )
            return
        if shutil.which("tesseract") is None:
            self._reason = (
                "The Tesseract engine is not installed on this machine, so scanned "
                "pages cannot be read."
            )
            self._pytesseract = None

    @property
    def available(self) -> bool:
        return self._pytesseract is not None

    @property
    def unavailable_reason(self) -> str | None:
        return self._reason

    def info(self) -> dict:
        version = None
        if self.available:
            try:
                version = str(self._pytesseract.get_tesseract_version())
            except Exception:  # noqa: BLE001
                version = "unknown"
        return {
            "available": self.available,
            "engine": "tesseract" if self.available else None,
            "version": version,
            "language": self.language,
            "dpi": self.dpi,
            "reason": self._reason,
        }

    # -- extraction --------------------------------------------------------
    def extract_page(self, path: Path, page_number: int) -> str:
        """OCR one page of a PDF or one image file."""
        if not self.available:
            raise RuntimeError(self._reason or "OCR is unavailable")
        image = self._render(path, page_number)
        return self._pytesseract.image_to_string(image, lang=self.language)

    def extract_image(self, path: Path) -> str:
        if not self.available:
            raise RuntimeError(self._reason or "OCR is unavailable")
        from PIL import Image

        with Image.open(path) as image:
            return self._pytesseract.image_to_string(image, lang=self.language)

    def _render(self, path: Path, page_number: int):
        from PIL import Image

        if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff"}:
            return Image.open(path)
        import pymupdf

        with pymupdf.open(path) as document:
            page = document.load_page(page_number - 1)
            zoom = self.dpi / 72
            matrix = pymupdf.Matrix(zoom, zoom)
            pixmap = page.get_pixmap(matrix=matrix)
            return Image.open(__import__("io").BytesIO(pixmap.tobytes("png")))
