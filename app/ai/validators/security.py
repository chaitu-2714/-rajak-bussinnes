"""Input sanitisation and prompt-injection defence.

Business data, imported documents and model output are all treated as untrusted
data. Commands are normalised and length-capped; a command that looks like an
attempt to rewrite the assistant's instructions is never sent to a language
model — it is handled by the deterministic rule engine only.
"""

from __future__ import annotations

import re
import unicodedata

MAX_COMMAND_LENGTH = 500

_INJECTION_PATTERNS = (
    r"ignore (all |any )?(previous|prior|above) instructions",
    r"disregard (the )?(system|previous) prompt",
    r"you are now (a|an|the) ",
    r"reveal (your|the) (system )?prompt",
    r"act as (a|an) (root|admin|developer)",
    r"print (your|the) (instructions|prompt)",
    r"\bDROP\s+TABLE\b",
    r"\bDELETE\s+FROM\b",
    r"\bUNION\s+SELECT\b",
    r"<\s*script",
    r"\bos\.system\b|\bsubprocess\b|\beval\(|\bexec\(",
)

_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def sanitise_command(command: str) -> tuple[str, bool]:
    """Normalise a user command.

    Returns ``(clean_text, flagged)``. ``flagged`` is True when the text contains
    patterns that must never reach an LLM.
    """
    if command is None:
        return "", False
    text = unicodedata.normalize("NFKC", str(command))
    text = _CONTROL_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_COMMAND_LENGTH:
        text = text[:MAX_COMMAND_LENGTH].rstrip()
    flagged = bool(_INJECTION_RE.search(text))
    return text, flagged


def sanitise_text(value: str, *, limit: int = 2000) -> str:
    """Clean free text coming from the database or a model."""
    text = _CONTROL_RE.sub(" ", str(value or ""))
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()[:limit]


def contains_injection(text: str) -> bool:
    return bool(_INJECTION_RE.search(text or ""))
