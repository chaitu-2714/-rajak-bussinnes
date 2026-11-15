"""Inventory and catalogue service.

Stock is only ever changed through :meth:`InventoryService.apply_change`, which
writes a movement row for every change, refuses to go negative and raises a
low-stock event when a product crosses its threshold.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    MODULE_INVENTORY,
    STATUS_FAILURE,
    EventType,
    MovementType,
    AuditAction,
)
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging_config import get_logger
from app.database.models.catalog import Category, Product
from app.database.models.inventory import Branch, Inventory, StockMovement
from app.database.repositories.catalog_repository import CatalogRepository
from app.database.repositories.inventory_repository import InventoryRepository
from app.database.types import ZERO, to_money
from app.schemas.catalog_schema import (
    CategoryCreateRequest,
    CategorySummary,
    CategoryUpdateRequest,
    ProductCreateRequest,
    ProductSummary,
    ProductUpdateRequest,
)
from app.schemas.inventory_schema import (
    InventoryDashboard,
    LowStockAlert,
    StockAdjustmentRequest,
    StockMovementView,
    StockRow,
)
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload
from app.services.event_service import EventService
from app.services.export_service import ExportService
from app.services.numbering import next_document_number
from app.utils.date_utils import utcnow

logger = get_logger("services.inventory")

#: Manual adjustments never use these; they are produced by business flows.
SYSTEM_MOVEMENT_TYPES = (MovementType.SALE, MovementType.PURCHASE, MovementType.RETURN)


class InventoryService(BaseService):
    """Products, categories, stock levels and stock movements."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        catalog_repository: CatalogRepository,
        inventory_repository: InventoryRepository,
        audit_service: AuditService,
        event_service: EventService,
        export_service: ExportService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._catalog = catalog_repository
        self._inventory = inventory_repository
        self._audit = audit_service
        self._events = event_service
        self._export = export_service

    # -- categories --------------------------------------------------------
    def list_categories(self, *, search: str | None = None) -> list[CategorySummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            return [
                CategorySummary.from_category(category)
                for category in self._catalog.list_categories(db, search=search)
            ]

    def create_category(self, payload: dict | CategoryCreateRequest) -> CategorySummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "inventory.create")
            data = validate_payload(CategoryCreateRequest, payload)
            if self._catalog.get_category_by_name(db, data.category_name):
                raise ConflictError(f"A category named '{data.category_name}' already exists")

            category = Category(
                category_name=data.category_name,
                description=data.description,
                is_active=data.is_active,
            )
            self._catalog.add_category(db, category)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_CATEGORY,
                module=MODULE_INVENTORY,
                entity_type="Category",
                entity_id=category.id,
                new_values={"category_name": category.category_name},
            )
            return CategorySummary.from_category(category)

    def update_category(
        self, category_id: int, payload: dict | CategoryUpdateRequest
    ) -> CategorySummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "inventory.update")
            data = validate_payload(CategoryUpdateRequest, payload)
            category = self._catalog.get_category(db, category_id)
            if category is None:
                raise NotFoundError(f"Category {category_id} was not found")

            duplicate = self._catalog.get_category_by_name(db, data.category_name)
            if duplicate is not None and duplicate.id != category.id:
                raise ConflictError(f"A category named '{data.category_name}' already exists")

            old_values = {
                "category_name": category.category_name,
                "description": category.description,
                "is_active": category.is_active,
            }
            category.category_name = data.category_name
            category.description = data.description
            category.is_active = data.is_active
            category.updated_at = utcnow()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_CATEGORY,
                module=MODULE_INVENTORY,
                entity_type="Category",
                entity_id=category.id,
                old_values=old_values,
                new_values={
                    "category_name": category.category_name,
                    "description": category.description,
                    "is_active": category.is_active,
                },
            )
            return CategorySummary.from_category(category)

    # -- products ----------------------------------------------------------
    def list_products(
        self,
        *,
        search: str | None = None,
        category_id: int | None = None,
        active_only: bool = False,
    ) -> list[ProductSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            return [
                ProductSummary.from_product(product)
                for product in self._catalog.list_products(
                    db, search=search, category_id=category_id, active_only=active_only
                )
            ]

    def get_product(self, product_id: int) -> ProductSummary:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            product = self._catalog.get_product(db, product_id)
            if product is None:
                raise NotFoundError(f"Product {product_id} was not found")
            return ProductSummary.from_product(product)

    def generate_sku(self) -> str:
        """Suggest the next free SKU (``SKU-0007``)."""
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.create")
            return next_document_number(
                db, Product, "sku", "SKU", with_year=False, width=4
            )

    def create_product(self, payload: dict | ProductCreateRequest) -> ProductSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "inventory.create")
            data = validate_payload(ProductCreateRequest, payload)
            sku = (data.sku or "").strip().upper() or next_document_number(
                db, Product, "sku", "SKU", with_year=False, width=4
            )
            if self._catalog.get_product_by_sku(db, sku):
                raise ConflictError(f"SKU '{sku}' is already in use")
            self._validate_pricing(db, data)

            product = Product(
                sku=sku,
                product_name=data.product_name,
                category_id=data.category_id,
                description=data.description,
                unit=data.unit,
                cost_price=to_money(data.cost_price),
                selling_price=to_money(data.selling_price),
                minimum_stock=data.minimum_stock,
                barcode=data.barcode,
                is_active=data.is_active,
            )
            self._catalog.add_product(db, product)

            # Every product gets a stock record so the inventory view is complete.
            branch = self._default_branch(db)
            self._inventory.get_or_create_stock(db, product.id, branch.id)

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_PRODUCT,
                module=MODULE_INVENTORY,
                entity_type="Product",
                entity_id=product.id,
                new_values={
                    "sku": product.sku,
                    "product_name": product.product_name,
                    "cost_price": str(product.cost_price),
                    "selling_price": str(product.selling_price),
                    "minimum_stock": product.minimum_stock,
                },
            )
            return ProductSummary.from_product(product)

    def update_product(self, product_id: int, payload: dict | ProductUpdateRequest) -> ProductSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "inventory.update")
            data = validate_payload(ProductUpdateRequest, payload)
            product = self._catalog.get_product(db, product_id)
            if product is None:
                raise NotFoundError(f"Product {product_id} was not found")

            sku = data.sku.strip().upper()
            duplicate = self._catalog.get_product_by_sku(db, sku)
            if duplicate is not None and duplicate.id != product.id:
                raise ConflictError(f"SKU '{sku}' is already in use")
            self._validate_pricing(db, data)

            old_values = {
                "sku": product.sku,
                "product_name": product.product_name,
                "category_id": product.category_id,
                "unit": product.unit,
                "cost_price": str(product.cost_price),
                "selling_price": str(product.selling_price),
                "minimum_stock": product.minimum_stock,
                "is_active": product.is_active,
            }

            product.sku = sku
            product.product_name = data.product_name
            product.category_id = data.category_id
            product.description = data.description
            product.unit = data.unit
            product.cost_price = to_money(data.cost_price)
            product.selling_price = to_money(data.selling_price)
            product.minimum_stock = data.minimum_stock
            product.barcode = data.barcode
            product.is_active = data.is_active
            product.updated_at = utcnow()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_PRODUCT,
                module=MODULE_INVENTORY,
                entity_type="Product",
                entity_id=product.id,
                old_values=old_values,
                new_values={
                    "sku": product.sku,
                    "product_name": product.product_name,
                    "category_id": product.category_id,
                    "unit": product.unit,
                    "cost_price": str(product.cost_price),
                    "selling_price": str(product.selling_price),
                    "minimum_stock": product.minimum_stock,
                    "is_active": product.is_active,
                },
            )
            return ProductSummary.from_product(product)

    def set_product_active(self, product_id: int, is_active: bool) -> ProductSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "inventory.update")
            product = self._catalog.get_product(db, product_id)
            if product is None:
                raise NotFoundError(f"Product {product_id} was not found")
            previous = product.is_active
            product.is_active = is_active
            product.updated_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_PRODUCT,
                module=MODULE_INVENTORY,
                entity_type="Product",
                entity_id=product.id,
                old_values={"is_active": previous},
                new_values={"is_active": is_active},
            )
            return ProductSummary.from_product(product)

    # -- stock -------------------------------------------------------------
    def stock_for_product(self, product_id: int) -> int:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            branch = self._default_branch(db)
            stock = self._inventory.get_stock(db, product_id, branch.id)
            return int(stock.available_quantity) if stock else 0

    def list_stock(
        self,
        *,
        search: str | None = None,
        category_id: int | None = None,
        low_stock_only: bool = False,
        out_of_stock_only: bool = False,
    ) -> list[StockRow]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            records = self._inventory.list_stock(
                db,
                search=search,
                category_id=category_id,
                low_stock_only=low_stock_only,
                out_of_stock_only=out_of_stock_only,
            )
            return [StockRow.from_record(record) for record in records]

    def adjust_stock(self, payload: dict | StockAdjustmentRequest) -> StockMovementView:
        """Manual stock change: opening stock, addition, reduction or damage."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "inventory.adjust")
            data = validate_payload(StockAdjustmentRequest, payload)
            product = self._catalog.get_product(db, data.product_id)
            if product is None:
                raise NotFoundError(f"Product {data.product_id} was not found")

            # Damage always removes stock; every other manual movement defaults
            # to an addition unless the caller explicitly asks for a reduction.
            direction = data.direction
            if direction is None:
                direction = -1 if data.movement_type == MovementType.DAMAGE else 1
            if data.movement_type == MovementType.DAMAGE and direction > 0:
                raise ValidationError(
                    "Damaged stock reduces inventory.", fields={"direction": "Must reduce stock"}
                )

            delta = data.quantity * (1 if direction >= 0 else -1)
            movement = self.apply_change(
                db,
                product=product,
                delta=delta,
                movement_type=data.movement_type,
                reference_type="MANUAL",
                reference_id=None,
                notes=data.reason,
                actor_id=actor.id,
            )
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.STOCK_ADJUSTMENT,
                module=MODULE_INVENTORY,
                entity_type="Product",
                entity_id=product.id,
                old_values={"available_quantity": movement.previous_quantity},
                new_values={
                    "available_quantity": movement.new_quantity,
                    "movement_type": movement.movement_type,
                    "quantity": movement.quantity,
                    "reason": data.reason,
                },
            )
            return StockMovementView.from_movement(movement)

    def apply_change(
        self,
        db: Session,
        *,
        product: Product,
        delta: int,
        movement_type: str,
        reference_type: str | None = None,
        reference_id: str | None = None,
        notes: str | None = None,
        actor_id: int | None = None,
        branch: Branch | None = None,
    ) -> StockMovement:
        """Apply a stock change inside an existing transaction.

        Used by sales, purchasing and manual adjustments. Refuses to go negative
        and always writes the movement ledger entry.
        """
        if delta == 0:
            raise ValidationError("A stock change of zero is not allowed.")
        branch = branch or self._default_branch(db)
        stock = self._inventory.get_or_create_stock(db, product.id, branch.id)
        previous = int(stock.available_quantity)
        new_quantity = previous + delta
        if new_quantity < 0:
            raise ConflictError(
                f"Insufficient stock for {product.product_name} ({product.sku}): "
                f"available {previous}, requested {abs(delta)}"
            )

        stock.available_quantity = new_quantity
        stock.updated_at = utcnow()

        movement = StockMovement(
            product_id=product.id,
            branch_id=branch.id,
            movement_type=movement_type,
            quantity=abs(delta),
            previous_quantity=previous,
            new_quantity=new_quantity,
            reference_type=reference_type,
            reference_id=str(reference_id) if reference_id is not None else None,
            notes=notes,
            created_by=actor_id,
            created_at=utcnow(),
        )
        self._inventory.add_movement(db, movement)

        # Raise the low-stock event only when the threshold is actually crossed.
        minimum = int(product.minimum_stock or 0)
        if new_quantity <= minimum < previous:
            self._events.publish(
                db,
                EventType.STOCK_BELOW_MINIMUM,
                aggregate_type="Product",
                aggregate_id=product.id,
                payload={
                    "product_id": product.id,
                    "sku": product.sku,
                    "product_name": product.product_name,
                    "available_quantity": new_quantity,
                    "minimum_stock": minimum,
                    "suggested_reorder_quantity": max(minimum * 2 - new_quantity, 1),
                },
            )
        return movement

    def opening_stock(self, product_id: int, quantity: int, notes: str | None = None) -> StockMovementView:
        """Record the first stock of a product."""
        return self.adjust_stock(
            {
                "product_id": product_id,
                "quantity": quantity,
                "movement_type": MovementType.OPENING_STOCK,
                "reason": notes or "Opening stock",
                "direction": 1,
            }
        )

    def movements(
        self,
        *,
        product_id: int | None = None,
        movement_type: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 300,
    ) -> list[StockMovementView]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            records = self._inventory.list_movements(
                db,
                product_id=product_id,
                movement_type=movement_type,
                date_from=date_from,
                date_to=date_to,
                limit=limit,
            )
            return [StockMovementView.from_movement(record) for record in records]

    def low_stock_alerts(self) -> list[LowStockAlert]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            alerts: list[LowStockAlert] = []
            for record in self._inventory.list_stock(db, low_stock_only=True):
                product = record.product
                available = int(record.available_quantity)
                minimum = int(product.minimum_stock or 0)
                alerts.append(
                    LowStockAlert(
                        product_id=product.id,
                        product_name=product.product_name,
                        sku=product.sku,
                        available_quantity=available,
                        minimum_stock=minimum,
                        suggested_reorder_quantity=max(minimum * 2 - available, 1),
                    )
                )
            return alerts

    def stock_valuation(self) -> Decimal:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            return self._inventory.stock_value(db)

    def dashboard(self) -> InventoryDashboard:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "inventory.view")
            records = self._inventory.list_stock(db, active_products_only=False)
            low = sum(1 for record in records if int(record.available_quantity) <= int(record.product.minimum_stock or 0))
            out = sum(1 for record in records if int(record.available_quantity) == 0)
            return InventoryDashboard(
                total_products=self._catalog.count_products(db),
                active_products=self._catalog.count_products(db, active_only=True),
                total_stock_quantity=self._inventory.total_quantity(db),
                low_stock_count=low,
                out_of_stock_count=out,
                stock_value=self._inventory.stock_value(db),
                recent_movement_count=len(self._inventory.list_movements(db, limit=50)),
            )

    # -- exports -----------------------------------------------------------
    def export_rows(self) -> tuple[list[str], list[list[str]]]:
        """Header and rows for the inventory CSV export."""
        headers = [
            "SKU",
            "Product",
            "Category",
            "Unit",
            "Available",
            "Reserved",
            "Minimum stock",
            "Cost price",
            "Selling price",
            "Stock value",
        ]
        rows = [
            [
                row.sku,
                row.product_name,
                row.category_name,
                row.unit,
                str(row.available_quantity),
                str(row.reserved_quantity),
                str(row.minimum_stock),
                f"{row.cost_price:.2f}",
                f"{row.selling_price:.2f}",
                f"{row.stock_value:.2f}",
            ]
            for row in self.list_stock()
        ]
        return headers, rows

    def export_stock_csv(self) -> str:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "inventory.export")
            headers, rows = self.export_rows()
            stamp = utcnow().strftime("%Y%m%d_%H%M%S")
            path = self._export.write_csv(f"inventory_{stamp}.csv", headers, rows)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.EXPORT_REPORT,
                module=MODULE_INVENTORY,
                entity_type="Report",
                entity_id="inventory",
                new_values={"format": "csv", "path": str(path)},
            )
        return str(path)

    # -- helpers -----------------------------------------------------------
    def _default_branch(self, db: Session) -> Branch:
        branch = self._inventory.default_branch(db)
        if branch is None:
            branch = self._inventory.add_branch(db, Branch(branch_name="Main Branch", is_default=True))
        return branch

    def _validate_pricing(self, db: Session, data) -> None:
        if data.category_id is not None and self._catalog.get_category(db, data.category_id) is None:
            raise ValidationError(
                "Select an existing category.", fields={"category_id": "Unknown category"}
            )
        if to_money(data.cost_price) > to_money(data.selling_price):
            # Not an error: loss-leader pricing is legitimate, but it is worth logging.
            logger.info("Product priced below cost: %s", data.product_name)
