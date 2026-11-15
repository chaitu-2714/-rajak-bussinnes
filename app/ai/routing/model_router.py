"""Hybrid model router: local Ollama, cloud Gemini, deterministic fallback.

Routing rules
-------------
1. the administrator's preferred provider (if configured and usable);
2. otherwise providers ordered by their configured priority;
3. cloud providers are skipped unless cloud data sharing is explicitly enabled;
4. if nothing is reachable the deterministic provider answers.

The router never raises: a failing provider returns ``None`` so the caller can
fall back, which is what keeps the application working fully offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.ai.routing.credentials import CredentialStore
from app.ai.routing.fallback_provider import FallbackProvider
from app.ai.routing.gemini_provider import GeminiProvider
from app.ai.routing.ollama_provider import OllamaProvider
from app.ai.routing.provider import AIProvider, ProviderReply, ProviderStatus
from app.core.constants import AIProviderName
from app.core.logging_config import get_logger

logger = get_logger("ai.router")


@dataclass
class ProviderSetting:
    """Persisted provider configuration (mirrors ``ai_model_settings``)."""

    provider: str
    model_name: str
    is_enabled: bool = True
    priority: int = 100
    configuration: dict[str, Any] = field(default_factory=dict)


DEFAULT_PROVIDER_SETTINGS: tuple[ProviderSetting, ...] = (
    ProviderSetting(AIProviderName.OLLAMA, "llama3.2", True, 10),
    ProviderSetting(AIProviderName.GEMINI, "gemini-2.0-flash", True, 20),
)


class ModelRouter:
    """Chooses which AI provider answers a request."""

    def __init__(
        self,
        *,
        credentials: CredentialStore | None = None,
        providers: list[AIProvider] | None = None,
        settings: list[ProviderSetting] | None = None,
        cloud_sharing_enabled: bool = False,
        preferred_provider: str = "auto",
        max_prompt_chars: int = 4000,
    ) -> None:
        self._credentials = credentials or CredentialStore()
        self._settings = list(settings or DEFAULT_PROVIDER_SETTINGS)
        self._cloud_sharing_enabled = cloud_sharing_enabled
        self._preferred_provider = preferred_provider or "auto"
        self._max_prompt_chars = max_prompt_chars
        self._fallback = FallbackProvider()

        if providers is not None:
            self._providers: list[AIProvider] = list(providers)
        else:
            self._providers = [
                OllamaProvider(model=self._model_for(AIProviderName.OLLAMA)),
                GeminiProvider(
                    model=self._model_for(AIProviderName.GEMINI), credentials=self._credentials
                ),
            ]

    # -- configuration -----------------------------------------------------
    def _model_for(self, provider: str) -> str:
        for setting in self._settings:
            if setting.provider == provider:
                return setting.model_name
        return "unknown"

    def configure(
        self,
        *,
        settings: list[ProviderSetting] | None = None,
        cloud_sharing_enabled: bool | None = None,
        preferred_provider: str | None = None,
    ) -> None:
        if settings is not None:
            self._settings = list(settings)
            for provider in self._providers:
                provider.model = self._model_for(provider.name)  # type: ignore[attr-defined]
        if cloud_sharing_enabled is not None:
            self._cloud_sharing_enabled = bool(cloud_sharing_enabled)
        if preferred_provider is not None:
            self._preferred_provider = preferred_provider

    @property
    def cloud_sharing_enabled(self) -> bool:
        return self._cloud_sharing_enabled

    @property
    def preferred_provider(self) -> str:
        return self._preferred_provider

    def _setting(self, name: str) -> ProviderSetting | None:
        return next((setting for setting in self._settings if setting.provider == name), None)

    def _enabled(self, provider: AIProvider) -> bool:
        setting = self._setting(provider.name)
        if setting is not None and not setting.is_enabled:
            return False
        if provider.kind == "cloud" and not self._cloud_sharing_enabled:
            return False
        return True

    def _priority(self, name: str) -> int:
        setting = self._setting(name)
        return setting.priority if setting else 100

    def ordered_providers(self) -> list[AIProvider]:
        """Usable providers in the order they should be tried."""
        candidates = [provider for provider in self._providers if self._enabled(provider)]
        if self._preferred_provider in (AIProviderName.OLLAMA, AIProviderName.GEMINI):
            candidates.sort(
                key=lambda provider: (
                    provider.name != self._preferred_provider,
                    self._priority(provider.name),
                )
            )
        else:
            candidates.sort(key=lambda provider: self._priority(provider.name))
        return [provider for provider in candidates if provider.is_available()]

    # -- status ------------------------------------------------------------
    def statuses(self) -> list[ProviderStatus]:
        statuses: list[ProviderStatus] = []
        for provider in self._providers:
            status = provider.status()
            if provider.kind == "cloud" and not self._cloud_sharing_enabled:
                status = ProviderStatus(
                    status.name,
                    status.kind,
                    status.model,
                    False,
                    "Cloud sharing is disabled — enable it in AI settings to use Gemini",
                )
            statuses.append(status)
        statuses.append(self._fallback.status())
        return statuses

    def available_provider_names(self) -> list[str]:
        return [provider.name for provider in self.ordered_providers()]

    def active_provider_name(self) -> str:
        ordered = self.ordered_providers()
        return ordered[0].name if ordered else self._fallback.name

    @property
    def narrator(self) -> FallbackProvider:
        return self._fallback

    # -- inference ---------------------------------------------------------
    def classify(self, prompt: str) -> ProviderReply | None:
        """Ask the first usable model to classify an intent."""
        return self._complete(prompt, json_mode=True, system=_CLASSIFIER_SYSTEM)

    def explain(self, prompt: str, *, system: str | None = None) -> ProviderReply | None:
        """Ask the first usable model to explain verified results."""
        return self._complete(prompt, json_mode=False, system=system or _NARRATOR_SYSTEM)

    def _complete(
        self, prompt: str, *, json_mode: bool, system: str
    ) -> ProviderReply | None:
        prompt = (prompt or "")[: self._max_prompt_chars]
        for provider in self.ordered_providers():
            reply = provider.complete(prompt, system=system, json_mode=json_mode)
            if reply is not None and reply.text.strip():
                logger.info(
                    "Provider %s answered in %sms", provider.name, reply.latency_ms
                )
                return reply
            logger.debug("Provider %s produced no usable reply", provider.name)
        return None

    def health(self) -> dict[str, Any]:
        statuses = self.statuses()
        return {
            "providers": [status.as_dict() for status in statuses],
            "active": self.active_provider_name(),
            "cloud_enabled": self._cloud_sharing_enabled,
            "preferred": self._preferred_provider,
        }


_CLASSIFIER_SYSTEM = (
    "You are an intent classifier for a business desktop application. "
    "Reply with JSON only, no prose, no markdown. "
    "Never invent intents outside the provided list."
)

_NARRATOR_SYSTEM = (
    "You summarise verified business figures for a shop owner. "
    "Use only the numbers provided. Never invent data. "
    "Be concise: at most 5 short sentences or bullets."
)
