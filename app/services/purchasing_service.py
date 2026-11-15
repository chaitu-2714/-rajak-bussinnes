"""Supplier and purchasing service: purchase orders and goods receipts.

Stock is only increased when goods are actually received — never when a
purchase order is created or approved.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    MODULE_PURCHASING,
    MODULE_SUPPLIERS,
    EventType,
    MovementType,
    PurchaseOrderStatus,
    AuditAction,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.purchasing import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.database.repositories.catalog_repository import CatalogRepository
from app.database.repositories.inventory_repository import InventoryRepository
from app.database.repositories.supply_repository import SupplyRepository
from app.database.types import ZERO, to_money
from app.schemas.purchasing_schema import (
    GoodsReceiptRequest,
    GoodsReceiptView,
    PurchaseOrderCreateRequest,
    PurchaseOrderSummary,
    SupplierCreateRequest,
    SupplierSummary,
    SupplierUpdateRequest,
)
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload
from app.services.event_service import EventService
from app.services.inventory_service import InventoryService
from app.services.numbering import next_document_number
from app.utils.date_utils import utcnow

logger = get_logger("services.purchasing")


class PurchasingService(BaseService):
    """Suppliers, purchase orders and goods receiving."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        supply_repository: SupplyRepository,
        catalog_repository: CatalogRepository,
        inventory_repository: InventoryRepository,
        inventory_service: InventoryService,
        audit_service: AuditService,
        event_service: EventService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._supply = supply_repository
        self._catalog = catalog_repository
        self._inventory = inventory_repository
        self._inventory_service = inventory_service
        self._audit = audit_service
        self._events = event_service

    # -- suppliers ---------------------------------------------------------
    def list_suppliers(self, *, search: str | None = None, is_active: bool | None = None) -> list[SupplierSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "suppliers.view")
            return [
                self._supplier_summary(db, supplier)
                for supplier in self._supply.list_suppliers(db, search=search, is_active=is_active)
            ]

    def get_supplier(self, supplier_id: int) -> SupplierSummary:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "suppliers.view")
            supplier = self._supply.get_supplier(db, supplier_id)
            if supplier is None:
                raise NotFoundError(f"Supplier {supplier_id} was not found")
            return self._supplier_summary(db, supplier)

    def create_supplier(self, payload: dict | SupplierCreateRequest) -> SupplierSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "suppliers.create")
            data = validate_payload(SupplierCreateRequest, payload)
            if self._supply.find_supplier_by_name(db, data.supplier_name):
                raise ValidationError(
                    "A supplier with this name already exists.",
                    fields={"supplier_name": "Already registered"},
                )

            code = (data.supplier_code or "").strip().upper() or next_document_number(
                db, Supplier, "supplier_code", "SUP", with_year=False, width=4
            )
            if self._supply.get_supplier_by_code(db, code):
                raise ConflictError(f"Supplier code '{code}' is already in use")

            supplier = Supplier(
                supplier_code=code,
                supplier_name=data.supplier_name,
                contact_person=data.contact_person,
                email=data.email,
                phone=data.phone,
                address=data.address,
                tax_identifier=data.tax_identifier,
                is_active=data.is_active,
            )
            self._supply.add_supplier(db, supplier)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_SUPPLIER,
                module=MODULE_SUPPLIERS,
                entity_type="Supplier",
                entity_id=supplier.id,
                new_values={
                    "supplier_code": supplier.supplier_code,
                    "supplier_name": supplier.supplier_name,
                    "email": supplier.email,
                },
            )
            return self._supplier_summary(db, supplier)

    def update_supplier(self, supplier_id: int, payload: dict | SupplierUpdateRequest) -> SupplierSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "suppliers.update")
            data = validate_payload(SupplierUpdateRequest, payload)
            supplier = self._supply.get_supplier(db, supplier_id)
            if supplier is None:
                raise NotFoundError(f"Supplier {supplier_id} was not found")

            duplicate = self._supply.find_supplier_by_name(db, data.supplier_name)
            if duplicate is not None and duplicate.id != supplier.id:
                raise ValidationError(
                    "A supplier with this name already exists.",
                    fields={"supplier_name": "Already registered"},
                )

            old_values = {
                "supplier_name": supplier.supplier_name,
                "contact_person": supplier.contact_person,
                "email": supplier.email,
                "phone": supplier.phone,
                "tax_identifier": supplier.tax_identifier,
                "is_active": supplier.is_active,
            }
            supplier.supplier_name = data.supplier_name
            supplier.contact_person = data.contact_person
            supplier.email = data.email
            supplier.phone = data.phone
            supplier.address = data.address
            supplier.tax_identifier = data.tax_identifier
            supplier.is_active = data.is_active
            supplier.updated_at = utcnow()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_SUPPLIER,
                module=MODULE_SUPPLIERS,
                entity_type="Supplier",
                entity_id=supplier.id,
                old_values=old_values,
                new_values={
                    "supplier_name": supplier.supplier_name,
                    "contact_person": supplier.contact_person,
                    "email": supplier.email,
                    "phone": supplier.phone,
                    "tax_identifier": supplier.tax_identifier,
                    "is_active": supplier.is_active,
                },
            )
            return self._supplier_summary(db, supplier)

    def set_supplier_active(self, supplier_id: int, is_active: bool) -> SupplierSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "suppliers.deactivate")
            supplier = self._supply.get_supplier(db, supplier_id)
            if supplier is None:
                raise NotFoundError(f"Supplier {supplier_id} was not found")
            previous = supplier.is_active
            supplier.is_active = is_active
            supplier.updated_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.DEACTIVATE_SUPPLIER,
                module=MODULE_SUPPLIERS,
                entity_type="Supplier",
                entity_id=supplier.id,
                old_values={"is_active": previous},
                new_values={"is_active": is_active},
            )
            return self._supplier_summary(db, supplier)

    # -- purchase orders ---------------------------------------------------
    def list_purchase_orders(
        self,
        *,
        supplier_id: int | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> list[PurchaseOrderSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "purchase_orders.view")
            orders = self._supply.list_purchase_orders(
                db, supplier_id=supplier_id, status=status, search=search
            )
            return [PurchaseOrderSummary.from_order(order) for order in orders]

    def get_purchase_order(self, order_id: int) -> PurchaseOrderSummary:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "purchase_orders.view")
            return PurchaseOrderSummary.from_order(self._load_po(db, order_id))

    def create_purchase_order(self, payload: dict | PurchaseOrderCreateRequest) -> PurchaseOrderSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "purchase_orders.create")
            data = validate_payload(PurchaseOrderCreateRequest, payload)

            supplier = self._supply.get_supplier(db, data.supplier_id)
            if supplier is None:
                raise ValidationError(
                    "Select an existing supplier.", fields={"supplier_id": "Unknown supplier"}
                )
            if not supplier.is_active:
                raise ValidationError(
                    "This supplier is inactive.", fields={"supplier_id": "Inactive supplier"}
                )

            subtotal = ZERO
            prepared: list[tuple] = []
            for item in data.items:
                product = self._catalog.get_product(db, item.product_id)
                if product is None:
                    raise ValidationError(
                        f"Product {item.product_id} does not exist.", fields={"items": "Unknown product"}
                    )
                unit_cost = to_money(item.unit_cost)
                line_total = to_money(unit_cost * item.ordered_quantity)
                prepared.append((product, item.ordered_quantity, unit_cost, line_total))
                subtotal += line_total

            tax = to_money(data.tax_amount)
            order = PurchaseOrder(
                purchase_order_number=next_document_number(
                    db, PurchaseOrder, "purchase_order_number", "PO"
                ),
                supplier_id=supplier.id,
                subtotal=to_money(subtotal),
                tax_amount=tax,
                total_amount=to_money(subtotal + tax),
                status=PurchaseOrderStatus.DRAFT,
                expected_delivery_date=data.expected_delivery_date,
                notes=data.notes,
                created_by=actor.id,
            )
            self._supply.add_purchase_order(db, order)
            for product, quantity, unit_cost, line_total in prepared:
                order.items.append(
                    PurchaseOrderItem(
                        purchase_order_id=order.id,
                        product_id=product.id,
                        ordered_quantity=quantity,
                        received_quantity=0,
                        unit_cost=unit_cost,
                        line_total=line_total,
                    )
                )
            db.flush()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_PURCHASE_ORDER,
                module=MODULE_PURCHASING,
                entity_type="PurchaseOrder",
                entity_id=order.id,
                new_values={
                    "purchase_order_number": order.purchase_order_number,
                    "supplier": supplier.supplier_name,
                    "total_amount": str(order.total_amount),
                    "items": len(prepared),
                },
            )
            self._events.publish(
                db,
                EventType.PURCHASE_ORDER_CREATED,
                aggregate_type="PurchaseOrder",
                aggregate_id=order.id,
                payload={
                    "purchase_order_id": order.id,
                    "purchase_order_number": order.purchase_order_number,
                    "supplier_id": supplier.id,
                    "total_amount": str(order.total_amount),
                },
            )
            summary = PurchaseOrderSummary.from_order(self._load_po(db, order.id))
        self._events.dispatch_pending()
        return summary

    def approve_purchase_order(self, order_id: int) -> PurchaseOrderSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "purchase_orders.approve")
            order = self._load_po(db, order_id)
            if order.status != PurchaseOrderStatus.DRAFT:
                raise ConflictError(
                    f"Only draft purchase orders can be approved (current: {order.status})"
                )
            order.status = PurchaseOrderStatus.APPROVED
            order.updated_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.APPROVE_PURCHASE_ORDER,
                module=MODULE_PURCHASING,
                entity_type="PurchaseOrder",
                entity_id=order.id,
                old_values={"status": PurchaseOrderStatus.DRAFT},
                new_values={"status": PurchaseOrderStatus.APPROVED},
            )
            return PurchaseOrderSummary.from_order(order)

    def mark_ordered(self, order_id: int) -> PurchaseOrderSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "purchase_orders.approve")
            order = self._load_po(db, order_id)
            if order.status != PurchaseOrderStatus.APPROVED:
                raise ConflictError("Only approved purchase orders can be marked as ordered")
            order.status = PurchaseOrderStatus.ORDERED
            order.updated_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.APPROVE_PURCHASE_ORDER,
                module=MODULE_PURCHASING,
                entity_type="PurchaseOrder",
                entity_id=order.id,
                old_values={"status": PurchaseOrderStatus.APPROVED},
                new_values={"status": PurchaseOrderStatus.ORDERED},
            )
            return PurchaseOrderSummary.from_order(order)

    def cancel_purchase_order(self, order_id: int, reason: str) -> PurchaseOrderSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "purchase_orders.approve")
            order = self._load_po(db, order_id)
            if order.status == PurchaseOrderStatus.RECEIVED:
                raise ConflictError("A fully received purchase order cannot be cancelled")
            if order.receipts:
                raise ConflictError(
                    "Goods have already been received against this order; reverse the receipt instead"
                )
            if not reason or len(reason.strip()) < 3:
                raise ValidationError("Provide a reason.", fields={"reason": "Required"})

            previous = order.status
            order.status = PurchaseOrderStatus.CANCELLED
            order.updated_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.APPROVE_PURCHASE_ORDER,
                module=MODULE_PURCHASING,
                entity_type="PurchaseOrder",
                entity_id=order.id,
                old_values={"status": previous},
                new_values={"status": PurchaseOrderStatus.CANCELLED, "reason": reason.strip()},
            )
            return PurchaseOrderSummary.from_order(order)

    # -- goods receipt -----------------------------------------------------
    def receive_goods(self, payload: dict | GoodsReceiptRequest) -> GoodsReceiptView:
        """Record a (possibly partial) delivery and increase stock."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "purchase_orders.receive")
            data = validate_payload(GoodsReceiptRequest, payload)

            order = self._load_po(db, data.purchase_order_id)
            if order.status not in PurchaseOrderStatus.RECEIVABLE:
                raise ConflictError(
                    "Goods can only be received against an approved, ordered or partially "
                    f"received purchase order (current: {order.status})"
                )

            items_by_id = {item.id: item for item in order.items}
            validated: list[tuple[PurchaseOrderItem, int]] = []
            for entry in data.items:
                item = items_by_id.get(entry.purchase_order_item_id)
                if item is None:
                    raise ValidationError(
                        f"Purchase order line {entry.purchase_order_item_id} does not belong to this order."
                    )
                if entry.quantity > item.outstanding_quantity:
                    raise ValidationError(
                        f"Cannot receive {entry.quantity} of {item.product.product_name if item.product else 'item'}: "
                        f"only {item.outstanding_quantity} outstanding.",
                        fields={"items": "Over-receipt"},
                    )
                validated.append((item, entry.quantity))

            receipt = GoodsReceipt(
                receipt_number=next_document_number(db, GoodsReceipt, "receipt_number", "GRN"),
                purchase_order_id=order.id,
                notes=data.notes,
                received_by=actor.id,
                received_at=utcnow(),
            )
            self._supply.add_receipt(db, receipt)
            order.receipts.append(receipt)

            branch = self._inventory.default_branch(db)
            if branch is None:
                raise ConflictError("No business location is configured for stock")

            for item, quantity in validated:
                product = item.product
                self._inventory_service.apply_change(
                    db,
                    product=product,
                    delta=quantity,
                    movement_type=MovementType.PURCHASE,
                    reference_type="GOODS_RECEIPT",
                    reference_id=receipt.receipt_number,
                    notes=f"Received against {order.purchase_order_number}",
                    actor_id=actor.id,
                    branch=branch,
                )
                item.received_quantity = int(item.received_quantity) + quantity
                receipt.items.append(
                    GoodsReceiptItem(
                        goods_receipt_id=receipt.id,
                        purchase_order_item_id=item.id,
                        product_id=item.product_id,
                        quantity=quantity,
                    )
                )

            fully_received = all(
                item.received_quantity >= item.ordered_quantity for item in order.items
            )
            order.status = (
                PurchaseOrderStatus.RECEIVED
                if fully_received
                else PurchaseOrderStatus.PARTIALLY_RECEIVED
            )
            order.updated_at = utcnow()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.RECEIVE_GOODS,
                module=MODULE_PURCHASING,
                entity_type="GoodsReceipt",
                entity_id=receipt.id,
                new_values={
                    "receipt_number": receipt.receipt_number,
                    "purchase_order": order.purchase_order_number,
                    "total_quantity": receipt.total_quantity,
                    "order_status": order.status,
                },
            )
            self._events.publish(
                db,
                EventType.GOODS_RECEIVED,
                aggregate_type="GoodsReceipt",
                aggregate_id=receipt.id,
                payload={
                    "receipt_id": receipt.id,
                    "receipt_number": receipt.receipt_number,
                    "purchase_order_id": order.id,
                    "total_quantity": receipt.total_quantity,
                    "order_status": order.status,
                },
            )
            view = GoodsReceiptView.from_receipt(receipt)
        self._events.dispatch_pending()
        return view

    def list_receipts(self, *, order_id: int | None = None) -> list[GoodsReceiptView]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "purchase_orders.view")
            return [
                GoodsReceiptView.from_receipt(receipt)
                for receipt in self._supply.list_receipts(db, order_id=order_id)
            ]

    # -- helpers -----------------------------------------------------------
    def _load_po(self, db: Session, order_id: int) -> PurchaseOrder:
        order = self._supply.get_purchase_order(db, order_id)
        if order is None:
            raise NotFoundError(f"Purchase order {order_id} was not found")
        return order

    def _supplier_summary(self, db: Session, supplier: Supplier) -> SupplierSummary:
        stats = self._supply.supplier_stats(db, supplier.id)
        return SupplierSummary(
            id=supplier.id,
            supplier_code=supplier.supplier_code,
            supplier_name=supplier.supplier_name,
            contact_person=supplier.contact_person,
            email=supplier.email,
            phone=supplier.phone,
            address=supplier.address,
            tax_identifier=supplier.tax_identifier,
            is_active=supplier.is_active,
            created_at=supplier.created_at,
            order_count=stats.order_count,
            total_order_value=stats.total_value,
            received_value=stats.received_value,
            last_order_at=stats.last_order_at,
        )
