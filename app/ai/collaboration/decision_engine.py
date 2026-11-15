"""Unified business decision synthesis.

Consolidates validated agent findings, ranks recommendations with transparent
criteria, and states the financial and operational impact. Every number comes
from agent evidence or the shared context; nothing is invented, and an
insufficient-evidence collaboration returns an explicitly inconclusive decision.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.ai.schemas.agent_schema import Evidence, Finding
from app.ai.schemas.collaboration_schema import (
    AgentCollaborationResult,
    ConflictRecord,
    DecisionRecommendation,
    SharedBusinessContext,
    UnifiedDecision,
    ValidationOutcome,
)
from app.core.constants import (
    ConflictStatus,
    EvidenceStatus,
    FindingSeverity,
)
from app.core.logging_config import get_logger
from app.utils.date_utils import utcnow

logger = get_logger("ai.collaboration.decision")

PRIORITY_WEIGHT = {"HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0}
OPPORTUNITY_TYPES = {
    "REVENUE_GROWTH",
    "TOP_PRODUCT",
    "DEMAND_LEVEL",
    "SEGMENTATION",
    "CUSTOMER_VALUE",
    "PROFIT_MARGIN",
}
APPROVAL_TRIGGERS = ("order", "purchase", "reorder", "price", "discount", "hire", "spend")


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}"


class BusinessDecisionEngine:
    """Builds the single decision a collaboration delivers."""

    # -- public API --------------------------------------------------------
    def build(
        self,
        *,
        collaboration_id: str,
        objective: str,
        results: list[AgentCollaborationResult],
        context: SharedBusinessContext,
        conflicts: list[ConflictRecord],
        validations: dict[str, list[ValidationOutcome]],
        failed_tasks: list[str] | None = None,
    ) -> UnifiedDecision:
        failed_tasks = failed_tasks or []
        participants = sorted({result.agent_id for result in results})
        consolidated = self._consolidate_findings(results, validations)
        risks = [f for f in consolidated if FindingSeverity.ORDER.get(f.severity, 0) >= 2]
        opportunities = [f for f in consolidated if f.finding_type in OPPORTUNITY_TYPES]
        recommendations = self._rank_recommendations(
            results=results, conflicts=conflicts, context=context, consolidated=consolidated
        )

        verified_count = sum(
            1
            for outcome_list in validations.values()
            for outcome in outcome_list
            if outcome.status == EvidenceStatus.VERIFIED
        )
        unresolved = [c for c in conflicts if c.status == ConflictStatus.UNRESOLVED]

        status = "FINAL"
        if verified_count == 0:
            status = "INCONCLUSIVE"
        elif unresolved or failed_tasks:
            status = "PARTIAL"

        financial = self._financial_impact(
            context=context, recommendations=recommendations, results=results
        )
        confidence = self._confidence(results=results, unresolved=unresolved, failed=failed_tasks)

        decision = UnifiedDecision(
            collaboration_id=collaboration_id,
            business_objective=objective,
            executive_summary=self._executive_summary(
                objective=objective,
                status=status,
                participants=participants,
                risks=risks,
                recommendations=recommendations,
                financial=financial,
                verified=verified_count,
            ),
            participating_agents=participants,
            consolidated_findings=consolidated,
            identified_risks=risks,
            opportunities=opportunities,
            conflicting_findings=[
                {
                    "conflict_id": conflict.conflict_id,
                    "type": conflict.conflict_type,
                    "agents": conflict.agents,
                    "description": conflict.description,
                    "status": conflict.status,
                    "resolution": conflict.resolution,
                }
                for conflict in conflicts
            ],
            recommended_actions=recommendations,
            financial_impact=financial,
            operational_impact=self._operational_impact(results=results, context=context),
            assumptions=self._assumptions(results=results, context=context),
            evidence_references=self._evidence_references(results=results, consolidated=consolidated),
            approval_requirements=self._approvals(recommendations),
            limitations=self._limitations(
                results=results, conflicts=conflicts, failed=failed_tasks, verified=verified_count
            ),
            status=status,
            confidence=confidence,
            generated_at=utcnow(),
        )
        return decision

    # -- consolidation -----------------------------------------------------
    def _consolidate_findings(
        self,
        results: list[AgentCollaborationResult],
        validations: dict[str, list[ValidationOutcome]],
    ) -> list[Finding]:
        """De-duplicate findings while keeping every evidence reference."""
        merged: dict[tuple[str, str], Finding] = {}
        evidence_by_key: dict[tuple[str, str], list[Evidence]] = {}

        for result in results:
            outcomes = validations.get(result.task_key, [])
            by_id = {outcome.finding.finding_id: outcome for outcome in outcomes}
            for finding in result.findings:
                outcome = by_id.get(finding.finding_id)
                if outcome is not None and outcome.status == EvidenceStatus.UNVERIFIED:
                    # Keep it, but never let it drive the decision.
                    continue
                key = (finding.finding_type, finding.description.strip().lower()[:100])
                existing = merged.get(key)
                if existing is None:
                    merged[key] = finding.model_copy(deep=True)
                    evidence_by_key[key] = list(finding.evidence)
                else:
                    if FindingSeverity.ORDER.get(finding.severity, 0) > FindingSeverity.ORDER.get(
                        existing.severity, 0
                    ):
                        existing.severity = finding.severity
                    evidence_by_key[key].extend(finding.evidence)

        for key, finding in merged.items():
            unique: list[Evidence] = []
            seen: set[tuple[str, str, str]] = set()
            for item in evidence_by_key[key]:
                signature = (item.source, item.metric, item.value)
                if signature in seen:
                    continue
                seen.add(signature)
                unique.append(item)
            finding.evidence = unique

        return sorted(
            merged.values(),
            key=lambda finding: FindingSeverity.ORDER.get(finding.severity, 0),
            reverse=True,
        )

    # -- recommendations ---------------------------------------------------
    def _rank_recommendations(
        self,
        *,
        results: list[AgentCollaborationResult],
        conflicts: list[ConflictRecord],
        context: SharedBusinessContext,
        consolidated: list[Finding],
    ) -> list[DecisionRecommendation]:
        recommendations: list[DecisionRecommendation] = []
        seen_actions: set[str] = set()

        for result in results:
            for recommendation in result.recommendations:
                signature = recommendation.recommendation.strip().lower()[:80]
                if signature in seen_actions:
                    continue
                seen_actions.add(signature)
                cost = _dec(recommendation.supporting_figures.get("estimated_cost", 0))
                benefit = _dec(recommendation.supporting_figures.get("expected_benefit", 0))
                recommendations.append(
                    DecisionRecommendation(
                        recommendation_id=recommendation.recommendation_id,
                        action=recommendation.recommendation,
                        reason=recommendation.reason,
                        supporting_evidence=[
                            item
                            for finding in result.findings
                            for item in finding.evidence[:1]
                        ][:3],
                        expected_benefit=benefit if benefit > 0 else None,
                        estimated_cost=cost if cost > 0 else None,
                        risk=recommendation.priority,
                        priority=recommendation.priority,
                        required_approvals=self._approvals_for(recommendation.recommendation, cost),
                        missing_information=list(result.limitations),
                        source_agents=[result.agent_id],
                    )
                )

        # Conflict resolutions can add a balanced action of their own.
        for conflict in conflicts:
            resolution = conflict.resolution or {}
            if conflict.status != ConflictStatus.RESOLVED:
                continue
            affordable = resolution.get("affordable_purchases") or []
            if not affordable:
                continue
            action = (
                f"Approve {len(affordable)} purchase(s) worth {resolution.get('committed')} "
                "and defer the rest until cash is available."
            )
            recommendations.append(
                DecisionRecommendation(
                    recommendation_id=f"rec-conflict-{conflict.conflict_id[-6:]}",
                    action=action,
                    reason=resolution.get("explanation", "Budget-constrained resolution."),
                    estimated_cost=_dec(resolution.get("committed", 0)),
                    risk="MEDIUM",
                    priority="HIGH",
                    required_approvals=["finance.approve", "purchase_orders.create"],
                    missing_information=[],
                    source_agents=list(conflict.agents),
                )
            )

        evidence_quality = {finding.finding_type: len(finding.evidence) for finding in consolidated}
        for recommendation in recommendations:
            recommendation.score = self._score(
                recommendation, context=context, evidence_quality=evidence_quality
            )

        return sorted(recommendations, key=lambda item: item.score, reverse=True)

    def _score(
        self,
        recommendation: DecisionRecommendation,
        *,
        context: SharedBusinessContext,
        evidence_quality: dict[str, int],
    ) -> float:
        """Transparent ranking: impact, feasibility, urgency, evidence, risk."""
        score = PRIORITY_WEIGHT.get(recommendation.priority, 2.0)
        if recommendation.estimated_cost:
            if context.available_budget and recommendation.estimated_cost <= context.available_budget:
                score += 1.0  # financially feasible
            elif context.available_budget and recommendation.estimated_cost > context.available_budget:
                score -= 1.0  # not affordable today
        if recommendation.supporting_evidence:
            score += min(len(recommendation.supporting_evidence), 3) * 0.4
        if recommendation.expected_benefit:
            score += 0.5
        if recommendation.risk == "HIGH":
            score -= 0.3
        if recommendation.missing_information:
            score -= 0.2
        if evidence_quality:
            score += 0.0
        return round(score, 3)

    # -- impact ------------------------------------------------------------
    def _financial_impact(
        self,
        *,
        context: SharedBusinessContext,
        recommendations: list[DecisionRecommendation],
        results: list[AgentCollaborationResult],
    ) -> dict[str, str]:
        planned_cost = sum(
            (rec.estimated_cost for rec in recommendations if rec.estimated_cost),
            Decimal("0.00"),
        )
        benefit = sum(
            (rec.expected_benefit for rec in recommendations if rec.expected_benefit),
            Decimal("0.00"),
        )
        finance = next((r for r in results if r.agent_id == "finance_agent"), None)
        impact = {
            "revenue": context.financial_context.get("revenue", "not reported"),
            "operating_expenses": context.financial_context.get("operating_expenses", "not reported"),
            "net_profit": context.financial_context.get("net_profit", "not reported"),
            "cash_received": context.financial_context.get("cash_received", "not reported"),
            "outstanding_receivables": context.financial_context.get(
                "outstanding_receivables", "not reported"
            ),
            "available_budget": _money(context.available_budget),
            "planned_spend": _money(planned_cost),
            "calculable_benefit": _money(benefit),
            "headroom_after_plan": _money(context.available_budget - planned_cost),
        }
        if finance is not None and finance.metrics.get("net_profit"):
            impact["net_profit"] = str(finance.metrics["net_profit"])
        impact["basis"] = (
            "Figures are taken from recorded transactions and agent metrics; planned spend and "
            "benefit are estimates derived from those figures, not guaranteed outcomes."
        )
        return impact

    def _operational_impact(
        self, *, results: list[AgentCollaborationResult], context: SharedBusinessContext
    ) -> list[str]:
        lines: list[str] = []
        for result in results:
            metrics = result.metrics or {}
            if result.agent_id == "inventory_agent" and metrics.get("low_stock_count"):
                lines.append(f"{metrics['low_stock_count']} product(s) at or below minimum stock.")
            if result.agent_id == "sales_agent" and metrics.get("pending_orders"):
                lines.append(f"{metrics['pending_orders']} order(s) still open.")
            if result.agent_id == "customer_agent" and metrics.get("inactive_customers"):
                lines.append(
                    f"{metrics['inactive_customers']} customer(s) inactive beyond "
                    f"{metrics.get('inactive_threshold_days', 90)} days."
                )
            if result.agent_id == "finance_agent" and metrics.get("unpaid_invoices"):
                lines.append(f"{metrics['unpaid_invoices']} unpaid invoice(s) to collect.")
        if context.inventory_context.get("low_stock_products"):
            lines.append(
                f"{context.inventory_context['low_stock_products']} low-stock product(s) in the "
                "shared context."
            )
        return lines

    def _assumptions(
        self, *, results: list[AgentCollaborationResult], context: SharedBusinessContext
    ) -> list[str]:
        assumptions: list[str] = []
        for result in results:
            assumptions.extend(result.assumptions)
        assumptions.extend(context.constraints)
        assumptions.append(
            "Analysis uses recorded transactions only; forecast or simulated values are labelled "
            "as hypothetical."
        )
        return sorted(set(assumptions))

    def _evidence_references(
        self, *, results: list[AgentCollaborationResult], consolidated: list[Finding]
    ) -> list[Evidence]:
        references: list[Evidence] = []
        seen: set[tuple[str, str, str]] = set()
        for finding in consolidated:
            for item in finding.evidence:
                signature = (item.source, item.metric, item.value)
                if signature in seen:
                    continue
                seen.add(signature)
                references.append(item)
        return references

    def _approvals(self, recommendations: list[DecisionRecommendation]) -> list[str]:
        approvals: set[str] = set()
        for recommendation in recommendations:
            approvals.update(recommendation.required_approvals)
        return sorted(approvals)

    def _approvals_for(self, action: str, cost: Decimal) -> list[str]:
        text = action.lower()
        required: set[str] = set()
        if cost > 0 or any(trigger in text for trigger in APPROVAL_TRIGGERS):
            required.add("finance.approve")
        if any(trigger in text for trigger in ("order", "purchase", "reorder", "supplier")):
            required.add("purchase_orders.create")
        if "price" in text or "discount" in text:
            required.add("sales.update")
        return sorted(required)

    def _limitations(
        self,
        *,
        results: list[AgentCollaborationResult],
        conflicts: list[ConflictRecord],
        failed: list[str],
        verified: int,
    ) -> list[str]:
        limitations: list[str] = []
        for result in results:
            limitations.extend(result.limitations)
        for conflict in conflicts:
            if conflict.status == ConflictStatus.UNRESOLVED:
                limitations.append(f"Unresolved {conflict.conflict_type}: {conflict.description}")
        if failed:
            limitations.append(f"Tasks that did not complete: {', '.join(sorted(failed))}")
        if verified == 0:
            limitations.append("No finding could be verified against a recognised data source.")
        return sorted(set(limitations))

    def _confidence(
        self,
        *,
        results: list[AgentCollaborationResult],
        unresolved: list[ConflictRecord],
        failed: list[str],
    ) -> float:
        if not results:
            return 0.05
        weights = [max(len(result.findings), 1) for result in results]
        weighted = sum(result.confidence * weight for result, weight in zip(results, weights))
        score = weighted / sum(weights)
        score -= 0.05 * len(unresolved)
        score -= 0.10 if failed else 0.0
        return round(max(0.05, min(0.95, score)), 2)

    # -- narrative ---------------------------------------------------------
    def _executive_summary(
        self,
        *,
        objective: str,
        status: str,
        participants: list[str],
        risks: list[Finding],
        recommendations: list[DecisionRecommendation],
        financial: dict[str, str],
        verified: int,
    ) -> str:
        parts = [
            f"Objective: {objective}.",
            f"{len(participants)} agent(s) contributed {verified} verified finding(s).",
        ]
        if financial.get("revenue") not in (None, "not reported"):
            parts.append(
                f"Revenue {financial['revenue']}, net profit {financial.get('net_profit', 'n/a')}, "
                f"available cash {financial.get('available_budget', 'n/a')}."
            )
        if risks:
            parts.append(f"Top risk: {risks[0].description}")
        if recommendations:
            parts.append(f"Priority action: {recommendations[0].action}")
        if status != "FINAL":
            parts.append(
                f"Decision status is {status} — see limitations before acting on it."
            )
        return " ".join(parts)
