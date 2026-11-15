"""The action allowlist.

Every business effect an autonomous workflow can have is declared here with its
permission, risk level, default autonomy mode, amount field and a handler that
calls an existing Phase 2 service. Nothing else is executable: an action that is
not in this registry cannot run, and no handler contains SQL, shell or eval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from app.core.constants import AutonomyMode
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger

logger = get_logger("ai.autonomy.actions")

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"


class ActionError(BizPilotError):
    default_user_message = "The workflow action could not be executed."


class ActionRestricted(ActionError):
    default_user_message = "This action is restricted and can never be automated."


class ActionUnavailable(ActionError):
    default_user_message = "This action needs a capability that is not configured."


@dataclass
class ActionContext:
    """Everything an action handler may use."""

    services: Any
    actor_id: int
    payload: dict[str, Any] = field(default_factory=dict)
    workflow_ref: str | None = None
    task_key: str | None = None

    def get(self, key: str, default: Any = None) -> Any:
        return self.payload.get(key, default)

    def amount(self, key: str = "amount") -> Decimal:
        try:
            return Decimal(str(self.payload.get(key, 0)).replace(",", "")).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")


@dataclass(frozen=True)
class ActionSpec:
    """One allowlisted action."""

    name: str
    display_name: str
    permission: str
    risk_level: str
    default_mode: str
    handler: Callable[[ActionContext], dict]
    amount_field: str | None = None
    reversible: bool = False
    compensate: Callable[[ActionContext, dict], dict] | None = None
    hard_restricted: bool = False
    description: str = ""


# ---------------------------------------------------------------------------
# read-only actions
# ---------------------------------------------------------------------------
def _retrieve_low_stock(ctx: ActionContext) -> dict:
    alerts = ctx.services.inventory_service.low_stock_alerts()
    return {
        "summary": f"{len(alerts)} product(s) at or below minimum stock.",
        "alerts": [
            {
                "product_id": alert.product_id,
                "product": alert.product_name,
                "sku": alert.sku,
                "available": alert.available_quantity,
                "minimum": alert.minimum_stock,
                "suggested_reorder": alert.suggested_reorder_quantity,
            }
            for alert in alerts
        ],
    }


def _retrieve_inventory_history(ctx: ActionContext) -> dict:
    product_id = ctx.get("product_id")
    movements = ctx.services.inventory_service.movements(product_id=product_id)
    return {
        "summary": f"{len(movements)} stock movement(s) retrieved.",
        "movements": [
            {
                "type": movement.movement_type,
                "quantity": movement.quantity,
                "before": movement.previous_quantity,
                "after": movement.new_quantity,
                "created_at": movement.created_at.isoformat() if movement.created_at else None,
            }
            for movement in movements[:20]
        ],
    }


def _retrieve_customer_history(ctx: ActionContext) -> dict:
    customer_id = ctx.get("customer_id")
    profile = ctx.services.customer_service.profile(customer_id)
    summary = profile.summary
    return {
        "summary": (
            f"{summary.full_name}: {summary.order_count} order(s), "
            f"lifetime value {summary.total_purchase}."
        ),
        "customer": {
            "id": summary.id,
            "name": summary.full_name,
            "orders": summary.order_count,
            "lifetime_value": str(summary.total_purchase),
            "last_purchase": summary.last_purchase_at.isoformat()
            if summary.last_purchase_at
            else None,
            "segment": summary.segment,
        },
    }


def _retrieve_overdue_invoices(ctx: ActionContext) -> dict:
    invoices = ctx.services.sales_service.list_invoices(status="UNPAID")
    overdue = [
        invoice
        for invoice in invoices
        if invoice.outstanding_amount > 0 and _is_overdue(invoice)
    ]
    return {
        "summary": f"{len(overdue)} overdue invoice(s) with an outstanding balance.",
        "invoices": [
            {
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "customer": invoice.customer_name,
                "outstanding": str(invoice.outstanding_amount),
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
            }
            for invoice in overdue[:20]
        ],
    }


def _is_overdue(invoice) -> bool:
    from app.utils.date_utils import utcnow

    return bool(invoice.due_date and invoice.due_date < utcnow())


def _retrieve_daily_metrics(ctx: ActionContext) -> dict:
    finance = ctx.services.finance_service.summary()
    sales = ctx.services.sales_service.dashboard()
    inventory = ctx.services.inventory_service.dashboard()
    return {
        "summary": (
            f"Revenue {finance.revenue}, cash {finance.cash_received}, "
            f"{sales.completed_orders} completed order(s)."
        ),
        "metrics": {
            "revenue": str(finance.revenue),
            "operating_expenses": str(finance.operating_expenses),
            "net_profit": str(finance.net_profit),
            "cash_received": str(finance.cash_received),
            "outstanding": str(finance.outstanding_receivables),
            "completed_orders": sales.completed_orders,
            "sales_value": str(sales.total_sales_value),
            "low_stock": inventory.low_stock_count,
        },
    }


# ---------------------------------------------------------------------------
# autonomous outputs (no business record is created)
# ---------------------------------------------------------------------------
def _create_purchase_recommendation(ctx: ActionContext) -> dict:
    alerts = ctx.services.inventory_service.low_stock_alerts()
    recommendation = {
        "summary": f"Draft recommendation for {len(alerts)} product(s).",
        "items": [
            {
                "product_id": alert.product_id,
                "product": alert.product_name,
                "sku": alert.sku,
                "suggested_quantity": alert.suggested_reorder_quantity,
                "available": alert.available_quantity,
                "minimum": alert.minimum_stock,
            }
            for alert in alerts
        ],
    }
    return recommendation


def _prepare_customer_followup(ctx: ActionContext) -> dict:
    customer = ctx.get("customer_name") or "the customer"
    draft = (
        f"Hello {customer}, we noticed it has been a while since your last order. "
        "We would be glad to help with your next purchase."
    )
    return {
        "summary": "Internal follow-up draft prepared (not sent).",
        "draft": draft,
        "channel": "INTERNAL",
        "sent": False,
    }


def _prepare_payment_reminder(ctx: ActionContext) -> dict:
    invoice_number = ctx.get("invoice_number", "the invoice")
    outstanding = ctx.get("outstanding", "0.00")
    draft = (
        f"Hello, this is a reminder that invoice {invoice_number} has an outstanding "
        f"balance of {outstanding}. Please let us know when payment is scheduled."
    )
    return {
        "summary": "Internal payment reminder drafted (not sent).",
        "draft": draft,
        "channel": "INTERNAL",
        "sent": False,
    }


def _generate_financial_report(ctx: ActionContext) -> dict:
    report = ctx.services.finance_service.build_report(
        ctx.get("report_type", "profit_and_loss")
    )
    return {
        "summary": f"{report.title} generated with {len(report.rows)} row(s).",
        "report": {
            "title": report.title,
            "headers": report.headers,
            "rows": report.rows,
            "totals": report.totals,
            "basis": report.basis,
        },
    }


def _generate_daily_report(ctx: ActionContext) -> dict:
    metrics = ctx.payload.get("metrics") or _retrieve_daily_metrics(ctx).get("metrics", {})
    headers = ["Metric", "Value"]
    rows = [[key.replace("_", " ").title(), str(value)] for key, value in metrics.items()]
    path = ctx.services.export_service.write_csv(
        f"daily_summary_{ctx.workflow_ref or 'manual'}.csv", headers, rows
    )
    return {
        "summary": f"Daily management report written to {path.name}.",
        "file": path.name,
        "rows": len(rows),
    }


# ---------------------------------------------------------------------------
# business-changing actions (approval gated)
# ---------------------------------------------------------------------------
def _create_purchase_order(ctx: ActionContext) -> dict:
    payload = {
        "supplier_id": ctx.get("supplier_id"),
        "items": ctx.get("items") or [],
        "tax_amount": ctx.get("tax_amount", "0.00"),
        "notes": ctx.get("notes") or "Created by an approved autonomous workflow",
    }
    order = ctx.services.purchasing_service.create_purchase_order(payload)
    return {
        "summary": f"Purchase order {order.purchase_order_number} created as a draft.",
        "record_type": "purchase_order",
        "record_id": order.id,
        "reference": order.purchase_order_number,
        "total": str(order.total_amount),
    }


def _cancel_purchase_order(ctx: ActionContext, result: dict) -> dict:
    order_id = result.get("record_id")
    ctx.services.purchasing_service.cancel_purchase_order(
        order_id, reason="Rolled back by workflow compensation"
    )
    return {"summary": f"Purchase order {result.get('reference')} cancelled."}


def _adjust_inventory(ctx: ActionContext) -> dict:
    payload = {
        "product_id": ctx.get("product_id"),
        "quantity": ctx.get("quantity"),
        "movement_type": ctx.get("movement_type", "ADJUSTMENT"),
        "reason": ctx.get("reason") or "Approved autonomous stock adjustment",
        "direction": ctx.get("direction", 1),
    }
    movement = ctx.services.inventory_service.adjust_stock(payload)
    return {
        "summary": (
            f"Stock adjusted for {movement.product_name}: "
            f"{movement.previous_quantity} → {movement.new_quantity}."
        ),
        "record_type": "stock_movement",
        "record_id": movement.id,
        "product_id": movement.product_id,
    }


def _record_expense(ctx: ActionContext) -> dict:
    expense = ctx.services.finance_service.create_expense(
        {
            "expense_category": ctx.get("expense_category", "OTHER"),
            "description": ctx.get("description") or "Expense recorded by workflow",
            "vendor_name": ctx.get("vendor_name"),
            "amount": str(ctx.get("amount", "0.00")),
            "payment_method": ctx.get("payment_method", "CASH"),
            "expense_date": ctx.get("expense_date"),
        }
    )
    return {
        "summary": f"Expense {expense.expense_number} recorded for {expense.amount}.",
        "record_type": "expense",
        "record_id": expense.id,
        "reference": expense.expense_number,
    }


def _reverse_expense(ctx: ActionContext, result: dict) -> dict:
    ctx.services.finance_service.reverse_expense(
        result.get("record_id"), reason="Rolled back by workflow compensation"
    )
    return {"summary": f"Expense {result.get('reference')} reversed."}


def _record_payment(ctx: ActionContext) -> dict:
    payment = ctx.services.sales_service.record_payment(
        {
            "invoice_id": ctx.get("invoice_id"),
            "amount": str(ctx.get("amount", "0.00")),
            "payment_method": ctx.get("payment_method", "CASH"),
            "payment_reference": ctx.get("payment_reference"),
        }
    )
    return {
        "summary": f"Payment of {payment.amount} recorded against invoice {payment.invoice_number}.",
        "record_type": "payment",
        "record_id": payment.id,
    }


def _change_product_price(ctx: ActionContext) -> dict:
    product = ctx.services.inventory_service.get_product(ctx.get("product_id"))
    previous = str(product.selling_price)
    updated = ctx.services.inventory_service.update_product(
        product.id,
        {
            "sku": product.sku,
            "product_name": product.product_name,
            "category_id": product.category_id,
            "unit": product.unit,
            "cost_price": str(product.cost_price),
            "selling_price": str(ctx.get("selling_price")),
            "minimum_stock": product.minimum_stock,
            "barcode": product.barcode,
            "is_active": product.is_active,
        },
    )
    return {
        "summary": f"Selling price of {updated.product_name} changed {previous} → {updated.selling_price}.",
        "record_type": "product",
        "record_id": updated.id,
        "previous_price": previous,
    }


def _restore_price(ctx: ActionContext, result: dict) -> dict:
    product = ctx.services.inventory_service.get_product(result.get("record_id"))
    ctx.services.inventory_service.update_product(
        product.id,
        {
            "sku": product.sku,
            "product_name": product.product_name,
            "category_id": product.category_id,
            "unit": product.unit,
            "cost_price": str(product.cost_price),
            "selling_price": result.get("previous_price"),
            "minimum_stock": product.minimum_stock,
            "barcode": product.barcode,
            "is_active": product.is_active,
        },
    )
    return {"summary": f"Price of {product.product_name} restored."}


def _send_customer_message(ctx: ActionContext) -> dict:
    raise ActionUnavailable(
        "No email or messaging provider is connected. The draft stays internal and "
        "nothing was sent."
    )


def _delete_financial_transaction(ctx: ActionContext) -> dict:
    raise ActionRestricted(
        "Deleting financial history is never automated, by policy or by workflow."
    )


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------
ACTIONS: tuple[ActionSpec, ...] = (
    # automatic (read-only / internal)
    ActionSpec("retrieve_low_stock", "Read low-stock alerts", "inventory.view", RISK_LOW,
               AutonomyMode.AUTOMATIC, _retrieve_low_stock,
               description="Read the current low-stock list"),
    ActionSpec("retrieve_inventory_history", "Read stock movements", "inventory.view", RISK_LOW,
               AutonomyMode.AUTOMATIC, _retrieve_inventory_history),
    ActionSpec("retrieve_customer_history", "Read customer history", "customers.view", RISK_LOW,
               AutonomyMode.AUTOMATIC, _retrieve_customer_history),
    ActionSpec("retrieve_overdue_invoices", "Read overdue invoices", "sales.view", RISK_LOW,
               AutonomyMode.AUTOMATIC, _retrieve_overdue_invoices),
    ActionSpec("retrieve_daily_metrics", "Read daily metrics", "dashboard.view", RISK_LOW,
               AutonomyMode.AUTOMATIC, _retrieve_daily_metrics),
    ActionSpec("create_purchase_recommendation", "Draft a purchase recommendation",
               "inventory.view", RISK_LOW, AutonomyMode.AUTOMATIC,
               _create_purchase_recommendation),
    ActionSpec("prepare_customer_followup", "Draft a customer follow-up", "customers.view",
               RISK_LOW, AutonomyMode.AUTOMATIC, _prepare_customer_followup),
    ActionSpec("prepare_payment_reminder", "Draft a payment reminder", "customers.view",
               RISK_LOW, AutonomyMode.AUTOMATIC, _prepare_payment_reminder),
    ActionSpec("generate_financial_report", "Generate a financial report", "finance.view",
               RISK_LOW, AutonomyMode.AUTOMATIC, _generate_financial_report),
    ActionSpec("generate_daily_report", "Generate the daily management report", "dashboard.view",
               RISK_LOW, AutonomyMode.AUTOMATIC, _generate_daily_report),
    # approval required (business changing)
    ActionSpec("create_purchase_order", "Create a purchase order", "purchase_orders.create",
               RISK_HIGH, AutonomyMode.APPROVAL, _create_purchase_order,
               amount_field="total_amount", reversible=True, compensate=_cancel_purchase_order),
    ActionSpec("adjust_inventory", "Adjust inventory", "inventory.adjust", RISK_MEDIUM,
               AutonomyMode.APPROVAL, _adjust_inventory),
    ActionSpec("record_expense", "Record an expense", "finance.create", RISK_MEDIUM,
               AutonomyMode.APPROVAL, _record_expense, amount_field="amount",
               reversible=True, compensate=_reverse_expense),
    ActionSpec("record_payment", "Record a payment", "finance.create", RISK_HIGH,
               AutonomyMode.APPROVAL, _record_payment, amount_field="amount"),
    ActionSpec("change_product_price", "Change a product price", "inventory.update",
               RISK_MEDIUM, AutonomyMode.APPROVAL, _change_product_price,
               reversible=True, compensate=_restore_price),
    ActionSpec("send_customer_message", "Send a customer message", "customers.update",
               RISK_HIGH, AutonomyMode.APPROVAL, _send_customer_message),
    # hard restricted
    ActionSpec("delete_financial_transaction", "Delete a financial transaction",
               "finance.update", RISK_HIGH, AutonomyMode.RESTRICTED,
               _delete_financial_transaction, hard_restricted=True),
)

ACTION_REGISTRY: dict[str, ActionSpec] = {spec.name: spec for spec in ACTIONS}


def get_action(name: str) -> ActionSpec:
    """Look up an action; unknown names are refused (default deny)."""
    spec = ACTION_REGISTRY.get(name)
    if spec is None:
        raise ActionRestricted(f"'{name}' is not an allowlisted workflow action")
    return spec


def is_registered(name: str) -> bool:
    return name in ACTION_REGISTRY


def action_names() -> list[str]:
    return sorted(ACTION_REGISTRY)
