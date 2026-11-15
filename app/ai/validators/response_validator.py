"""Response validation: never leak secrets or unverified claims to the UI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ai.validators.security import sanitise_text

_SECRET_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"AIza[0-9A-Za-z\-_]{30,}", "[redacted-api-key]"),
    (r"sk-[A-Za-z0-9]{16,}", "[redacted-api-key]"),
    (r"\$argon2id\$[^\s]+", "[redacted-hash]"),
    (r"(?i)\bbearer\s+[A-Za-z0-9._\-]+", "Bearer [redacted]"),
    (r"(?i)(password|passwd|pwd)\s*[:=]\s*\S+", r"\1: [redacted]"),
    (r"(?i)(api[_-]?key|token)\s*[:=]\s*\S+", r"\1: [redacted]"),
)

_SQL_PATTERN = re.compile(
    r"(?i)\b(select\s+.+\s+from|insert\s+into|update\s+\w+\s+set|delete\s+from|drop\s+table)\b"
)

MAX_RESPONSE_LENGTH = 4000


@dataclass
class ResponseValidation:
    text: str
    safe: bool
    issues: list[str] = field(default_factory=list)


class ResponseValidator:
    """Cleans and sanity-checks the final text shown to the user."""

    def __init__(self, *, max_length: int = MAX_RESPONSE_LENGTH) -> None:
        self._max_length = max_length

    def redact(self, text: str) -> str:
        cleaned = text or ""
        for pattern, replacement in _SECRET_PATTERNS:
            cleaned = re.sub(pattern, replacement, cleaned)
        return cleaned

    def validate(self, text: str) -> ResponseValidation:
        issues: list[str] = []
        cleaned = sanitise_text(self.redact(text or ""), limit=self._max_length)

        if not cleaned:
            cleaned = "The workflow finished but produced no readable result."
            issues.append("empty response replaced with a fallback message")

        if _SQL_PATTERN.search(cleaned):
            cleaned = _SQL_PATTERN.sub("[removed-sql]", cleaned)
            issues.append("SQL-like text removed from the response")

        if len(cleaned) >= self._max_length:
            issues.append("response truncated to the maximum length")

        return ResponseValidation(text=cleaned, safe=not issues, issues=issues)
