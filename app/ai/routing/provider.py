"""Provider protocol and shared types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderStatus:
    """Health snapshot shown in the AI Command Center."""

    name: str
    kind: str  # local | cloud | offline
    model: str
    available: bool
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind,
            "model": self.model,
            "available": self.available,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ProviderReply:
    """A single completion returned by a provider."""

    text: str
    provider: str
    model: str
    latency_ms: int = 0
    json_mode: bool = False


class AIProvider(Protocol):
    """Anything that can answer a prompt (local, cloud or deterministic)."""

    name: str
    kind: str

    def status(self) -> ProviderStatus: ...

    def is_available(self) -> bool: ...

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> ProviderReply | None: ...
