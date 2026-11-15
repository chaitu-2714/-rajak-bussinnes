"""Deterministic fallback provider.

This is not an LLM: it composes a readable answer from the verified tool results
using templates. It is always available, which is what makes the whole AI
Command Center work with no AI provider installed at all.
"""

from __future__ import annotations

from app.ai.routing.provider import ProviderReply, ProviderStatus

MAX_LINES = 6


class FallbackProvider:
    """Offline narrator used when no model is reachable."""

    name = "fallback"
    kind = "offline"

    def __init__(self) -> None:
        self.model = "deterministic"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            self.name,
            self.kind,
            self.model,
            True,
            "Deterministic rules and templates — always available offline",
        )

    def is_available(self) -> bool:
        return True

    def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_mode: bool = False,
        timeout: float | None = None,
    ) -> ProviderReply | None:
        """The fallback never invents prose; callers use :meth:`compose` instead."""
        return None

    # -- narration ---------------------------------------------------------
    def compose(
        self,
        *,
        intent_label: str,
        step_summaries: list[str],
        business_name: str,
        warnings: list[str] | None = None,
    ) -> str:
        """Build a plain answer from verified step summaries."""
        lines: list[str] = []
        if intent_label:
            lines.append(f"{intent_label} for {business_name}:")
        for summary in [item for item in step_summaries if item][:MAX_LINES]:
            lines.append(f"• {summary}")
        for warning in warnings or []:
            lines.append(f"⚠ {warning}")
        if len(lines) <= 1:
            lines.append("No business records matched this request yet.")
        return "\n".join(lines)
