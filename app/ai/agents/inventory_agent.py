"""Inventory Agent: stock health, replenishment, overstock and dead stock."""

from __future__ import annotations

from typing import Any

from app.ai.agent_tools.inventory_tools import (
    ReorderPolicy,
    build_purchase_recommendations,
    calculate_reorder,
    detect_dead_stock,
    detect_low_stock,
    detect_overstock,
)
from app.ai.agents.base_agent import BaseBusinessAgent, ToolRunner
from app.ai.schemas.agent_schema import AgentTask, Finding, Recommendation
from app.ai.schemas.intent_schema import Intent

TASK_INVENTORY_ANALYSIS = "INVENTORY_ANALYSIS"
TASK_REORDER = "REORDER_PLANNING"


class InventoryAgent(BaseBusinessAgent):
    """Analyses stock levels, demand-aware replenishment and stock risk."""

    agent_id = "inventory_agent"
    name = "Inventory Agent"
    description = (
        "Stock monitoring, demand-aware reorder points, overstock and dead-stock detection"
    )
    intents = (
        Intent.CHECK_STOCK,
        Intent.LOW_STOCK_ANALYSIS,
        Intent.CREATE_PURCHASE_RECOMMENDATION,
        Intent.GENERATE_INVENTORY_REPORT,
    )
    task_types = (TASK_INVENTORY_ANALYSIS, TASK_REORDER)
    default_task_type = TASK_INVENTORY_ANALYSIS
    data_tools = (
        "get_product_stock",
        "get_low_stock_products",
        "get_stock_valuation",
        "get_product_velocity",
        "get_supplier_details",
    )
    capabilities = (
        "calculate_reorder_quantity",
        "detect_overstock",
        "detect_dead_stock",
        "get_stock_movements",
        "generate_inventory_report",
    )
    required_permissions = ("inventory.view",)

    def __init__(self, *, policy: ReorderPolicy | None = None) -> None:
        super().__init__()
        self._policy = policy or ReorderPolicy()

    def collect_context(
        self, task: AgentTask, runner: ToolRunner
    ) -> tuple[dict[str, Any], list[str], list[str]]:
        used: list[str] = []
        failures: list[str] = []

        context: dict[str, Any] = {
            "stock": self._call(
                runner, "get_product_stock", {}, used=used, failures=failures
            ),
            "low_stock": self._call(
                runner, "get_low_stock_products", {}, used=used, failures=failures
            ),
            "valuation": self._call(
                runner, "get_stock_valuation", {}, used=used, failures=failures
            ),
            "velocity": self._call(
                runner, "get_product_velocity", {"window_days": 30}, used=used, failures=failures
            ),
            "supplier": self._call(
                runner, "get_supplier_details", {}, used=used, failures=failures
            ),
        }
        return context, used, failures

    def analyse(
        self, task: AgentTask, context: dict[str, Any], failures: list[str]
    ) -> tuple[list[Finding], list[Recommendation], dict[str, Any], list[str]]:
        period_label = task.period_label
        findings: list[Finding] = []
        metrics: dict[str, Any] = {}
        gaps: list[str] = []

        stock_rows = context.get("stock", {}).get("products", []) or []
        if not stock_rows:
            gaps.append("product stock records (the catalogue is empty)")

        low_findings, low_metrics = detect_low_stock(
            stock_rows=stock_rows, period_label=period_label
        )
        findings.extend(low_findings)
        metrics.update(low_metrics)

        valuation = context.get("valuation", {})
        metrics["total_stock_value"] = valuation.get("total_stock_value", "0.00")
        metrics["total_quantity"] = valuation.get("total_quantity", 0)
        metrics["valuation_method"] = valuation.get("valuation_method")

        velocity_rows = context.get("velocity", {}).get("products", []) or []
        velocity_by_sku = {
            str(row.get("sku")): float(row.get("units_per_day", 0) or 0) for row in velocity_rows
        }
        last_sold = {
            str(row.get("sku")): row.get("last_sold") for row in velocity_rows
        }
        metrics["products_with_sales"] = len(velocity_rows)
        if not velocity_rows:
            gaps.append("sales velocity (no completed sales in the last 30 days)")

        reorder_rows: list[dict] = []
        for row in stock_rows:
            sku = str(row.get("sku"))
            available = int(row.get("available", 0) or 0)
            minimum = int(row.get("minimum", 0) or 0)
            rate = velocity_by_sku.get(sku)
            if rate is None and available > minimum:
                continue
            calculation = calculate_reorder(
                available=available,
                minimum=minimum,
                units_per_day=rate,
                policy=self._policy,
                lead_time_days=None,
            )
            calculation.update({"product": row.get("product"), "sku": sku})
            reorder_rows.append(calculation)

        metrics["reorder_analysis"] = reorder_rows[:10]
        if reorder_rows:
            missing = sorted({item for row in reorder_rows for item in row["missing_inputs"]})
            if missing:
                gaps.extend(missing[:2])

        over_findings, overstocked = detect_overstock(
            stock_rows=stock_rows,
            velocity_by_product=velocity_by_sku,
            policy=self._policy,
        )
        findings.extend(over_findings)
        metrics["overstocked_products"] = overstocked[:5]

        dead_findings, dead = detect_dead_stock(
            stock_rows=stock_rows, last_sold=last_sold, policy=self._policy
        )
        findings.extend(dead_findings)
        metrics["dead_stock_products"] = dead[:5]

        supplier_name = context.get("supplier", {}).get("supplier")
        recommendations = build_purchase_recommendations(
            reorder_rows=reorder_rows,
            stock_rows=stock_rows,
            policy=self._policy,
            supplier_name=supplier_name,
        )
        if failures:
            gaps.append(f"tools unavailable: {', '.join(sorted(set(failures)))}")

        return findings, recommendations, metrics, gaps
