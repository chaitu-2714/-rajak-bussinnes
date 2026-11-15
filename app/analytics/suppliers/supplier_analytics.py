"""Supplier performance analytics from purchase orders and goods receipts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.analytics.data_collector import BusinessDataset
from app.analytics.schemas import DataIssue, DataQuality, SupplierAnalytics, money
from app.utils.date_utils import utcnow

ZERO = Decimal("0.00")


class AdvancedSupplierAnalytics:
    """Delivery and price analysis; lead times only from real receipts."""

    def analyze(self, dataset: BusinessDataset, *, quality: DataQuality | None = None) -> SupplierAnalytics:
        period = dataset.period
        orders = [
            order
            for order in dataset.purchase_orders
            if order["created_at"] and period.start <= order["created_at"] <= period.end
        ]
        receipts = [
            receipt
            for receipt in dataset.receipts
            if receipt["received_at"] and period.start <= receipt["received_at"] <= period.end
        ]
        receipt_by_order: dict[str, list[dict]] = {}
        for receipt in receipts:
            receipt_by_order.setdefault(receipt["order"], []).append(receipt)

        quality = quality or DataQuality()
        with_expected = [order for order in orders if order["expected"] is not None]
        if orders and not with_expected:
            quality.issues.append(
                DataIssue(
                    code="NO_EXPECTED_DELIVERY_DATES",
                    severity="INFO",
                    message="Purchase orders have no expected delivery dates, so on-time "
                    "delivery cannot be measured; only receipt-based lead times are shown.",
                    count=len(orders),
                )
            )

        on_time = 0
        measurable = 0
        lead_times: list[Decimal] = []
        delayed = 0
        for order in orders:
            order_receipts = receipt_by_order.get(order["number"], [])
            if not order_receipts:
                continue
            first_receipt = min(receipt["received_at"] for receipt in order_receipts)
            lead_times.append(
                Decimal(str(max(0, (first_receipt - order["created_at"]).days)))
            )
            if order["expected"] is not None:
                measurable += 1
                if first_receipt <= order["expected"]:
                    on_time += 1
                else:
                    delayed += 1

        on_time_percent = (
            (Decimal(on_time) / Decimal(measurable) * 100).quantize(Decimal("0.01"))
            if measurable
            else None
        )
        average_lead = (
            (sum(lead_times, ZERO) / Decimal(len(lead_times))).quantize(Decimal("0.01"))
            if lead_times
            else None
        )

        ordered_qty = sum(int(order["ordered_quantity"]) for order in orders)
        received_qty = sum(int(order["received_quantity"]) for order in orders)
        fulfilment = (
            (Decimal(received_qty) / Decimal(ordered_qty) * 100).quantize(Decimal("0.01"))
            if ordered_qty
            else None
        )

        totals: dict[str, Decimal] = {}
        for order in orders:
            totals[order["supplier"]] = totals.get(order["supplier"], ZERO) + Decimal(
                str(order["total"])
            )
        grand = sum(totals.values(), ZERO)
        top3 = (
            (sum(sorted(totals.values(), reverse=True)[:3], ZERO) / grand * 100).quantize(
                Decimal("0.01")
            )
            if grand > ZERO
            else ZERO
        )

        return SupplierAnalytics(
            period_label=period.label,
            supplier_count=len(dataset.suppliers),
            purchase_order_count=len(orders),
            purchase_value=money(grand),
            receipt_count=len(receipts),
            on_time_delivery_percent=on_time_percent,
            average_lead_time_days=average_lead,
            delayed_orders=delayed,
            fulfilment_percent=fulfilment,
            concentration_top3_percent=top3,
            supplier_rows=self._supplier_rows(dataset, orders, receipt_by_order),
            price_trends=self.price_trends(dataset),
            quality=quality,
        )

    def _supplier_rows(
        self,
        dataset: BusinessDataset,
        orders: list[dict],
        receipt_by_order: dict[str, list[dict]],
    ) -> list[dict]:
        rows: list[dict] = []
        by_supplier: dict[str, list[dict]] = {}
        for order in orders:
            by_supplier.setdefault(order["supplier"], []).append(order)
        for supplier, supplier_orders in sorted(by_supplier.items()):
            received = [o for o in supplier_orders if receipt_by_order.get(o["number"])]
            leads = []
            on_time = 0
            measurable = 0
            for order in received:
                first = min(r["received_at"] for r in receipt_by_order[order["number"]])
                leads.append(Decimal(str(max(0, (first - order["created_at"]).days))))
                if order["expected"] is not None:
                    measurable += 1
                    if first <= order["expected"]:
                        on_time += 1
            rows.append(
                {
                    "supplier": supplier,
                    "orders": len(supplier_orders),
                    "received_orders": len(received),
                    "value": str(money(sum((Decimal(str(o["total"])) for o in supplier_orders), ZERO))),
                    "average_lead_time_days": str(
                        (sum(leads, ZERO) / Decimal(len(leads))).quantize(Decimal("0.01"))
                    )
                    if leads
                    else "not measurable",
                    "on_time_percent": str(
                        (Decimal(on_time) / Decimal(measurable) * 100).quantize(Decimal("0.01"))
                    )
                    if measurable
                    else "not measurable",
                    "note": ""
                    if measurable
                    else "no expected delivery date recorded",
                }
            )
        return rows

    def price_trends(self, dataset: BusinessDataset) -> list[dict]:
        """Average purchase unit cost per product across recorded purchase orders."""
        series: dict[int, dict] = {}
        for order in dataset.purchase_orders:
            for line in order["lines"]:
                entry = series.setdefault(
                    line["product_id"],
                    {"product": line["product"], "prices": []},
                )
                entry["prices"].append(
                    {
                        "date": order["created_at"],
                        "unit_cost": Decimal(str(line["unit_cost"])),
                    }
                )
        rows: list[dict] = []
        for entry in series.values():
            prices = sorted(entry["prices"], key=lambda item: item["date"])
            if len(prices) < 2:
                continue
            first, last = prices[0]["unit_cost"], prices[-1]["unit_cost"]
            change = (
                ((last - first) / first * 100).quantize(Decimal("0.01")) if first > ZERO else None
            )
            rows.append(
                {
                    "product": entry["product"],
                    "first_unit_cost": str(money(first)),
                    "latest_unit_cost": str(money(last)),
                    "change_percent": str(change) if change is not None else "not calculable",
                    "observations": len(prices),
                }
            )
        return rows
