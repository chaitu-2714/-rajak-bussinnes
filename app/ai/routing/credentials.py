"""Secure API-key storage.

Keys are never written to the database or the source tree. The lookup order is:

1. the operating system credential store (Windows Credential Manager through
   ``keyring``, Secret Service / Keychain on other platforms);
2. an environment variable (``GEMINI_API_KEY``), which is standard practice for
   server and CI environments;
3. nothing — the provider then reports itself as unavailable.
"""

from __future__ import annotations

import os
from typing import Protocol

from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger

logger = get_logger("ai.credentials")

SERVICE_NAME = "BizPilotAI"


class CredentialError(BizPilotError):
    default_user_message = "The API key could not be stored securely on this computer."


class CredentialBackend(Protocol):
    """Minimal interface so tests can substitute an in-memory store."""

    def get_password(self, service: str, username: str) -> str | None: ...

    def set_password(self, service: str, username: str, password: str) -> None: ...

    def delete_password(self, service: str, username: str) -> None: ...


def _default_backend() -> CredentialBackend | None:
    try:
        import keyring

        return keyring
    except Exception:  # pragma: no cover - keyring is an optional extra
        logger.warning("keyring is not available; falling back to environment variables")
        return None


class CredentialStore:
    """Reads and writes provider API keys without ever persisting plaintext."""

    def __init__(self, backend: CredentialBackend | None = None, *, use_environment: bool = True):
        self._backend = backend if backend is not None else _default_backend()
        self._use_environment = use_environment
        self._memory: dict[str, str] = {}

    @staticmethod
    def _key(provider: str) -> str:
        return f"{provider.lower()}_api_key"

    @staticmethod
    def _env_name(provider: str) -> str:
        return f"{provider.upper()}_API_KEY"

    def get_api_key(self, provider: str) -> str | None:
        provider = provider.lower()
        if provider in self._memory:
            return self._memory[provider]
        if self._backend is not None:
            try:
                value = self._backend.get_password(SERVICE_NAME, self._key(provider))
                if value:
                    return value
            except Exception as exc:  # pragma: no cover - platform specific
                logger.debug("Credential store read failed: %s", exc)
        if self._use_environment:
            value = os.environ.get(self._env_name(provider))
            if value:
                return value
        return None

    def has_api_key(self, provider: str) -> bool:
        return bool(self.get_api_key(provider))

    def set_api_key(self, provider: str, api_key: str) -> None:
        """Store a key in the OS credential store (never in SQLite)."""
        provider = provider.lower()
        api_key = (api_key or "").strip()
        if not api_key:
            raise CredentialError("An API key is required")
        if self._backend is None:
            # No secure backend available: keep it in memory for this session only
            # and tell the caller to use the environment variable instead.
            self._memory[provider] = api_key
            logger.warning(
                "No secure credential backend available; %s key held in memory for this "
                "session only. Set %s to persist it.",
                provider,
                self._env_name(provider),
            )
            return
        try:
            self._backend.set_password(SERVICE_NAME, self._key(provider), api_key)
        except Exception as exc:
            # The platform store is present but refused (for example a headless
            # Linux session without a Secret Service). Keep the key in memory for
            # this session only: it is never written to disk or to SQLite.
            self._memory[provider] = api_key
            logger.warning(
                "The credential store refused the %s key (%s); it is held in memory for "
                "this session only. Set %s to persist it.",
                provider,
                exc,
                self._env_name(provider),
            )
            return
        logger.info("Stored %s API key in the OS credential store", provider)

    def delete_api_key(self, provider: str) -> None:
        provider = provider.lower()
        self._memory.pop(provider, None)
        if self._backend is None:
            return
        try:
            self._backend.delete_password(SERVICE_NAME, self._key(provider))
        except Exception:  # pragma: no cover - nothing stored
            pass

    def describe(self, provider: str) -> str:
        """Human-readable description that never reveals the key."""
        key = self.get_api_key(provider)
        if not key:
            return "no API key configured"
        if provider.lower() in self._memory:
            return "API key configured for this session only"
        return f"API key configured ({len(key)} characters)"
