"""Repository layer: the only place raw SQL / ORM queries are issued."""

from app.database.repositories.audit_repository import AuditRepository
from app.database.repositories.business_repository import BusinessRepository
from app.database.repositories.catalog_repository import CatalogRepository
from app.database.repositories.crm_repository import CrmRepository
from app.database.repositories.event_repository import EventRepository
from app.database.repositories.finance_repository import FinanceRepository
from app.database.repositories.inventory_repository import InventoryRepository
from app.database.repositories.permission_repository import PermissionRepository
from app.database.repositories.role_repository import RoleRepository
from app.database.repositories.sales_repository import SalesRepository
from app.database.repositories.session_repository import SessionRepository
from app.database.repositories.supply_repository import SupplyRepository
from app.database.repositories.user_repository import UserRepository

__all__ = [
    "AuditRepository",
    "BusinessRepository",
    "CatalogRepository",
    "CrmRepository",
    "EventRepository",
    "FinanceRepository",
    "InventoryRepository",
    "PermissionRepository",
    "RoleRepository",
    "SalesRepository",
    "SessionRepository",
    "SupplyRepository",
    "UserRepository",
]
