"""Evidence validation.

A finding is only promoted to "verified" when it cites a recognised data source,
carries a value and states its reporting period. Everything else is kept, but
labelled honestly so the decision cannot present an unverified claim as fact.
"""

from __future__ import annotations

from app.ai.schemas.agent_schema import Finding
from app.ai.schemas.collaboration_schema import AgentCollaborationResult, ValidationOutcome
from app.core.constants import EvidenceStatus
from app.core.logging_config import get_logger

logger = get_logger("ai.collaboration.evidence")

PLACEHOLDER_VALUES = {"", "n/a", "na", "none", "null", "-", "—", "unknown"}


class EvidenceValidator:
    """Deterministic validation of agent evidence."""

    def __init__(self, *, known_sources: set[str], require_period: bool = True) -> None:
        self._known_sources = {source for source in known_sources if source}
        self._require_period = require_period

    def known_source(self, source: str) -> bool:
        return source in self._known_sources

    def validate_finding(self, finding: Finding) -> ValidationOutcome:
        issues: list[str] = []
        verified_sources: list[str] = []

        if not finding.evidence:
            return ValidationOutcome(
                finding=finding,
                status=EvidenceStatus.UNVERIFIED,
                issues=["no evidence attached"],
            )

        for item in finding.evidence:
            if not self.known_source(item.source):
                issues.append(f"unrecognised data source '{item.source}'")
                continue
            if str(item.value).strip().lower() in PLACEHOLDER_VALUES:
                issues.append(f"source '{item.source}' reported no value for '{item.metric}'")
                continue
            if self._require_period and not item.period and not finding.reporting_period:
                issues.append(f"no reporting period for '{item.metric}'")
                continue
            verified_sources.append(item.source)

        if not verified_sources:
            status = EvidenceStatus.UNVERIFIED
        elif issues:
            status = EvidenceStatus.PARTIAL
        else:
            status = EvidenceStatus.VERIFIED

        return ValidationOutcome(
            finding=finding,
            status=status,
            issues=issues,
            verified_sources=sorted(set(verified_sources)),
        )

    def validate_result(
        self, result: AgentCollaborationResult
    ) -> tuple[list[ValidationOutcome], str]:
        """Validate every finding in a result and return an overall status."""
        outcomes = [self.validate_finding(finding) for finding in result.findings]
        if not outcomes:
            return [], EvidenceStatus.UNVERIFIED

        statuses = {outcome.status for outcome in outcomes}
        if statuses == {EvidenceStatus.VERIFIED}:
            overall = EvidenceStatus.VERIFIED
        elif EvidenceStatus.VERIFIED in statuses or EvidenceStatus.PARTIAL in statuses:
            overall = EvidenceStatus.PARTIAL
        else:
            overall = EvidenceStatus.UNVERIFIED

        if result.limitations:
            overall = EvidenceStatus.PARTIAL if overall == EvidenceStatus.VERIFIED else overall
        return outcomes, overall

    def verified_only(self, outcomes: list[ValidationOutcome]) -> list[Finding]:
        return [
            outcome.finding
            for outcome in outcomes
            if outcome.status == EvidenceStatus.VERIFIED
        ]
