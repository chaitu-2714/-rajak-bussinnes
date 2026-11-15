"""Permission catalogue, default roles, audit actions and business enums.

The permission catalogue is the single source of truth: it seeds the
``permissions`` table and drives the RBAC UI grouping.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import APP_VERSION

APP_TITLE = "BizPilot AI"

# --- Modules (used for grouping permissions in the UI) ----------------------
MODULE_DASHBOARD = "Dashboard"
MODULE_AUTHENTICATION = "Authentication"
MODULE_USERS = "User Management"
MODULE_ROLES = "Roles"
MODULE_FINANCE = "Finance"
MODULE_SALES = "Sales"
MODULE_CUSTOMERS = "Customers"
MODULE_INVENTORY = "Inventory"
MODULE_SUPPLIERS = "Suppliers"
MODULE_PURCHASING = "Purchasing"
MODULE_AGENTS = "AI Agents"
MODULE_AUTOMATION = "Automation"
MODULE_APPROVALS = "Approvals"
MODULE_ANALYTICS = "Business Intelligence"
MODULE_KNOWLEDGE = "Knowledge"
MODULE_SECURITY = "Security"
MODULE_REPORTS = "Reports"
MODULE_AUDIT = "Audit"
MODULE_SETTINGS = "Settings"

PERMISSION_MODULES: tuple[str, ...] = (
    MODULE_DASHBOARD,
    MODULE_AUTHENTICATION,
    MODULE_USERS,
    MODULE_ROLES,
    MODULE_FINANCE,
    MODULE_SALES,
    MODULE_CUSTOMERS,
    MODULE_INVENTORY,
    MODULE_SUPPLIERS,
    MODULE_PURCHASING,
    MODULE_AGENTS,
    MODULE_AUTOMATION,
    MODULE_APPROVALS,
    MODULE_ANALYTICS,
    MODULE_REPORTS,
    MODULE_AUDIT,
    MODULE_SETTINGS,
)


@dataclass(frozen=True)
class PermissionDefinition:
    key: str
    name: str
    module: str
    description: str


PERMISSION_DEFINITIONS: tuple[PermissionDefinition, ...] = (
    PermissionDefinition("dashboard.view", "View dashboard", MODULE_DASHBOARD, "Access the overview dashboard"),
    PermissionDefinition("auth.change_password", "Change own password", MODULE_AUTHENTICATION, "Change the password of the signed-in account"),
    PermissionDefinition("users.view", "View users", MODULE_USERS, "List and inspect user accounts"),
    PermissionDefinition("users.create", "Create users", MODULE_USERS, "Create new user accounts"),
    PermissionDefinition("users.update", "Update users", MODULE_USERS, "Edit user details and roles"),
    PermissionDefinition("users.deactivate", "Deactivate users", MODULE_USERS, "Activate or deactivate user accounts"),
    PermissionDefinition("users.reset_password", "Reset user passwords", MODULE_USERS, "Set a temporary password for another user"),
    PermissionDefinition("roles.view", "View roles", MODULE_ROLES, "List roles and their permissions"),
    PermissionDefinition("roles.create", "Create roles", MODULE_ROLES, "Create custom roles"),
    PermissionDefinition("roles.update", "Update roles", MODULE_ROLES, "Edit custom roles and their permissions"),
    PermissionDefinition("roles.assign", "Assign roles", MODULE_ROLES, "Assign roles to users"),
    PermissionDefinition("finance.view", "View finance", MODULE_FINANCE, "Access financial summaries, transactions and reports"),
    PermissionDefinition("finance.create", "Record expenses and income", MODULE_FINANCE, "Add expenses and other financial records"),
    PermissionDefinition("finance.update", "Update finance records", MODULE_FINANCE, "Edit or reverse financial records"),
    PermissionDefinition("finance.approve", "Approve finance", MODULE_FINANCE, "Approve financial records and reversals"),
    PermissionDefinition("finance.export", "Export finance", MODULE_FINANCE, "Export financial reports to CSV and PDF"),
    PermissionDefinition("sales.view", "View sales", MODULE_SALES, "Access sales orders and invoices"),
    PermissionDefinition("sales.create", "Create sales", MODULE_SALES, "Create, confirm and complete sales orders"),
    PermissionDefinition("sales.update", "Update sales", MODULE_SALES, "Edit draft sales orders and record payments"),
    PermissionDefinition("sales.cancel", "Cancel sales", MODULE_SALES, "Cancel sales orders and reverse stock"),
    PermissionDefinition("sales.export", "Export sales", MODULE_SALES, "Export sales reports to CSV and PDF"),
    PermissionDefinition("customers.view", "View customers", MODULE_CUSTOMERS, "Access customer records and history"),
    PermissionDefinition("customers.create", "Create customers", MODULE_CUSTOMERS, "Add customer records"),
    PermissionDefinition("customers.update", "Update customers", MODULE_CUSTOMERS, "Edit customer records and follow-ups"),
    PermissionDefinition("customers.deactivate", "Deactivate customers", MODULE_CUSTOMERS, "Activate or deactivate customers"),
    PermissionDefinition("customers.export", "Export customers", MODULE_CUSTOMERS, "Export the customer list"),
    PermissionDefinition("inventory.view", "View inventory", MODULE_INVENTORY, "Access products, stock and movements"),
    PermissionDefinition("inventory.create", "Create products", MODULE_INVENTORY, "Add products and categories"),
    PermissionDefinition("inventory.update", "Update inventory", MODULE_INVENTORY, "Edit products and categories"),
    PermissionDefinition("inventory.adjust", "Adjust stock", MODULE_INVENTORY, "Record stock additions, reductions and adjustments"),
    PermissionDefinition("inventory.export", "Export inventory", MODULE_INVENTORY, "Export inventory and stock reports"),
    PermissionDefinition("suppliers.view", "View suppliers", MODULE_SUPPLIERS, "Access supplier records"),
    PermissionDefinition("suppliers.create", "Create suppliers", MODULE_SUPPLIERS, "Add supplier records"),
    PermissionDefinition("suppliers.update", "Update suppliers", MODULE_SUPPLIERS, "Edit supplier records"),
    PermissionDefinition("suppliers.deactivate", "Deactivate suppliers", MODULE_SUPPLIERS, "Activate or deactivate suppliers"),
    PermissionDefinition("purchase_orders.view", "View purchase orders", MODULE_PURCHASING, "Access purchase orders and goods receipts"),
    PermissionDefinition("purchase_orders.create", "Create purchase orders", MODULE_PURCHASING, "Raise purchase orders with suppliers"),
    PermissionDefinition("purchase_orders.approve", "Approve purchase orders", MODULE_PURCHASING, "Approve and place purchase orders"),
    PermissionDefinition("purchase_orders.receive", "Receive goods", MODULE_PURCHASING, "Record goods receipts against purchase orders"),
    PermissionDefinition("agents.view", "View AI agents", MODULE_AGENTS, "Access the AI Command Center and agent registry"),
    PermissionDefinition("agents.execute", "Run AI commands", MODULE_AGENTS, "Execute AI orchestration workflows"),
    PermissionDefinition("agents.configure", "Configure AI", MODULE_AGENTS, "Change AI provider settings and cloud data sharing"),
    PermissionDefinition("automation.view", "View automation", MODULE_AUTOMATION, "Access the automation studio"),
    PermissionDefinition("automation.execute", "Run automations", MODULE_AUTOMATION, "Start, pause, resume and retry autonomous workflows"),
    PermissionDefinition("approvals.view", "View approvals", MODULE_APPROVALS, "Access the approval center"),
    PermissionDefinition("approvals.approve", "Approve requests", MODULE_APPROVALS, "Approve or reject pending requests"),
    PermissionDefinition("analytics.view", "View business intelligence", MODULE_ANALYTICS, "Access analytics dashboards"),
    PermissionDefinition("analytics.manage", "Manage analytics", MODULE_ANALYTICS, "Run forecasts and simulations, review anomalies"),
    PermissionDefinition("knowledge.view", "View knowledge", MODULE_KNOWLEDGE, "Browse and search business documents"),
    PermissionDefinition("knowledge.upload", "Upload documents", MODULE_KNOWLEDGE, "Add business documents to the knowledge base"),
    PermissionDefinition("knowledge.manage", "Manage knowledge", MODULE_KNOWLEDGE, "Reprocess, archive and delete documents"),
    PermissionDefinition("knowledge.ask", "Ask the document assistant", MODULE_KNOWLEDGE, "Ask questions answered from business documents"),
    PermissionDefinition("security.view", "View security", MODULE_SECURITY, "See the security dashboard and governance settings"),
    PermissionDefinition("security.manage", "Manage security", MODULE_SECURITY, "Change security policies, MFA enforcement and agent limits"),
    PermissionDefinition("audit.export", "Export audit trail", MODULE_SECURITY, "Export audit records for external retention"),
    PermissionDefinition("backup.view", "View backups", MODULE_SECURITY, "See backup and restore history"),
    PermissionDefinition("backup.create", "Create backups", MODULE_SECURITY, "Create and validate backups"),
    PermissionDefinition("backup.restore", "Restore backups", MODULE_SECURITY, "Restore a validated backup"),
    PermissionDefinition("reports.view", "View reports", MODULE_REPORTS, "Generate and view reports"),
    PermissionDefinition("audit.view", "View audit log", MODULE_AUDIT, "Read the audit trail"),
    PermissionDefinition("settings.view", "View settings", MODULE_SETTINGS, "View business and application settings"),
    PermissionDefinition("settings.update", "Update settings", MODULE_SETTINGS, "Change business and application settings"),
)

PERMISSION_KEYS: tuple[str, ...] = tuple(p.key for p in PERMISSION_DEFINITIONS)

# --- Roles ------------------------------------------------------------------
ROLE_SUPER_ADMIN = "Super Admin"
ROLE_BUSINESS_ADMIN = "Business Admin"
ROLE_FINANCE_MANAGER = "Finance Manager"
ROLE_SALES_MANAGER = "Sales Manager"
ROLE_INVENTORY_MANAGER = "Inventory Manager"
ROLE_EMPLOYEE = "Employee"


@dataclass(frozen=True)
class RoleDefinition:
    name: str
    description: str
    permissions: tuple[str, ...]  # "*" means every permission


DEFAULT_ROLES: tuple[RoleDefinition, ...] = (
    RoleDefinition(ROLE_SUPER_ADMIN, "Full control over the workspace, users, roles and settings", ("*",)),
    RoleDefinition(
        ROLE_BUSINESS_ADMIN,
        "Runs day-to-day business operations and manages employees",
        (
            "dashboard.view",
            "auth.change_password",
            "users.view",
            "users.create",
            "users.update",
            "users.deactivate",
            "users.reset_password",
            "roles.view",
            "roles.assign",
            "finance.view",
            "finance.export",
            "sales.view",
            "sales.export",
            "sales.cancel",
            "customers.view",
            "customers.create",
            "customers.update",
            "customers.deactivate",
            "customers.export",
            "inventory.view",
            "inventory.export",
            "suppliers.view",
            "suppliers.create",
            "suppliers.update",
            "suppliers.deactivate",
            "purchase_orders.view",
            "purchase_orders.approve",
            "agents.view",
            "agents.execute",
            "automation.view",
            "automation.execute",
            "approvals.view",
            "approvals.approve",
            "analytics.view",
            "analytics.manage",
            "knowledge.view",
            "knowledge.upload",
            "knowledge.manage",
            "knowledge.ask",
            "reports.view",
            "settings.view",
        ),
    ),
    RoleDefinition(
        ROLE_FINANCE_MANAGER,
        "Owns finance, expenses and financial reporting",
        (
            "dashboard.view",
            "auth.change_password",
            "finance.view",
            "finance.create",
            "finance.update",
            "finance.approve",
            "finance.export",
            "sales.view",
            "customers.view",
            "purchase_orders.view",
            "agents.view",
            "agents.execute",
            "reports.view",
            "analytics.view",
            "approvals.view",
        ),
    ),
    RoleDefinition(
        ROLE_SALES_MANAGER,
        "Owns sales, orders and customer relationships",
        (
            "dashboard.view",
            "auth.change_password",
            "sales.view",
            "sales.create",
            "sales.update",
            "sales.cancel",
            "sales.export",
            "customers.view",
            "customers.create",
            "customers.update",
            "customers.export",
            "inventory.view",
            "agents.view",
            "agents.execute",
            "reports.view",
            "analytics.view",
        ),
    ),
    RoleDefinition(
        ROLE_INVENTORY_MANAGER,
        "Owns inventory, products, suppliers and goods receipts",
        (
            "dashboard.view",
            "auth.change_password",
            "inventory.view",
            "inventory.create",
            "inventory.update",
            "inventory.adjust",
            "inventory.export",
            "suppliers.view",
            "suppliers.create",
            "suppliers.update",
            "purchase_orders.view",
            "purchase_orders.create",
            "purchase_orders.receive",
            "agents.view",
            "agents.execute",
            "reports.view",
            "analytics.view",
        ),
    ),
    RoleDefinition(
        ROLE_EMPLOYEE,
        "Baseline access; additional permissions are assigned explicitly",
        ("dashboard.view", "auth.change_password"),
    ),
)

# --- Audit actions ----------------------------------------------------------
class AuditAction:
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILURE = "LOGIN_FAILURE"
    LOGOUT = "LOGOUT"
    SETUP_COMPLETE = "SETUP_COMPLETE"
    CREATE_USER = "CREATE_USER"
    UPDATE_USER = "UPDATE_USER"
    ACTIVATE_USER = "ACTIVATE_USER"
    DEACTIVATE_USER = "DEACTIVATE_USER"
    RESET_PASSWORD = "RESET_PASSWORD"
    ASSIGN_ROLE = "ASSIGN_ROLE"
    CREATE_ROLE = "CREATE_ROLE"
    UPDATE_ROLE = "UPDATE_ROLE"
    UPDATE_ROLE_PERMISSIONS = "UPDATE_ROLE_PERMISSIONS"
    CHANGE_PASSWORD = "CHANGE_PASSWORD"
    UPDATE_BUSINESS_SETTINGS = "UPDATE_BUSINESS_SETTINGS"
    CREATE_BACKUP = "CREATE_BACKUP"
    RESTORE_BACKUP = "RESTORE_BACKUP"
    # Phase 2 business actions
    CREATE_CATEGORY = "CREATE_CATEGORY"
    UPDATE_CATEGORY = "UPDATE_CATEGORY"
    CREATE_PRODUCT = "CREATE_PRODUCT"
    UPDATE_PRODUCT = "UPDATE_PRODUCT"
    STOCK_ADJUSTMENT = "STOCK_ADJUSTMENT"
    CREATE_CUSTOMER = "CREATE_CUSTOMER"
    UPDATE_CUSTOMER = "UPDATE_CUSTOMER"
    DEACTIVATE_CUSTOMER = "DEACTIVATE_CUSTOMER"
    CREATE_FOLLOW_UP = "CREATE_FOLLOW_UP"
    COMPLETE_FOLLOW_UP = "COMPLETE_FOLLOW_UP"
    CREATE_SUPPLIER = "CREATE_SUPPLIER"
    UPDATE_SUPPLIER = "UPDATE_SUPPLIER"
    DEACTIVATE_SUPPLIER = "DEACTIVATE_SUPPLIER"
    CREATE_SALES_ORDER = "CREATE_SALES_ORDER"
    CONFIRM_SALES_ORDER = "CONFIRM_SALES_ORDER"
    COMPLETE_SALES_ORDER = "COMPLETE_SALES_ORDER"
    CANCEL_SALES_ORDER = "CANCEL_SALES_ORDER"
    CREATE_INVOICE = "CREATE_INVOICE"
    RECORD_PAYMENT = "RECORD_PAYMENT"
    RECORD_EXPENSE = "RECORD_EXPENSE"
    UPDATE_EXPENSE = "UPDATE_EXPENSE"
    REVERSE_EXPENSE = "REVERSE_EXPENSE"
    CREATE_PURCHASE_ORDER = "CREATE_PURCHASE_ORDER"
    APPROVE_PURCHASE_ORDER = "APPROVE_PURCHASE_ORDER"
    RECEIVE_GOODS = "RECEIVE_GOODS"
    EXPORT_REPORT = "EXPORT_REPORT"
    # Phase 3 AI actions
    AI_COMMAND = "AI_COMMAND"
    AI_WORKFLOW_COMPLETED = "AI_WORKFLOW_COMPLETED"
    AI_WORKFLOW_FAILED = "AI_WORKFLOW_FAILED"
    AI_WORKFLOW_CANCELLED = "AI_WORKFLOW_CANCELLED"
    AI_WORKFLOW_APPROVED = "AI_WORKFLOW_APPROVED"
    AI_EVENT_PROCESSED = "AI_EVENT_PROCESSED"
    AI_SETTINGS_UPDATED = "AI_SETTINGS_UPDATED"
    AI_TOOL_EXECUTED = "AI_TOOL_EXECUTED"
    # Phase 4 agent actions
    AGENT_EXECUTED = "AGENT_EXECUTED"
    AGENT_FAILED = "AGENT_FAILED"
    AGENT_RECOMMENDATION_UPDATED = "AGENT_RECOMMENDATION_UPDATED"
    # Phase 5 collaboration actions
    COLLABORATION_STARTED = "COLLABORATION_STARTED"
    COLLABORATION_COMPLETED = "COLLABORATION_COMPLETED"
    COLLABORATION_FAILED = "COLLABORATION_FAILED"
    COLLABORATION_CANCELLED = "COLLABORATION_CANCELLED"
    COLLABORATION_DECISION_GENERATED = "COLLABORATION_DECISION_GENERATED"
    COLLABORATION_DECISION_EXPORTED = "COLLABORATION_DECISION_EXPORTED"
    # Phase 6 automation actions
    WORKFLOW_CREATED = "WORKFLOW_CREATED"
    WORKFLOW_STARTED = "WORKFLOW_STARTED"
    WORKFLOW_COMPLETED = "WORKFLOW_COMPLETED"
    WORKFLOW_FAILED = "WORKFLOW_FAILED"
    WORKFLOW_CANCELLED = "WORKFLOW_CANCELLED"
    WORKFLOW_PAUSED = "WORKFLOW_PAUSED"
    WORKFLOW_RESUMED = "WORKFLOW_RESUMED"
    WORKFLOW_ROLLED_BACK = "WORKFLOW_ROLLED_BACK"
    WORKFLOW_ACTION_EXECUTED = "WORKFLOW_ACTION_EXECUTED"
    WORKFLOW_ACTION_BLOCKED = "WORKFLOW_ACTION_BLOCKED"
    APPROVAL_REQUESTED = "APPROVAL_REQUESTED"
    APPROVAL_APPROVED = "APPROVAL_APPROVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    AUTONOMY_POLICY_CREATED = "AUTONOMY_POLICY_CREATED"
    AUTONOMY_POLICY_UPDATED = "AUTONOMY_POLICY_UPDATED"
    SCHEDULE_CREATED = "SCHEDULE_CREATED"
    SCHEDULE_UPDATED = "SCHEDULE_UPDATED"
    SCHEDULE_RUN = "SCHEDULE_RUN"
    # Phase 7 analytics actions
    ANALYTICS_REPORT_GENERATED = "ANALYTICS_REPORT_GENERATED"
    # Phase 8 knowledge actions
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED"
    DOCUMENT_INDEXED = "DOCUMENT_INDEXED"
    DOCUMENT_FAILED = "DOCUMENT_FAILED"
    DOCUMENT_ARCHIVED = "DOCUMENT_ARCHIVED"
    DOCUMENT_DELETED = "DOCUMENT_DELETED"
    DOCUMENT_VERSION_ADDED = "DOCUMENT_VERSION_ADDED"
    DOCUMENT_ACCESSED = "DOCUMENT_ACCESSED"
    DOCUMENT_ACCESS_DENIED = "DOCUMENT_ACCESS_DENIED"
    KNOWLEDGE_SEARCHED = "KNOWLEDGE_SEARCHED"
    RAG_ANSWER_GENERATED = "RAG_ANSWER_GENERATED"
    EXTRACTION_VERIFIED = "EXTRACTION_VERIFIED"
    # Phase 9 security actions
    LOGIN_BLOCKED = "LOGIN_BLOCKED"
    SESSION_REVOKED = "SESSION_REVOKED"
    MFA_ENROLLMENT_STARTED = "MFA_ENROLLMENT_STARTED"
    MFA_ENABLED = "MFA_ENABLED"
    MFA_DISABLED = "MFA_DISABLED"
    MFA_VERIFICATION_FAILED = "MFA_VERIFICATION_FAILED"
    MFA_POLICY_CHANGED = "MFA_POLICY_CHANGED"
    AGENT_POLICY_UPDATED = "AGENT_POLICY_UPDATED"
    DATA_GOVERNANCE_UPDATED = "DATA_GOVERNANCE_UPDATED"
    SECURITY_EVENT_REVIEWED = "SECURITY_EVENT_REVIEWED"
    SECURITY_POLICY_UPDATED = "SECURITY_POLICY_UPDATED"
    BACKUP_CREATED = "BACKUP_CREATED"
    BACKUP_RESTORED = "BACKUP_RESTORED"
    BACKUP_VALIDATION_FAILED = "BACKUP_VALIDATION_FAILED"
    AUDIT_CHAIN_BACKFILLED = "AUDIT_CHAIN_BACKFILLED"
    AUDIT_INTEGRITY_FAILED = "AUDIT_INTEGRITY_FAILED"
    UNAUTHORIZED_ACCESS_ATTEMPT = "UNAUTHORIZED_ACCESS_ATTEMPT"
    APPROVAL_PAYLOAD_MISMATCH = "APPROVAL_PAYLOAD_MISMATCH"
    ANALYTICS_ACCESSED = "ANALYTICS_ACCESSED"
    ANOMALY_REVIEWED = "ANOMALY_REVIEWED"
    FORECAST_GENERATED = "FORECAST_GENERATED"
    SIMULATION_RUN = "SIMULATION_RUN"


AUDIT_ACTIONS: tuple[str, ...] = tuple(
    value for name, value in vars(AuditAction).items() if not name.startswith("_")
)

# --- Status labels ----------------------------------------------------------
STATUS_SUCCESS = "SUCCESS"
STATUS_FAILURE = "FAILURE"

CURRENCIES: tuple[str, ...] = ("INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD")
TIMEZONES: tuple[str, ...] = (
    "Asia/Kolkata",
    "Asia/Dubai",
    "Asia/Singapore",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles",
    "Australia/Sydney",
    "UTC",
)


# --- Business enums (stored as strings for SQLite portability) --------------
class MovementType:
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    RETURN = "RETURN"
    ADJUSTMENT = "ADJUSTMENT"
    DAMAGE = "DAMAGE"
    OPENING_STOCK = "OPENING_STOCK"

    ALL = (PURCHASE, SALE, RETURN, ADJUSTMENT, DAMAGE, OPENING_STOCK)
    # Movement types that add stock; the rest remove it.
    INBOUND = (PURCHASE, RETURN, OPENING_STOCK, ADJUSTMENT)


class OrderStatus:
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    ALL = (DRAFT, CONFIRMED, COMPLETED, CANCELLED)


class PaymentStatus:
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"

    ALL = (UNPAID, PARTIALLY_PAID, PAID, REFUNDED)


class InvoiceStatus:
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    CANCELLED = "CANCELLED"

    ALL = (UNPAID, PARTIALLY_PAID, PAID, CANCELLED)


class PaymentMethod:
    CASH = "CASH"
    CARD = "CARD"
    UPI = "UPI"
    BANK_TRANSFER = "BANK_TRANSFER"
    OTHER = "OTHER"

    ALL = (CASH, CARD, UPI, BANK_TRANSFER, OTHER)


class PurchaseOrderStatus:
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    ORDERED = "ORDERED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"

    ALL = (DRAFT, APPROVED, ORDERED, PARTIALLY_RECEIVED, RECEIVED, CANCELLED)
    RECEIVABLE = (APPROVED, ORDERED, PARTIALLY_RECEIVED)


class ExpenseCategory:
    RENT = "RENT"
    SALARY = "SALARY"
    UTILITIES = "UTILITIES"
    TRANSPORT = "TRANSPORT"
    PURCHASE = "PURCHASE"
    MARKETING = "MARKETING"
    MAINTENANCE = "MAINTENANCE"
    OTHER = "OTHER"

    ALL = (RENT, SALARY, UTILITIES, TRANSPORT, PURCHASE, MARKETING, MAINTENANCE, OTHER)
    # Purchases are capitalised into inventory and expensed through COGS,
    # so they are excluded from operating expenses in the P&L.
    CAPITALISED = (PURCHASE,)


class ExpenseStatus:
    RECORDED = "RECORDED"
    REVERSED = "REVERSED"

    ALL = (RECORDED, REVERSED)


class CustomerType:
    INDIVIDUAL = "INDIVIDUAL"
    BUSINESS = "BUSINESS"
    WHOLESALE = "WHOLESALE"
    RETAIL = "RETAIL"

    ALL = (INDIVIDUAL, BUSINESS, WHOLESALE, RETAIL)


class FollowUpStatus:
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, COMPLETED, CANCELLED)


class TransactionType:
    INCOME = "INCOME"
    EXPENSE = "EXPENSE"
    REFUND = "REFUND"

    ALL = (INCOME, EXPENSE, REFUND)


class TransactionCategory:
    """Categories used on ``financial_transactions``."""

    SALES_REVENUE = "SALES_REVENUE"
    PAYMENT_RECEIVED = "PAYMENT_RECEIVED"
    SALES_REFUND = "SALES_REFUND"
    CASH_REFUND = "CASH_REFUND"
    OPERATING_EXPENSE = "OPERATING_EXPENSE"
    CAPITAL_PURCHASE = "CAPITAL_PURCHASE"
    OTHER_INCOME = "OTHER_INCOME"


class CustomerSegment:
    NEW = "New"
    REGULAR = "Regular"
    HIGH_VALUE = "High value"
    OCCASIONAL = "Occasional"
    INACTIVE = "Inactive"

    ALL = (NEW, REGULAR, HIGH_VALUE, OCCASIONAL, INACTIVE)


# --- Business events (outbox) ----------------------------------------------
class EventType:
    SALE_COMPLETED = "SaleCompleted"
    SALE_CANCELLED = "SaleCancelled"
    STOCK_BELOW_MINIMUM = "StockBelowMinimum"
    EXPENSE_RECORDED = "ExpenseRecorded"
    PAYMENT_RECEIVED = "PaymentReceived"
    CUSTOMER_CREATED = "CustomerCreated"
    PURCHASE_ORDER_CREATED = "PurchaseOrderCreated"
    GOODS_RECEIVED = "GoodsReceived"

    ALL = (
        SALE_COMPLETED,
        SALE_CANCELLED,
        STOCK_BELOW_MINIMUM,
        EXPENSE_RECORDED,
        PAYMENT_RECEIVED,
        CUSTOMER_CREATED,
        PURCHASE_ORDER_CREATED,
        GOODS_RECEIVED,
    )


class AIWorkflowStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, RUNNING, WAITING_FOR_APPROVAL, COMPLETED, FAILED, CANCELLED)
    TERMINAL = (COMPLETED, FAILED, CANCELLED)


class AIStepStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, RUNNING, COMPLETED, FAILED, SKIPPED, CANCELLED)


class AIRiskLevel:
    READ_ONLY = "READ_ONLY"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    ALL = (READ_ONLY, LOW, MEDIUM, HIGH)
    #: Risk levels that may never run without explicit human approval.
    APPROVAL_REQUIRED = (MEDIUM, HIGH)


class AIProviderName:
    OLLAMA = "ollama"
    GEMINI = "gemini"
    FALLBACK = "fallback"

    ALL = (OLLAMA, GEMINI, FALLBACK)


class AITriggerType:
    COMMAND = "COMMAND"
    EVENT = "EVENT"
    APPROVAL = "APPROVAL"

    ALL = (COMMAND, EVENT, APPROVAL)


class AgentExecutionStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    ALL = (PENDING, RUNNING, COMPLETED, FAILED)
    TERMINAL = (COMPLETED, FAILED)


class FindingSeverity:
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

    ALL = (INFO, LOW, MEDIUM, HIGH)
    ORDER = {INFO: 0, LOW: 1, MEDIUM: 2, HIGH: 3}


class RecommendationStatus:
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DISMISSED = "DISMISSED"
    DONE = "DONE"

    ALL = (OPEN, ACCEPTED, DISMISSED, DONE)


class AgentMemoryType:
    SNAPSHOT = "SNAPSHOT"
    RECOMMENDATION = "RECOMMENDATION"
    NOTE = "NOTE"

    ALL = (SNAPSHOT, RECOMMENDATION, NOTE)


class DocumentStatus:
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    EXTRACTING = "EXTRACTING"
    INDEXING = "INDEXING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    ARCHIVED = "ARCHIVED"
    DELETED = "DELETED"

    ALL = (PENDING, PROCESSING, EXTRACTING, INDEXING, INDEXED, FAILED, ARCHIVED, DELETED)
    ACTIVE = (PENDING, PROCESSING, EXTRACTING, INDEXING)
    SEARCHABLE = (INDEXED,)


class KnowledgeCategory:
    BUSINESS_POLICY = "BUSINESS_POLICY"
    SUPPLIER_AGREEMENT = "SUPPLIER_AGREEMENT"
    CUSTOMER_AGREEMENT = "CUSTOMER_AGREEMENT"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    INVOICE = "INVOICE"
    PRODUCT_CATALOGUE = "PRODUCT_CATALOGUE"
    BUSINESS_MANUAL = "BUSINESS_MANUAL"
    EMPLOYEE_PROCEDURE = "EMPLOYEE_PROCEDURE"
    FINANCIAL_DOCUMENT = "FINANCIAL_DOCUMENT"
    SALES_DOCUMENT = "SALES_DOCUMENT"
    INVENTORY_DOCUMENT = "INVENTORY_DOCUMENT"
    MANAGEMENT_REPORT = "MANAGEMENT_REPORT"
    RESEARCH_REFERENCE = "RESEARCH_REFERENCE"
    OTHER = "OTHER"

    ALL = (BUSINESS_POLICY, SUPPLIER_AGREEMENT, CUSTOMER_AGREEMENT, PURCHASE_ORDER,
           INVOICE, PRODUCT_CATALOGUE, BUSINESS_MANUAL, EMPLOYEE_PROCEDURE,
           FINANCIAL_DOCUMENT, SALES_DOCUMENT, INVENTORY_DOCUMENT,
           MANAGEMENT_REPORT, RESEARCH_REFERENCE, OTHER)

    LABELS = {
        BUSINESS_POLICY: "Business policies",
        SUPPLIER_AGREEMENT: "Supplier agreements",
        CUSTOMER_AGREEMENT: "Customer agreements",
        PURCHASE_ORDER: "Purchase orders",
        INVOICE: "Invoices and receipts",
        PRODUCT_CATALOGUE: "Product catalogues",
        BUSINESS_MANUAL: "Business manuals",
        EMPLOYEE_PROCEDURE: "Employee procedures",
        FINANCIAL_DOCUMENT: "Financial documents",
        SALES_DOCUMENT: "Sales documents",
        INVENTORY_DOCUMENT: "Inventory documents",
        MANAGEMENT_REPORT: "Management reports",
        RESEARCH_REFERENCE: "Research and reference",
        OTHER: "Other documents",
    }


class AITaskKind:
    """What kind of work an AI request is, for task-based routing."""

    CLASSIFY = "CLASSIFY"
    NARRATE = "NARRATE"
    SUMMARISE = "SUMMARISE"
    DOCUMENT_ANSWER = "DOCUMENT_ANSWER"
    SENSITIVE_ANALYSIS = "SENSITIVE_ANALYSIS"
    EXTRACTION = "EXTRACTION"
    CLOUD_ONLY = "CLOUD_ONLY"

    ALL = (CLASSIFY, NARRATE, SUMMARISE, DOCUMENT_ANSWER, SENSITIVE_ANALYSIS,
           EXTRACTION, CLOUD_ONLY)
    LOCAL_ONLY = (CLASSIFY, NARRATE, SUMMARISE, DOCUMENT_ANSWER, SENSITIVE_ANALYSIS,
                  EXTRACTION)


class RoutingPolicy:
    LOCAL_FIRST = "LOCAL_FIRST"
    CLOUD_FIRST = "CLOUD_FIRST"
    TASK_BASED = "TASK_BASED"
    OFFLINE = "OFFLINE"

    ALL = (LOCAL_FIRST, CLOUD_FIRST, TASK_BASED, OFFLINE)


class WorkflowStatus:
    PENDING = "PENDING"
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"

    ALL = (PENDING, PLANNED, SCHEDULED, RUNNING, WAITING_APPROVAL, PAUSED,
           COMPLETED, FAILED, CANCELLED, ROLLED_BACK)
    TERMINAL = (COMPLETED, FAILED, CANCELLED, ROLLED_BACK)
    ACTIVE = (PENDING, PLANNED, SCHEDULED, RUNNING, WAITING_APPROVAL, PAUSED)


class WorkflowTaskType:
    DATA_RETRIEVAL = "DATA_RETRIEVAL"
    BUSINESS_ANALYSIS = "BUSINESS_ANALYSIS"
    AGENT_COLLABORATION = "AGENT_COLLABORATION"
    VALIDATION = "VALIDATION"
    RECOMMENDATION = "RECOMMENDATION"
    APPROVAL_REQUEST = "APPROVAL_REQUEST"
    BUSINESS_ACTION = "BUSINESS_ACTION"
    NOTIFICATION = "NOTIFICATION"
    REPORT_GENERATION = "REPORT_GENERATION"
    VERIFICATION = "VERIFICATION"

    ALL = (DATA_RETRIEVAL, BUSINESS_ANALYSIS, AGENT_COLLABORATION, VALIDATION,
           RECOMMENDATION, APPROVAL_REQUEST, BUSINESS_ACTION, NOTIFICATION,
           REPORT_GENERATION, VERIFICATION)


class WorkflowTaskStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, RUNNING, WAITING_APPROVAL, COMPLETED, FAILED, SKIPPED, CANCELLED)
    TERMINAL = (COMPLETED, FAILED, SKIPPED, CANCELLED)


class AutonomyMode:
    AUTOMATIC = "AUTOMATIC"
    APPROVAL = "APPROVAL"
    RESTRICTED = "RESTRICTED"

    ALL = (AUTOMATIC, APPROVAL, RESTRICTED)


class ApprovalStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, APPROVED, REJECTED, EXPIRED, CANCELLED)
    TERMINAL = (APPROVED, REJECTED, EXPIRED, CANCELLED)


class WorkflowTriggerType:
    EVENT = "EVENT"
    SCHEDULE = "SCHEDULE"
    THRESHOLD = "THRESHOLD"
    MANUAL = "MANUAL"

    ALL = (EVENT, SCHEDULE, THRESHOLD, MANUAL)


class WorkflowType:
    LOW_STOCK_REPLENISHMENT = "LOW_STOCK_REPLENISHMENT"
    CUSTOMER_FOLLOWUP = "CUSTOMER_FOLLOWUP"
    DAILY_SUMMARY = "DAILY_SUMMARY"
    UNUSUAL_EXPENSE_REVIEW = "UNUSUAL_EXPENSE_REVIEW"
    SALES_RECOVERY = "SALES_RECOVERY"
    PENDING_PAYMENT_FOLLOWUP = "PENDING_PAYMENT_FOLLOWUP"

    ALL = (LOW_STOCK_REPLENISHMENT, CUSTOMER_FOLLOWUP, DAILY_SUMMARY,
           UNUSUAL_EXPENSE_REVIEW, SALES_RECOVERY, PENDING_PAYMENT_FOLLOWUP)


class ScheduleFrequency:
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    INTERVAL_HOURS = "INTERVAL_HOURS"

    ALL = (DAILY, WEEKLY, INTERVAL_HOURS)


class CollaborationStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING = "WAITING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, RUNNING, WAITING, COMPLETED, PARTIAL, FAILED, CANCELLED)
    TERMINAL = (COMPLETED, PARTIAL, FAILED, CANCELLED)


class CollaborationTaskStatus:
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"

    ALL = (PENDING, RUNNING, COMPLETED, FAILED, SKIPPED, CANCELLED)
    TERMINAL = (COMPLETED, FAILED, SKIPPED, CANCELLED)


class CollaborationStrategy:
    SEQUENTIAL = "SEQUENTIAL"
    PARALLEL = "PARALLEL"
    SUPERVISOR_WORKER = "SUPERVISOR_WORKER"
    CONSENSUS = "CONSENSUS"

    ALL = (SEQUENTIAL, PARALLEL, SUPERVISOR_WORKER, CONSENSUS)


class CollaborationMessageType:
    TASK_REQUEST = "TASK_REQUEST"
    TASK_RESPONSE = "TASK_RESPONSE"
    CONTEXT_REQUEST = "CONTEXT_REQUEST"
    CONTEXT_RESPONSE = "CONTEXT_RESPONSE"
    FINDING = "FINDING"
    WARNING = "WARNING"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"
    CONFLICT_NOTIFICATION = "CONFLICT_NOTIFICATION"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"

    ALL = (
        TASK_REQUEST,
        TASK_RESPONSE,
        CONTEXT_REQUEST,
        CONTEXT_RESPONSE,
        FINDING,
        WARNING,
        CLARIFICATION_REQUEST,
        CONFLICT_NOTIFICATION,
        TASK_COMPLETED,
        TASK_FAILED,
    )


class ConflictType:
    FINANCIAL_CONFLICT = "FINANCIAL_CONFLICT"
    INVENTORY_CONFLICT = "INVENTORY_CONFLICT"
    SALES_CONFLICT = "SALES_CONFLICT"
    CUSTOMER_CONFLICT = "CUSTOMER_CONFLICT"
    REPORTING_PERIOD_CONFLICT = "REPORTING_PERIOD_CONFLICT"
    DATA_SOURCE_CONFLICT = "DATA_SOURCE_CONFLICT"
    ASSUMPTION_CONFLICT = "ASSUMPTION_CONFLICT"

    ALL = (
        FINANCIAL_CONFLICT,
        INVENTORY_CONFLICT,
        SALES_CONFLICT,
        CUSTOMER_CONFLICT,
        REPORTING_PERIOD_CONFLICT,
        DATA_SOURCE_CONFLICT,
        ASSUMPTION_CONFLICT,
    )


class ConflictStatus:
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    UNRESOLVED = "UNRESOLVED"

    ALL = (OPEN, RESOLVED, UNRESOLVED)


class EvidenceStatus:
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"

    ALL = (VERIFIED, PARTIAL, UNVERIFIED)


class EventStatus:
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    FAILED = "FAILED"

    ALL = (PENDING, DISPATCHED, FAILED)


DEFAULT_BRANCH_NAME = "Main Branch"
DEFAULT_UNIT = "pcs"
