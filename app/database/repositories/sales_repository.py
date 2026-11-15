"""Data access for sales orders, invoices and payments."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.constants import OrderStatus
from app.database.models.catalog import Product
from app.database.models.crm import Customer
from app.database.models.sales import Invoice, Payment, SalesOrder, SalesOrderItem
from app.database.types import ZERO, to_money


class SalesRepository:
    """Queries for the sales pipeline."""

    # -- orders ------------------------------------------------------------
    def _order_options(self):
        return (
            selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
            selectinload(SalesOrder.customer),
            selectinload(SalesOrder.invoice),
        )

    def get_order(self, db: Session, order_id: int) -> SalesOrder | None:
        return db.scalars(
            select(SalesOrder).options(*self._order_options()).where(SalesOrder.id == order_id)
        ).first()

    def list_orders(
        self,
        db: Session,
        *,
        search: str | None = None,
        status: str | None = None,
        customer_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        limit: int = 300,
    ) -> list[SalesOrder]:
        stmt = select(SalesOrder).options(*self._order_options())
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.outerjoin(Customer, Customer.id == SalesOrder.customer_id).where(
                or_(
                    func.lower(SalesOrder.order_number).like(pattern),
                    func.lower(Customer.full_name).like(pattern),
                )
            )
        if status:
            stmt = stmt.where(SalesOrder.order_status == status)
        if customer_id is not None:
            stmt = stmt.where(SalesOrder.customer_id == customer_id)
        if date_from is not None:
            stmt = stmt.where(SalesOrder.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(SalesOrder.created_at <= date_to)
        stmt = stmt.order_by(SalesOrder.created_at.desc(), SalesOrder.id.desc()).limit(limit)
        return list(db.scalars(stmt).unique().all())

    def add_order(self, db: Session, order: SalesOrder) -> SalesOrder:
        db.add(order)
        db.flush()
        return order

    def count_orders(self, db: Session, *, status: str | None = None) -> int:
        stmt = select(func.count(SalesOrder.id))
        if status:
            stmt = stmt.where(SalesOrder.order_status == status)
        return int(db.scalar(stmt) or 0)

    def sales_total(
        self,
        db: Session,
        *,
        status: str = OrderStatus.COMPLETED,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Decimal:
        stmt = select(func.coalesce(func.sum(SalesOrder.total_amount), 0)).where(
            SalesOrder.order_status == status
        )
        if date_from is not None:
            stmt = stmt.where(SalesOrder.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(SalesOrder.created_at <= date_to)
        return to_money(db.scalar(stmt) or 0)

    def top_products(self, db: Session, limit: int = 5) -> list[tuple[str, int, Decimal]]:
        rows = db.execute(
            select(
                Product.product_name,
                func.coalesce(func.sum(SalesOrderItem.quantity), 0),
                func.coalesce(func.sum(SalesOrderItem.line_total), 0),
            )
            .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
            .join(Product, Product.id == SalesOrderItem.product_id)
            .where(SalesOrder.order_status == OrderStatus.COMPLETED)
            .group_by(Product.product_name)
            .order_by(func.sum(SalesOrderItem.line_total).desc())
            .limit(limit)
        ).all()
        return [(str(name), int(quantity or 0), to_money(total or 0)) for name, quantity, total in rows]

    def monthly_sales(self, db: Session, months: int = 6) -> list[tuple[str, Decimal]]:
        rows = db.execute(
            select(
                func.strftime("%Y-%m", SalesOrder.created_at).label("month"),
                func.coalesce(func.sum(SalesOrder.total_amount), 0),
            )
            .where(SalesOrder.order_status == OrderStatus.COMPLETED)
            .group_by("month")
            .order_by("month")
        ).all()
        return [(str(month), to_money(total or 0)) for month, total in rows][-months:]

    def daily_sales(self, db: Session, days: int = 14) -> list[tuple[str, Decimal]]:
        rows = db.execute(
            select(
                func.strftime("%Y-%m-%d", SalesOrder.created_at).label("day"),
                func.coalesce(func.sum(SalesOrder.total_amount), 0),
            )
            .where(SalesOrder.order_status == OrderStatus.COMPLETED)
            .group_by("day")
            .order_by("day")
        ).all()
        return [(str(day), to_money(total or 0)) for day, total in rows][-days:]

    def cogs(self, db: Session, *, date_from: datetime | None = None, date_to: datetime | None = None) -> Decimal:
        """Cost of goods sold from completed orders, using price snapshots."""
        stmt = (
            select(
                func.coalesce(
                    func.sum(SalesOrderItem.cost_price_snapshot * SalesOrderItem.quantity), 0
                )
            )
            .join(SalesOrder, SalesOrder.id == SalesOrderItem.sales_order_id)
            .where(SalesOrder.order_status == OrderStatus.COMPLETED)
        )
        if date_from is not None:
            stmt = stmt.where(SalesOrder.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(SalesOrder.created_at <= date_to)
        return to_money(db.scalar(stmt) or 0)

    # -- invoices ----------------------------------------------------------
    def add_invoice(self, db: Session, invoice: Invoice) -> Invoice:
        db.add(invoice)
        db.flush()
        return invoice

    def get_invoice(self, db: Session, invoice_id: int) -> Invoice | None:
        return db.scalars(
            select(Invoice)
            .options(
                selectinload(Invoice.payments),
                selectinload(Invoice.customer),
                selectinload(Invoice.order).selectinload(SalesOrder.items).selectinload(SalesOrderItem.product),
            )
            .where(Invoice.id == invoice_id)
        ).first()

    def get_invoice_for_order(self, db: Session, order_id: int) -> Invoice | None:
        return db.scalars(select(Invoice).where(Invoice.sales_order_id == order_id)).first()

    def list_invoices(
        self,
        db: Session,
        *,
        status: str | None = None,
        customer_id: int | None = None,
        limit: int = 300,
    ) -> list[Invoice]:
        stmt = select(Invoice).options(selectinload(Invoice.payments), selectinload(Invoice.customer))
        if status:
            stmt = stmt.where(Invoice.status == status)
        if customer_id is not None:
            stmt = stmt.where(Invoice.customer_id == customer_id)
        stmt = stmt.order_by(Invoice.created_at.desc()).limit(limit)
        return list(db.scalars(stmt).unique().all())

    def outstanding_total(self, db: Session) -> Decimal:
        invoices = db.scalars(
            select(Invoice).options(selectinload(Invoice.payments)).where(
                Invoice.status.in_(("UNPAID", "PARTIALLY_PAID"))
            )
        ).unique().all()
        total = ZERO
        for invoice in invoices:
            total += to_money(invoice.total_amount) - invoice.paid_amount
        return to_money(total)

    # -- payments ----------------------------------------------------------
    def add_payment(self, db: Session, payment: Payment) -> Payment:
        db.add(payment)
        db.flush()
        return payment

    def payments_for_invoice(self, db: Session, invoice_id: int) -> list[Payment]:
        return list(
            db.scalars(
                select(Payment)
                .where(Payment.invoice_id == invoice_id)
                .order_by(Payment.payment_date)
            ).all()
        )

    def payments_received(
        self, db: Session, *, date_from: datetime | None = None, date_to: datetime | None = None
    ) -> Decimal:
        stmt = select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.payment_status == "COMPLETED"
        )
        if date_from is not None:
            stmt = stmt.where(Payment.payment_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(Payment.payment_date <= date_to)
        return to_money(db.scalar(stmt) or 0)

    def list_payments(self, db: Session, *, limit: int = 300) -> list[Payment]:
        return list(
            db.scalars(
                select(Payment)
                .options(selectinload(Payment.invoice))
                .order_by(Payment.payment_date.desc())
                .limit(limit)
            ).all()
        )
