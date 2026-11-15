"""Local AI provider backed by Ollama.

Ollama runs entirely on the user's machine, so this is the default AI path and
the only one that can work without an internet connection.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.ai.routing.provider import ProviderReply, ProviderStatus
from app.core.logging_config import get_logger

logger = get_logger("ai.ollama")


class OllamaProvider:
    """Talks to a local Ollama server over HTTP."""

    name = "ollama"
    kind = "local"

    def __init__(
        self,
        *,
        model: str = "llama3.2",
        host: str = "http://localhost:11434",
        client_factory: Callable[..., Any] | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.model = model
        self.host = host
        self._client_factory = client_factory
        self._timeout = timeout
        self._last_error: str | None = None
        self._cached_status: ProviderStatus | None = None
        self._status_cache_time: float = 0.0
        self._status_cache_ttl: float = 5.0

    # -- plumbing ----------------------------------------------------------
    def _is_reachable(self, timeout: float = 0.08) -> bool:
        if self._client_factory is not None:
            return True
        try:
            import socket
            import urllib.parse

            parsed = urllib.parse.urlsplit(self.host)
            host = parsed.hostname or "127.0.0.1"
            port = parsed.port or 11434
            target_hosts = ["127.0.0.1"] if host in ("localhost", "127.0.0.1") else [host]
            for target in target_hosts:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(timeout)
                    if sock.connect_ex((target, port)) == 0:
                        return True
            return False
        except Exception:
            return False

    def _client(self):
        if self._client_factory is not None:
            return self._client_factory(host=self.host)
        import ollama

        return ollama.Client(host=self.host)

    def status(self, force: bool = False) -> ProviderStatus:
        now = time.monotonic()
        if (
            not force
            and self._cached_status is not None
            and (now - self._status_cache_time) < self._status_cache_ttl
        ):
            return self._cached_status

        if not self._is_reachable():
            st = ProviderStatus(
                self.name,
                self.kind,
                self.model,
                False,
                "Ollama is not reachable — start it with `ollama serve`",
            )
            self._cached_status = st
            self._status_cache_time = now
            return st

        try:
            client = self._client()
            listing = client.list()
            models = []
            for entry in getattr(listing, "models", None) or listing.get("models", []):
                model_name = getattr(entry, "model", None) or (
                    entry.get("model") if isinstance(entry, dict) else None
                )
                if model_name:
                    models.append(str(model_name))
            self._last_error = None
            detail = (
                f"Ollama reachable at {self.host}; {len(models)} model(s) installed"
                if models
                else f"Ollama reachable at {self.host}; no models installed yet"
            )
            st = ProviderStatus(self.name, self.kind, self.model, True, detail)
        except Exception as exc:  # server not running / not installed
            self._last_error = str(exc)
            st = ProviderStatus(
                self.name,
                self.kind,
                self.model,
                False,
                "Ollama is not reachable — start it with `ollama serve`",
            )
        self._cached_status = st
        self._status_cache_time = now
        return st

    def is_available(self) -> bool:
        return self.status().available

    # -- completion --------------------------------------------------------
    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> ProviderReply | None:
        if not prompt or not prompt.strip():
            return None
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        started = time.perf_counter()
        try:
            client = self._client()
            kwargs: dict[str, Any] = {
                "model": self.model,
                "messages": messages,
                "options": {"temperature": 0.1},
            }
            if json_mode:
                kwargs["format"] = "json"
            response = client.chat(**kwargs)
            text = ""
            message = getattr(response, "message", None) or (
                response.get("message") if isinstance(response, dict) else None
            )
            if message is not None:
                text = getattr(message, "content", None) or (
                    message.get("content") if isinstance(message, dict) else ""
                ) or ""
            if not text:
                logger.warning("Ollama returned an empty response")
                return None
            return ProviderReply(
                text=str(text),
                provider=self.name,
                model=self.model,
                latency_ms=int((time.perf_counter() - started) * 1000),
                json_mode=json_mode,
            )
        except Exception as exc:
            self._last_error = str(exc)
            self._cached_status = None
            self._status_cache_time = 0.0
            logger.warning("Ollama completion failed: %s", exc)
            return None
