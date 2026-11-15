"""AI data governance: classify information and decide what may leave the machine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging_config import get_logger
from app.database.models.security import AIDataGovernancePolicy
from app.security.data_protection.secret_manager import SecretManager

logger = get_logger("security.data_governance")

PUBLIC = "PUBLIC"
INTERNAL = "INTERNAL"
CONFIDENTIAL = "CONFIDENTIAL"
RESTRICTED = "RESTRICTED"
CLASSIFICATIONS = (PUBLIC, INTERNAL, CONFIDENTIAL, RESTRICTED)

# Signals that raise the classification of a payload.
CONFIDENTIAL_SIGNALS = (
    r"\b(invoice|gst|revenue|profit|margin|payroll|salary|balance sheet)\b",
    r"\b(agreement|contract|terms|discount)\b",
    r"\b(customer|phone|email|address|gstin|pan)\b",
)
RESTRICTED_SIGNALS = (
    r"(?i)\b(password|passphrase)\b",
    r"(?i)\b(api[_\- ]?key|secret[_\- ]?key|access[_\- ]?token|bearer)\b",
    r"\bAIza[0-9A-Za-z\-_]{20,}\b",
    r"(?i)\b(otp|totp|mfa secret|recovery code)\b",
    r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",  # card-like number
)

DEFAULT_MATRIX = {
    (PUBLIC, "ollama"): (True, False, False),
    (PUBLIC, "gemini"): (True, False, True),
    (INTERNAL, "ollama"): (True, False, False),
    (INTERNAL, "gemini"): (True, True, True),
    (CONFIDENTIAL, "ollama"): (True, False, False),
    (CONFIDENTIAL, "gemini"): (False, True, True),
    (RESTRICTED, "ollama"): (True, False, False),
    (RESTRICTED, "gemini"): (False, True, True),
}


@dataclass(frozen=True)
class Classification:
    level: str
    reasons: list[str]

    @property
    def is_cloud_eligible(self) -> bool:
        return self.level in (PUBLIC, INTERNAL)


@dataclass(frozen=True)
class CloudDecision:
    allowed: bool
    reason: str
    classification: str
    redacted_payload: str | None = None


class AIDataGovernanceService:
    """Classifies payloads and blocks or redacts cloud requests."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        secret_manager: SecretManager | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._secrets = secret_manager or SecretManager.__new__(SecretManager)  # unused fallback

    # -- defaults ----------------------------------------------------------
    def seed_defaults(self) -> int:
        created = 0
        with self._session_factory() as db:
            existing = {
                (row.classification, row.provider)
                for row in db.scalars(select(AIDataGovernancePolicy)).all()
            }
            for (classification, provider), (allowed, redact, opt_in) in DEFAULT_MATRIX.items():
                if (classification, provider) in existing:
                    continue
                db.add(
                    AIDataGovernancePolicy(
                        classification=classification,
                        provider=provider,
                        allowed=allowed,
                        requires_redaction=redact,
                        requires_opt_in=opt_in,
                        notes=(
                            "Restricted data may never be sent to a cloud provider."
                            if classification == RESTRICTED and provider != "ollama"
                            else "Confidential data stays local unless an administrator "
                            "explicitly allows it."
                            if classification == CONFIDENTIAL and provider != "ollama"
                            else ""
                        ),
                    )
                )
                created += 1
            db.commit()
        return created

    def policies(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(AIDataGovernancePolicy).order_by(
                    AIDataGovernancePolicy.classification, AIDataGovernancePolicy.provider
                )
            ).all()
            return [
                {
                    "classification": row.classification,
                    "provider": row.provider,
                    "allowed": row.allowed,
                    "requires_redaction": row.requires_redaction,
                    "requires_opt_in": row.requires_opt_in,
                    "notes": row.notes,
                }
                for row in rows
            ]

    def update_policy(
        self, classification: str, provider: str, *, changes: dict[str, Any]
    ) -> dict[str, Any]:
        if classification == RESTRICTED and provider != "ollama" and changes.get("allowed"):
            raise ValueError(
                "Restricted data can never be allowed to leave the machine, whatever "
                "the setting says"
            )
        with self._session_factory() as db:
            row = db.scalars(
                select(AIDataGovernancePolicy).where(
                    AIDataGovernancePolicy.classification == classification,
                    AIDataGovernancePolicy.provider == provider,
                )
            ).first()
            if row is None:
                row = AIDataGovernancePolicy(classification=classification, provider=provider)
                db.add(row)
            for key in ("allowed", "requires_redaction", "requires_opt_in", "notes"):
                if key in changes:
                    setattr(row, key, changes[key])
            db.commit()
            return {
                "classification": row.classification,
                "provider": row.provider,
                "allowed": row.allowed,
            }

    # -- classification ----------------------------------------------------
    def classify(self, payload: str, *, declared: str | None = None) -> Classification:
        text = payload or ""
        reasons: list[str] = []
        level = declared if declared in CLASSIFICATIONS else INTERNAL

        if any(re.search(pattern, text) for pattern in RESTRICTED_SIGNALS):
            return Classification(RESTRICTED, ["contains credential-like or highly sensitive data"])
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in CONFIDENTIAL_SIGNALS):
            if level in (PUBLIC, INTERNAL):
                level = CONFIDENTIAL
                reasons.append("contains financial, contractual or customer information")
        if level == PUBLIC and len(text) > 400:
            level = INTERNAL
            reasons.append("substantial internal content")
        return Classification(level, reasons or ["no sensitive signal detected"])

    # -- cloud gate --------------------------------------------------------
    def evaluate_cloud_request(
        self,
        payload: str,
        *,
        provider: str,
        declared: str | None = None,
        cloud_enabled: bool,
        redactor: Any | None = None,
    ) -> CloudDecision:
        classification = self.classify(payload, declared=declared)
        if provider == "ollama":
            return CloudDecision(True, "Local provider", classification.level)

        if not cloud_enabled:
            return CloudDecision(
                False, "Cloud data sharing is disabled in the AI settings", classification.level
            )
        if classification.level == RESTRICTED:
            return CloudDecision(
                False,
                "Restricted data must never be sent to a cloud provider",
                classification.level,
            )

        policy = self._policy(classification.level, provider)
        if policy is None or not policy["allowed"]:
            return CloudDecision(
                False,
                f"{classification.level} data is not allowed to be sent to {provider}",
                classification.level,
            )

        redacted = payload
        if policy["requires_redaction"]:
            redacted = (redactor.redact(payload) if redactor else payload)
            if redacted != payload:
                logger.info("Redacted sensitive values before a cloud request")
        return CloudDecision(
            True,
            f"{classification.level} data permitted for {provider}"
            + (" with redaction" if policy["requires_redaction"] else ""),
            classification.level,
            redacted,
        )

    def _policy(self, classification: str, provider: str) -> dict[str, Any] | None:
        with self._session_factory() as db:
            row = db.scalars(
                select(AIDataGovernancePolicy).where(
                    AIDataGovernancePolicy.classification == classification,
                    AIDataGovernancePolicy.provider == provider,
                )
            ).first()
            if row is None:
                return None
            return {
                "allowed": row.allowed,
                "requires_redaction": row.requires_redaction,
                "requires_opt_in": row.requires_opt_in,
            }
