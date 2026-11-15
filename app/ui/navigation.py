"""Navigation model for the main window.

Each entry declares the permission required to see it. Modules that arrive in
later phases are marked ``coming_soon`` so the UI never pretends they work.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NavItem:
    key: str
    label: str
    icon: str
    permission: str
    section: str
    coming_soon: bool = False
    phase: str = ""
    description: str = ""


NAV_ITEMS: tuple[NavItem, ...] = (
    NavItem("overview", "Overview", "overview", "dashboard.view", "Workspace"),
    NavItem(
        "command_center",
        "AI Command Center",
        "command",
        "agents.view",
        "Workspace",
        coming_soon=False,
        phase="Phase 3",
        description="Ask BizPilot to run business operations in natural language.",
    ),
    NavItem(
        "finance",
        "Finance",
        "finance",
        "finance.view",
        "Business",
        phase="Phase 2",
        description="Income, expenses, transactions and financial reporting.",
    ),
    NavItem(
        "sales",
        "Sales",
        "sales",
        "sales.view",
        "Business",
        phase="Phase 3",
        description="Orders, invoices and sales performance tracking.",
    ),
    NavItem(
        "customers",
        "Customers",
        "customers",
        "customers.view",
        "Business",
        phase="Phase 4",
        description="Customer records, interactions and relationship history.",
    ),
    NavItem(
        "inventory",
        "Inventory",
        "inventory",
        "inventory.view",
        "Business",
        phase="Phase 5",
        description="Products, stock levels and movement tracking.",
    ),
    NavItem(
        "suppliers",
        "Suppliers",
        "suppliers",
        "suppliers.view",
        "Business",
        phase="Phase 5",
        description="Supplier directory, purchase records and payables.",
    ),
    NavItem(
        "collaboration",
        "Collaboration Center",
        "analytics",
        "agents.view",
        "Intelligence",
        coming_soon=False,
        phase="Phase 5",
        description="Coordinated multi-agent decisions with conflicts resolved on evidence.",
    ),
    NavItem(
        "agents",
        "AI Agents",
        "agents",
        "agents.view",
        "Intelligence",
        coming_soon=False,
        phase="Phase 4",
        description="Specialised finance, sales, customer, inventory and BI agents.",
    ),
    NavItem(
        "automation",
        "Operations Center",
        "automation",
        "automation.view",
        "Intelligence",
        coming_soon=False,
        phase="Phase 6",
        description="Autonomous workflows, approval gates and autonomy policies.",
    ),
        NavItem(
        "analytics",
        "Business Intelligence",
        "analytics",
        "analytics.view",
        "Intelligence",
        coming_soon=False,
        phase="Phase 7",
        description="Analytics, forecasts, anomalies, risks and what-if simulation.",
    ),
    NavItem(
        "knowledge",
        "Knowledge Center",
        "knowledge",
        "knowledge.view",
        "Intelligence",
        coming_soon=False,
        phase="Phase 8",
        description="Upload documents, search them and ask grounded questions.",
    ),
    NavItem(
        "reports",
        "Reports",
        "reports",
        "reports.view",
        "Intelligence",
        coming_soon=False,
        phase="Phase 10",
        description="Generate financial, sales and analytics reports.",
    ),
    NavItem(
        "security",
        "Security Center",
        "security",
        "security.view",
        "Administration",
        coming_soon=False,
        phase="Phase 9",
        description="Security overview, MFA, AI governance, audit chain and backups.",
    ),
    NavItem(
        "audit",
        "Audit Logs",
        "audit",
        "audit.view",
        "Administration",
        coming_soon=False,
        phase="Phase 10",
        description="Search the append-only audit trail.",
    ),
    NavItem("users", "User Management", "users", "users.view", "Administration"),
    NavItem("roles", "Roles and Permissions", "settings", "roles.view", "Administration"),
    NavItem("settings", "Settings", "settings", "settings.view", "Administration"),
)

NAV_BY_KEY = {item.key: item for item in NAV_ITEMS}
SECTION_ORDER = ("Workspace", "Business", "Intelligence", "Administration")
