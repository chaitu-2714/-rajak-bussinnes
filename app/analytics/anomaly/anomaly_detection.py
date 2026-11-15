"""Anomaly detection: rule-based, moving average, MAD and IQR.

Findings are review items only. Nothing here modifies, deletes or reverses a
business record, and nothing is labelled fraud.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal
from statistics import median

from app.analytics.data_collector import BusinessDataset
from app.analytics.schemas import AnomalyFinding, money
from app.utils.date_utils import utcnow

ZERO = Decimal("0.00")

# Rule thresholds (documented, deterministic).
EXPENSE_Z_THRESHOLD = Decimal("2.5")       # z-score against the same category
EXPENSE_SPIKE_MULTIPLIER = Decimal("3.0")  # 3x the category median
REVENUE_DROP_PERCENT = Decimal("-40.0")    # day-over-day drop
REVENUE_SPIKE_PERCENT = Decimal("100.0")   # day-over-day rise
STOCK_ADJUSTMENT_COUNT = 3                 # repeated manual adjustments
DUPLICATE_AMOUNT_TOLERANCE = Decimal("0.00")
PRICE_CHANGE_PERCENT = Decimal("15.0")


class BusinessAnomalyDetectionEngine:
    """Detects unusual patterns and explains each one with its evidence."""

    def detect(self, dataset: BusinessDataset) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        findings.extend(self.detect_financial_anomalies(dataset))
        findings.extend(self.detect_sales_anomalies(dataset))
        findings.extend(self.detect_inventory_anomalies(dataset))
        findings.extend(self.detect_supplier_anomalies(dataset))
        return findings

    # -- financial ---------------------------------------------------------
    def detect_financial_anomalies(self, dataset: BusinessDataset) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        by_category: dict[str, list[dict]] = {}
        for expense in dataset.expenses:
            by_category.setdefault(expense["category"], []).append(expense)

        for category, expenses in by_category.items():
            amounts = [Decimal(str(expense["amount"])) for expense in expenses]
            if len(amounts) < 3:
                continue
            centre = Decimal(str(median([float(a) for a in amounts])))
            deviations = [abs(float(a) - float(centre)) for a in amounts]
            mad = Decimal(str(median(deviations))) if deviations else ZERO
            mean = sum(amounts, ZERO) / Decimal(len(amounts))
            variance = sum(((a - mean) ** 2 for a in amounts), ZERO) / Decimal(len(amounts))
            std = Decimal(str(float(variance) ** 0.5))
            for expense in expenses:
                amount = Decimal(str(expense["amount"]))
                if std > ZERO:
                    z = ((amount - mean) / std).quantize(Decimal("0.01"))
                    if z >= EXPENSE_Z_THRESHOLD:
                        findings.append(
                            self._finding(
                                category="FINANCIAL",
                                anomaly_type="UNUSUAL_EXPENSE",
                                record=f"Expense {expense['number']} ({expense['category']})",
                                record_id=expense["id"],
                                method="Z_SCORE",
                                observed=amount,
                                expected=money(mean),
                                severity=self._severity_from_z(z),
                                evidence={
                                    "category": category,
                                    "z_score": str(z),
                                    "category_mean": str(money(mean)),
                                    "category_std": str(money(std)),
                                    "sample_size": len(amounts),
                                },
                                explanation=(
                                    f"{expense['number']} is {z} standard deviations above the "
                                    f"{category} average of {money(mean):,.2f}. This is a review "
                                    "flag, not a finding of wrongdoing."
                                ),
                            )
                        )
                if mad > ZERO and centre > ZERO:
                    ratio = amount / centre
                    if ratio >= EXPENSE_SPIKE_MULTIPLIER:
                        findings.append(
                            self._finding(
                                category="FINANCIAL",
                                anomaly_type="EXPENSE_SPIKE",
                                record=f"Expense {expense['number']} ({expense['category']})",
                                record_id=expense["id"],
                                method="MEDIAN_DEVIATION",
                                observed=amount,
                                expected=money(centre),
                                severity="MEDIUM" if ratio < 5 else "HIGH",
                                evidence={
                                    "category": category,
                                    "category_median": str(money(centre)),
                                    "ratio": str(ratio.quantize(Decimal("0.01"))),
                                },
                                explanation=(
                                    f"Amount is {ratio.quantize(Decimal('0.01'))}× the category "
                                    "median. Verify the invoice before assuming anything unusual."
                                ),
                            )
                        )

        findings.extend(self._duplicate_expenses(dataset))
        findings.extend(self._cash_flow_shift(dataset))
        return findings

    def _duplicate_expenses(self, dataset: BusinessDataset) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        seen: dict[tuple, dict] = {}
        for expense in dataset.expenses:
            key = (expense["category"], Decimal(str(expense["amount"])), expense["vendor"])
            if key in seen:
                first = seen[key]
                gap = abs((expense["date"] - first["date"]).days)
                if gap <= 3:
                    findings.append(
                        self._finding(
                            category="FINANCIAL",
                            anomaly_type="DUPLICATE_LOOKING_EXPENSE",
                            record=f"Expenses {first['number']} and {expense['number']}",
                            record_id=expense["id"],
                            method="RULE_BASED",
                            observed=Decimal(str(expense["amount"])),
                            expected=Decimal(str(first["amount"])),
                            severity="MEDIUM",
                            evidence={
                                "first_expense": first["number"],
                                "second_expense": expense["number"],
                                "days_apart": gap,
                                "same_category": expense["category"],
                                "same_vendor": expense["vendor"],
                            },
                            explanation=(
                                "Two expenses share the same category, amount and vendor within "
                                f"{gap} day(s). This may be a legitimate repeat payment — it is "
                                "flagged for review only."
                            ),
                        )
                    )
            else:
                seen[key] = expense
        return findings

    def _cash_flow_shift(self, dataset: BusinessDataset) -> list[AnomalyFinding]:
        """Compare this period's net cash flow with the previous period."""
        previous = dataset.previous_finance_summary
        if not previous:
            return []
        current_net = Decimal(str(dataset.finance_summary.get("cash_received", 0))) - Decimal(
            str(dataset.finance_summary.get("operating_expenses", 0))
        )
        previous_net = Decimal(str(previous.get("cash_received", 0))) - Decimal(
            str(previous.get("operating_expenses", 0))
        )
        if previous_net == ZERO:
            return []
        change = ((current_net - previous_net) / abs(previous_net) * 100).quantize(Decimal("0.01"))
        if change > REVENUE_DROP_PERCENT:
            return []
        return [
            self._finding(
                category="FINANCIAL",
                anomaly_type="CASH_FLOW_DETERIORATION",
                record=f"Period {dataset.period.label}",
                record_id=None,
                method="PERIOD_COMPARISON",
                observed=money(current_net),
                expected=money(previous_net),
                severity="HIGH" if change <= -70 else "MEDIUM",
                evidence={"change_percent": str(change), "previous_net_cash": str(money(previous_net))},
                explanation=(
                    f"Net cash flow changed {change}% versus the previous period "
                    f"({money(previous_net):,.2f} → {money(current_net):,.2f})."
                ),
            )
        ]

    # -- sales -------------------------------------------------------------
    def detect_sales_anomalies(self, dataset: BusinessDataset) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        from app.analytics.periods import daily_buckets

        buckets = daily_buckets(dataset.period)
        daily: dict[str, Decimal] = {label: ZERO for label, _, _ in buckets}
        for order in dataset.orders:
            from app.utils.date_utils import to_local

            local = to_local(order["created_at"])
            for label, start, end in buckets:
                if local and start <= local <= end:
                    daily[label] += Decimal(str(order["total"]))
                    break
        values = list(daily.items())
        for index in range(3, len(values)):
            window = [values[i][1] for i in range(index - 3, index)]
            average = sum(window, ZERO) / Decimal(len(window))
            label, value = values[index]
            if average <= ZERO:
                continue
            change = ((value - average) / average * 100).quantize(Decimal("0.01"))
            if change <= REVENUE_DROP_PERCENT and value > ZERO:
                findings.append(
                    self._finding(
                        category="SALES",
                        anomaly_type="REVENUE_DROP",
                        record=f"Sales on {label}",
                        record_id=None,
                        method="MOVING_AVERAGE",
                        observed=money(value),
                        expected=money(average),
                        severity="HIGH" if change <= -60 else "MEDIUM",
                        evidence={
                            "window_days": 3,
                            "moving_average": str(money(average)),
                            "change_percent": str(change),
                        },
                        explanation=(
                            f"Sales on {label} were {change}% below the previous 3-day average "
                            f"of {money(average):,.2f}."
                        ),
                    )
                )
            elif change >= REVENUE_SPIKE_PERCENT and average > ZERO:
                findings.append(
                    self._finding(
                        category="SALES",
                        anomaly_type="SALES_SPIKE",
                        record=f"Sales on {label}",
                        record_id=None,
                        method="MOVING_AVERAGE",
                        observed=money(value),
                        expected=money(average),
                        severity="LOW",
                        evidence={"window_days": 3, "change_percent": str(change)},
                        explanation=(
                            f"Sales on {label} were {change}% above the previous 3-day average. "
                            "A large order can explain this."
                        ),
                    )
                )
        findings.extend(self._quantity_anomalies(dataset))
        return findings

    def _quantity_anomalies(self, dataset: BusinessDataset) -> list[AnomalyFinding]:
        """IQR test on order values within the period."""
        values = sorted(Decimal(str(order["total"])) for order in dataset.orders)
        if len(values) < 5:
            return []
        q1 = values[len(values) // 4]
        q3 = values[(len(values) * 3) // 4]
        iqr = q3 - q1
        upper = q3 + iqr * Decimal("3")
        findings = []
        for order in dataset.orders:
            total = Decimal(str(order["total"]))
            if total > upper and upper > ZERO:
                findings.append(
                    self._finding(
                        category="SALES",
                        anomaly_type="UNUSUAL_ORDER_VALUE",
                        record=f"Order {order['number']} ({order['customer']})",
                        record_id=order["id"],
                        method="IQR",
                        observed=money(total),
                        expected=money(q3),
                        severity="LOW",
                        evidence={
                            "q1": str(money(q1)),
                            "q3": str(money(q3)),
                            "upper_fence": str(money(upper)),
                            "sample_size": len(values),
                        },
                        explanation=(
                            f"Order value {money(total):,.2f} is above the upper fence "
                            f"{money(upper):,.2f} of the period's order distribution."
                        ),
                    )
                )
        return findings

    # -- inventory ---------------------------------------------------------
    def detect_inventory_anomalies(self, dataset: BusinessDataset) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        adjustments: dict[int, list[dict]] = {}
        for movement in dataset.movements:
            if movement["type"] == "ADJUSTMENT":
                adjustments.setdefault(movement["product_id"], []).append(movement)
        for product_id, movements in adjustments.items():
            if len(movements) >= STOCK_ADJUSTMENT_COUNT:
                product = movements[0]["product"]
                findings.append(
                    self._finding(
                        category="INVENTORY",
                        anomaly_type="REPEATED_STOCK_ADJUSTMENTS",
                        record=f"{product} (product #{product_id})",
                        record_id=product_id,
                        method="RULE_BASED",
                        observed=Decimal(len(movements)),
                        expected=Decimal(STOCK_ADJUSTMENT_COUNT - 1),
                        severity="MEDIUM" if len(movements) < 6 else "HIGH",
                        evidence={
                            "adjustment_count": len(movements),
                            "threshold": STOCK_ADJUSTMENT_COUNT,
                            "last_reason": movements[-1].get("reference_type"),
                        },
                        explanation=(
                            f"{len(movements)} manual stock adjustments were recorded for "
                            f"{product}. Repeated adjustments usually mean a counting or "
                            "receiving process problem."
                        ),
                    )
                )
        for row in dataset.stock:
            value = Decimal(str(row["value"]))
            if int(row["available"]) > 0 and value <= ZERO:
                findings.append(
                    self._finding(
                        category="INVENTORY",
                        anomaly_type="VALUATION_INCONSISTENCY",
                        record=f"{row['product']} ({row['sku']})",
                        record_id=row["product_id"],
                        method="RULE_BASED",
                        observed=value,
                        expected=Decimal(str(row["cost_price"])) * int(row["available"]),
                        severity="MEDIUM",
                        evidence={
                            "available": int(row["available"]),
                            "cost_price": str(row["cost_price"]),
                        },
                        explanation=(
                            "Stock is held but its recorded cost price is zero, so inventory "
                            "value is understated."
                        ),
                    )
                )
        return findings

    # -- supplier ----------------------------------------------------------
    def detect_supplier_anomalies(self, dataset: BusinessDataset) -> list[AnomalyFinding]:
        findings: list[AnomalyFinding] = []
        prices: dict[int, list[tuple]] = {}
        for order in dataset.purchase_orders:
            for line in order["lines"]:
                prices.setdefault(line["product_id"], []).append(
                    (order["created_at"], Decimal(str(line["unit_cost"])), line["product"], order["number"])
                )
        for product_id, observations in prices.items():
            observations.sort(key=lambda item: item[0])
            if len(observations) < 2:
                continue
            first = observations[0][1]
            latest = observations[-1][1]
            if first <= ZERO:
                continue
            change = ((latest - first) / first * 100).quantize(Decimal("0.01"))
            if abs(change) >= PRICE_CHANGE_PERCENT:
                findings.append(
                    self._finding(
                        category="SUPPLIER",
                        anomaly_type="PURCHASE_PRICE_CHANGE",
                        record=f"{observations[-1][2]} purchase price",
                        record_id=product_id,
                        method="RULE_BASED",
                        observed=money(latest),
                        expected=money(first),
                        severity="MEDIUM" if abs(change) < 30 else "HIGH",
                        evidence={
                            "change_percent": str(change),
                            "observations": len(observations),
                            "latest_order": observations[-1][3],
                        },
                        explanation=(
                            f"The purchase price of {observations[-1][2]} moved {change}% "
                            f"({money(first):,.2f} → {money(latest):,.2f})."
                        ),
                    )
                )

        receipts_by_order: dict[str, list] = {}
        for receipt in dataset.receipts:
            receipts_by_order.setdefault(receipt["order"], []).append(receipt)
        for order in dataset.purchase_orders:
            if order["expected"] is None:
                continue
            for receipt in receipts_by_order.get(order["number"], []):
                delay = (receipt["received_at"] - order["expected"]).days
                if delay > 7:
                    findings.append(
                        self._finding(
                            category="SUPPLIER",
                            anomaly_type="DELIVERY_DELAY",
                            record=f"{order['number']} from {order['supplier']}",
                            record_id=order["id"],
                            method="RULE_BASED",
                            observed=Decimal(delay),
                            expected=ZERO,
                            severity="MEDIUM" if delay < 21 else "HIGH",
                            evidence={
                                "expected": order["expected"].isoformat(),
                                "received": receipt["received_at"].isoformat(),
                                "days_late": delay,
                            },
                            explanation=(
                                f"Goods for {order['number']} arrived {delay} days after the "
                                "expected delivery date."
                            ),
                        )
                    )
        return findings

    # -- helpers -----------------------------------------------------------
    def _finding(
        self,
        *,
        category: str,
        anomaly_type: str,
        record: str,
        record_id: int | None,
        method: str,
        observed: Decimal | None,
        expected: Decimal | None,
        severity: str,
        evidence: dict,
        explanation: str,
    ) -> AnomalyFinding:
        deviation = None
        if observed is not None and expected is not None:
            deviation = (observed - expected).quantize(Decimal("0.01"))
        return AnomalyFinding(
            anomaly_id=f"anm-{uuid.uuid4().hex[:12]}",
            category=category,
            anomaly_type=anomaly_type,
            affected_record=record,
            affected_record_id=record_id,
            detection_method=method,
            observed_value=observed,
            expected_value=expected,
            deviation=deviation,
            severity=severity,
            evidence=evidence,
            explanation=explanation,
            detected_at=utcnow(),
        )

    def _severity_from_z(self, z: Decimal) -> str:
        if z >= 4:
            return "CRITICAL"
        if z >= 3.5:
            return "HIGH"
        if z >= 3:
            return "MEDIUM"
        return "LOW"
