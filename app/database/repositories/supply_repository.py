"""Data access for suppliers, purchase orders and goods receipts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.models.purchasing import (
    GoodsReceipt,
    GoodsReceiptItem,
    PurchaseOrder,
    PurchaseOrderItem,
    Supplier,
)
from app.database.types import ZERO, to_money


@dataclass(frozen=True)
class SupplierPurchaseStats:
    order_count: int = 0
    total_value: Decimal = ZERO
    received_value: Decimal = ZERO
    last_order_at: datetime | None = None


class SupplyRepository:
    """Supplier and purchasing queries."""

    # -- suppliers ---------------------------------------------------------
    def get_supplier(self, db: Session, supplier_id: int) -> Supplier | None:
        return db.get(Supplier, supplier_id)

    def get_supplier_by_code(self, db: Session, code: str) -> Supplier | None:
        return db.scalars(
            select(Supplier).where(func.lower(Supplier.supplier_code) == code.strip().lower())
        ).first()

    def find_supplier_by_name(self, db: Session, name: str) -> Supplier | None:
        return db.scalars(
            select(Supplier).where(func.lower(Supplier.supplier_name) == name.strip().lower())
        ).first()

    def list_suppliers(
        self, db: Session, *, search: str | None = None, is_active: bool | None = None
    ) -> list[Supplier]:
        stmt = select(Supplier)
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Supplier.supplier_name).like(pattern),
                    func.lower(Supplier.supplier_code).like(pattern),
                    func.lower(func.coalesce(Supplier.contact_person, "")).like(pattern),
                    func.lower(func.coalesce(Supplier.email, "")).like(pattern),
                )
            )
        if is_active is not None:
            stmt = stmt.where(Supplier.is_active.is_(is_active))
        return list(db.scalars(stmt.order_by(Supplier.supplier_name)).all())

    def add_supplier(self, db: Session, supplier: Supplier) -> Supplier:
        db.add(supplier)
        db.flush()
        return supplier

    def count_suppliers(self, db: Session, *, is_active: bool | None = None) -> int:
        stmt = select(func.count(Supplier.id))
        if is_active is not None:
            stmt = stmt.where(Supplier.is_active.is_(is_active))
        return int(db.scalar(stmt) or 0)

    # -- purchase orders ---------------------------------------------------
    def _po_options(self):
        return (
            selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.product),
            selectinload(PurchaseOrder.supplier),
            selectinload(PurchaseOrder.receipts),
        )

    def get_purchase_order(self, db: Session, order_id: int) -> PurchaseOrder | None:
        return db.scalars(
            select(PurchaseOrder)
            .options(*self._po_options())
            .where(PurchaseOrder.id == order_id)
        ).first()

    def list_purchase_orders(
        self,
        db: Session,
        *,
        supplier_id: int | None = None,
        status: str | None = None,
        search: str | None = None,
        limit: int = 300,
    ) -> list[PurchaseOrder]:
        stmt = select(PurchaseOrder).options(*self._po_options())
        if supplier_id is not None:
            stmt = stmt.where(PurchaseOrder.supplier_id == supplier_id)
        if status:
            stmt = stmt.where(PurchaseOrder.status == status)
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.outerjoin(Supplier, Supplier.id == PurchaseOrder.supplier_id).where(
                or_(
                    func.lower(PurchaseOrder.purchase_order_number).like(pattern),
                    func.lower(Supplier.supplier_name).like(pattern),
                )
            )
        stmt = stmt.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc()).limit(limit)
        return list(db.scalars(stmt).unique().all())

    def add_purchase_order(self, db: Session, order: PurchaseOrder) -> PurchaseOrder:
        db.add(order)
        db.flush()
        return order

    def count_purchase_orders(self, db: Session, *, status: str | None = None) -> int:
        stmt = select(func.count(PurchaseOrder.id))
        if status:
            stmt = stmt.where(PurchaseOrder.status == status)
        return int(db.scalar(stmt) or 0)

    def supplier_stats(self, db: Session, supplier_id: int) -> SupplierPurchaseStats:
        row = db.execute(
            select(
                func.count(PurchaseOrder.id),
                func.coalesce(func.sum(PurchaseOrder.total_amount), 0),
                func.max(PurchaseOrder.created_at),
            ).where(PurchaseOrder.supplier_id == supplier_id)
        ).one()
        received = db.scalar(
            select(
                func.coalesce(
                    func.sum(PurchaseOrderItem.received_quantity * PurchaseOrderItem.unit_cost), 0
                )
            )
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .where(PurchaseOrder.supplier_id == supplier_id)
        )
        return SupplierPurchaseStats(
            order_count=int(row[0] or 0),
            total_value=to_money(row[1] or 0),
            received_value=to_money(received or 0),
            last_order_at=row[2],
        )

    # -- goods receipts ----------------------------------------------------
    def add_receipt(self, db: Session, receipt: GoodsReceipt) -> GoodsReceipt:
        db.add(receipt)
        db.flush()
        return receipt

    def add_receipt_item(self, db: Session, item: GoodsReceiptItem) -> GoodsReceiptItem:
        db.add(item)
        db.flush()
        return item

    def list_receipts(self, db: Session, *, order_id: int | None = None, limit: int = 200) -> list[GoodsReceipt]:
        stmt = select(GoodsReceipt).options(
            selectinload(GoodsReceipt.items).selectinload(GoodsReceiptItem.product),
            selectinload(GoodsReceipt.order),
        )
        if order_id is not None:
            stmt = stmt.where(GoodsReceipt.purchase_order_id == order_id)
        stmt = stmt.order_by(GoodsReceipt.received_at.desc()).limit(limit)
        return list(db.scalars(stmt).unique().all())
