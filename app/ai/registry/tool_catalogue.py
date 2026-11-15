"""The registered tool catalogue.

Every tool is a thin adapter over an existing Phase 2 service. No tool issues SQL,
executes Python or touches the database directly.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.ai.registry.tool_inputs import (
    CustomerRef,
    EmptyArgs,
    HistoryArgs,
    InactiveCustomersArgs,
    LimitArgs,
    MovementsArgs,
    PeriodArgs,
    PrepareExpenseArgs,
    PrepareSalesOrderArgs,
    ProductRef,
    PurchaseOrderStatusArgs,
    PurchaseRecommendationArgs,
    ReportArgs,
    SupplierRef,
    TopProductsArgs,
    TrendArgs,
)
from app.ai.registry.tool_registry import ToolRegistry
from app.ai.schemas.tool_schema import ToolContext, ToolDefinition
from app.core.constants import AIRiskLevel
from app.core.exceptions import NotFoundError
from app.database.types import ZERO, to_money
from app.utils.date_utils import local_to_utc, to_local, utcnow

PERIOD_LABELS = {
    "today": "today",
    "this_week": "this week",
    "this_month": "this month",
    "last_month": "last month",
    "this_year": "this year",
    "last_30_days": "the last 30 days",
    "all_time": "all recorded time",
}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def resolve_period(
    period: str | None, date_from: datetime | None = None, date_to: datetime | None = None
) -> tuple[datetime | None, datetime | None, str]:
    """Turn a named period into UTC boundaries plus a human label."""
    if period in (None, "all_time"):
        label = "all recorded time" if not (date_from or date_to) else "the selected dates"
        return date_from, date_to, label

    now_local = to_local(utcnow())
    end_local = now_local

    if period == "today":
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "this_week":
        start_local = (now_local - timedelta(days=now_local.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "this_month":
        start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "last_month":
        first_this_month = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_local = (first_this_month - timedelta(days=1)).replace(day=1)
        end_local = first_this_month - timedelta(seconds=1)
    elif period == "this_year":
        start_local = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "last_30_days":
        start_local = now_local - timedelta(days=30)
    else:  # pragma: no cover - guarded by the schema Literal
        return date_from, date_to, "all recorded time"

    return local_to_utc(start_local), local_to_utc(end_local), PERIOD_LABELS.get(period, period)


def _money(value) -> str:
    return f"{to_money(value):,.2f}"


def _find_product(context: ToolContext, ref: ProductRef | PurchaseRecommendationArgs | None):
    service = context.services.inventory_service
    if ref is None:
        return None
    product_id = getattr(ref, "product_id", None)
    sku = getattr(ref, "sku", None)
    name = getattr(ref, "product_name", None)
    if product_id:
        try:
            return service.get_product(product_id)
        except NotFoundError:
            return None
    products = service.list_products()
    if sku:
        match = next((p for p in products if p.sku.lower() == sku.lower()), None)
        if match:
            return match
    if name:
        lowered = name.lower().strip()
        exact = next((p for p in products if p.product_name.lower() == lowered), None)
        if exact:
            return exact
        partial = [p for p in products if lowered in p.product_name.lower()]
        if len(partial) == 1:
            return partial[0]
        if partial:
            return partial[0]
    return None


def _find_customer(context: ToolContext, ref: CustomerRef | PrepareSalesOrderArgs | None):
    service = context.services.customer_service
    if ref is None:
        return None
    customer_id = getattr(ref, "customer_id", None)
    name = getattr(ref, "customer_name", None)
    if customer_id:
        try:
            return service.get_customer(customer_id)
        except NotFoundError:
            return None
    if name:
        matches = service.list_customers(search=name.strip())
        if matches:
            return matches[0]
    return None


def _find_supplier(context: ToolContext, ref: SupplierRef | None):
    service = context.services.purchasing_service
    if ref is None:
        return None
    supplier_id = getattr(ref, "supplier_id", None)
    name = getattr(ref, "supplier_name", None)
    if supplier_id:
        try:
            return service.get_supplier(supplier_id)
        except NotFoundError:
            return None
    if name:
        matches = service.list_suppliers(search=name.strip())
        if matches:
            return matches[0]
    return None


# ---------------------------------------------------------------------------
# finance tools
# ---------------------------------------------------------------------------
def _get_revenue(context: ToolContext, args: PeriodArgs) -> dict:
    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    summary = context.services.finance_service.summary(date_from=date_from, date_to=date_to)
    return {
        "period": label,
        "revenue": _money(summary.revenue),
        "refunds_paid": _money(summary.refunds_paid),
        "basis": summary.basis,
        "summary": f"Revenue for {label} is {_money(summary.revenue)} (net of refunds).",
    }


def _get_expenses(context: ToolContext, args: PeriodArgs) -> dict:
    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    service = context.services.finance_service
    summary = service.summary(date_from=date_from, date_to=date_to)
    expenses = service.list_expenses(date_from=date_from, date_to=date_to)
    by_category: dict[str, Decimal] = {}
    for expense in expenses:
        if expense.status != "RECORDED":
            continue
        by_category[expense.expense_category] = by_category.get(
            expense.expense_category, ZERO
        ) + to_money(expense.amount)
    breakdown = [
        {"category": category, "amount": _money(amount)}
        for category, amount in sorted(by_category.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "period": label,
        "operating_expenses": _money(summary.operating_expenses),
        "capital_purchases": _money(summary.total_expenses - summary.cogs - summary.operating_expenses),
        "breakdown": breakdown,
        "expense_count": len(expenses),
        "summary": (
            f"Operating expenses for {label} total {_money(summary.operating_expenses)} "
            f"across {len(expenses)} record(s)."
        ),
    }


def _calculate_profit(context: ToolContext, args: PeriodArgs) -> dict:
    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    summary = context.services.finance_service.summary(date_from=date_from, date_to=date_to)
    return {
        "period": label,
        "revenue": _money(summary.revenue),
        "cogs": _money(summary.cogs),
        "gross_profit": _money(summary.gross_profit),
        "operating_expenses": _money(summary.operating_expenses),
        "net_profit": _money(summary.net_profit),
        "basis": summary.basis,
        "summary": (
            f"Gross profit {_money(summary.gross_profit)} "
            f"(revenue {_money(summary.revenue)} − COGS {_money(summary.cogs)}); "
            f"net profit {_money(summary.net_profit)} after "
            f"{_money(summary.operating_expenses)} operating expenses."
        ),
    }


def _get_cash_flow(context: ToolContext, args: PeriodArgs) -> dict:
    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    summary = context.services.finance_service.summary(date_from=date_from, date_to=date_to)
    net_cash = to_money(summary.cash_received - summary.refunds_paid - summary.operating_expenses)
    return {
        "period": label,
        "cash_received": _money(summary.cash_received),
        "refunds_paid": _money(summary.refunds_paid),
        "expenses_paid": _money(summary.operating_expenses),
        "net_cash_movement": _money(net_cash),
        "outstanding_receivables": _money(summary.outstanding_receivables),
        "summary": (
            f"Cash received {_money(summary.cash_received)}, refunds {_money(summary.refunds_paid)}, "
            f"expenses {_money(summary.operating_expenses)} → net cash movement {_money(net_cash)}. "
            f"Outstanding receivables {_money(summary.outstanding_receivables)}."
        ),
    }


def _get_outstanding_payments(context: ToolContext, args: EmptyArgs) -> dict:
    report = context.services.finance_service.build_report("outstanding")
    rows = [
        {
            "invoice": row[0],
            "date": row[1],
            "customer": row[2],
            "total": row[3],
            "paid": row[4],
            "outstanding": row[5],
            "due": row[6],
        }
        for row in report.rows[:20]
    ]
    total = report.totals[-1] if report.totals else "0.00"
    return {
        "invoice_count": len(report.rows),
        "total_outstanding": total,
        "invoices": rows,
        "summary": f"{len(report.rows)} unpaid invoice(s) totalling {total}.",
    }


def _generate_financial_report(context: ToolContext, args: ReportArgs) -> dict:
    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    path = context.services.finance_service.export_report(
        args.report_type,
        file_format=args.file_format,
        date_from=date_from,
        date_to=date_to,
    )
    return {
        "report_type": args.report_type,
        "format": args.file_format,
        "path": str(path),
        "period": label,
        "summary": f"{args.report_type.replace('_', ' ').title()} report saved as {args.file_format.upper()}.",
    }


# ---------------------------------------------------------------------------
# sales tools
# ---------------------------------------------------------------------------
def _get_sales_summary(context: ToolContext, args: PeriodArgs) -> dict:
    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    service = context.services.sales_service
    dashboard = service.dashboard()
    orders = service.list_orders(date_from=date_from, date_to=date_to)
    completed = [order for order in orders if order.order_status == "COMPLETED"]
    value = sum((to_money(order.total_amount) for order in completed), ZERO)
    return {
        "period": label,
        "total_orders": len(orders),
        "completed_orders": len(completed),
        "pending_orders": sum(
            1 for order in orders if order.order_status in ("DRAFT", "CONFIRMED")
        ),
        "sales_value": _money(value),
        "average_order_value": _money(to_money(value / len(completed)) if completed else ZERO),
        "lifetime_sales_value": _money(dashboard.total_sales_value),
        "outstanding_total": _money(dashboard.outstanding_total),
        "summary": (
            f"{len(completed)} completed order(s) worth {_money(value)} for {label}; "
            f"{dashboard.outstanding_total and _money(dashboard.outstanding_total)} outstanding overall."
        ),
    }


def _get_sales_history(context: ToolContext, args: HistoryArgs) -> dict:
    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    orders = context.services.sales_service.list_orders(date_from=date_from, date_to=date_to)
    rows = [
        {
            "order": order.order_number,
            "date": order.created_at.strftime("%d %b %Y"),
            "customer": order.customer_name,
            "status": order.order_status,
            "payment": order.payment_status,
            "total": _money(order.total_amount),
        }
        for order in orders[: args.limit]
    ]
    return {
        "period": label,
        "order_count": len(orders),
        "orders": rows,
        "summary": f"{len(orders)} order(s) found for {label}.",
    }


def _get_top_products(context: ToolContext, args: TopProductsArgs) -> dict:
    dashboard = context.services.sales_service.dashboard()
    products = dashboard.top_products[: args.limit]
    return {
        "products": products,
        "summary": (
            "Top products by revenue: "
            + ", ".join(f"{item['product']} ({item['revenue']})" for item in products)
            if products
            else "No completed sales yet, so there is nothing to rank."
        ),
    }


def _get_sales_trends(context: ToolContext, args: TrendArgs) -> dict:
    dashboard = context.services.sales_service.dashboard()
    monthly = [
        {"month": month, "sales": _money(value)}
        for month, value in dashboard.monthly_sales[-args.months :]
    ]
    daily = [
        {"day": day, "sales": _money(value)} for day, value in dashboard.daily_sales[-14:]
    ]
    return {
        "monthly": monthly,
        "daily": daily,
        "summary": f"Sales trend across {len(monthly)} month(s) of completed orders.",
    }


def _get_pending_orders(context: ToolContext, args: EmptyArgs) -> dict:
    service = context.services.sales_service
    pending = service.list_orders(status="DRAFT") + service.list_orders(status="CONFIRMED")
    rows = [
        {
            "order": order.order_number,
            "customer": order.customer_name,
            "status": order.order_status,
            "total": _money(order.total_amount),
            "date": order.created_at.strftime("%d %b %Y"),
        }
        for order in pending
    ]
    return {
        "pending_count": len(rows),
        "orders": rows,
        "summary": f"{len(rows)} order(s) are still open (draft or confirmed).",
    }


# ---------------------------------------------------------------------------
# customer tools
# ---------------------------------------------------------------------------
def _get_customer_summary(context: ToolContext, args: EmptyArgs) -> dict:
    dashboard = context.services.customer_service.dashboard()
    return {
        "total_customers": dashboard.total_customers,
        "active_customers": dashboard.active_customers,
        "new_customers_30d": dashboard.new_customers_30d,
        "inactive_customers": dashboard.inactive_customers,
        "total_purchase_value": _money(dashboard.total_purchase_value),
        "segments": dashboard.segments,
        "top_customers": [
            {
                "name": customer.full_name,
                "segment": customer.segment,
                "total_purchase": _money(customer.total_purchase),
            }
            for customer in dashboard.top_customers
        ],
        "summary": (
            f"{dashboard.total_customers} customer(s), {dashboard.active_customers} active, "
            f"lifetime purchases {_money(dashboard.total_purchase_value)}."
        ),
    }


def _get_inactive_customers(context: ToolContext, args: InactiveCustomersArgs) -> dict:
    service = context.services.customer_service
    customers = service.list_customers()
    cutoff = utcnow() - timedelta(days=args.days)
    inactive = [
        customer
        for customer in customers
        if customer.last_purchase_at is None or customer.last_purchase_at < cutoff
    ]
    rows = [
        {
            "customer": customer.full_name,
            "code": customer.customer_code,
            "last_purchase": customer.last_purchase_at.strftime("%d %b %Y")
            if customer.last_purchase_at
            else "never",
            "lifetime_value": _money(customer.total_purchase),
            "segment": customer.segment,
        }
        for customer in inactive[: args.limit]
    ]
    return {
        "threshold_days": args.days,
        "inactive_count": len(inactive),
        "customers": rows,
        "summary": (
            f"{len(inactive)} customer(s) have not purchased in the last {args.days} days."
            if inactive
            else f"Every customer has purchased within the last {args.days} days."
        ),
    }


def _get_customer_history(context: ToolContext, args: CustomerRef) -> dict:
    customer = _find_customer(context, args)
    if customer is None:
        raise NotFoundError("No matching customer was found")
    orders = context.services.sales_service.list_orders(customer_id=customer.id, limit=20)
    rows = [
        {
            "order": order.order_number,
            "date": order.created_at.strftime("%d %b %Y"),
            "status": order.order_status,
            "total": _money(order.total_amount),
            "paid": _money(order.paid_amount),
        }
        for order in orders
    ]
    return {
        "customer": customer.full_name,
        "order_count": len(rows),
        "orders": rows,
        "summary": f"{customer.full_name} has {len(rows)} order(s) on record.",
    }


def _get_customer_purchase_history(context: ToolContext, args: CustomerRef) -> dict:
    customer = _find_customer(context, args)
    if customer is None:
        raise NotFoundError("No matching customer was found")
    profile = context.services.customer_service.profile(customer.id)
    return {
        "customer": profile.summary.full_name,
        "segment": profile.summary.segment,
        "segment_reason": profile.segment_reason,
        "order_count": profile.summary.order_count,
        "total_purchase": _money(profile.summary.total_purchase),
        "outstanding": _money(profile.outstanding_amount),
        "last_purchase": profile.summary.last_purchase_at.strftime("%d %b %Y")
        if profile.summary.last_purchase_at
        else "never",
        "invoices": [
            {
                "invoice": invoice.invoice_number,
                "total": _money(invoice.total_amount),
                "outstanding": _money(invoice.outstanding),
                "status": invoice.status,
            }
            for invoice in profile.invoices[:10]
        ],
        "summary": (
            f"{profile.summary.full_name}: {profile.summary.order_count} order(s), "
            f"{_money(profile.summary.total_purchase)} lifetime, "
            f"{_money(profile.outstanding_amount)} outstanding ({profile.summary.segment})."
        ),
    }


# ---------------------------------------------------------------------------
# inventory tools
# ---------------------------------------------------------------------------
def _get_product_stock(context: ToolContext, args: ProductRef) -> dict:
    service = context.services.inventory_service
    product = _find_product(context, args)
    if product is not None:
        rows = service.list_stock(search=product.sku)
    else:
        rows = service.list_stock()
    items = [
        {
            "product": row.product_name,
            "sku": row.sku,
            "available": row.available_quantity,
            "minimum": row.minimum_stock,
            "unit": row.unit,
            "cost_price": f"{to_money(row.cost_price):.2f}",
            "stock_value": _money(row.stock_value),
            "low": row.is_low,
        }
        for row in rows[:30]
    ]
    if product is not None and items:
        summary = (
            f"{items[0]['product']} has {items[0]['available']} {items[0]['unit']} in stock "
            f"(minimum {items[0]['minimum']})."
        )
    else:
        total = sum(row.available_quantity for row in rows)
        summary = f"{len(rows)} product(s) in the catalogue with {total} units on hand."
    return {"products": items, "product_count": len(rows), "summary": summary}


def _get_low_stock_products(context: ToolContext, args: EmptyArgs) -> dict:
    alerts = context.services.inventory_service.low_stock_alerts()
    rows = [
        {
            "product": alert.product_name,
            "sku": alert.sku,
            "available": alert.available_quantity,
            "minimum": alert.minimum_stock,
            "suggested_reorder": alert.suggested_reorder_quantity,
        }
        for alert in alerts
    ]
    return {
        "low_stock_count": len(rows),
        "products": rows,
        "summary": (
            f"{len(rows)} product(s) are at or below their minimum stock."
            if rows
            else "No product is below its minimum stock level."
        ),
    }


def _get_stock_movements(context: ToolContext, args: MovementsArgs) -> dict:
    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    product = None
    if args.product_id or args.product_name:
        product = _find_product(
            context, ProductRef(product_id=args.product_id, product_name=args.product_name)
        )
    movements = context.services.inventory_service.movements(
        product_id=product.id if product else None,
        date_from=date_from,
        date_to=date_to,
        limit=args.limit,
    )
    rows = [
        {
            "date": movement.created_at.strftime("%d %b %Y"),
            "product": movement.product_name,
            "type": movement.movement_type,
            "quantity": movement.quantity,
            "before": movement.previous_quantity,
            "after": movement.new_quantity,
            "reference": f"{movement.reference_type or ''} {movement.reference_id or ''}".strip(),
        }
        for movement in movements
    ]
    return {
        "period": label,
        "movement_count": len(rows),
        "movements": rows,
        "summary": f"{len(rows)} stock movement(s) recorded for {label}.",
    }


def _get_stock_valuation(context: ToolContext, args: EmptyArgs) -> dict:
    service = context.services.inventory_service
    dashboard = service.dashboard()
    rows = service.list_stock()
    top = sorted(rows, key=lambda row: row.stock_value, reverse=True)[:10]
    return {
        "total_stock_value": _money(dashboard.stock_value),
        "total_quantity": dashboard.total_stock_quantity,
        "product_count": dashboard.total_products,
        "valuation_method": dashboard.valuation_method,
        "top_items": [
            {
                "product": row.product_name,
                "available": row.available_quantity,
                "cost_price": _money(row.cost_price),
                "value": _money(row.stock_value),
            }
            for row in top
        ],
        "summary": (
            f"Stock at cost is {_money(dashboard.stock_value)} across "
            f"{dashboard.total_stock_quantity} units ({dashboard.total_products} products)."
        ),
    }


# ---------------------------------------------------------------------------
# supplier tools
# ---------------------------------------------------------------------------
def _get_supplier_details(context: ToolContext, args: SupplierRef) -> dict:
    supplier = _find_supplier(context, args)
    if supplier is None:
        suppliers = context.services.purchasing_service.list_suppliers()
        if not suppliers:
            raise NotFoundError("No suppliers are registered")
        supplier = suppliers[0]
    return {
        "supplier": supplier.supplier_name,
        "code": supplier.supplier_code,
        "contact_person": supplier.contact_person,
        "email": supplier.email,
        "phone": supplier.phone,
        "active": supplier.is_active,
        "order_count": supplier.order_count,
        "total_order_value": _money(supplier.total_order_value),
        "received_value": _money(supplier.received_value),
        "last_order": supplier.last_order_at.strftime("%d %b %Y")
        if supplier.last_order_at
        else "never",
        "summary": (
            f"{supplier.supplier_name}: {supplier.order_count} purchase order(s) worth "
            f"{_money(supplier.total_order_value)}, received {_money(supplier.received_value)}."
        ),
    }


def _get_supplier_purchase_history(context: ToolContext, args: SupplierRef) -> dict:
    supplier = _find_supplier(context, args)
    if supplier is None:
        raise NotFoundError("No matching supplier was found")
    orders = context.services.purchasing_service.list_purchase_orders(supplier_id=supplier.id)
    rows = [
        {
            "po": order.purchase_order_number,
            "status": order.status,
            "total": _money(order.total_amount),
            "ordered": order.ordered_quantity,
            "received": order.received_quantity,
            "created": order.created_at.strftime("%d %b %Y"),
        }
        for order in orders[:20]
    ]
    return {
        "supplier": supplier.supplier_name,
        "order_count": len(rows),
        "orders": rows,
        "summary": f"{supplier.supplier_name} has {len(rows)} purchase order(s).",
    }


def _get_purchase_order_status(context: ToolContext, args: PurchaseOrderStatusArgs) -> dict:
    orders = context.services.purchasing_service.list_purchase_orders(
        status=args.status, supplier_id=args.supplier_id
    )
    rows = [
        {
            "po": order.purchase_order_number,
            "supplier": order.supplier_name,
            "status": order.status,
            "total": _money(order.total_amount),
            "received": f"{order.received_quantity}/{order.ordered_quantity}",
            "created": order.created_at.strftime("%d %b %Y"),
        }
        for order in orders[:20]
    ]
    open_orders = [
        order
        for order in orders
        if order.status in ("APPROVED", "ORDERED", "PARTIALLY_RECEIVED")
    ]
    return {
        "order_count": len(rows),
        "open_count": len(open_orders),
        "orders": rows,
        "summary": f"{len(open_orders)} purchase order(s) are awaiting goods.",
    }


# ---------------------------------------------------------------------------
# reporting tools
# ---------------------------------------------------------------------------
def _generate_sales_report(context: ToolContext, args: PeriodArgs) -> dict:
    path = context.services.sales_service.export_sales_csv()
    return {
        "format": "csv",
        "path": str(path),
        "summary": "Sales report exported to CSV.",
    }


def _generate_inventory_report(context: ToolContext, args: EmptyArgs) -> dict:
    path = context.services.inventory_service.export_stock_csv()
    return {
        "format": "csv",
        "path": str(path),
        "summary": "Inventory report exported to CSV.",
    }


# ---------------------------------------------------------------------------
# approval-gated preparation tools (never write to the database)
# ---------------------------------------------------------------------------
def _prepare_sales_order(context: ToolContext, args: PrepareSalesOrderArgs) -> dict:
    if not args.items:
        raise NotFoundError("No products were supplied for the order")
    customer = _find_customer(context, args)
    if customer is None:
        raise NotFoundError("No matching customer was found")

    inventory = context.services.inventory_service
    lines = []
    total = ZERO
    warnings: list[str] = []
    for item in args.items:
        product = _find_product(
            context, ProductRef(product_id=item.product_id, product_name=item.product_name)
        )
        if product is None:
            raise NotFoundError(f"Product not found: {item.product_name or item.product_id}")
        available = inventory.stock_for_product(product.id)
        if available < item.quantity:
            warnings.append(
                f"{product.product_name}: only {available} in stock, {item.quantity} requested"
            )
        line_total = to_money(product.selling_price * item.quantity)
        total += line_total
        lines.append(
            {
                "product_id": product.id,
                "product": product.product_name,
                "quantity": item.quantity,
                "unit_price": _money(product.selling_price),
                "line_total": _money(line_total),
                "available": available,
            }
        )

    return {
        "draft_action": "CREATE_SALES_ORDER",
        "customer_id": customer.id,
        "customer": customer.full_name,
        "items": lines,
        "total": f"{to_money(total):.2f}",
        "total_display": _money(total),
        "warnings": warnings,
        "summary": (
            f"Draft order for {customer.full_name}: {len(lines)} line(s) totalling {_money(total)}. "
            + ("Stock warning: " + "; ".join(warnings) if warnings else "Stock is available.")
            + " Awaiting your approval."
        ),
    }


def _prepare_expense(context: ToolContext, args: PrepareExpenseArgs) -> dict:
    return {
        "draft_action": "CREATE_EXPENSE",
        "expense_category": args.expense_category,
        "description": args.description,
        # Machine-readable amount for the approval step; display value alongside.
        "amount": f"{to_money(args.amount):.2f}",
        "amount_display": _money(args.amount),
        "vendor_name": args.vendor_name,
        "payment_method": args.payment_method,
        "summary": (
            f"Draft expense {args.expense_category} {_money(args.amount)} "
            f"({args.description}). Awaiting your approval."
        ),
    }


def _create_purchase_recommendation(context: ToolContext, args: PurchaseRecommendationArgs) -> dict:
    product = _find_product(context, args)
    if product is None:
        raise NotFoundError("No matching product was found")

    inventory = context.services.inventory_service
    sales = context.services.sales_service
    finance = context.services.finance_service

    available = inventory.stock_for_product(product.id)
    minimum = product.minimum_stock

    # Demand over the last 30 days, from real completed orders.
    since = utcnow() - timedelta(days=30)
    sold = 0
    for order in sales.list_orders(date_from=since):
        if order.order_status != "COMPLETED":
            continue
        for line in order.lines:
            if line.product_id == product.id:
                sold += line.quantity
    monthly_demand = sold

    cash = finance.summary()
    cash_available = to_money(cash.cash_received - cash.operating_expenses)
    unit_cost = to_money(product.cost_price)

    target_quantity = max(monthly_demand, minimum * 2)
    suggested = max(target_quantity - available, 0)
    if args.requested_quantity is not None:
        suggested = args.requested_quantity
    estimated_cost = to_money(unit_cost * suggested)

    affordable = estimated_cost <= cash_available if cash_available > 0 else False
    reasons = [
        f"On hand {available} (minimum {minimum})",
        f"Sold {monthly_demand} unit(s) in the last 30 days",
        f"Estimated cost {_money(estimated_cost)} at {_money(unit_cost)} per unit",
        f"Net cash available {_money(cash_available)}",
    ]
    if suggested == 0:
        recommendation = "No purchase needed right now."
    elif affordable:
        recommendation = (
            f"Purchase up to {suggested} unit(s) of {product.product_name}; "
            "cash on hand covers the estimated cost."
        )
    else:
        recommendation = (
            f"Demand supports {suggested} unit(s), but net cash ({_money(cash_available)}) "
            f"does not cover the estimated {_money(estimated_cost)}. Review cash before ordering."
        )

    return {
        "product": product.product_name,
        "sku": product.sku,
        "available_quantity": available,
        "minimum_stock": minimum,
        "sold_last_30_days": monthly_demand,
        "unit_cost": _money(unit_cost),
        "suggested_quantity": suggested,
        "estimated_cost": _money(estimated_cost),
        "cash_available": _money(cash_available),
        "affordable": affordable,
        "reasons": reasons,
        "recommendation": recommendation,
        "summary": recommendation,
    }


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------
def build_tool_registry() -> ToolRegistry:
    """Register every Phase 3 tool."""
    registry = ToolRegistry()

    definitions = [
        # -- finance ------------------------------------------------------
        ToolDefinition(
            name="get_revenue",
            description="Revenue recognised from completed sales, net of refunds",
            category="finance",
            input_model=PeriodArgs,
            required_permission="finance.view",
            handler=_get_revenue,
        ),
        ToolDefinition(
            name="get_expenses",
            description="Recorded operating expenses with a category breakdown",
            category="finance",
            input_model=PeriodArgs,
            required_permission="finance.view",
            handler=_get_expenses,
        ),
        ToolDefinition(
            name="calculate_profit",
            description="Gross and net profit from the financial ledger",
            category="finance",
            input_model=PeriodArgs,
            required_permission="finance.view",
            handler=_calculate_profit,
        ),
        ToolDefinition(
            name="get_cash_flow",
            description="Cash received, refunds, expenses paid and net movement",
            category="finance",
            input_model=PeriodArgs,
            required_permission="finance.view",
            handler=_get_cash_flow,
        ),
        ToolDefinition(
            name="get_outstanding_payments",
            description="Unpaid invoices and total receivables",
            category="finance",
            input_model=EmptyArgs,
            required_permission="finance.view",
            handler=_get_outstanding_payments,
        ),
        ToolDefinition(
            name="generate_financial_report",
            description="Export a financial report to CSV or PDF",
            category="finance",
            input_model=ReportArgs,
            required_permission="finance.export",
            risk_level=AIRiskLevel.LOW,
            timeout_seconds=45.0,
            handler=_generate_financial_report,
        ),
        # -- sales --------------------------------------------------------
        ToolDefinition(
            name="get_sales_summary",
            description="Order counts and sales value for a period",
            category="sales",
            input_model=PeriodArgs,
            required_permission="sales.view",
            handler=_get_sales_summary,
        ),
        ToolDefinition(
            name="get_sales_history",
            description="Recent sales orders with status and totals",
            category="sales",
            input_model=HistoryArgs,
            required_permission="sales.view",
            handler=_get_sales_history,
        ),
        ToolDefinition(
            name="get_top_products",
            description="Best selling products by revenue",
            category="sales",
            input_model=TopProductsArgs,
            required_permission="sales.view",
            handler=_get_top_products,
        ),
        ToolDefinition(
            name="get_sales_trends",
            description="Monthly and daily sales trend",
            category="sales",
            input_model=TrendArgs,
            required_permission="sales.view",
            handler=_get_sales_trends,
        ),
        ToolDefinition(
            name="get_pending_orders",
            description="Draft and confirmed orders awaiting completion",
            category="sales",
            input_model=EmptyArgs,
            required_permission="sales.view",
            handler=_get_pending_orders,
        ),
        # -- customers ----------------------------------------------------
        ToolDefinition(
            name="get_customer_summary",
            description="Customer counts, segments and lifetime value",
            category="customers",
            input_model=EmptyArgs,
            required_permission="customers.view",
            handler=_get_customer_summary,
        ),
        ToolDefinition(
            name="get_inactive_customers",
            description="Customers without a recent purchase",
            category="customers",
            input_model=InactiveCustomersArgs,
            required_permission="customers.view",
            handler=_get_inactive_customers,
        ),
        ToolDefinition(
            name="get_customer_history",
            description="Order history for one customer",
            category="customers",
            input_model=CustomerRef,
            required_permission="customers.view",
            handler=_get_customer_history,
        ),
        ToolDefinition(
            name="get_customer_purchase_history",
            description="Purchase profile, invoices and outstanding balance",
            category="customers",
            input_model=CustomerRef,
            required_permission="customers.view",
            handler=_get_customer_purchase_history,
        ),
        # -- inventory ----------------------------------------------------
        ToolDefinition(
            name="get_product_stock",
            description="Current stock levels for a product or the catalogue",
            category="inventory",
            input_model=ProductRef,
            required_permission="inventory.view",
            handler=_get_product_stock,
        ),
        ToolDefinition(
            name="get_low_stock_products",
            description="Products at or below their minimum stock",
            category="inventory",
            input_model=EmptyArgs,
            required_permission="inventory.view",
            handler=_get_low_stock_products,
        ),
        ToolDefinition(
            name="get_stock_movements",
            description="Stock movement ledger entries",
            category="inventory",
            input_model=MovementsArgs,
            required_permission="inventory.view",
            handler=_get_stock_movements,
        ),
        ToolDefinition(
            name="get_stock_valuation",
            description="Inventory value at recorded cost",
            category="inventory",
            input_model=EmptyArgs,
            required_permission="inventory.view",
            handler=_get_stock_valuation,
        ),
        # -- suppliers ----------------------------------------------------
        ToolDefinition(
            name="get_supplier_details",
            description="Supplier profile and purchase totals",
            category="suppliers",
            input_model=SupplierRef,
            required_permission="suppliers.view",
            handler=_get_supplier_details,
        ),
        ToolDefinition(
            name="get_supplier_purchase_history",
            description="Purchase orders for one supplier",
            category="suppliers",
            input_model=SupplierRef,
            required_permission="suppliers.view",
            handler=_get_supplier_purchase_history,
        ),
        ToolDefinition(
            name="get_purchase_order_status",
            description="Purchase orders filtered by status",
            category="suppliers",
            input_model=PurchaseOrderStatusArgs,
            required_permission="purchase_orders.view",
            handler=_get_purchase_order_status,
        ),
        # -- reporting ----------------------------------------------------
        ToolDefinition(
            name="generate_sales_report",
            description="Export the sales report to CSV",
            category="reporting",
            input_model=PeriodArgs,
            required_permission="sales.export",
            risk_level=AIRiskLevel.LOW,
            timeout_seconds=45.0,
            handler=_generate_sales_report,
        ),
        ToolDefinition(
            name="generate_inventory_report",
            description="Export the inventory report to CSV",
            category="reporting",
            input_model=EmptyArgs,
            required_permission="inventory.export",
            risk_level=AIRiskLevel.LOW,
            timeout_seconds=45.0,
            handler=_generate_inventory_report,
        ),
        # -- approval-gated preparation -----------------------------------
        ToolDefinition(
            name="prepare_sales_order",
            description="Prepare a sales order draft for human approval",
            category="actions",
            input_model=PrepareSalesOrderArgs,
            required_permission="sales.create",
            risk_level=AIRiskLevel.MEDIUM,
            handler=_prepare_sales_order,
        ),
        ToolDefinition(
            name="prepare_expense",
            description="Prepare an expense draft for human approval",
            category="actions",
            input_model=PrepareExpenseArgs,
            required_permission="finance.create",
            risk_level=AIRiskLevel.MEDIUM,
            handler=_prepare_expense,
        ),
        ToolDefinition(
            name="create_purchase_recommendation",
            description="Analyse stock, demand and cash to recommend a purchase",
            category="actions",
            input_model=PurchaseRecommendationArgs,
            required_permission="inventory.view",
            handler=_create_purchase_recommendation,
        ),
    ]
    registry.register_all(definitions)

    # Phase 4: agent data tools and the five agent runners live in the same
    # registry, so planning, validation and permission checks are unchanged.
    from app.ai.registry.phase4_tools import build_agent_runner_tools, build_phase4_tools

    registry.register_all(build_phase4_tools())
    registry.register_all(build_agent_runner_tools())

    from app.ai.registry.analytics_tools import build_analytics_tools
    from app.ai.registry.knowledge_tools import build_knowledge_tools
    from app.ai.registry.collaboration_tools import build_collaboration_tools

    registry.register_all(build_collaboration_tools())
    registry.register_all(build_analytics_tools())
    registry.register_all(build_knowledge_tools())
    return registry
