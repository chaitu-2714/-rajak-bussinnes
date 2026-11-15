"""File-upload security: signatures, safe names and path containment."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.core.exceptions import ValidationError

MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Magic numbers we can verify. Extensions alone are never trusted.
SIGNATURES: tuple[tuple[bytes, tuple[str, ...]], ...] = (
    (b"%PDF-", (".pdf",)),
    (b"\x89PNG\r\n\x1a\n", (".png",)),
    (b"\xff\xd8\xff", (".jpg", ".jpeg")),
    (b"GIF87a", (".gif",)),
    (b"GIF89a", (".gif",)),
    (b"PK\x03\x04", (".docx", ".xlsx", ".pptx", ".zip")),
    (b"\xd0\xcf\x11\xe0", (".doc", ".xls", ".ppt")),
    (b"BM", (".bmp",)),
)
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".json", ".log", ".rst"}
DANGEROUS_EXTENSIONS = {
    ".exe", ".dll", ".bat", ".cmd", ".ps1", ".sh", ".js", ".vbs", ".scr",
    ".com", ".msi", ".jar", ".py", ".php", ".htaccess",
}
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class UploadCheck:
    ok: bool
    reason: str
    safe_name: str
    detected_type: str | None = None


class FileSecurityService:
    """Validates uploads before anything is stored or parsed."""

    def safe_filename(self, name: str) -> str:
        """Strip directories, control characters and leading dots."""
        candidate = Path(name or "").name
        candidate = CONTROL_CHARS.sub("", candidate)
        candidate = candidate.replace("\\", "_").replace("/", "_").replace("..", "_")
        candidate = candidate.strip().strip(".")
        if not candidate:
            raise ValidationError("The file name is not usable")
        if len(candidate) > 180:
            stem, suffix = candidate[:170], Path(candidate).suffix[:10]
            candidate = f"{stem}{suffix}"
        return candidate

    def detect_type(self, path: Path) -> str | None:
        try:
            with open(path, "rb") as handle:
                head = handle.read(16)
        except OSError:
            return None
        for signature, extensions in SIGNATURES:
            if head.startswith(signature):
                return extensions[0]
        # Text formats have no signature; verify they decode as text.
        try:
            sample = Path(path).read_bytes()[:2048]
            sample.decode("utf-8")
            return "text"
        except (UnicodeDecodeError, OSError):
            return None

    def validate_upload(self, path: Path, *, declared_name: str | None = None) -> UploadCheck:
        path = Path(path)
        name = declared_name or path.name
        safe_name = self.safe_filename(name)
        suffix = Path(safe_name).suffix.lower()

        if not path.exists():
            return UploadCheck(False, "The file was not found", safe_name)
        if suffix in DANGEROUS_EXTENSIONS:
            return UploadCheck(False, f"'{suffix}' files are not accepted", safe_name)
        size = path.stat().st_size
        if size == 0:
            return UploadCheck(False, "The file is empty", safe_name)
        if size > MAX_UPLOAD_BYTES:
            return UploadCheck(
                False,
                f"The file is {size / 1024 / 1024:.1f} MB, above the "
                f"{MAX_UPLOAD_BYTES / 1024 / 1024:.0f} MB limit",
                safe_name,
            )

        detected = self.detect_type(path)
        if detected is None:
            return UploadCheck(
                False, "The file content does not match any supported format", safe_name
            )
        if detected == "text":
            if suffix not in TEXT_EXTENSIONS and suffix not in {".xml", ".yaml", ".yml", ".ini"}:
                return UploadCheck(
                    False,
                    f"The file looks like plain text but has the extension '{suffix}'",
                    safe_name,
                )
            return UploadCheck(True, "Text file verified", safe_name, "text")

        allowed_for_detected = {
            ".pdf": {".pdf"},
            ".png": {".png"},
            ".jpg": {".jpg", ".jpeg"},
            ".gif": {".gif"},
            ".docx": {".docx", ".xlsx", ".pptx", ".zip"},
            ".xlsx": {".docx", ".xlsx", ".pptx", ".zip"},
            ".pptx": {".docx", ".xlsx", ".pptx", ".zip"},
            ".doc": {".doc", ".xls", ".ppt"},
            ".bmp": {".bmp"},
        }.get(detected, {detected})
        if suffix not in allowed_for_detected:
            return UploadCheck(
                False,
                f"The file content is {detected} but the extension is '{suffix}'",
                safe_name,
                detected,
            )
        return UploadCheck(True, "File signature verified", safe_name, detected)

    def resolve_within(self, root: Path, relative: str) -> Path:
        """Resolve a path, refusing anything that escapes the root."""
        root = Path(root).resolve()
        candidate = (root / relative).resolve()
        if root != candidate and root not in candidate.parents:
            raise ValidationError("The requested path is outside the permitted directory")
        return candidate

    def assert_within(self, root: Path, path: Path) -> None:
        root = Path(root).resolve()
        resolved = Path(path).resolve()
        if root != resolved and root not in resolved.parents:
            raise ValidationError("The requested path is outside the permitted directory")
