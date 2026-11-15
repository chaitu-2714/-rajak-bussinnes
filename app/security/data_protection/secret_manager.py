"""Secret storage and sensitive-data handling.

Application-managed secrets (currently the TOTP secrets) are encrypted with
Fernet (AES-128-CBC + HMAC-SHA256) using a key held in a separate file with
owner-only permissions, outside the database. API keys continue to live in the
operating-system credential store (Phase 3 ``CredentialStore``).

The limitation is stated plainly: a key file beside the database protects against
casual inspection and database copies, not against an attacker who already has the
user's filesystem. Key backup is the operator's responsibility.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.logging_config import get_logger

logger = get_logger("security.secrets")

# Patterns that must never reach a log line or a cloud provider.
SECRET_PATTERNS = (
    re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),          # Google API key
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),                # generic secret key
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),               # GitHub token
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),           # long base64 blob
    re.compile(r"(?i)\b(password|passwd|secret|token|api[_\- ]?key)\s*[:=]\s*\S+"),
)


class SecretManagerError(Exception):
    """Raised when a secret cannot be stored or read safely."""


class SecretManager:
    """Encrypts application secrets with a key kept separate from the data."""

    def __init__(self, key_path: Path) -> None:
        self._key_path = Path(key_path)
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        self._fernet = Fernet(self._load_or_create_key())

    # -- key handling ------------------------------------------------------
    def _load_or_create_key(self) -> bytes:
        if self._key_path.exists():
            self._restrict_permissions()
            return self._key_path.read_bytes().strip()
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        self._restrict_permissions()
        logger.info("Created a new application secret key")
        return key

    def _restrict_permissions(self) -> None:
        try:
            os.chmod(self._key_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:  # pragma: no cover - platform dependent
            logger.warning("Could not restrict key permissions: %s", exc)

    @property
    def key_location(self) -> str:
        return str(self._key_path)

    # -- encryption --------------------------------------------------------
    def encrypt(self, value: str) -> str:
        if value is None:
            raise SecretManagerError("Nothing to encrypt")
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            raise SecretManagerError(
                "The stored secret cannot be decrypted with the current key. "
                "The key file may have been replaced."
            ) from exc

    # -- detection ---------------------------------------------------------
    def contains_secret(self, text: str) -> bool:
        return any(pattern.search(text or "") for pattern in SECRET_PATTERNS)

    def redact(self, text: str) -> str:
        """Replace anything that looks like a credential."""
        if not text:
            return text
        redacted = text
        for pattern in SECRET_PATTERNS:
            redacted = pattern.sub("[REDACTED]", redacted)
        return redacted

    def mask(self, value: str | None, *, keep: int = 4) -> str:
        if not value:
            return "not set"
        if len(value) <= keep:
            return "*" * len(value)
        return value[:2] + "*" * (len(value) - keep - 2) + value[-keep:]
