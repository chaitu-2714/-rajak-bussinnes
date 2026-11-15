"""Data collection: pull real business records through the service layer.

Nothing is cached here and nothing is invented: every figure the analytics
package reports traces back to a row these methods read. Permission checks are
performed by the services themselves, so analytics inherits the user's RBAC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.analytics.periods import AnalyticsPeriod
from app.core.logging_config import get_logger

logger = get_logger("analytics.collector")

ZERO = Decimal("0.00")


@dataclass
class BusinessDataset:
    """Raw records for one reporting period (plus the comparison period)."""

    period: AnalyticsPeriod
    comparison: AnalyticsPeriod | None = None
    orders: list[dict[str, Any]] = field(default_factory=list)
    lines: list[dict[str, Any]] = field(default_factory=list)
    cancelled_orders: list[dict[str, Any]] = field(default_factory=list)
    invoices: list[dict[str, Any]] = field(default_factory=list)
    expenses: list[dict[str, Any]] = field(default_factory=list)
    transactions: list[dict[str, Any]] = field(default_factory=list)
    products: list[dict[str, Any]] = field(default_factory=list)
    stock: list[dict[str, Any]] = field(default_factory=list)
    movements: list[dict[str, Any]] = field(default_factory=list)
    customers: list[dict[str, Any]] = field(default_factory=list)
    purchase_orders: list[dict[str, Any]] = field(default_factory=list)
    receipts: list[dict[str, Any]] = field(default_factory=list)
    suppliers: list[dict[str, Any]] = field(default_factory=list)
    finance_summary: dict[str, Any] = field(default_factory=dict)
    previous_finance_summary: dict[str, Any] = field(default_factory=dict)
    previous_orders: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_sales(self) -> bool:
        return bool(self.orders)


class BusinessDataCollector:
    """Reads the records the analytics modules need, within a period."""

    def __init__(self, services: Any) -> None:
        self._services = services

    # -- main entry --------------------------------------------------------
    def collect_business_data(
        self, period: AnalyticsPeriod, *, comparison: AnalyticsPeriod | None = None
    ) -> BusinessDataset:
        dataset = BusinessDataset(period=period, comparison=comparison)
        dataset.orders, dataset.cancelled_orders, dataset.lines = self._collect_orders(period)
        dataset.expenses = self._collect_expenses(period)
        dataset.transactions = self._collect_transactions(period)
        dataset.invoices = self._collect_invoices()
        dataset.products = self._collect_products()
        dataset.stock = self._collect_stock()
        dataset.movements = self._collect_movements()
        dataset.customers = self._collect_customers()
        dataset.purchase_orders, dataset.receipts = self._collect_purchasing()
        dataset.suppliers = self._collect_suppliers()
        dataset.finance_summary = self._collect_finance_summary(period)
        if comparison is not None:
            dataset.previous_orders, _, _ = self._collect_orders(comparison)
            dataset.previous_finance_summary = self._collect_finance_summary(comparison)
        return dataset

    # -- collectors --------------------------------------------------------
    def _collect_orders(self, period: AnalyticsPeriod):
        orders: list[dict[str, Any]] = []
        cancelled: list[dict[str, Any]] = []
        lines: list[dict[str, Any]] = []
        for order in self._services.sales_service.list_orders(
            date_from=period.start, date_to=period.end
        ):
            record = {
                "id": order.id,
                "number": order.order_number,
                "customer_id": order.customer_id,
                "customer": order.customer_name,
                "status": order.order_status,
                "total": order.total_amount,
                "subtotal": order.subtotal,
                "discount": order.discount_amount,
                "tax": order.tax_amount,
                "paid": order.paid_amount,
                "outstanding": order.outstanding_amount,
                "created_at": order.created_at,
                "invoice_id": order.invoice_id,
            }
            if order.order_status == "COMPLETED":
                orders.append(record)
                for line in order.lines:
                    lines.append(
                        {
                            "order_id": order.id,
                            "order_number": order.order_number,
                            "created_at": order.created_at,
                            "customer_id": order.customer_id,
                            "customer": order.customer_name,
                            "product_id": line.product_id,
                            "product": line.product_name,
                            "sku": line.sku,
                            "quantity": line.quantity,
                            "unit_price": line.unit_price,
                            "line_total": line.line_total,
                        }
                    )
            elif order.order_status == "CANCELLED":
                cancelled.append(record)
        return orders, cancelled, lines

    def _collect_expenses(self, period: AnalyticsPeriod) -> list[dict[str, Any]]:
        return [
            {
                "id": expense.id,
                "number": expense.expense_number,
                "category": expense.expense_category,
                "description": expense.description,
                "vendor": expense.vendor_name,
                "amount": expense.amount,
                "date": expense.expense_date,
                "status": expense.status,
            }
            for expense in self._services.finance_service.list_expenses(
                date_from=period.start, date_to=period.end
            )
        ]

    def _collect_transactions(self, period: AnalyticsPeriod) -> list[dict[str, Any]]:
        return [
            {
                "id": row.id,
                "number": row.transaction_number,
                "type": row.transaction_type,
                "category": row.category,
                "amount": row.amount,
                "date": row.transaction_date,
                "reference_type": row.reference_type,
                "reference_id": row.reference_id,
                "description": row.description,
            }
            for row in self._services.finance_service.list_transactions(
                date_from=period.start, date_to=period.end, limit=1000
            )
        ]

    def _collect_invoices(self) -> list[dict[str, Any]]:
        return [
            {
                "id": invoice.id,
                "number": invoice.invoice_number,
                "customer_id": None,
                "customer": invoice.customer_name,
                "total": invoice.total_amount,
                "paid": invoice.paid_amount,
                "outstanding": invoice.outstanding_amount,
                "status": invoice.status,
                "invoice_date": invoice.invoice_date,
                "due_date": invoice.due_date,
            }
            for invoice in self._services.sales_service.list_invoices()
        ]

    def _collect_products(self) -> list[dict[str, Any]]:
        return [
            {
                "id": product.id,
                "sku": product.sku,
                "product": product.product_name,
                "category": product.category_name,
                "unit": product.unit,
                "cost_price": product.cost_price,
                "selling_price": product.selling_price,
                "minimum_stock": product.minimum_stock,
                "is_active": getattr(product, "is_active", True),
            }
            for product in self._services.inventory_service.list_products()
        ]

    def _collect_stock(self) -> list[dict[str, Any]]:
        return [
            {
                "product_id": row.product_id,
                "sku": row.sku,
                "product": row.product_name,
                "category": row.category_name,
                "unit": row.unit,
                "available": row.available_quantity,
                "minimum": row.minimum_stock,
                "cost_price": row.cost_price,
                "selling_price": row.selling_price,
                "value": row.cost_price * row.available_quantity,
                "is_low": row.is_low,
            }
            for row in self._services.inventory_service.list_stock()
        ]

    def _collect_movements(self) -> list[dict[str, Any]]:
        return [
            {
                "id": movement.id,
                "product_id": movement.product_id,
                "product": movement.product_name,
                "type": movement.movement_type,
                "quantity": movement.quantity,
                "before": movement.previous_quantity,
                "after": movement.new_quantity,
                "date": movement.created_at,
                "reference_type": movement.reference_type,
            }
            for movement in self._services.inventory_service.movements()
        ]

    def _collect_customers(self) -> list[dict[str, Any]]:
        return [
            {
                "id": customer.id,
                "name": customer.full_name,
                "type": customer.customer_type,
                "active": customer.is_active,
                "created_at": customer.created_at,
                "orders": customer.order_count,
                "total_purchase": customer.total_purchase,
                "last_purchase": customer.last_purchase_at,
                "segment": customer.segment,
            }
            for customer in self._services.customer_service.list_customers()
        ]

    def _collect_purchasing(self):
        orders = [
            {
                "id": order.id,
                "number": order.purchase_order_number,
                "supplier_id": order.supplier_id,
                "supplier": order.supplier_name,
                "status": order.status,
                "total": order.total_amount,
                "expected": order.expected_delivery_date,
                "created_at": order.created_at,
                "ordered_quantity": order.ordered_quantity,
                "received_quantity": order.received_quantity,
                "receipt_count": order.receipt_count,
                "lines": [
                    {
                        "product_id": line.product_id,
                        "product": line.product_name,
                        "quantity": line.ordered_quantity,
                        "unit_cost": line.unit_cost,
                    }
                    for line in order.lines
                ],
            }
            for order in self._services.purchasing_service.list_purchase_orders()
        ]
        receipts = [
            {
                "id": receipt.id,
                "number": receipt.receipt_number,
                "order": receipt.purchase_order_number,
                "received_at": receipt.received_at,
                "quantity": receipt.total_quantity,
            }
            for receipt in self._services.purchasing_service.list_receipts()
        ]
        return orders, receipts

    def _collect_suppliers(self) -> list[dict[str, Any]]:
        return [
            {
                "id": supplier.id,
                "name": supplier.supplier_name,
                "active": getattr(supplier, "is_active", True),
                "lead_time_days": getattr(supplier, "lead_time_days", None),
            }
            for supplier in self._services.purchasing_service.list_suppliers()
        ]

    def _collect_finance_summary(self, period: AnalyticsPeriod) -> dict[str, Any]:
        summary = self._services.finance_service.summary(
            date_from=period.start, date_to=period.end
        )
        return {
            "revenue": summary.revenue,
            "cogs": summary.cogs,
            "gross_profit": summary.gross_profit,
            "operating_expenses": summary.operating_expenses,
            "net_profit": summary.net_profit,
            "total_expenses": summary.total_expenses,
            "cash_received": summary.cash_received,
            "refunds_paid": summary.refunds_paid,
            "outstanding_receivables": summary.outstanding_receivables,
            "transaction_count": summary.transaction_count,
            "basis": summary.basis,
        }
