"""Hybrid AI router: local-first provider selection with explicit policies.

Extends the Phase 3 ``ModelRouter`` rather than replacing it: the same provider
objects, health checks and cloud-sharing gate, plus task-based routing, offline
mode, usage recording and a guarantee that a cloud provider is never used when a
policy forbids it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.routing.model_router import ModelRouter
from app.ai.routing.provider import ProviderReply, ProviderStatus
from app.core.constants import AITaskKind, RoutingPolicy
from app.core.logging_config import get_logger
from app.database.models.knowledge import HybridAIUsage
from app.utils.date_utils import utcnow

logger = get_logger("ai.hybrid_router")

# Tasks whose content must stay on the machine.
LOCAL_ONLY_TASKS = set(AITaskKind.LOCAL_ONLY)


@dataclass(frozen=True)
class RouteDecision:
    task: str
    policy: str
    provider: str
    model: str
    allowed: bool
    reason: str
    cloud_permitted: bool


class HybridAIModelRouter:
    """Chooses a provider for a task, honouring the configured policy."""

    def __init__(
        self,
        base_router: ModelRouter,
        *,
        session_factory: sessionmaker[Session] | None = None,
        policy: str = RoutingPolicy.LOCAL_FIRST,
        offline_mode: bool = False,
        max_retries: int = 1,
    ) -> None:
        self._base = base_router
        self._session_factory = session_factory
        self._policy = policy if policy in RoutingPolicy.ALL else RoutingPolicy.LOCAL_FIRST
        self._offline_mode = offline_mode
        self._max_retries = max(1, max_retries)
        self._governance = None

    def attach_governance(self, governance: Any, *, redactor: Any | None = None) -> None:
        """Enable Phase 9 data classification before any cloud request."""
        self._governance = governance
        self._redactor = redactor

    # -- configuration -----------------------------------------------------
    @property
    def policy(self) -> str:
        return self._policy

    @property
    def offline_mode(self) -> bool:
        return self._offline_mode

    def configure(
        self,
        *,
        policy: str | None = None,
        offline_mode: bool | None = None,
        cloud_sharing_enabled: bool | None = None,
    ) -> None:
        if policy is not None:
            if policy not in RoutingPolicy.ALL:
                raise ValueError(f"'{policy}' is not a supported routing policy")
            self._policy = policy
        if offline_mode is not None:
            self._offline_mode = bool(offline_mode)
        if cloud_sharing_enabled is not None:
            self._base.configure(cloud_sharing_enabled=cloud_sharing_enabled)

    def configuration(self) -> dict[str, Any]:
        return {
            "policy": self._policy,
            "offline_mode": self._offline_mode,
            "cloud_sharing_enabled": self._base.cloud_sharing_enabled,
            "preferred_provider": self._base.preferred_provider,
            "providers": [status.as_dict() for status in self.get_provider_status()],
        }

    # -- health ------------------------------------------------------------
    def get_available_providers(self) -> list[str]:
        names: list[str] = []
        for provider in self._base.ordered_providers():
            if provider.kind == "cloud" and self._cloud_blocked():
                continue
            names.append(provider.name)
        names.append("deterministic")
        return names

    def check_provider_health(self) -> dict[str, dict[str, Any]]:
        health: dict[str, dict[str, Any]] = {}
        for provider in self._base._providers:  # noqa: SLF001 - same package boundary
            status: ProviderStatus = provider.status()
            health[provider.name] = {
                "available": status.available,
                "kind": status.kind,
                "model": status.model,
                "detail": status.detail,
                "enabled": self._base._enabled(provider),  # noqa: SLF001
                "blocked_by_policy": provider.kind == "cloud" and self._cloud_blocked(),
            }
        return health

    def get_provider_status(self) -> list[ProviderStatus]:
        return self._base.statuses()

    def get_model_capabilities(self) -> dict[str, Any]:
        return {
            "providers": [
                {
                    "provider": status.name,
                    "kind": status.kind,
                    "model": status.model,
                    "available": status.available,
                    "capabilities": (
                        ["completion", "json", "summarise"]
                        if status.kind == "cloud"
                        else ["completion", "json", "summarise", "offline"]
                    ),
                }
                for status in self.get_provider_status()
            ],
            "local_only_tasks": sorted(LOCAL_ONLY_TASKS),
            "policy": self._policy,
        }

    # -- routing -----------------------------------------------------------
    def _cloud_blocked(self) -> bool:
        if self._offline_mode:
            return True
        if self._policy == RoutingPolicy.OFFLINE:
            return True
        return not self._base.cloud_sharing_enabled

    def select_provider(self, task: str = AITaskKind.NARRATE) -> RouteDecision:
        task = (task or AITaskKind.NARRATE).upper()
        cloud_permitted = not self._cloud_blocked()
        available = self.get_available_providers()

        if self._offline_mode or self._policy == RoutingPolicy.OFFLINE:
            if "ollama" in available:
                return RouteDecision(task, self._policy, "ollama", self._model_name("ollama"),
                                     True, "Offline mode: local provider only.", False)
            return RouteDecision(task, self._policy, "deterministic", "deterministic",
                                 True, "Offline mode: no local model is available, so "
                                 "deterministic output is used.", False)

        if task in LOCAL_ONLY_TASKS and self._policy != RoutingPolicy.CLOUD_FIRST:
            if "ollama" in available:
                return RouteDecision(task, self._policy, "ollama", self._model_name("ollama"),
                                     True, "This task is answered locally by policy.", cloud_permitted)
            return RouteDecision(task, self._policy, "deterministic", "deterministic", True,
                                 "No local model is available; deterministic output is used.",
                                 cloud_permitted)

        if self._policy == RoutingPolicy.CLOUD_FIRST and cloud_permitted and "gemini" in available:
            return RouteDecision(task, self._policy, "gemini", self._model_name("gemini"), True,
                                 "Cloud-first policy with cloud sharing enabled.", True)

        if task in LOCAL_ONLY_TASKS and not cloud_permitted:
            return RouteDecision(task, self._policy, "deterministic", "deterministic", True,
                                 "Cloud is not permitted and no local model is available.",
                                 False)

        if "ollama" in available:
            return RouteDecision(task, self._policy, "ollama", self._model_name("ollama"), True,
                                 "Local provider preferred.", cloud_permitted)
        if cloud_permitted and "gemini" in available:
            return RouteDecision(task, self._policy, "gemini", self._model_name("gemini"), True,
                                 "No local model is available; cloud is permitted.", True)
        return RouteDecision(task, self._policy, "deterministic", "deterministic", True,
                             "No AI provider is available; deterministic output is used.",
                             cloud_permitted)

    def _model_name(self, provider: str) -> str:
        for status in self.get_provider_status():
            if status.name == provider:
                return status.model
        return "unknown"

    def estimate_request_requirements(self, prompt: str, task: str = AITaskKind.NARRATE) -> dict:
        prompt = prompt or ""
        return {
            "prompt_chars": len(prompt),
            "estimated_tokens": max(1, len(prompt) // 4),
            "task": task,
            "needs_cloud": task == AITaskKind.CLOUD_ONLY,
            "local_only": task in LOCAL_ONLY_TASKS,
        }

    # -- execution ---------------------------------------------------------
    def route_task(
        self,
        prompt: str,
        *,
        task: str = AITaskKind.NARRATE,
        system: str | None = None,
        json_mode: bool = False,
        allow_fallback: bool = True,
    ) -> tuple[ProviderReply | None, RouteDecision]:
        decision = self.select_provider(task)
        requirements = self.estimate_request_requirements(prompt, task)
        started = utcnow()

        if decision.provider == "deterministic":
            self.record_model_usage(
                task=task, decision=decision, success=True, fallback_used=True,
                prompt_chars=requirements["prompt_chars"],
                latency_ms=0, note="deterministic fallback",
            )
            return None, decision

        if decision.provider == "gemini" and not decision.cloud_permitted:
            # A privacy policy must never be silently bypassed.
            logger.warning("Cloud provider requested but blocked by policy")
            self.record_model_usage(
                task=task, decision=decision, success=False, fallback_used=True,
                prompt_chars=requirements["prompt_chars"], latency_ms=0,
                note="cloud blocked by policy",
            )
            if allow_fallback and decision.task not in ():
                return None, decision
            return None, decision

        # Phase 9: nothing confidential leaves the machine without a decision.
        if decision.provider == "gemini":
            governed = self._apply_governance(prompt, task=task)
            if governed is None:
                self.record_model_usage(
                    task=task, decision=decision, success=False, fallback_used=True,
                    prompt_chars=requirements["prompt_chars"], latency_ms=0,
                    note="blocked by the AI data governance policy",
                )
                return None, decision
            prompt = governed

        reply = self._execute_with_retries(
            decision, prompt, system=system, json_mode=json_mode
        )
        elapsed = int((utcnow() - started).total_seconds() * 1000)
        if reply is not None:
            self.record_model_usage(
                task=task, decision=decision, success=True, fallback_used=False,
                prompt_chars=requirements["prompt_chars"], latency_ms=elapsed,
            )
            return reply, decision

        if allow_fallback:
            self.record_model_usage(
                task=task, decision=decision, success=False, fallback_used=True,
                prompt_chars=requirements["prompt_chars"], latency_ms=elapsed,
                note="provider returned no usable reply",
            )
        return None, decision

    def _apply_governance(self, prompt: str, *, task: str) -> str | None:
        """Return the (possibly redacted) prompt, or None if cloud is forbidden."""
        governance = getattr(self, "_governance", None)
        if governance is None:
            return prompt
        decision = governance.evaluate_cloud_request(
            prompt,
            provider="gemini",
            cloud_enabled=self._base.cloud_sharing_enabled,
            redactor=getattr(self, "_redactor", None),
        )
        if not decision.allowed:
            logger.warning("Cloud request blocked: %s", decision.reason)
            return None
        return decision.redacted_payload or prompt

    def _execute_with_retries(
        self, decision: RouteDecision, prompt: str, *, system: str | None, json_mode: bool
    ) -> ProviderReply | None:
        for attempt in range(1, self._max_retries + 1):
            try:
                if decision.provider == "ollama":
                    return self.execute_local_model(
                        prompt, model=decision.model, system=system, json_mode=json_mode
                    )
                if decision.provider == "gemini":
                    return self.execute_cloud_model(
                        prompt, model=decision.model, system=system, json_mode=json_mode
                    )
            except Exception as exc:  # noqa: BLE001 - provider failure is data
                logger.warning(
                    "Provider %s failed on attempt %s: %s", decision.provider, attempt, exc
                )
        return None

    def execute_local_model(
        self, prompt: str, *, model: str | None = None, system: str | None = None,
        json_mode: bool = False,
    ) -> ProviderReply | None:
        for provider in self._base._providers:  # noqa: SLF001
            if provider.kind == "local":
                return provider.complete(prompt, system=system, json_mode=json_mode)
        return None

    def execute_cloud_model(
        self, prompt: str, *, model: str | None = None, system: str | None = None,
        json_mode: bool = False,
    ) -> ProviderReply | None:
        if self._cloud_blocked():
            raise RuntimeError(
                "Cloud providers are disabled by the current routing policy or the "
                "cloud-sharing setting."
            )
        for provider in self._base._providers:  # noqa: SLF001
            if provider.kind == "cloud":
                return provider.complete(prompt, system=system, json_mode=json_mode)
        return None

    def execute_fallback(self, prompt: str, *, reason: str = "") -> ProviderReply:
        return ProviderReply(
            text="", provider="deterministic", model="deterministic", latency_ms=0
        )

    # -- usage -------------------------------------------------------------
    def record_model_usage(
        self,
        *,
        task: str,
        decision: RouteDecision,
        success: bool,
        fallback_used: bool,
        prompt_chars: int,
        latency_ms: int,
        note: str | None = None,
    ) -> None:
        if self._session_factory is None:
            return
        try:
            with self._session_factory() as db:
                db.add(
                    HybridAIUsage(
                        task=task,
                        policy=decision.policy,
                        provider=decision.provider,
                        model=decision.model,
                        success=success,
                        fallback_used=fallback_used,
                        latency_ms=latency_ms,
                        prompt_chars=prompt_chars,
                        note=note,
                    )
                )
                db.commit()
        except Exception:  # noqa: BLE001 - usage logging must never break a request
            logger.exception("Could not record AI usage")

    def usage_summary(self, limit: int = 20) -> list[dict[str, Any]]:
        if self._session_factory is None:
            return []
        with self._session_factory() as db:
            rows = db.scalars(
                select(HybridAIUsage).order_by(HybridAIUsage.id.desc()).limit(limit)
            ).all()
            return [
                {
                    "task": row.task,
                    "policy": row.policy,
                    "provider": row.provider,
                    "model": row.model,
                    "success": row.success,
                    "fallback_used": row.fallback_used,
                    "latency_ms": row.latency_ms,
                    "note": row.note,
                    "created_at": row.created_at,
                }
                for row in rows
            ]
