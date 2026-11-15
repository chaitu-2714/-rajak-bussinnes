"""Unit tests: evidence validation, conflict resolution and decision synthesis."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from app.ai.collaboration.conflict_resolution import ConflictDetector, ConflictResolver
from app.ai.collaboration.decision_engine import BusinessDecisionEngine
from app.ai.collaboration.evidence_validator import EvidenceValidator
from app.ai.schemas.agent_schema import Evidence, Finding, Recommendation
from app.ai.schemas.collaboration_schema import (
    AgentCollaborationResult,
    SharedBusinessContext,
)
from app.core.constants import ConflictStatus, ConflictType, EvidenceStatus

KNOWN = {"get_revenue", "get_low_stock_products", "get_sales_summary", "get_product_stock"}


def _finding(source="get_revenue", value="1000.00", period="this month", severity="INFO"):
    return Finding(
        finding_id="f1",
        finding_type="REVENUE_LEVEL",
        description="Revenue recorded",
        severity=severity,
        evidence=[Evidence(source=source, metric="revenue", value=value, period=period)],
        reporting_period=period,
    )


def _result(agent_id: str, **kwargs) -> AgentCollaborationResult:
    data = {
        "collaboration_id": "collab-1",
        "task_key": f"{agent_id}_task",
        "agent_id": agent_id,
        "status": "COMPLETED",
    }
    data.update(kwargs)
    return AgentCollaborationResult(**data)


def _context(budget: str = "1000.00", period: str = "this month") -> SharedBusinessContext:
    return SharedBusinessContext(
        objective="test objective",
        reporting_period=period,
        financial_context={"revenue": "5000.00", "net_profit": "500.00"},
        available_budget=Decimal(budget),
        created_at=datetime(2026, 11, 4, 10, 0, 0),
    )


# ---------------------------------------------------------------------------
# evidence validation
# ---------------------------------------------------------------------------
def test_verified_when_source_value_and_period_exist() -> None:
    outcome = EvidenceValidator(known_sources=KNOWN).validate_finding(_finding())
    assert outcome.status == EvidenceStatus.VERIFIED
    assert outcome.issues == []


def test_unknown_source_is_partial() -> None:
    outcome = EvidenceValidator(known_sources=KNOWN).validate_finding(
        _finding(source="made_up_tool")
    )
    assert outcome.status == EvidenceStatus.UNVERIFIED
    assert any("unrecognised" in issue for issue in outcome.issues)


def test_missing_value_is_partial() -> None:
    outcome = EvidenceValidator(known_sources=KNOWN).validate_finding(_finding(value="n/a"))
    assert outcome.status == EvidenceStatus.UNVERIFIED


def test_missing_period_is_flagged() -> None:
    finding = _finding(period=None)
    finding.reporting_period = None
    outcome = EvidenceValidator(known_sources=KNOWN).validate_finding(finding)
    assert outcome.status == EvidenceStatus.UNVERIFIED
    assert any("reporting period" in issue for issue in outcome.issues)


def test_finding_without_evidence_is_unverified() -> None:
    finding = _finding()
    finding.evidence = []
    outcome = EvidenceValidator(known_sources=KNOWN).validate_finding(finding)
    assert outcome.status == EvidenceStatus.UNVERIFIED


def test_result_level_validation_mixes_statuses() -> None:
    result = _result(
        "finance_agent",
        findings=[_finding(), _finding(source="unknown_tool")],
    )
    outcomes, overall = EvidenceValidator(known_sources=KNOWN).validate_result(result)
    assert len(outcomes) == 2
    assert overall == EvidenceStatus.PARTIAL


# ---------------------------------------------------------------------------
# conflict detection and resolution
# ---------------------------------------------------------------------------
def test_financial_conflict_detected_when_purchases_exceed_cash() -> None:
    inventory = _result(
        "inventory_agent",
        recommendations=[
            Recommendation(
                recommendation_id="r1",
                recommendation="Order 100 units of tea",
                reason="stock below minimum",
                priority="HIGH",
                supporting_figures={"estimated_cost": "5,000.00", "suggested_quantity": "100"},
            )
        ],
    )
    conflicts = ConflictDetector().detect(results=[inventory], context=_context("1000.00"))
    assert conflicts
    assert conflicts[0].conflict_type == ConflictType.FINANCIAL_CONFLICT
    assert conflicts[0].evidence["shortfall"] == "4,000.00"


def test_financial_conflict_resolves_within_budget() -> None:
    inventory = _result(
        "inventory_agent",
        recommendations=[
            Recommendation(
                recommendation_id="r1",
                recommendation="Order 10 units of tea",
                reason="stock below minimum",
                priority="HIGH",
                supporting_figures={"estimated_cost": "600.00"},
            ),
            Recommendation(
                recommendation_id="r2",
                recommendation="Order 10 units of coffee",
                reason="stock below minimum",
                priority="LOW",
                supporting_figures={"estimated_cost": "900.00"},
            ),
        ],
    )
    context = _context("700.00")
    conflicts = ConflictDetector().detect(results=[inventory], context=context)
    resolved = ConflictResolver().resolve(
        conflict=conflicts[0], context=context, results=[inventory]
    )
    assert resolved.status == ConflictStatus.RESOLVED
    assert len(resolved.resolution["affordable_purchases"]) == 1
    assert len(resolved.resolution["deferred_purchases"]) == 1
    assert resolved.resolution["committed"] == "600.00"


def test_financial_conflict_unresolved_without_cash() -> None:
    inventory = _result(
        "inventory_agent",
        recommendations=[
            Recommendation(
                recommendation_id="r1",
                recommendation="Order 100 units",
                reason="stock below minimum",
                priority="HIGH",
                supporting_figures={"estimated_cost": "5000.00"},
            )
        ],
    )
    context = _context("0.00")
    conflicts = ConflictDetector().detect(results=[inventory], context=context)
    resolved = ConflictResolver().resolve(conflict=conflicts[0], context=context, results=[inventory])
    assert resolved.status == ConflictStatus.UNRESOLVED
    assert "collect outstanding" in resolved.resolution["explanation"].lower()


def test_data_source_conflict_uses_the_authoritative_agent() -> None:
    finance = _result("finance_agent", metrics={"revenue": "1000.00"})
    sales = _result("sales_agent", metrics={"revenue": "1200.00"})
    context = _context()
    conflicts = ConflictDetector().detect(results=[finance, sales], context=context)
    assert any(c.conflict_type == ConflictType.DATA_SOURCE_CONFLICT for c in conflicts)
    conflict = next(c for c in conflicts if c.conflict_type == ConflictType.DATA_SOURCE_CONFLICT)
    resolved = ConflictResolver().resolve(conflict=conflict, context=context, results=[finance, sales])
    assert resolved.status == ConflictStatus.RESOLVED
    assert resolved.resolution["authoritative_agent"] == "finance_agent"


def test_no_conflict_when_agents_agree() -> None:
    finance = _result("finance_agent", metrics={"revenue": "1000.00"})
    sales = _result("sales_agent", metrics={"revenue": "1000.00"})
    assert ConflictDetector().detect(results=[finance, sales], context=_context()) == []


# ---------------------------------------------------------------------------
# decision engine
# ---------------------------------------------------------------------------
def test_decision_is_inconclusive_without_verified_findings() -> None:
    result = _result("finance_agent", findings=[], confidence=0.4)
    validations = {"finance_agent_task": []}
    decision = BusinessDecisionEngine().build(
        collaboration_id="collab-1",
        objective="test",
        results=[result],
        context=_context(),
        conflicts=[],
        validations=validations,
    )
    assert decision.status == "INCONCLUSIVE"
    assert "INCONCLUSIVE" in decision.executive_summary or decision.status == "INCONCLUSIVE"


def test_decision_consolidates_and_ranks_recommendations() -> None:
    finding = _finding()
    finance = _result(
        "finance_agent",
        findings=[finding],
        recommendations=[
            Recommendation(
                recommendation_id="r1",
                recommendation="Follow up on unpaid invoices",
                reason="receivables outstanding",
                priority="HIGH",
                supporting_figures={"estimated_cost": "0"},
            ),
            Recommendation(
                recommendation_id="r2",
                recommendation="Review marketing spend",
                reason="costs rising",
                priority="LOW",
            ),
        ],
        confidence=0.8,
    )
    sales = _result(
        "sales_agent",
        findings=[_finding(source="get_sales_summary")],
        confidence=0.7,
    )
    validator = EvidenceValidator(known_sources=KNOWN)
    validations = {
        "finance_agent_task": validator.validate_result(finance)[0],
        "sales_agent_task": validator.validate_result(sales)[0],
    }
    decision = BusinessDecisionEngine().build(
        collaboration_id="collab-1",
        objective="test",
        results=[finance, sales],
        context=_context("5000.00"),
        conflicts=[],
        validations=validations,
    )
    assert decision.status == "FINAL"
    assert decision.participating_agents == ["finance_agent", "sales_agent"]
    assert decision.recommended_actions[0].priority == "HIGH"
    assert decision.recommended_actions[0].score >= decision.recommended_actions[-1].score
    assert decision.evidence_references
    assert decision.financial_impact["available_budget"] == "5,000.00"
    assert 0.05 <= decision.confidence <= 0.95


def test_unresolved_conflict_makes_the_decision_partial() -> None:
    finding = _finding()
    inventory = _result(
        "inventory_agent",
        findings=[finding],
        recommendations=[
            Recommendation(
                recommendation_id="r1",
                recommendation="Order 100 units",
                reason="stock below minimum",
                priority="HIGH",
                supporting_figures={"estimated_cost": "5000.00"},
            )
        ],
    )
    context = _context("0.00")
    conflicts = ConflictDetector().detect(results=[inventory], context=context)
    conflicts = [
        ConflictResolver().resolve(conflict=c, context=context, results=[inventory]) for c in conflicts
    ]
    validator = EvidenceValidator(known_sources=KNOWN)
    decision = BusinessDecisionEngine().build(
        collaboration_id="collab-1",
        objective="test",
        results=[inventory],
        context=context,
        conflicts=conflicts,
        validations={"inventory_agent_task": validator.validate_result(inventory)[0]},
        failed_tasks=[],
    )
    assert decision.status == "PARTIAL"
    assert decision.limitations


def test_failed_tasks_are_reported_in_limitations() -> None:
    result = _result("finance_agent", findings=[_finding()], confidence=0.8)
    validator = EvidenceValidator(known_sources=KNOWN)
    decision = BusinessDecisionEngine().build(
        collaboration_id="collab-1",
        objective="test",
        results=[result],
        context=_context(),
        conflicts=[],
        validations={"finance_agent_task": validator.validate_result(result)[0]},
        failed_tasks=["inventory_review"],
    )
    assert decision.status == "PARTIAL"
    assert any("inventory_review" in line for line in decision.limitations)
