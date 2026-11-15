"""Inventory analytics: movement, cover, slow/non-moving stock, turnover."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.analytics.data_collector import BusinessDataset
from app.analytics.schemas import DataIssue, DataQuality, InventoryAnalytics, money
from app.utils.date_utils import utcnow

ZERO = Decimal("0.00")

SLOW_MOVING_DAYS = 60      # no sale for 60 days
NON_MOVING_DAYS = 90       # no sale for 90 days
OVERSTOCK_DAYS_COVER = 90  # more than 90 days of cover at current demand


class AdvancedInventoryAnalytics:
    """Stock analytics that never guesses at demand or cost."""

    def analyze(self, dataset: BusinessDataset, *, quality: DataQuality | None = None) -> InventoryAnalytics:
        period = dataset.period
        now = utcnow()
        stock_rows = dataset.stock
        units_on_hand = sum(int(row["available"]) for row in stock_rows)
        inventory_value = money(sum((Decimal(str(row["value"])) for row in stock_rows), ZERO))
        low_stock = [row for row in stock_rows if row["is_low"]]
        stockouts = [row for row in stock_rows if int(row["available"]) <= 0]

        sold_by_product: dict[int, int] = {}
        for line in dataset.lines:
            sold_by_product[line["product_id"]] = sold_by_product.get(line["product_id"], 0) + int(
                line["quantity"]
            )

        last_sale: dict[int, object] = {}
        for line in dataset.lines:
            current = last_sale.get(line["product_id"])
            if current is None or line["created_at"] > current:
                last_sale[line["product_id"]] = line["created_at"]

        days = max(1, period.days)
        demand: list[dict] = []
        slow: list[dict] = []
        non_moving: list[dict] = []
        overstock: list[dict] = []

        for row in stock_rows:
            product_id = row["product_id"]
            sold = sold_by_product.get(product_id, 0)
            daily = (Decimal(sold) / Decimal(days)).quantize(Decimal("0.01"))
            cover = (
                (Decimal(int(row["available"])) / daily).quantize(Decimal("0.01"))
                if daily > ZERO
                else None
            )
            demand.append(
                {
                    "product": row["product"],
                    "sku": row["sku"],
                    "available": int(row["available"]),
                    "sold": sold,
                    "units_per_day": str(daily),
                    "days_of_cover": str(cover) if cover is not None else "not calculable",
                }
            )
            last = last_sale.get(product_id)
            days_since = (now - last).days if last else None
            if sold == 0:
                status = self._no_sale_status(row, dataset, days_since)
                entry = {
                    "product": row["product"],
                    "sku": row["sku"],
                    "available": int(row["available"]),
                    "value": str(money(Decimal(str(row["value"])))),
                    "status": status,
                    "note": self._no_sale_note(status),
                }
                if status == "NON_MOVING_STOCK":
                    non_moving.append(entry)
                elif status == "SLOW_MOVING_STOCK":
                    slow.append(entry)
            elif days_since is not None and days_since >= SLOW_MOVING_DAYS:
                slow.append(
                    {
                        "product": row["product"],
                        "sku": row["sku"],
                        "available": int(row["available"]),
                        "value": str(money(Decimal(str(row["value"])))),
                        "status": "SLOW_MOVING_STOCK",
                        "note": f"last sold {days_since} days ago",
                    }
                )
            if cover is not None and cover > OVERSTOCK_DAYS_COVER:
                overstock.append(
                    {
                        "product": row["product"],
                        "sku": row["sku"],
                        "available": int(row["available"]),
                        "days_of_cover": str(cover),
                        "note": f"more than {OVERSTOCK_DAYS_COVER} days of cover at current demand",
                    }
                )

        turnover, basis = self._turnover(dataset, inventory_value)

        return InventoryAnalytics(
            period_label=period.label,
            sku_count=len(stock_rows),
            units_on_hand=units_on_hand,
            inventory_value=inventory_value,
            low_stock_count=len(low_stock),
            stockout_products=len(stockouts),
            slow_moving=slow,
            non_moving=non_moving,
            overstock=overstock,
            turnover_ratio=turnover,
            turnover_basis=basis,
            average_days_of_cover=self._average_cover(demand),
            demand=sorted(demand, key=lambda row: row["sold"], reverse=True)[:20],
            quality=quality or DataQuality(),
        )

    # -- turnover ----------------------------------------------------------
    def _turnover(self, dataset: BusinessDataset, inventory_value: Decimal) -> tuple[Decimal | None, str]:
        """Turnover needs reliable COGS and an inventory valuation."""
        cogs = money(dataset.finance_summary.get("cogs"))
        missing_cost = [p for p in dataset.products if Decimal(str(p["cost_price"])) <= ZERO]
        if missing_cost:
            return (
                None,
                "Not calculated: cost of goods sold is unreliable because "
                f"{len(missing_cost)} product(s) have no cost price.",
            )
        if cogs <= ZERO:
            return None, "Not calculated: no cost of goods sold was recorded in this period."
        if inventory_value <= ZERO:
            return None, "Not calculated: inventory has no recorded valuation."
        ratio = (cogs / inventory_value).quantize(Decimal("0.01"))
        return (
            ratio,
            "Cost of goods sold ÷ current inventory value (quantity-based alternative: "
            f"{self._quantity_turnover(dataset)} units sold per unit on hand).",
        )

    def _quantity_turnover(self, dataset: BusinessDataset) -> str:
        units_sold = sum(int(line["quantity"]) for line in dataset.lines)
        on_hand = sum(int(row["available"]) for row in dataset.stock)
        if on_hand <= 0:
            return "not calculable"
        return str((Decimal(units_sold) / Decimal(on_hand)).quantize(Decimal("0.01")))

    def _average_cover(self, demand: list[dict]) -> Decimal | None:
        values = [
            Decimal(row["days_of_cover"])
            for row in demand
            if row["days_of_cover"] not in ("not calculable", None)
        ]
        if not values:
            return None
        return (sum(values, ZERO) / Decimal(len(values))).quantize(Decimal("0.01"))

    # -- no-sale explanations ---------------------------------------------
    def _no_sale_status(self, row: dict, dataset: BusinessDataset, days_since: int | None) -> str:
        product = next((p for p in dataset.products if p["id"] == row["product_id"]), None)
        if product is not None and not product.get("is_active", True):
            return "PRODUCT_INACTIVE"
        if int(row["available"]) <= 0:
            return "NO_STOCK_AVAILABLE"
        if days_since is not None and days_since >= NON_MOVING_DAYS:
            return "NON_MOVING_STOCK"
        if days_since is not None and days_since >= SLOW_MOVING_DAYS:
            return "SLOW_MOVING_STOCK"
        return "NO_SALES_RECORDED"

    def _no_sale_note(self, status: str) -> str:
        return {
            "PRODUCT_INACTIVE": "The product is not available for sale.",
            "NO_STOCK_AVAILABLE": "No stock is available, so it could not be sold.",
            "NON_MOVING_STOCK": f"No sale for more than {NON_MOVING_DAYS} days. This is not proof "
            "that the product is obsolete.",
            "SLOW_MOVING_STOCK": f"No sale for more than {SLOW_MOVING_DAYS} days.",
            "NO_SALES_RECORDED": "No sale was recorded in this period; it may simply be outside it.",
        }[status]

    # -- stockout frequency ------------------------------------------------
    def stockout_frequency(self, dataset: BusinessDataset) -> dict:
        """Counts products whose stock reached zero during the period."""
        hits = 0
        products = set()
        for movement in dataset.movements:
            if int(movement["after"]) <= 0:
                hits += 1
                products.add(movement["product_id"])
        return {
            "events": hits,
            "products": len(products),
            "basis": "stock movements that ended at zero units during the period",
        }
