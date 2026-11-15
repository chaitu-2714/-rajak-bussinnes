"""Intent registry and classification result schemas.

The registry is the single source of truth: the classifier may only ever return
an intent from :class:`Intent`, and every LLM response is validated against it.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Intent(str, Enum):
    """Every intent the orchestrator understands in Phase 3."""

    GET_REVENUE = "GET_REVENUE"
    GET_EXPENSES = "GET_EXPENSES"
    CALCULATE_PROFIT = "CALCULATE_PROFIT"
    GET_CASH_FLOW = "GET_CASH_FLOW"
    ANALYZE_SALES = "ANALYZE_SALES"
    GET_TOP_PRODUCTS = "GET_TOP_PRODUCTS"
    CHECK_STOCK = "CHECK_STOCK"
    LOW_STOCK_ANALYSIS = "LOW_STOCK_ANALYSIS"
    CUSTOMER_ANALYSIS = "CUSTOMER_ANALYSIS"
    GET_INACTIVE_CUSTOMERS = "GET_INACTIVE_CUSTOMERS"
    GET_SUPPLIER_DETAILS = "GET_SUPPLIER_DETAILS"
    GENERATE_FINANCIAL_REPORT = "GENERATE_FINANCIAL_REPORT"
    GENERATE_SALES_REPORT = "GENERATE_SALES_REPORT"
    GENERATE_INVENTORY_REPORT = "GENERATE_INVENTORY_REPORT"
    CREATE_SALES_ORDER = "CREATE_SALES_ORDER"
    CREATE_EXPENSE = "CREATE_EXPENSE"
    CREATE_PURCHASE_RECOMMENDATION = "CREATE_PURCHASE_RECOMMENDATION"
    GENERAL_BUSINESS_ANALYSIS = "GENERAL_BUSINESS_ANALYSIS"
    # Phase 4: intents that route to a specialist agent
    FINANCIAL_ANALYSIS = "FINANCIAL_ANALYSIS"
    ANALYZE_EXPENSE_ANOMALIES = "ANALYZE_EXPENSE_ANOMALIES"
    BUSINESS_HEALTH_REPORT = "BUSINESS_HEALTH_REPORT"
    COMPARE_SALES_INVENTORY = "COMPARE_SALES_INVENTORY"
    BUSINESS_RISK_ANALYSIS = "BUSINESS_RISK_ANALYSIS"
    # Phase 5: multi-agent collaborations
    COLLAB_SALES_GROWTH = "COLLAB_SALES_GROWTH"
    COLLAB_REORDER_CASHFLOW = "COLLAB_REORDER_CASHFLOW"
    COLLAB_DECLINING_SALES = "COLLAB_DECLINING_SALES"
    COLLAB_BUSINESS_HEALTH = "COLLAB_BUSINESS_HEALTH"
    COLLAB_SUPPLIER_CASHFLOW = "COLLAB_SUPPLIER_CASHFLOW"
    ANALYTICS_PERFORMANCE = "ANALYTICS_PERFORMANCE"
    ANALYTICS_FORECAST = "ANALYTICS_FORECAST"
    ANALYTICS_ANOMALIES = "ANALYTICS_ANOMALIES"
    ANALYTICS_RISK = "ANALYTICS_RISK"
    ANALYTICS_SIMULATION = "ANALYTICS_SIMULATION"
    KNOWLEDGE_SEARCH = "KNOWLEDGE_SEARCH"
    DOCUMENT_QUESTION = "DOCUMENT_QUESTION"
    UNKNOWN_INTENT = "UNKNOWN_INTENT"


class IntentDefinition(BaseModel):
    """Registry entry describing one intent."""

    model_config = ConfigDict(frozen=True)

    intent: Intent
    label: str
    description: str
    example: str
    required_permission: str
    tools: tuple[str, ...] = ()
    requires_approval: bool = False


INTENT_DEFINITIONS: dict[Intent, IntentDefinition] = {
    Intent.GET_REVENUE: IntentDefinition(
        intent=Intent.GET_REVENUE,
        label="Revenue",
        description="Revenue recognised from completed sales, net of refunds",
        example="Show this month's revenue.",
        required_permission="finance.view",
        tools=("get_revenue",),
    ),
    Intent.GET_EXPENSES: IntentDefinition(
        intent=Intent.GET_EXPENSES,
        label="Expenses",
        description="Recorded operating expenses for a period",
        example="What are my expenses this month?",
        required_permission="finance.view",
        tools=("get_expenses",),
    ),
    Intent.CALCULATE_PROFIT: IntentDefinition(
        intent=Intent.CALCULATE_PROFIT,
        label="Profit",
        description="Gross and net profit from real ledger data",
        example="Calculate my business profit.",
        required_permission="finance.view",
        tools=("calculate_profit",),
    ),
    Intent.GET_CASH_FLOW: IntentDefinition(
        intent=Intent.GET_CASH_FLOW,
        label="Cash flow",
        description="Cash received, refunds and expenses paid",
        example="Show my cash flow for this month.",
        required_permission="finance.view",
        tools=("get_cash_flow", "get_outstanding_payments"),
    ),
    Intent.ANALYZE_SALES: IntentDefinition(
        intent=Intent.ANALYZE_SALES,
        label="Sales analysis",
        description="Order counts, values, trends and pending orders",
        example="Analyse my sales this month.",
        required_permission="sales.view",
        tools=("get_sales_summary", "get_sales_trends"),
    ),
    Intent.GET_TOP_PRODUCTS: IntentDefinition(
        intent=Intent.GET_TOP_PRODUCTS,
        label="Top products",
        description="Best selling products by revenue and quantity",
        example="Which products are selling the most?",
        required_permission="sales.view",
        tools=("get_top_products",),
    ),
    Intent.CHECK_STOCK: IntentDefinition(
        intent=Intent.CHECK_STOCK,
        label="Stock check",
        description="Current stock level for a product or the whole catalogue",
        example="Check the stock of Assam Tea.",
        required_permission="inventory.view",
        tools=("get_product_stock", "get_stock_valuation"),
    ),
    Intent.LOW_STOCK_ANALYSIS: IntentDefinition(
        intent=Intent.LOW_STOCK_ANALYSIS,
        label="Low stock",
        description="Products at or below their minimum stock",
        example="Find products running out of stock.",
        required_permission="inventory.view",
        tools=("get_low_stock_products",),
    ),
    Intent.CUSTOMER_ANALYSIS: IntentDefinition(
        intent=Intent.CUSTOMER_ANALYSIS,
        label="Customer analysis",
        description="Customer counts, segments and purchase behaviour",
        example="Tell me about my customers.",
        required_permission="customers.view",
        tools=("get_customer_summary",),
    ),
    Intent.GET_INACTIVE_CUSTOMERS: IntentDefinition(
        intent=Intent.GET_INACTIVE_CUSTOMERS,
        label="Inactive customers",
        description="Customers without a recent purchase",
        example="Show customers who haven't purchased recently.",
        required_permission="customers.view",
        tools=("get_inactive_customers",),
    ),
    Intent.GET_SUPPLIER_DETAILS: IntentDefinition(
        intent=Intent.GET_SUPPLIER_DETAILS,
        label="Supplier details",
        description="Supplier profile, purchase history and open orders",
        example="Show details for my supplier Odisha Beverages.",
        required_permission="suppliers.view",
        tools=("get_supplier_details", "get_purchase_order_status"),
    ),
    Intent.GENERATE_FINANCIAL_REPORT: IntentDefinition(
        intent=Intent.GENERATE_FINANCIAL_REPORT,
        label="Financial report",
        description="Profit and loss report exported to PDF",
        example="Prepare my monthly financial report.",
        required_permission="finance.export",
        tools=("generate_financial_report",),
    ),
    Intent.GENERATE_SALES_REPORT: IntentDefinition(
        intent=Intent.GENERATE_SALES_REPORT,
        label="Sales report",
        description="Sales report exported to CSV",
        example="Generate a sales report.",
        required_permission="sales.export",
        tools=("generate_sales_report",),
    ),
    Intent.GENERATE_INVENTORY_REPORT: IntentDefinition(
        intent=Intent.GENERATE_INVENTORY_REPORT,
        label="Inventory report",
        description="Inventory report exported to CSV",
        example="Generate an inventory report.",
        required_permission="inventory.export",
        tools=("generate_inventory_report",),
    ),
    Intent.CREATE_SALES_ORDER: IntentDefinition(
        intent=Intent.CREATE_SALES_ORDER,
        label="New sales order",
        description="Prepare a sales order for human approval before it is created",
        example="Create a sale of 2 Assam Tea for Asha Rao.",
        required_permission="sales.create",
        tools=("prepare_sales_order",),
        requires_approval=True,
    ),
    Intent.CREATE_EXPENSE: IntentDefinition(
        intent=Intent.CREATE_EXPENSE,
        label="Record expense",
        description="Prepare an expense for human approval before it is recorded",
        example="Record an expense of 5000 for shop rent.",
        required_permission="finance.create",
        tools=("prepare_expense",),
        requires_approval=True,
    ),
    Intent.CREATE_PURCHASE_RECOMMENDATION: IntentDefinition(
        intent=Intent.CREATE_PURCHASE_RECOMMENDATION,
        label="Purchase recommendation",
        description="Demand, stock and cash analysis that recommends a purchase quantity",
        example="Check whether I can purchase 50 units of Assam Tea.",
        required_permission="inventory.view",
        tools=(
            "get_product_stock",
            "get_sales_history",
            "get_cash_flow",
            "create_purchase_recommendation",
        ),
    ),
    Intent.GENERAL_BUSINESS_ANALYSIS: IntentDefinition(
        intent=Intent.GENERAL_BUSINESS_ANALYSIS,
        label="Business overview",
        description="Combined finance, sales and inventory snapshot",
        example="How is my business doing?",
        required_permission="dashboard.view",
        tools=("get_revenue", "get_sales_summary", "get_low_stock_products", "calculate_profit"),
    ),
    Intent.FINANCIAL_ANALYSIS: IntentDefinition(
        intent=Intent.FINANCIAL_ANALYSIS,
        label="Financial analysis",
        description="Full finance review delegated to the Finance Agent",
        example="Analyze my monthly finances.",
        required_permission="finance.view",
        tools=("run_finance_agent",),
    ),
    Intent.ANALYZE_EXPENSE_ANOMALIES: IntentDefinition(
        intent=Intent.ANALYZE_EXPENSE_ANOMALIES,
        label="Expense anomalies",
        description="Statistical outliers in recorded expenses",
        example="Find unusual business expenses.",
        required_permission="finance.view",
        tools=("run_finance_agent",),
    ),
    Intent.BUSINESS_HEALTH_REPORT: IntentDefinition(
        intent=Intent.BUSINESS_HEALTH_REPORT,
        label="Business health report",
        description="Cross-functional analysis from all five agents",
        example="Give me a complete business health report.",
        required_permission="dashboard.view",
        tools=("run_business_intelligence_agent",),
    ),
    Intent.COMPARE_SALES_INVENTORY: IntentDefinition(
        intent=Intent.COMPARE_SALES_INVENTORY,
        label="Sales vs inventory",
        description="Demand versus stock cover, with stockout risk",
        example="Compare sales and inventory performance.",
        required_permission="inventory.view",
        tools=("run_business_intelligence_agent",),
    ),
    Intent.BUSINESS_RISK_ANALYSIS: IntentDefinition(
        intent=Intent.BUSINESS_RISK_ANALYSIS,
        label="Business risks",
        description="Risks across finance, sales, customers and inventory",
        example="Identify business risks.",
        required_permission="dashboard.view",
        tools=("run_business_intelligence_agent",),
    ),
    Intent.COLLAB_SALES_GROWTH: IntentDefinition(
        intent=Intent.COLLAB_SALES_GROWTH,
        label="Sales growth feasibility",
        description="Five-agent collaboration on whether sales can grow",
        example="Can I increase my sales by 20% next month?",
        required_permission="agents.execute",
        tools=("run_collaboration",),
    ),
    Intent.COLLAB_REORDER_CASHFLOW: IntentDefinition(
        intent=Intent.COLLAB_REORDER_CASHFLOW,
        label="Reorder within cash flow",
        description="Replenishment prioritised against available cash",
        example="Which products should I reorder without affecting my cash flow?",
        required_permission="agents.execute",
        tools=("run_collaboration",),
    ),
    Intent.COLLAB_DECLINING_SALES: IntentDefinition(
        intent=Intent.COLLAB_DECLINING_SALES,
        label="Declining sales investigation",
        description="Evidence-based investigation of a sales decline",
        example="Why are my sales decreasing?",
        required_permission="agents.execute",
        tools=("run_collaboration",),
    ),
    Intent.COLLAB_BUSINESS_HEALTH: IntentDefinition(
        intent=Intent.COLLAB_BUSINESS_HEALTH,
        label="Complete business performance",
        description="All five agents collaborate on business performance",
        example="Analyze my complete business performance.",
        required_permission="agents.execute",
        tools=("run_collaboration",),
    ),
    Intent.COLLAB_SUPPLIER_CASHFLOW: IntentDefinition(
        intent=Intent.COLLAB_SUPPLIER_CASHFLOW,
        label="Supplier purchase and cash",
        description="Whether inventory can be purchased this week",
        example="Can I purchase inventory from my suppliers this week?",
        required_permission="agents.execute",
        tools=("run_collaboration",),
    ),
    Intent.ANALYTICS_PERFORMANCE: IntentDefinition(
        intent=Intent.ANALYTICS_PERFORMANCE,
        label="Business performance analytics",
        description="Period performance across finance, sales, customers and inventory",
        example="How did my business perform this month?",
        required_permission="analytics.view",
        tools=("get_business_analytics", "get_business_kpis"),
    ),
    Intent.ANALYTICS_FORECAST: IntentDefinition(
        intent=Intent.ANALYTICS_FORECAST,
        label="Forecast",
        description="Validated forecast of sales, revenue, expenses, cash or demand",
        example="Forecast next month's sales.",
        required_permission="analytics.view",
        tools=("forecast_business_metric",),
    ),
    Intent.ANALYTICS_ANOMALIES: IntentDefinition(
        intent=Intent.ANALYTICS_ANOMALIES,
        label="Anomaly detection",
        description="Unusual expenses, sales and stock patterns for review",
        example="Identify unusual expenses.",
        required_permission="analytics.view",
        tools=("detect_business_anomalies",),
    ),
    Intent.ANALYTICS_RISK: IntentDefinition(
        intent=Intent.ANALYTICS_RISK,
        label="Business risk assessment",
        description="Scored business risks with evidence and mitigation",
        example="What are my biggest business risks?",
        required_permission="analytics.view",
        tools=("assess_business_risks",),
    ),
    Intent.ANALYTICS_SIMULATION: IntentDefinition(
        intent=Intent.ANALYTICS_SIMULATION,
        label="What-if simulation",
        description="Hypothetical scenario compared with a real baseline",
        example="Simulate a 10% reduction in sales.",
        required_permission="analytics.manage",
        tools=("simulate_business_scenario",),
    ),
    Intent.KNOWLEDGE_SEARCH: IntentDefinition(
        intent=Intent.KNOWLEDGE_SEARCH,
        label="Document search",
        description="Find passages in uploaded business documents",
        example="Find supplier agreements mentioning 30-day payment terms.",
        required_permission="knowledge.view",
        tools=("search_business_documents",),
    ),
    Intent.DOCUMENT_QUESTION: IntentDefinition(
        intent=Intent.DOCUMENT_QUESTION,
        label="Document question",
        description="Answer a question from business documents, with citations",
        example="What are the payment terms in our supplier agreement?",
        required_permission="knowledge.ask",
        tools=("ask_business_documents",),
    ),
    Intent.UNKNOWN_INTENT: IntentDefinition(
        intent=Intent.UNKNOWN_INTENT,
        label="Unknown",
        description="The command did not match any supported intent",
        example="Sing me a song.",
        required_permission="dashboard.view",
        tools=(),
    ),
}


class ClassifiedBy(str, Enum):
    RULES = "rules"
    OLLAMA = "ollama"
    GEMINI = "gemini"
    FALLBACK = "fallback"


class IntentResult(BaseModel):
    """Outcome of intent classification."""

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    classified_by: ClassifiedBy = ClassifiedBy.RULES
    rationale: str = ""
    entities: dict[str, Any] = Field(default_factory=dict)
    alternatives: list[tuple[str, float]] = Field(default_factory=list)
    requires_clarification: bool = False
    clarification_question: str | None = None

    @property
    def definition(self) -> IntentDefinition:
        return INTENT_DEFINITIONS[self.intent]

    @property
    def is_actionable(self) -> bool:
        return self.intent is not Intent.UNKNOWN_INTENT and not self.requires_clarification
