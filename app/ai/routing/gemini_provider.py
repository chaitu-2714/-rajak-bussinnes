"""Cloud AI provider backed by the Gemini API.

Cloud use is opt-in: :class:`~app.ai.routing.model_router.ModelRouter` will not
call this provider unless cloud data sharing has been explicitly enabled by an
administrator, and only aggregated business figures are ever sent.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.ai.routing.credentials import CredentialStore
from app.ai.routing.provider import ProviderReply, ProviderStatus
from app.core.logging_config import get_logger

logger = get_logger("ai.gemini")


class GeminiProvider:
    """Gemini through the official ``google-genai`` client."""

    name = "gemini"
    kind = "cloud"

    def __init__(
        self,
        *,
        model: str = "gemini-2.0-flash",
        credentials: CredentialStore | None = None,
        client_factory: Callable[..., Any] | None = None,
        timeout: float = 25.0,
    ) -> None:
        self.model = model
        self._credentials = credentials or CredentialStore()
        self._client_factory = client_factory
        self._timeout = timeout
        self._last_error: str | None = None

    # -- plumbing ----------------------------------------------------------
    def _api_key(self) -> str | None:
        return self._credentials.get_api_key("gemini")

    def _client(self, api_key: str):
        if self._client_factory is not None:
            return self._client_factory(api_key=api_key)
        from google import genai

        return genai.Client(api_key=api_key)

    def status(self) -> ProviderStatus:
        if not self._api_key():
            return ProviderStatus(
                self.name,
                self.kind,
                self.model,
                False,
                "No Gemini API key configured (Settings → AI)",
            )
        detail = self._credentials.describe("gemini")
        if self._last_error:
            detail = f"key configured; last error: {self._last_error[:80]}"
        return ProviderStatus(self.name, self.kind, self.model, True, detail)

    def is_available(self) -> bool:
        return bool(self._api_key())

    # -- completion --------------------------------------------------------
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> ProviderReply | None:
        api_key = self._api_key()
        if not api_key or not prompt or not prompt.strip():
            return None

        started = time.perf_counter()
        try:
            from google.genai import types as genai_types

            client = self._client(api_key)
            config = genai_types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json" if json_mode else "text/plain",
                system_instruction=system,
            )
            response = client.models.generate_content(
                model=self.model, contents=prompt, config=config
            )
            text = getattr(response, "text", None) or ""
            if not text.strip():
                logger.warning("Gemini returned an empty response")
                return None
            self._last_error = None
            return ProviderReply(
                text=str(text),
                provider=self.name,
                model=self.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                json_mode=json_mode,
            )
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Gemini completion failed: %s", exc)
            return None
