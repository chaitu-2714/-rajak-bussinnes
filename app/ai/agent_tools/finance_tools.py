"""Deterministic finance analysis used by the Finance Agent.

Everything here is pure Python over data that was already retrieved through
permission-checked tools. No model output is trusted, and no number is invented.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from statistics import median

from app.ai.schemas.agent_schema import Evidence, Finding, Recommendation
from app.core.constants import FindingSeverity


@dataclass
class AnomalyThresholds:
    """Configurable statistical thresholds for expense anomaly detection."""

    iqr_factor: float = 1.5
    minimum_history: int = 3
    relative_jump: float = 0.5  # 50% above the category median


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value: Decimal | float | int) -> str:
    return f"{Decimal(str(value)).quantize(Decimal('0.01')):,.2f}"


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def analyse_revenue(
    *,
    current: dict,
    previous: dict | None,
    period_label: str,
    currency: str = "INR",
) -> tuple[list[Finding], dict]:
    """Revenue level plus period-over-period movement."""
    revenue = _dec(current.get("revenue", 0))
    findings: list[Finding] = []
    metrics: dict = {
        "revenue": _money(revenue),
        "refunds_paid": current.get("refunds_paid", "0.00"),
        "period": period_label,
    }

    findings.append(
        Finding(
            finding_id="fin-revenue-level",
            finding_type="REVENUE_LEVEL",
            description=f"Revenue for {period_label} was {_money(revenue)} {currency}.",
            severity=FindingSeverity.INFO,
            evidence=[
                Evidence(
                    source="get_revenue",
                    metric="revenue",
                    value=_money(revenue),
                    period=period_label,
                )
            ],
            reporting_period=period_label,
            metric_value=float(revenue),
            agent_id="finance_agent",
        )
    )

    if previous is not None:
        prior = _dec(previous.get("revenue", 0))
        metrics["previous_revenue"] = _money(prior)
        if prior > 0:
            change = (revenue - prior) / prior
            metrics["revenue_change_pct"] = round(float(change) * 100, 2)
            if change <= -0.10:
                severity = FindingSeverity.HIGH if change <= -0.25 else FindingSeverity.MEDIUM
                findings.append(
                    Finding(
                        finding_id="fin-revenue-decline",
                        finding_type="REVENUE_DECLINE",
                        description=(
                            f"Revenue fell {_pct(abs(float(change)))} from "
                            f"{_money(prior)} to {_money(revenue)}."
                        ),
                        severity=severity,
                        evidence=[
                            Evidence(source="get_revenue", metric="current revenue", value=_money(revenue), period=period_label),
                            Evidence(source="get_revenue", metric="previous period revenue", value=_money(prior), period=previous.get("period")),
                        ],
                        reporting_period=period_label,
                        metric_value=round(float(change) * 100, 2),
                        agent_id="finance_agent",
                    )
                )
            elif change >= 0.10:
                findings.append(
                    Finding(
                        finding_id="fin-revenue-growth",
                        finding_type="REVENUE_GROWTH",
                        description=(
                            f"Revenue grew {_pct(float(change))} from {_money(prior)} "
                            f"to {_money(revenue)}."
                        ),
                        severity=FindingSeverity.INFO,
                        evidence=[
                            Evidence(source="get_revenue", metric="current revenue", value=_money(revenue), period=period_label),
                            Evidence(source="get_revenue", metric="previous period revenue", value=_money(prior), period=previous.get("period")),
                        ],
                        reporting_period=period_label,
                        metric_value=round(float(change) * 100, 2),
                        agent_id="finance_agent",
                    )
                )
    return findings, metrics


def analyse_expenses(*, expenses: dict, period_label: str) -> tuple[list[Finding], dict]:
    """Operating expense level and category concentration."""
    operating = _dec(expenses.get("operating_expenses", 0))
    breakdown = expenses.get("breakdown", []) or []
    findings: list[Finding] = []
    metrics: dict = {
        "operating_expenses": _money(operating),
        "expense_count": expenses.get("expense_count", 0),
        "categories": {item["category"]: item["amount"] for item in breakdown},
    }

    findings.append(
        Finding(
            finding_id="fin-expense-level",
            finding_type="EXPENSE_LEVEL",
            description=(
                f"Operating expenses for {period_label} were {_money(operating)} "
                f"across {expenses.get('expense_count', 0)} record(s)."
            ),
            severity=FindingSeverity.INFO,
            evidence=[
                Evidence(source="get_expenses", metric="operating expenses", value=_money(operating), period=period_label, record_count=expenses.get("expense_count"))
            ],
            reporting_period=period_label,
            metric_value=float(operating),
            agent_id="finance_agent",
        )
    )

    if operating > 0 and breakdown:
        top = max(breakdown, key=lambda item: _dec(item["amount"]))
        share = float(_dec(top["amount"]) / operating)
        metrics["largest_category"] = top["category"]
        metrics["largest_category_share_pct"] = round(share * 100, 2)
        if share >= 0.40:
            findings.append(
                Finding(
                    finding_id="fin-expense-concentration",
                    finding_type="EXPENSE_CONCENTRATION",
                    description=(
                        f"{top['category']} accounts for {_pct(share)} of operating "
                        f"expenses ({_money(_dec(top['amount']))})."
                    ),
                    severity=FindingSeverity.MEDIUM if share >= 0.55 else FindingSeverity.LOW,
                    evidence=[
                        Evidence(source="get_expenses", metric=f"{top['category']} amount", value=top["amount"], period=period_label),
                        Evidence(source="get_expenses", metric="total operating expenses", value=_money(operating), period=period_label),
                    ],
                    reporting_period=period_label,
                    metric_value=round(share * 100, 2),
                    agent_id="finance_agent",
                )
            )
    return findings, metrics


def analyse_profit(*, profit: dict, revenue: dict, period_label: str) -> tuple[list[Finding], dict]:
    """Gross and net margin analysis."""
    rev = _dec(profit.get("revenue", revenue.get("revenue", 0)))
    gross = _dec(profit.get("gross_profit", 0))
    net = _dec(profit.get("net_profit", 0))
    opex = _dec(profit.get("operating_expenses", 0))

    gross_margin = float(gross / rev) if rev > 0 else 0.0
    net_margin = float(net / rev) if rev > 0 else 0.0
    opex_share = float(opex / rev) if rev > 0 else 0.0

    metrics = {
        "revenue": _money(rev),
        "cogs": profit.get("cogs", "0.00"),
        "gross_profit": _money(gross),
        "net_profit": _money(net),
        "gross_margin_pct": round(gross_margin * 100, 2),
        "net_margin_pct": round(net_margin * 100, 2),
        "opex_share_pct": round(opex_share * 100, 2),
    }
    findings: list[Finding] = []

    if rev > 0:
        severity = FindingSeverity.INFO
        if net < 0:
            severity = FindingSeverity.HIGH
        elif net_margin < 0.05:
            severity = FindingSeverity.MEDIUM
        findings.append(
            Finding(
                finding_id="fin-profit-margin",
                finding_type="PROFIT_MARGIN",
                description=(
                    f"Net profit {_money(net)} on revenue {_money(rev)} "
                    f"({_pct(net_margin)} net margin, {_pct(gross_margin)} gross margin)."
                ),
                severity=severity,
                evidence=[
                    Evidence(source="calculate_profit", metric="revenue", value=_money(rev), period=period_label),
                    Evidence(source="calculate_profit", metric="gross profit", value=_money(gross), period=period_label),
                    Evidence(source="calculate_profit", metric="net profit", value=_money(net), period=period_label),
                ],
                reporting_period=period_label,
                metric_value=round(net_margin * 100, 2),
                agent_id="finance_agent",
            )
        )
        if opex_share >= 0.5:
            findings.append(
                Finding(
                    finding_id="fin-opex-share",
                    finding_type="OPEX_SHARE",
                    description=(
                        f"Operating expenses consume {_pct(opex_share)} of revenue "
                        f"({_money(opex)} of {_money(rev)})."
                    ),
                    severity=FindingSeverity.MEDIUM,
                    evidence=[
                        Evidence(source="calculate_profit", metric="operating expenses", value=_money(opex), period=period_label),
                        Evidence(source="calculate_profit", metric="revenue", value=_money(rev), period=period_label),
                    ],
                    reporting_period=period_label,
                    metric_value=round(opex_share * 100, 2),
                    agent_id="finance_agent",
                )
            )
    else:
        findings.append(
            Finding(
                finding_id="fin-no-revenue",
                finding_type="NO_REVENUE",
                description=(
                    f"No revenue was recognised for {period_label}, so margins cannot be "
                    "computed."
                ),
                severity=FindingSeverity.MEDIUM,
                evidence=[
                    Evidence(source="calculate_profit", metric="revenue", value="0.00", period=period_label),
                ],
                reporting_period=period_label,
                agent_id="finance_agent",
            )
        )
    return findings, metrics


def analyse_cash_flow(
    *, cash: dict, outstanding: dict, period_label: str
) -> tuple[list[Finding], dict]:
    """Cash collected versus revenue recognised, plus receivables."""
    received = _dec(cash.get("cash_received", 0))
    refunds = _dec(cash.get("refunds_paid", 0))
    net_cash = _dec(cash.get("net_cash_movement", 0))
    receivables = _dec(outstanding.get("total_outstanding", 0))

    metrics = {
        "cash_received": _money(received),
        "refunds_paid": _money(refunds),
        "net_cash_movement": _money(net_cash),
        "outstanding_receivables": _money(receivables),
        "unpaid_invoices": outstanding.get("invoice_count", 0),
    }
    findings: list[Finding] = []

    findings.append(
        Finding(
            finding_id="fin-cash-position",
            finding_type="CASH_POSITION",
            description=(
                f"Cash received {_money(received)}, refunds {_money(refunds)}, "
                f"net cash movement {_money(net_cash)} for {period_label}."
            ),
            severity=FindingSeverity.INFO,
            evidence=[
                Evidence(source="get_cash_flow", metric="cash received", value=_money(received), period=period_label),
                Evidence(source="get_cash_flow", metric="net cash movement", value=_money(net_cash), period=period_label),
            ],
            reporting_period=period_label,
            metric_value=float(net_cash),
            agent_id="finance_agent",
        )
    )

    if receivables > 0:
        invoices = outstanding.get("invoices", []) or []
        oldest = None
        if invoices:
            oldest = invoices[0].get("due") if isinstance(invoices[0], dict) else None
        findings.append(
            Finding(
                finding_id="fin-receivables",
                finding_type="OUTSTANDING_RECEIVABLES",
                description=(
                    f"{outstanding.get('invoice_count', 0)} invoice(s) remain unpaid, "
                    f"totalling {_money(receivables)}."
                    + (f" Earliest due date on record: {oldest}." if oldest else "")
                ),
                severity=FindingSeverity.HIGH if receivables > 10000 else FindingSeverity.MEDIUM,
                evidence=[
                    Evidence(source="get_outstanding_payments", metric="outstanding total", value=_money(receivables), period=None, record_count=outstanding.get("invoice_count"))
                ],
                reporting_period=period_label,
                metric_value=float(receivables),
                agent_id="finance_agent",
            )
        )
    return findings, metrics


def detect_expense_anomalies(
    expenses: list[dict],
    *,
    thresholds: AnomalyThresholds | None = None,
) -> tuple[list[Finding], list[dict]]:
    """Median/IQR based outlier detection over recorded expense amounts.

    An anomaly is a statistical outlier, not evidence of wrongdoing.
    """
    thresholds = thresholds or AnomalyThresholds()
    rows = [row for row in expenses if _dec(row.get("amount", 0)) > 0]
    if len(rows) < thresholds.minimum_history:
        return [], []

    amounts = sorted(_dec(row["amount"]) for row in rows)
    med = median(amounts)
    lower_half = amounts[: max(1, len(amounts) // 2)]
    upper_half = amounts[len(amounts) // 2 :]
    q1 = median(lower_half)
    q3 = median(upper_half)
    iqr = q3 - q1
    upper_fence = q3 + Decimal(str(thresholds.iqr_factor)) * iqr
    relative_fence = med * Decimal(str(1 + thresholds.relative_jump))

    findings: list[Finding] = []
    anomalies: list[dict] = []
    for row in rows:
        amount = _dec(row["amount"])
        if amount <= upper_fence and amount <= relative_fence:
            continue
        if amount <= med:
            continue
        anomalies.append(
            {
                "expense": row.get("expense_number") or row.get("description"),
                "category": row.get("expense_category"),
                "amount": _money(amount),
                "median": _money(med),
                "date": row.get("expense_date"),
            }
        )
        findings.append(
            Finding(
                finding_id=f"fin-anomaly-{len(findings) + 1}",
                finding_type="EXPENSE_ANOMALY",
                description=(
                    f"Expense {row.get('expense_number', '')} "
                    f"({row.get('expense_category', 'OTHER')}) of {_money(amount)} is well "
                    f"above the median of {_money(med)} for {len(rows)} recorded expenses."
                ),
                severity=FindingSeverity.MEDIUM,
                evidence=[
                    Evidence(source="get_expense_breakdown", metric="expense amount", value=_money(amount), period=str(row.get("expense_date") or "")),
                    Evidence(source="get_expense_breakdown", metric="median expense", value=_money(med), period=None, record_count=len(rows)),
                ],
                metric_value=float(amount),
                agent_id="finance_agent",
            )
        )
        if len(findings) >= 5:
            break
    return findings, anomalies


def build_finance_recommendations(
    *, findings: list[Finding], metrics: dict, period_label: str
) -> list[Recommendation]:
    """Turn finance findings into prioritised, evidence-linked actions."""
    recommendations: list[Recommendation] = []
    by_type = {finding.finding_type: finding for finding in findings}

    if "REVENUE_DECLINE" in by_type:
        finding = by_type["REVENUE_DECLINE"]
        recommendations.append(
            Recommendation(
                recommendation_id="fin-rec-revenue-decline",
                recommendation="Review pricing, demand and order volume for the drop in revenue.",
                reason=finding.description,
                priority="HIGH",
                supporting_figures={
                    "revenue_change_pct": str(metrics.get("revenue_change_pct", "")),
                    "period": period_label,
                },
                agent_id="finance_agent",
            )
        )
    if "OUTSTANDING_RECEIVABLES" in by_type:
        finding = by_type["OUTSTANDING_RECEIVABLES"]
        recommendations.append(
            Recommendation(
                recommendation_id="fin-rec-receivables",
                recommendation="Follow up on unpaid invoices and agree payment dates.",
                reason=finding.description,
                priority="HIGH",
                supporting_figures={
                    "outstanding": str(metrics.get("outstanding_receivables", "")),
                    "invoices": str(metrics.get("unpaid_invoices", "")),
                },
                agent_id="finance_agent",
            )
        )
    if "OPEX_SHARE" in by_type:
        finding = by_type["OPEX_SHARE"]
        recommendations.append(
            Recommendation(
                recommendation_id="fin-rec-opex",
                recommendation="Review the largest operating expense categories for savings.",
                reason=finding.description,
                priority="MEDIUM",
                supporting_figures={
                    "opex_share_pct": str(metrics.get("opex_share_pct", "")),
                    "largest_category": str(metrics.get("largest_category", "n/a")),
                },
                agent_id="finance_agent",
            )
        )
    if "EXPENSE_ANOMALY" in by_type:
        finding = by_type["EXPENSE_ANOMALY"]
        recommendations.append(
            Recommendation(
                recommendation_id="fin-rec-anomaly",
                recommendation="Verify the unusual expense against its bill or voucher.",
                reason=finding.description,
                priority="MEDIUM",
                supporting_figures={"period": period_label},
                agent_id="finance_agent",
            )
        )
    return recommendations
