"""Phase 4 tools: data retrieval for agents plus the five agent runners.

The data tools are ordinary registry tools (permission checked, schema validated).
The ``run_*_agent`` tools let the orchestrator invoke a specialist agent exactly
like any other tool, so planning, validation, persistence and LangGraph execution
all keep working unchanged.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any, Callable

from app.ai.registry.tool_inputs import (
    AgentRunArgs,
    FollowUpArgs,
    LimitArgs,
    MonthsArgs,
    PeriodArgs,
    ProductRef,
    VelocityArgs,
)
from app.ai.schemas.tool_schema import ToolContext, ToolDefinition
from app.core.constants import AIRiskLevel
from app.core.exceptions import NotFoundError
from app.database.types import ZERO, to_money
from app.utils.date_utils import utcnow

AGENT_PERMISSION = "agents.execute"


def _money(value) -> str:
    return f"{to_money(value):,.2f}"


def _period_bounds(context_period: str | None) -> tuple[Any, Any, str]:
    from app.ai.registry.tool_catalogue import resolve_period

    return resolve_period(context_period)


# ---------------------------------------------------------------------------
# data tools
# ---------------------------------------------------------------------------
def _get_expense_breakdown(context: ToolContext, args: PeriodArgs) -> dict:
    from app.ai.registry.tool_catalogue import resolve_period

    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    service = context.services.finance_service
    summary = service.summary(date_from=date_from, date_to=date_to)
    expenses = service.list_expenses(date_from=date_from, date_to=date_to)

    by_category: dict[str, Decimal] = {}
    rows: list[dict[str, Any]] = []
    for expense in expenses:
        if expense.status != "RECORDED":
            continue
        by_category[expense.expense_category] = by_category.get(
            expense.expense_category, ZERO
        ) + to_money(expense.amount)
        rows.append(
            {
                "expense_number": expense.expense_number,
                "expense_category": expense.expense_category,
                "description": expense.description,
                "amount": f"{to_money(expense.amount):.2f}",
                "expense_date": expense.expense_date.isoformat() if expense.expense_date else None,
                "status": expense.status,
            }
        )
    breakdown = [
        {"category": category, "amount": _money(amount)}
        for category, amount in sorted(by_category.items(), key=lambda item: item[1], reverse=True)
    ]
    return {
        "period": label,
        "operating_expenses": _money(summary.operating_expenses),
        "breakdown": breakdown,
        "expenses": rows[:200],
        "expense_count": len(rows),
        "summary": f"{len(rows)} expense record(s) across {len(breakdown)} category(ies) for {label}.",
    }


def _get_monthly_financial_summary(context: ToolContext, args: MonthsArgs) -> dict:
    service = context.services.finance_service
    series = service.monthly_series(months=args.months)
    monthly = [
        {
            "month": label,
            "income": f"{to_money(income):.2f}",
            "expenses": f"{to_money(expenses):.2f}",
            "net": f"{to_money(income - expenses):.2f}",
        }
        for label, income, expenses in zip(
            series["labels"], series["income"], series["expenses"]
        )
    ]
    return {
        "monthly": monthly,
        "months": len(monthly),
        "summary": f"Monthly financial history for {len(monthly)} month(s).",
    }


def _get_product_velocity(context: ToolContext, args: VelocityArgs) -> dict:
    inventory = context.services.inventory_service
    sales = context.services.sales_service
    since = utcnow() - timedelta(days=args.window_days)

    quantities: dict[int, int] = {}
    last_sold: dict[int, Any] = {}
    for order in sales.list_orders(date_from=since):
        if order.order_status != "COMPLETED":
            continue
        for line in order.lines:
            quantities[line.product_id] = quantities.get(line.product_id, 0) + line.quantity
            stamp = order.created_at
            if line.product_id not in last_sold or stamp > last_sold[line.product_id]:
                last_sold[line.product_id] = stamp

    rows: list[dict[str, Any]] = []
    for product in inventory.list_products():
        quantity = quantities.get(product.id, 0)
        last = last_sold.get(product.id)
        rows.append(
            {
                "product": product.product_name,
                "sku": product.sku,
                "product_id": product.id,
                "quantity_sold": quantity,
                "units_per_day": round(quantity / args.window_days, 3),
                "window_days": args.window_days,
                "last_sold": last.strftime("%d %b %Y") if last else None,
            }
        )
    rows.sort(key=lambda row: row["quantity_sold"], reverse=True)
    return {
        "window_days": args.window_days,
        "products": rows,
        "summary": (
            f"Sales velocity for {len(rows)} product(s) over the last {args.window_days} days."
        ),
    }


def _get_low_performing_products(context: ToolContext, args: LimitArgs) -> dict:
    sales = context.services.sales_service
    inventory = context.services.inventory_service
    revenue: dict[int, Decimal] = {}
    quantity: dict[int, int] = {}
    for order in sales.list_orders():
        if order.order_status != "COMPLETED":
            continue
        for line in order.lines:
            revenue[line.product_id] = revenue.get(line.product_id, ZERO) + to_money(line.line_total)
            quantity[line.product_id] = quantity.get(line.product_id, 0) + line.quantity

    rows = []
    for product in inventory.list_products():
        product_revenue = revenue.get(product.id, ZERO)
        rows.append(
            {
                "product": product.product_name,
                "sku": product.sku,
                "revenue": _money(product_revenue),
                "_sort_value": product_revenue,
                "quantity": quantity.get(product.id, 0),
            }
        )
    rows.sort(key=lambda row: row["_sort_value"])
    for row in rows:
        row.pop("_sort_value", None)
    return {
        "products": rows[: args.limit],
        "summary": f"{min(len(rows), args.limit)} lowest-revenue product(s) listed.",
    }


def _get_customer_portfolio(context: ToolContext, args: PeriodArgs) -> dict:
    service = context.services.customer_service
    customers = service.list_customers()
    rows = [
        {
            "customer_id": customer.id,
            "customer_code": customer.customer_code,
            "full_name": customer.full_name,
            "email": customer.email,
            "phone": customer.phone,
            "city": customer.city,
            "customer_type": customer.customer_type,
            "is_active": customer.is_active,
            "order_count": customer.order_count,
            "total_purchase": f"{to_money(customer.total_purchase):.2f}",
            "last_purchase_at": customer.last_purchase_at.strftime("%d %b %Y")
            if customer.last_purchase_at
            else None,
            "created_at": customer.created_at.strftime("%d %b %Y")
            if getattr(customer, "created_at", None)
            else None,
            "segment": customer.segment,
        }
        for customer in customers
    ]
    return {
        "customers": rows,
        "customer_count": len(rows),
        "summary": f"{len(rows)} customer record(s) loaded with purchase history.",
    }


def _get_business_snapshot(context: ToolContext, args: PeriodArgs) -> dict:
    from app.ai.registry.tool_catalogue import resolve_period

    date_from, date_to, label = resolve_period(args.period, args.date_from, args.date_to)
    finance = context.services.finance_service
    sales = context.services.sales_service
    inventory = context.services.inventory_service
    customers = context.services.customer_service

    summary = finance.summary(date_from=date_from, date_to=date_to)
    sales_dashboard = sales.dashboard()
    inventory_dashboard = inventory.dashboard()
    customer_dashboard = customers.dashboard()
    series = finance.monthly_series(months=6)

    monthly = [
        {
            "month": month,
            "revenue": f"{to_money(income):.2f}",
            "expenses": f"{to_money(expenses):.2f}",
            "net": f"{to_money(income - expenses):.2f}",
        }
        for month, income, expenses in zip(
            series["labels"], series["income"], series["expenses"]
        )
    ]
    return {
        "period": label,
        "revenue": _money(summary.revenue),
        "operating_expenses": _money(summary.operating_expenses),
        "net_profit": _money(summary.net_profit),
        "cash_received": _money(summary.cash_received),
        "outstanding": _money(summary.outstanding_receivables),
        "sales_value": _money(sales_dashboard.total_sales_value),
        "completed_orders": sales_dashboard.completed_orders,
        "total_orders": sales_dashboard.total_orders,
        "active_customers": customer_dashboard.active_customers,
        "total_customers": customer_dashboard.total_customers,
        "low_stock_products": len(inventory.low_stock_alerts()),
        "stock_value": _money(inventory_dashboard.stock_value),
        "products": inventory_dashboard.total_products,
        "monthly": monthly,
        "summary": (
            f"Snapshot for {label}: revenue {_money(summary.revenue)}, net profit "
            f"{_money(summary.net_profit)}, sales {_money(sales_dashboard.total_sales_value)}, "
            f"{len(inventory.low_stock_alerts())} low-stock product(s)."
        ),
    }


def _schedule_customer_followup(context: ToolContext, args: FollowUpArgs) -> dict:
    service = context.services.customer_service
    customer_id = args.customer_id
    if customer_id is None:
        if not args.customer_name:
            raise NotFoundError("A customer name or id is required")
        matches = service.list_customers(search=args.customer_name)
        if not matches:
            raise NotFoundError(f"No customer matched '{args.customer_name}'")
        customer_id = matches[0].id
    due = utcnow() + timedelta(days=args.due_in_days)
    follow_up = service.create_follow_up(
        {
            "customer_id": customer_id,
            "title": args.title,
            "due_date": due,
        }
    )
    return {
        "follow_up_id": follow_up.id,
        "customer": follow_up.customer_name,
        "due_date": follow_up.due_date.isoformat(),
        "status": follow_up.status,
        "summary": (
            f"Follow-up '{args.title}' scheduled for {follow_up.customer_name} in "
            f"{args.due_in_days} day(s)."
        ),
    }


# ---------------------------------------------------------------------------
# agent runner tools
# ---------------------------------------------------------------------------
def _agent_tool(
    *,
    name: str,
    description: str,
    agent_id: str,
) -> ToolDefinition:
    def handler(context: ToolContext, args: AgentRunArgs) -> dict:
        manager = getattr(context.services, "agent_manager", None)
        if manager is None:
            raise NotFoundError("The agent manager is not available")
        result = manager.run_agent(
            agent_id,
            period=args.period,
            task_type=args.task_type,
            parameters=args.parameters,
            user_id=context.user_id,
            workflow_id=context.workflow_id,
        )
        top_findings = [finding.description for finding in result.top_findings(2)]
        summary_text = result.summary
        if top_findings:
            summary_text = f"{result.summary} Key: " + " | ".join(top_findings)

        return {
            "agent_id": result.agent_id,
            "status": result.status,
            "confidence": result.confidence,
            "confidence_basis": result.confidence_basis,
            "summary": summary_text,
            "findings": [finding.model_dump(mode="json") for finding in result.findings],
            "recommendations": [
                recommendation.model_dump(mode="json")
                for recommendation in result.recommendations
            ],
            "metrics": result.metrics,
            "data_gaps": result.data_gaps,
            "tools_used": result.tools_used,
            "execution_ms": round(result.execution_ms, 1),
            "error": result.error,
        }

    return ToolDefinition(
        name=name,
        description=description,
        category="agents",
        input_model=AgentRunArgs,
        required_permission=AGENT_PERMISSION,
        risk_level=AIRiskLevel.READ_ONLY,
        timeout_seconds=120.0,
        handler=handler,
    )


def build_phase4_tools() -> list[ToolDefinition]:
    """Data tools used by the specialist agents."""
    return [
        ToolDefinition(
            name="get_expense_breakdown",
            description="Expense categories, raw expense rows and totals for a period",
            category="finance",
            input_model=PeriodArgs,
            required_permission="finance.view",
            handler=_get_expense_breakdown,
        ),
        ToolDefinition(
            name="get_monthly_financial_summary",
            description="Monthly income, expense and net history",
            category="finance",
            input_model=MonthsArgs,
            required_permission="finance.view",
            handler=_get_monthly_financial_summary,
        ),
        ToolDefinition(
            name="get_product_velocity",
            description="Units sold per day per product over a window",
            category="inventory",
            input_model=VelocityArgs,
            required_permission="inventory.view",
            handler=_get_product_velocity,
        ),
        ToolDefinition(
            name="get_low_performing_products",
            description="Lowest revenue products from completed orders",
            category="sales",
            input_model=LimitArgs,
            required_permission="sales.view",
            handler=_get_low_performing_products,
        ),
        ToolDefinition(
            name="get_customer_portfolio",
            description="All customers with order counts, lifetime value and recency",
            category="customers",
            input_model=PeriodArgs,
            required_permission="customers.view",
            handler=_get_customer_portfolio,
        ),
        ToolDefinition(
            name="get_business_snapshot",
            description="Combined finance, sales, inventory and customer metrics",
            category="business",
            input_model=PeriodArgs,
            required_permission="dashboard.view",
            handler=_get_business_snapshot,
        ),
        ToolDefinition(
            name="schedule_customer_followup",
            description="Create a local follow-up reminder for a customer",
            category="customers",
            input_model=FollowUpArgs,
            required_permission="customers.update",
            risk_level=AIRiskLevel.LOW,
            handler=_schedule_customer_followup,
        ),
    ]


def build_agent_runner_tools() -> list[ToolDefinition]:
    """The five agents, exposed to the orchestrator as tools."""
    return [
        _agent_tool(
            name="run_finance_agent",
            description="Run the Finance Agent (revenue, expenses, profit, cash, anomalies)",
            agent_id="finance_agent",
        ),
        _agent_tool(
            name="run_sales_agent",
            description="Run the Sales Agent (performance, products, trends, demand)",
            agent_id="sales_agent",
        ),
        _agent_tool(
            name="run_customer_agent",
            description="Run the Customer Agent (segments, inactivity, value, follow-ups)",
            agent_id="customer_agent",
        ),
        _agent_tool(
            name="run_inventory_agent",
            description="Run the Inventory Agent (stock health, reorder points, overstock)",
            agent_id="inventory_agent",
        ),
        _agent_tool(
            name="run_business_intelligence_agent",
            description="Run the Business Intelligence Agent (cross-functional health and risks)",
            agent_id="business_intelligence_agent",
        ),
    ]
