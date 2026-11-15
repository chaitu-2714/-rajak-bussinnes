"""The six autonomous workflow templates.

Each template is a declarative task graph: what to retrieve, which agent to ask,
where an approval checkpoint sits, and what must be verified afterwards. Nothing
here executes anything — the engine does that, through the action allowlist.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.ai.schemas.autonomy_schema import WorkflowTaskSpec
from app.core.constants import (
    WorkflowTaskType,
    WorkflowTriggerType,
    WorkflowType,
)


@dataclass(frozen=True)
class WorkflowTemplate:
    workflow_type: str
    label: str
    objective_template: str
    trigger_description: str
    default_trigger: str
    tasks: tuple[WorkflowTaskSpec, ...] = field(default_factory=tuple)
    requires_approval: bool = False

    @property
    def task_keys(self) -> list[str]:
        return [task.task_key for task in self.tasks]

    @property
    def agents(self) -> list[str]:
        return sorted({task.assigned_agent for task in self.tasks if task.assigned_agent})


def _task(
    key: str,
    task_type: str,
    title: str,
    *,
    action: str | None = None,
    agent: str | None = None,
    depends_on: tuple[str, ...] = (),
    risk: str = "LOW",
    permission: str | None = None,
    params: dict | None = None,
) -> WorkflowTaskSpec:
    return WorkflowTaskSpec(
        task_key=key,
        task_type=task_type,
        title=title,
        assigned_agent=agent,
        action_name=action,
        input_data=dict(params or {}),
        dependencies=list(depends_on),
        permission_required=permission,
        risk_level=risk,
    )


LOW_STOCK_REPLENISHMENT = WorkflowTemplate(
    workflow_type=WorkflowType.LOW_STOCK_REPLENISHMENT,
    label="Smart low-stock replenishment",
    objective_template="Replenish {product} safely within the available cash.",
    trigger_description="A product fell to or below its minimum stock level",
    default_trigger=WorkflowTriggerType.EVENT,
    requires_approval=True,
    tasks=(
        _task("detect_stock", WorkflowTaskType.DATA_RETRIEVAL, "Read current low-stock alerts",
              action="retrieve_low_stock"),
        _task("stock_history", WorkflowTaskType.DATA_RETRIEVAL, "Read recent stock movements",
              action="retrieve_inventory_history", depends_on=("detect_stock",)),
        _task("inventory_analysis", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Inventory agent analyses the shortage", agent="inventory_agent",
              depends_on=("detect_stock",), params={"task_type": "REORDER_PLANNING"}),
        _task("demand_analysis", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Sales agent confirms demand", agent="sales_agent",
              depends_on=("detect_stock",), params={"task_type": "SALES_ANALYSIS"}),
        _task("budget_check", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Finance agent checks the budget", agent="finance_agent",
              depends_on=("inventory_analysis",), params={"task_type": "FINANCIAL_ANALYSIS"}),
        _task("recommendation", WorkflowTaskType.RECOMMENDATION,
              "Draft the purchase recommendation", action="create_purchase_recommendation",
              depends_on=("demand_analysis", "budget_check")),
        _task("approval", WorkflowTaskType.APPROVAL_REQUEST,
              "Request approval to create the purchase order", action="create_purchase_order",
              depends_on=("recommendation",), risk="HIGH",
              permission="purchase_orders.create"),
        _task("verify", WorkflowTaskType.VERIFICATION, "Verify the purchase order exists",
              depends_on=("approval",)),
        _task("notify", WorkflowTaskType.NOTIFICATION, "Record the outcome",
              action="prepare_customer_followup", depends_on=("verify",),
              params={"internal_only": True}),
    ),
)

CUSTOMER_FOLLOWUP = WorkflowTemplate(
    workflow_type=WorkflowType.CUSTOMER_FOLLOWUP,
    label="Customer follow-up",
    objective_template="Re-engage {customer} who has not purchased recently.",
    trigger_description="A customer has been inactive beyond the configured period",
    default_trigger=WorkflowTriggerType.THRESHOLD,
    requires_approval=True,
    tasks=(
        _task("customer_history", WorkflowTaskType.DATA_RETRIEVAL, "Read the customer history",
              action="retrieve_customer_history"),
        _task("customer_analysis", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Customer agent analyses the relationship", agent="customer_agent",
              depends_on=("customer_history",), params={"task_type": "CUSTOMER_ANALYSIS"}),
        _task("sales_pattern", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Sales agent checks purchasing patterns", agent="sales_agent",
              depends_on=("customer_history",), params={"task_type": "SALES_ANALYSIS"}),
        _task("draft", WorkflowTaskType.RECOMMENDATION, "Prepare the follow-up draft",
              action="prepare_customer_followup", depends_on=("customer_analysis", "sales_pattern")),
        _task("approval", WorkflowTaskType.APPROVAL_REQUEST,
              "Approve sending the follow-up", action="send_customer_message",
              depends_on=("draft",), risk="HIGH", permission="customers.update"),
        _task("record", WorkflowTaskType.NOTIFICATION, "Record the follow-up outcome",
              depends_on=("draft",)),
    ),
)

DAILY_SUMMARY = WorkflowTemplate(
    workflow_type=WorkflowType.DAILY_SUMMARY,
    label="Daily business summary",
    objective_template="Produce today's management summary.",
    trigger_description="Configured daily schedule",
    default_trigger=WorkflowTriggerType.SCHEDULE,
    tasks=(
        _task("daily_metrics", WorkflowTaskType.DATA_RETRIEVAL, "Collect today's figures",
              action="retrieve_daily_metrics"),
        _task("consolidation", WorkflowTaskType.BUSINESS_ANALYSIS,
              "BI agent consolidates the findings", agent="business_intelligence_agent",
              depends_on=("daily_metrics",), params={"task_type": "BUSINESS_HEALTH"}),
        _task("report", WorkflowTaskType.REPORT_GENERATION, "Write the daily report",
              action="generate_daily_report", depends_on=("daily_metrics",)),
        _task("verify", WorkflowTaskType.VERIFICATION, "Verify the report was produced",
              depends_on=("report",)),
    ),
)

UNUSUAL_EXPENSE_REVIEW = WorkflowTemplate(
    workflow_type=WorkflowType.UNUSUAL_EXPENSE_REVIEW,
    label="Unusual expense review",
    objective_template="Review the unusual expense of {amount}.",
    trigger_description="A recorded expense exceeded the configured threshold",
    default_trigger=WorkflowTriggerType.EVENT,
    tasks=(
        _task("expense_context", WorkflowTaskType.DATA_RETRIEVAL, "Read the expense and context",
              action="retrieve_daily_metrics"),
        _task("finance_analysis", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Finance agent reviews the anomaly", agent="finance_agent",
              depends_on=("expense_context",), params={"task_type": "EXPENSE_ANOMALIES"}),
        _task("bi_context", WorkflowTaskType.BUSINESS_ANALYSIS,
              "BI agent evaluates the business context", agent="business_intelligence_agent",
              depends_on=("expense_context", "finance_analysis"),
              params={"task_type": "RISK_ANALYSIS"}),
        _task("alert", WorkflowTaskType.NOTIFICATION,
              "Raise an internal review alert (no reversal, no deletion)",
              depends_on=("bi_context",)),
    ),
)

SALES_RECOVERY = WorkflowTemplate(
    workflow_type=WorkflowType.SALES_RECOVERY,
    label="Sales performance recovery",
    objective_template="Investigate the sales decline and prepare a recovery plan.",
    trigger_description="Sales fell below the configured threshold",
    default_trigger=WorkflowTriggerType.THRESHOLD,
    tasks=(
        _task("sales_trend", WorkflowTaskType.DATA_RETRIEVAL, "Read the sales trend",
              action="retrieve_daily_metrics"),
        _task("sales_analysis", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Sales agent investigates", agent="sales_agent",
              depends_on=("sales_trend",), params={"task_type": "SALES_ANALYSIS"}),
        _task("customer_scan", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Customer agent inspects activity", agent="customer_agent",
              depends_on=("sales_trend",), params={"task_type": "CUSTOMER_ANALYSIS"}),
        _task("inventory_scan", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Inventory agent inspects availability", agent="inventory_agent",
              depends_on=("sales_trend",), params={"task_type": "INVENTORY_ANALYSIS"}),
        _task("finance_scan", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Finance agent inspects margins", agent="finance_agent",
              depends_on=("sales_trend",), params={"task_type": "FINANCIAL_ANALYSIS"}),
        _task("coordination", WorkflowTaskType.AGENT_COLLABORATION,
              "BI agent coordinates the findings", agent="business_intelligence_agent",
              depends_on=("sales_analysis", "customer_scan", "inventory_scan", "finance_scan")),
        _task("plan", WorkflowTaskType.RECOMMENDATION, "Prepare the recovery action plan",
              depends_on=("coordination",)),
        _task("notify", WorkflowTaskType.NOTIFICATION,
              "Record the plan for human action", depends_on=("plan",)),
    ),
)

PENDING_PAYMENT_FOLLOWUP = WorkflowTemplate(
    workflow_type=WorkflowType.PENDING_PAYMENT_FOLLOWUP,
    label="Pending payment follow-up",
    objective_template="Follow up on overdue invoice {invoice_number}.",
    trigger_description="An invoice passed its due date with a balance outstanding",
    default_trigger=WorkflowTriggerType.SCHEDULE,
    requires_approval=True,
    tasks=(
        _task("overdue", WorkflowTaskType.DATA_RETRIEVAL, "Read overdue invoices",
              action="retrieve_overdue_invoices"),
        _task("customer_context", WorkflowTaskType.DATA_RETRIEVAL, "Read the customer history",
              action="retrieve_customer_history", depends_on=("overdue",)),
        _task("customer_analysis", WorkflowTaskType.BUSINESS_ANALYSIS,
              "Customer agent evaluates the relationship", agent="customer_agent",
              depends_on=("customer_context",), params={"task_type": "CUSTOMER_ANALYSIS"}),
        _task("reminder", WorkflowTaskType.RECOMMENDATION, "Prepare the reminder draft",
              action="prepare_payment_reminder", depends_on=("customer_analysis",)),
        _task("approval", WorkflowTaskType.APPROVAL_REQUEST,
              "Approve sending the reminder", action="send_customer_message",
              depends_on=("reminder",), risk="HIGH", permission="customers.update"),
        _task("record", WorkflowTaskType.NOTIFICATION, "Record the reminder outcome",
              depends_on=("reminder",)),
    ),
)

TEMPLATES: dict[str, WorkflowTemplate] = {
    template.workflow_type: template
    for template in (
        LOW_STOCK_REPLENISHMENT,
        CUSTOMER_FOLLOWUP,
        DAILY_SUMMARY,
        UNUSUAL_EXPENSE_REVIEW,
        SALES_RECOVERY,
        PENDING_PAYMENT_FOLLOWUP,
    )
}


def get_template(workflow_type: str) -> WorkflowTemplate:
    template = TEMPLATES.get(workflow_type)
    if template is None:
        raise ValueError(
            f"Unknown workflow type '{workflow_type}'. Known: {', '.join(sorted(TEMPLATES))}"
        )
    return template


def workflow_types() -> list[str]:
    return sorted(TEMPLATES)
