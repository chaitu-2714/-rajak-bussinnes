"""Unit tests: hybrid model routing and deterministic fallback."""

from __future__ import annotations

import pytest

from app.ai.routing.fallback_provider import FallbackProvider
from app.ai.routing.model_router import ModelRouter, ProviderSetting
from app.ai.routing.provider import ProviderReply, ProviderStatus


class FakeProvider:
    def __init__(
        self,
        name: str,
        kind: str = "local",
        *,
        available: bool = True,
        text: str | None = '{"intent": "GET_REVENUE", "confidence": 0.9}',
    ) -> None:
        self.name = name
        self.kind = kind
        self.model = f"{name}-model"
        self._available = available
        self._text = text
        self.calls = 0

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, self.kind, self.model, self._available, "fake")

    def is_available(self) -> bool:
        return self._available

    def complete(self, prompt, *, system=None, json_mode=False, timeout=None):
        self.calls += 1
        if not self._available or self._text is None:
            return None
        return ProviderReply(text=self._text, provider=self.name, model=self.model, json_mode=json_mode)


def _router(providers, *, cloud: bool = False, preferred: str = "auto", settings=None):
    return ModelRouter(
        providers=providers,
        settings=settings
        or [
            ProviderSetting("ollama", "llama3.2", True, 10),
            ProviderSetting("gemini", "gemini-2.0-flash", True, 20),
        ],
        cloud_sharing_enabled=cloud,
        preferred_provider=preferred,
    )


def test_ollama_is_used_when_available() -> None:
    ollama = FakeProvider("ollama")
    gemini = FakeProvider("gemini", "cloud")
    router = _router([ollama, gemini], cloud=True)
    reply = router.classify("show revenue")
    assert reply is not None
    assert reply.provider == "ollama"
    assert gemini.calls == 0


def test_gemini_is_skipped_while_cloud_sharing_is_disabled() -> None:
    ollama = FakeProvider("ollama", available=False)
    gemini = FakeProvider("gemini", "cloud")
    router = _router([ollama, gemini], cloud=False)
    assert router.classify("show revenue") is None
    assert gemini.calls == 0
    statuses = {status.name: status for status in router.statuses()}
    assert statuses["gemini"].available is False
    assert "Cloud sharing is disabled" in statuses["gemini"].detail


def test_gemini_is_used_when_cloud_sharing_is_enabled_and_ollama_is_down() -> None:
    ollama = FakeProvider("ollama", available=False)
    gemini = FakeProvider("gemini", "cloud")
    router = _router([ollama, gemini], cloud=True)
    reply = router.classify("show revenue")
    assert reply is not None
    assert reply.provider == "gemini"


def test_preferred_provider_wins() -> None:
    ollama = FakeProvider("ollama")
    gemini = FakeProvider("gemini", "cloud")
    router = _router([ollama, gemini], cloud=True, preferred="gemini")
    reply = router.classify("show revenue")
    assert reply is not None
    assert reply.provider == "gemini"


def test_priority_order_is_respected() -> None:
    ollama = FakeProvider("ollama")
    gemini = FakeProvider("gemini", "cloud")
    router = _router(
        [ollama, gemini],
        cloud=True,
        settings=[
            ProviderSetting("ollama", "llama3.2", True, 50),
            ProviderSetting("gemini", "gemini-2.0-flash", True, 5),
        ],
    )
    reply = router.classify("show revenue")
    assert reply is not None
    assert reply.provider == "gemini"


def test_disabled_provider_is_skipped() -> None:
    ollama = FakeProvider("ollama")
    gemini = FakeProvider("gemini", "cloud")
    router = _router(
        [ollama, gemini],
        cloud=True,
        settings=[
            ProviderSetting("ollama", "llama3.2", False, 10),
            ProviderSetting("gemini", "gemini-2.0-flash", True, 20),
        ],
    )
    reply = router.classify("show revenue")
    assert reply is not None
    assert reply.provider == "gemini"
    assert ollama.calls == 0


def test_both_providers_unavailable_returns_none() -> None:
    router = _router(
        [FakeProvider("ollama", available=False), FakeProvider("gemini", "cloud", available=False)],
        cloud=True,
    )
    assert router.classify("show revenue") is None
    assert router.active_provider_name() == "fallback"


def test_empty_model_reply_is_treated_as_unavailable() -> None:
    router = _router([FakeProvider("ollama", text="   "), FakeProvider("gemini", "cloud", available=False)])
    assert router.classify("show revenue") is None


def test_statuses_always_include_the_fallback() -> None:
    router = _router([FakeProvider("ollama", available=False)])
    names = [status.name for status in router.statuses()]
    assert names == ["ollama", "fallback"]
    fallback = next(status for status in router.statuses() if status.name == "fallback")
    assert fallback.available is True
    assert fallback.kind == "offline"


def test_health_payload_shape() -> None:
    router = _router([FakeProvider("ollama", available=False)])
    health = router.health()
    assert health["active"] == "fallback"
    assert health["cloud_enabled"] is False
    assert len(health["providers"]) == 2


def test_fallback_narrator_composes_from_verified_summaries() -> None:
    narrator = FallbackProvider()
    text = narrator.compose(
        intent_label="Get Revenue",
        step_summaries=["Revenue for this month is 3,120.00", "Refunds 0.00"],
        business_name="Patnaik Traders",
        warnings=["Stock is low for Assam Tea"],
    )
    assert "Get Revenue for Patnaik Traders" in text
    assert "3,120.00" in text
    assert "⚠" in text


def test_fallback_narrator_handles_no_data() -> None:
    narrator = FallbackProvider()
    text = narrator.compose(
        intent_label="Get Revenue", step_summaries=[], business_name="Shop"
    )
    assert "No business records" in text


def test_prompt_is_length_capped() -> None:
    seen: list[str] = []

    class CapturingProvider(FakeProvider):
        def complete(self, prompt, *, system=None, json_mode=False, timeout=None):
            seen.append(prompt)
            return super().complete(prompt, system=system, json_mode=json_mode)

    router = ModelRouter(
        providers=[CapturingProvider("ollama")],
        settings=[ProviderSetting("ollama", "llama3.2", True, 10)],
        max_prompt_chars=100,
    )
    router.classify("x" * 5000)
    assert seen and len(seen[0]) <= 100
