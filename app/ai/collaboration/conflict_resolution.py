"""Conflict detection and resolution between agent results.

Conflicts are detected from evidence, never from opinion, and every resolution
keeps the original findings alongside the explanation. A conflict that cannot be
resolved with the available data stays UNRESOLVED and is carried into the final
decision as a limitation.
"""

from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation

from app.ai.schemas.collaboration_schema import (
    AgentCollaborationResult,
    ConflictRecord,
    SharedBusinessContext,
)
from app.core.constants import ConflictStatus, ConflictType, FindingSeverity
from app.core.logging_config import get_logger
from app.utils.date_utils import utcnow

logger = get_logger("ai.collaboration.conflicts")

COMPARABLE_METRICS = ("revenue", "net_profit", "sales_value", "operating_expenses")
GROWTH_ACTIONS = ("stock", "reorder", "order", "purchase", "increase")
REDUCE_ACTIONS = ("reduce", "overstock", "dead stock", "stop ordering", "discount")


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}"


class ConflictDetector:
    """Finds contradictions and data disagreements across agent results."""

    def detect(
        self,
        *,
        results: list[AgentCollaborationResult],
        context: SharedBusinessContext,
    ) -> list[ConflictRecord]:
        conflicts: list[ConflictRecord] = []
        conflicts.extend(self._financial_conflicts(results, context))
        conflicts.extend(self._data_source_conflicts(results))
        conflicts.extend(self._period_conflicts(results))
        conflicts.extend(self._inventory_sales_conflicts(results))
        return conflicts

    # -- rules -------------------------------------------------------------
    def _financial_conflicts(
        self, results: list[AgentCollaborationResult], context: SharedBusinessContext
    ) -> list[ConflictRecord]:
        """Purchase recommendations that exceed the cash available."""
        budget = context.available_budget or Decimal("0.00")
        inventory = next((r for r in results if r.agent_id == "inventory_agent"), None)
        finance = next((r for r in results if r.agent_id == "finance_agent"), None)
        if inventory is None:
            return []

        planned: list[dict] = []
        total = Decimal("0.00")
        for recommendation in inventory.recommendations:
            cost = _dec(recommendation.supporting_figures.get("estimated_cost", 0))
            if cost <= 0:
                continue
            planned.append(
                {
                    "recommendation_id": recommendation.recommendation_id,
                    "action": recommendation.recommendation,
                    "quantity": recommendation.supporting_figures.get("suggested_quantity"),
                    "cost": _money(cost),
                    "priority": recommendation.priority,
                    "product": recommendation.supporting_figures.get("available"),
                }
            )
            total += cost

        if total <= 0 or total <= budget:
            return []

        agents = ["inventory_agent"] + (["finance_agent"] if finance else [])
        return [
            ConflictRecord(
                conflict_id=f"conf-{uuid.uuid4().hex[:10]}",
                conflict_type=ConflictType.FINANCIAL_CONFLICT,
                agents=agents,
                description=(
                    f"The Inventory Agent proposes {len(planned)} purchase(s) costing "
                    f"{_money(total)} but only {_money(budget)} of cash is available."
                ),
                evidence={
                    "proposed_total": _money(total),
                    "available_budget": _money(budget),
                    "shortfall": _money(total - budget),
                    "planned_purchases": planned,
                    "finance_metrics": (finance.metrics if finance else {}),
                },
            )
        ]

    def _data_source_conflicts(
        self, results: list[AgentCollaborationResult]
    ) -> list[ConflictRecord]:
        """Two agents reporting different values for the same metric."""
        conflicts: list[ConflictRecord] = []
        seen: dict[str, dict[str, Decimal]] = {}
        for result in results:
            for metric in COMPARABLE_METRICS:
                if metric in result.metrics:
                    value = _dec(result.metrics[metric])
                    seen.setdefault(metric, {})[result.agent_id] = value

        for metric, per_agent in seen.items():
            values = set(per_agent.values())
            if len(per_agent) < 2 or len(values) < 2:
                continue
            agents = sorted(per_agent)
            conflicts.append(
                ConflictRecord(
                    conflict_id=f"conf-{uuid.uuid4().hex[:10]}",
                    conflict_type=ConflictType.DATA_SOURCE_CONFLICT,
                    agents=agents,
                    description=(
                        f"Agents disagree on {metric.replace('_', ' ')}: "
                        + ", ".join(f"{agent} {_money(value)}" for agent, value in per_agent.items())
                        + "."
                    ),
                    evidence={
                        "metric": metric,
                        "values": {agent: _money(value) for agent, value in per_agent.items()},
                    },
                )
            )
        return conflicts

    def _period_conflicts(
        self, results: list[AgentCollaborationResult]
    ) -> list[ConflictRecord]:
        """The same finding type measured over different periods."""
        periods: dict[str, set[str]] = {}
        agents: dict[str, set[str]] = {}
        for result in results:
            for finding in result.findings:
                period = finding.reporting_period
                if not period:
                    continue
                periods.setdefault(finding.finding_type, set()).add(period)
                agents.setdefault(finding.finding_type, set()).add(result.agent_id)

        conflicts: list[ConflictRecord] = []
        for finding_type, values in periods.items():
            if len(values) < 2:
                continue
            conflicts.append(
                ConflictRecord(
                    conflict_id=f"conf-{uuid.uuid4().hex[:10]}",
                    conflict_type=ConflictType.REPORTING_PERIOD_CONFLICT,
                    agents=sorted(agents.get(finding_type, set())),
                    description=(
                        f"'{finding_type.replace('_', ' ').title()}' is reported for "
                        f"{len(values)} different periods ({', '.join(sorted(values))})."
                    ),
                    evidence={"finding_type": finding_type, "periods": sorted(values)},
                )
            )
        return conflicts

    def _inventory_sales_conflicts(
        self, results: list[AgentCollaborationResult]
    ) -> list[ConflictRecord]:
        """One agent pushes more stock while another reports excess stock."""
        inventory = next((r for r in results if r.agent_id == "inventory_agent"), None)
        sales = next((r for r in results if r.agent_id == "sales_agent"), None)
        if inventory is None or sales is None:
            return []

        wants_more = any(
            any(keyword in rec.recommendation.lower() for keyword in GROWTH_ACTIONS)
            for rec in inventory.recommendations
        )
        has_excess = any(
            finding.finding_type in ("OVERSTOCK", "DEAD_STOCK")
            and FindingSeverity.ORDER.get(finding.severity, 0) >= 1
            for finding in inventory.findings
        )
        declining = any(
            finding.finding_type == "SALES_DECLINE" for finding in sales.findings
        )
        if not (wants_more and has_excess and declining):
            return []

        return [
            ConflictRecord(
                conflict_id=f"conf-{uuid.uuid4().hex[:10]}",
                conflict_type=ConflictType.INVENTORY_CONFLICT,
                agents=["inventory_agent", "sales_agent"],
                description=(
                    "The Inventory Agent proposes replenishment while reporting excess "
                    "stock and the Sales Agent reports declining sales."
                ),
                evidence={
                    "inventory_findings": [
                        finding.finding_type for finding in inventory.findings
                    ],
                    "sales_findings": [finding.finding_type for finding in sales.findings],
                },
            )
        ]


class ConflictResolver:
    """Deterministic resolution using authoritative business figures."""

    def resolve(
        self,
        *,
        conflict: ConflictRecord,
        context: SharedBusinessContext,
        results: list[AgentCollaborationResult],
    ) -> ConflictRecord:
        resolver = {
            ConflictType.FINANCIAL_CONFLICT: self._resolve_financial,
            ConflictType.DATA_SOURCE_CONFLICT: self._resolve_data_source,
            ConflictType.REPORTING_PERIOD_CONFLICT: self._resolve_period,
            ConflictType.INVENTORY_CONFLICT: self._resolve_inventory,
        }.get(conflict.conflict_type)

        if resolver is None:
            conflict.status = ConflictStatus.UNRESOLVED
            conflict.resolution = {
                "explanation": "No deterministic resolution rule exists for this conflict type.",
            }
            return conflict

        conflict = resolver(conflict=conflict, context=context, results=results)
        conflict.resolution.setdefault("resolved_at", utcnow().isoformat())
        conflict.resolution.setdefault("original_evidence", conflict.evidence)
        return conflict

    # -- resolvers ---------------------------------------------------------
    def _resolve_financial(
        self,
        *,
        conflict: ConflictRecord,
        context: SharedBusinessContext,
        results: list[AgentCollaborationResult],
    ) -> ConflictRecord:
        budget = context.available_budget or Decimal("0.00")
        planned = conflict.evidence.get("planned_purchases", []) or []
        affordable: list[dict] = []
        deferred: list[dict] = []
        spent = Decimal("0.00")

        priority_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        for item in sorted(planned, key=lambda row: priority_rank.get(row.get("priority"), 3)):
            cost = _dec(item.get("cost", 0))
            if spent + cost <= budget:
                affordable.append(item)
                spent += cost
            else:
                deferred.append(item)

        if affordable:
            conflict.status = ConflictStatus.RESOLVED
            conflict.resolution = {
                "strategy": "BUDGET_CONSTRAINED_PURCHASE",
                "explanation": (
                    f"Cash available is {_money(budget)}. Approve the "
                    f"{len(affordable)} highest-priority purchase(s) totalling "
                    f"{_money(spent)} and defer {len(deferred)} purchase(s) worth "
                    f"{_money(sum((_dec(item.get('cost', 0)) for item in deferred), Decimal('0.00')))} "
                    "until cash is available."
                ),
                "affordable_purchases": affordable,
                "deferred_purchases": deferred,
                "budget": _money(budget),
                "committed": _money(spent),
                "remaining": _money(budget - spent),
                "requires_approval": True,
            }
        else:
            conflict.status = ConflictStatus.UNRESOLVED
            conflict.resolution = {
                "strategy": "INSUFFICIENT_CASH",
                "explanation": (
                    f"No purchase fits within the available cash of {_money(budget)}; "
                    "collect outstanding receivables or raise funds first."
                ),
                "budget": _money(budget),
                "deferred_purchases": deferred,
            }
        return conflict

    def _resolve_data_source(
        self,
        *,
        conflict: ConflictRecord,
        context: SharedBusinessContext,
        results: list[AgentCollaborationResult],
    ) -> ConflictRecord:
        metric = conflict.evidence.get("metric")
        authoritative: str | None = None
        value = None
        # Authoritative mapping: finance owns revenue/profit, sales owns sales value.
        owner = {
            "revenue": "finance_agent",
            "net_profit": "finance_agent",
            "operating_expenses": "finance_agent",
            "sales_value": "sales_agent",
        }.get(metric)
        if owner:
            source = next((r for r in results if r.agent_id == owner), None)
            if source is not None and metric in source.metrics:
                authoritative = owner
                value = source.metrics[metric]

        if authoritative:
            conflict.status = ConflictStatus.RESOLVED
            conflict.resolution = {
                "strategy": "AUTHORITATIVE_SOURCE",
                "explanation": (
                    f"{authoritative} owns the {str(metric).replace('_', ' ')} figure; its "
                    f"value {value} is used and the other figures are treated as "
                    "differently-scoped measurements, not errors."
                ),
                "authoritative_agent": authoritative,
                "authoritative_value": str(value),
            }
        else:
            conflict.status = ConflictStatus.UNRESOLVED
            conflict.resolution = {
                "explanation": "No authoritative owner is defined for this metric.",
            }
        return conflict

    def _resolve_period(
        self,
        *,
        conflict: ConflictRecord,
        context: SharedBusinessContext,
        results: list[AgentCollaborationResult],
    ) -> ConflictRecord:
        periods = conflict.evidence.get("periods", [])
        chosen = context.reporting_period
        conflict.status = ConflictStatus.RESOLVED if chosen else ConflictStatus.UNRESOLVED
        conflict.resolution = {
            "strategy": "ALIGN_TO_REQUESTED_PERIOD",
            "explanation": (
                f"Findings were aligned to the collaboration period '{chosen}'."
                if chosen
                else "The collaboration did not fix a reporting period, so the difference is preserved."
            ),
            "periods_seen": periods,
            "aligned_period": chosen,
        }
        return conflict

    def _resolve_inventory(
        self,
        *,
        conflict: ConflictRecord,
        context: SharedBusinessContext,
        results: list[AgentCollaborationResult],
    ) -> ConflictRecord:
        conflict.status = ConflictStatus.RESOLVED
        conflict.resolution = {
            "strategy": "REPLENISH_ONLY_FAST_MOVERS",
            "explanation": (
                "Replenish only products with recent demand; hold or discount stock "
                "that is already overstocked while sales are declining."
            ),
            "requires_inventory_review": True,
        }
        return conflict
