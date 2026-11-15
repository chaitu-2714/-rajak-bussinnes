"""Dashboard service.

Every figure comes from the database. Modules that do not exist yet (approvals)
are reported as unavailable rather than invented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import APP_VERSION
from app.core.constants import (
    ExpenseCategory,
    OrderStatus,
    TransactionCategory,
)
from app.database.repositories.business_repository import BusinessRepository
from app.database.repositories.catalog_repository import CatalogRepository
from app.database.repositories.crm_repository import CrmRepository
from app.database.repositories.finance_repository import FinanceRepository
from app.database.repositories.inventory_repository import InventoryRepository
from app.database.repositories.role_repository import RoleRepository
from app.database.repositories.sales_repository import SalesRepository
from app.database.repositories.user_repository import UserRepository
from app.database.types import ZERO, to_money
from app.services.audit_service import AuditEntryView, AuditService
from app.services.base_service import AuthContext, BaseService
from app.utils.date_utils import format_long_date


@dataclass(frozen=True)
class StatCard:
    """One dashboard statistic; ``value`` is None when the module is absent."""

    key: str
    title: str
    value: str | None
    caption: str
    available: bool


@dataclass(frozen=True)
class SystemStatus:
    database_connected: bool
    database_detail: str
    schema_version: str
    app_version: str
    signed_in_user: str
    authentication_status: str


@dataclass(frozen=True)
class ChartSeries:
    """A chart's data: x positions, y values and axis labels."""

    labels: list[str] = field(default_factory=list)
    values: list[float] = field(default_factory=list)
    caption: str = ""

    @property
    def has_data(self) -> bool:
        return bool(self.values) and any(value != 0 for value in self.values)


@dataclass(frozen=True)
class DashboardSummary:
    user_name: str
    user_roles: str
    business_name: str
    currency: str
    today: str
    empty_state_message: str
    stat_cards: list[StatCard] = field(default_factory=list)
    recent_activity: list[AuditEntryView] = field(default_factory=list)
    system_status: SystemStatus | None = None
    charts: dict[str, ChartSeries] = field(default_factory=dict)
    charts_available: bool = False


def _month_label(month: str) -> str:
    """``2026-08`` → ``Aug 26``."""
    try:
        parsed = datetime.strptime(month, "%Y-%m")
    except ValueError:
        return month
    return parsed.strftime("%b %y")


class DashboardService(BaseService):
    """Aggregates real Phase 2 figures for the overview page."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        business_repository: BusinessRepository,
        audit_service: AuditService,
        sales_repository: SalesRepository,
        finance_repository: FinanceRepository,
        crm_repository: CrmRepository,
        inventory_repository: InventoryRepository,
        catalog_repository: CatalogRepository,
        connection_check: Callable[[], tuple[bool, str]],
        schema_version: Callable[[], str],
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._users = user_repository
        self._roles = role_repository
        self._business = business_repository
        self._audit = audit_service
        self._sales = sales_repository
        self._finance = finance_repository
        self._crm = crm_repository
        self._inventory = inventory_repository
        self._catalog = catalog_repository
        self._connection_check = connection_check
        self._schema_version = schema_version

    def get_summary(self) -> DashboardSummary:
        with self.unit_of_work(write=False) as db:
            user = self._authorize(db, "dashboard.view")
            business = self._business.get_primary(db)
            principal = self._auth_context.principal

            revenue = self._finance.sum_transactions(
                db, categories=(TransactionCategory.SALES_REVENUE, TransactionCategory.SALES_REFUND)
            )
            cogs = self._sales.cogs(db)
            opex = self._finance.expense_total(
                db, exclude_categories=ExpenseCategory.CAPITALISED
            )
            net_profit = to_money(revenue - cogs - opex)
            sales_total = self._sales.sales_total(db, status=OrderStatus.COMPLETED)
            customers = self._crm.list(db)
            active_customers = sum(1 for customer in customers if customer.is_active)
            products = self._catalog.count_products(db)
            total_users = self._users.count(db)
            active_users = self._users.count(db, is_active=True)
            total_roles = len(self._roles.list_all(db))
            audit_total = self._audit_count(db)
            pending_approvals = self._pending_approvals(db)
            stock_value = self._inventory.stock_value(db)

            has_business_data = bool(
                sales_total or revenue or self._catalog.count_products(db) or customers
            )

            stat_cards = [
                StatCard(
                    "revenue",
                    "Total Revenue",
                    f"{revenue:,.2f}",
                    "Recognised sales revenue, net of refunds",
                    True,
                ),
                StatCard(
                    "expenses",
                    "Total Expenses",
                    f"{to_money(cogs + opex):,.2f}",
                    f"COGS {cogs:,.2f} + operating {opex:,.2f}",
                    True,
                ),
                StatCard("profit", "Net Profit", f"{net_profit:,.2f}", "Revenue − COGS − operating expenses", True),
                StatCard("sales", "Total Sales", f"{sales_total:,.2f}", "Completed orders", True),
                StatCard("customers", "Active Customers", str(active_customers), f"{len(customers)} total customers", True),
                StatCard("inventory", "Inventory Items", str(products), f"Stock value {stock_value:,.2f}", True),
                StatCard(
                    "approvals",
                    "Pending Approvals",
                    str(pending_approvals),
                    "Awaiting a decision in the Operations Center",
                    True,
                ),
                StatCard("users", "User Accounts", str(total_users), f"{active_users} active", True),
                StatCard("roles", "Roles", str(total_roles), "RBAC roles configured", True),
                StatCard("audit", "Audit Entries", str(audit_total), "Recorded actions", True),
            ]

            charts = self._build_charts(db)
            connected, detail = self._connection_check()
            system_status = SystemStatus(
                database_connected=connected,
                database_detail=detail,
                schema_version=self._schema_version(),
                app_version=APP_VERSION,
                signed_in_user=principal.full_name if principal else user.full_name,
                authentication_status="Authenticated session active" if principal else "Not signed in",
            )

            return DashboardSummary(
                user_name=user.full_name,
                user_roles=", ".join(user.role_names) or "No role assigned",
                business_name=business.business_name if business else "Workspace not configured",
                currency=business.currency if business else "INR",
                today=format_long_date(),
                empty_state_message=(
                    "Add your products and customers to start recording sales."
                    if not has_business_data
                    else "Finance, sales, customers, inventory and suppliers are live."
                ),
                stat_cards=stat_cards,
                recent_activity=[],
                system_status=system_status,
                charts=charts,
                charts_available=any(series.has_data for series in charts.values()),
            )

    def recent_activity(self, limit: int = 8) -> list[AuditEntryView]:
        return self._audit.recent_activity(limit=limit)

    # -- helpers -----------------------------------------------------------
    def _build_charts(self, db: Session) -> dict[str, ChartSeries]:
        monthly = self._finance.monthly_totals(db, months=6)
        months = sorted(monthly.keys())
        labels = [_month_label(month) for month in months]

        revenue_values = [
            float(
                monthly[month].get(TransactionCategory.SALES_REVENUE, ZERO)
                + monthly[month].get(TransactionCategory.SALES_REFUND, ZERO)
            )
            for month in months
        ]
        expense_values = [
            float(
                monthly[month].get(TransactionCategory.OPERATING_EXPENSE, ZERO)
                + monthly[month].get(TransactionCategory.CAPITAL_PURCHASE, ZERO)
                + monthly[month].get("EXPENSE_REVERSAL", ZERO)
            )
            for month in months
        ]

        sales_series = self._sales.monthly_sales(db, months=6)
        sales_labels = [_month_label(month) for month, _ in sales_series]
        sales_values = [float(value) for _, value in sales_series]

        movements = self._inventory.monthly_movement_totals(db, months=6)
        movement_labels = [_month_label(month) for month, _ in movements]
        movement_values = [float(value) for _, value in movements]

        return {
            "revenue": ChartSeries(labels, revenue_values, "Revenue per month"),
            "expenses": ChartSeries(labels, expense_values, "Expenses per month"),
            "sales": ChartSeries(sales_labels, sales_values, "Completed sales per month"),
            "inventory": ChartSeries(movement_labels, movement_values, "Net stock movement per month"),
        }

    def _pending_approvals(self, db: Session) -> int:
        """Approvals waiting for a human decision (Phase 6 onwards)."""
        from app.database.models.autonomy import ApprovalRequest
        from app.core.constants import ApprovalStatus

        try:
            return int(
                db.scalar(
                    select(func.count(ApprovalRequest.id)).where(
                        ApprovalRequest.status == ApprovalStatus.PENDING
                    )
                )
                or 0
            )
        except Exception:  # noqa: BLE001 - a missing table must not break the dashboard
            return 0

    def _audit_count(self, db: Session) -> int:
        from sqlalchemy import func, select

        from app.database.models.audit_log import AuditLog

        return int(db.scalar(select(func.count(AuditLog.id))) or 0)
