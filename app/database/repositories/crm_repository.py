"""Data access for customers, follow-ups and derived purchase statistics."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.constants import OrderStatus
from app.database.models.crm import Customer, CustomerFollowUp
from app.database.models.sales import SalesOrder
from app.database.types import ZERO, to_money


@dataclass(frozen=True)
class CustomerPurchaseStats:
    """Derived from real completed sales orders — never stored or invented."""

    order_count: int = 0
    total_purchase: Decimal = ZERO
    last_purchase_at: datetime | None = None
    first_purchase_at: datetime | None = None


class CrmRepository:
    """Customer queries and purchase aggregates."""

    def get(self, db: Session, customer_id: int) -> Customer | None:
        return db.get(Customer, customer_id)

    def get_by_code(self, db: Session, code: str) -> Customer | None:
        return db.scalars(
            select(Customer).where(func.lower(Customer.customer_code) == code.strip().lower())
        ).first()

    def find_by_contact(self, db: Session, *, email: str | None, phone: str | None) -> Customer | None:
        """Duplicate detection on email or phone (both normalised)."""
        conditions = []
        if email:
            conditions.append(func.lower(Customer.email) == email.strip().lower())
        if phone:
            conditions.append(func.replace(Customer.phone, " ", "") == phone.replace(" ", ""))
        if not conditions:
            return None
        return db.scalars(select(Customer).where(or_(*conditions))).first()

    def list(
        self,
        db: Session,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        city: str | None = None,
        customer_type: str | None = None,
    ) -> list[Customer]:
        stmt = select(Customer)
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Customer.full_name).like(pattern),
                    func.lower(Customer.customer_code).like(pattern),
                    func.lower(func.coalesce(Customer.email, "")).like(pattern),
                    func.coalesce(Customer.phone, "").like(pattern),
                    func.lower(func.coalesce(Customer.city, "")).like(pattern),
                )
            )
        if is_active is not None:
            stmt = stmt.where(Customer.is_active.is_(is_active))
        if city:
            stmt = stmt.where(func.lower(func.coalesce(Customer.city, "")) == city.strip().lower())
        if customer_type:
            stmt = stmt.where(Customer.customer_type == customer_type)
        return list(db.scalars(stmt.order_by(Customer.full_name)).all())

    def add(self, db: Session, customer: Customer) -> Customer:
        db.add(customer)
        db.flush()
        return customer

    def count(self, db: Session, *, is_active: bool | None = None) -> int:
        stmt = select(func.count(Customer.id))
        if is_active is not None:
            stmt = stmt.where(Customer.is_active.is_(is_active))
        return int(db.scalar(stmt) or 0)

    def new_since(self, db: Session, since: datetime) -> int:
        return int(
            db.scalar(select(func.count(Customer.id)).where(Customer.created_at >= since)) or 0
        )

    # -- purchase statistics ----------------------------------------------
    def purchase_stats(self, db: Session, customer_id: int) -> CustomerPurchaseStats:
        row = db.execute(
            select(
                func.count(SalesOrder.id),
                func.coalesce(func.sum(SalesOrder.total_amount), 0),
                func.max(SalesOrder.created_at),
                func.min(SalesOrder.created_at),
            ).where(
                SalesOrder.customer_id == customer_id,
                SalesOrder.order_status == OrderStatus.COMPLETED,
            )
        ).one()
        return CustomerPurchaseStats(
            order_count=int(row[0] or 0),
            total_purchase=to_money(row[1] or 0),
            last_purchase_at=row[2],
            first_purchase_at=row[3],
        )

    def purchase_stats_map(self, db: Session) -> dict[int, CustomerPurchaseStats]:
        rows = db.execute(
            select(
                SalesOrder.customer_id,
                func.count(SalesOrder.id),
                func.coalesce(func.sum(SalesOrder.total_amount), 0),
                func.max(SalesOrder.created_at),
                func.min(SalesOrder.created_at),
            )
            .where(SalesOrder.order_status == OrderStatus.COMPLETED)
            .group_by(SalesOrder.customer_id)
        ).all()
        return {
            int(customer_id): CustomerPurchaseStats(
                order_count=int(count or 0),
                total_purchase=to_money(total or 0),
                last_purchase_at=last,
                first_purchase_at=first,
            )
            for customer_id, count, total, last, first in rows
        }

    def top_customers(self, db: Session, limit: int = 5) -> list[tuple[Customer, CustomerPurchaseStats]]:
        stats = self.purchase_stats_map(db)
        ranked = sorted(stats.items(), key=lambda item: item[1].total_purchase, reverse=True)[:limit]
        result: list[tuple[Customer, CustomerPurchaseStats]] = []
        for customer_id, stat in ranked:
            customer = self.get(db, customer_id)
            if customer is not None:
                result.append((customer, stat))
        return result

    def outstanding_by_customer(self, db: Session, customer_id: int) -> Decimal:
        from app.database.models.sales import Invoice

        rows = db.execute(
            select(Invoice.total_amount, Invoice.id).where(
                Invoice.customer_id == customer_id,
                Invoice.status.in_(("UNPAID", "PARTIALLY_PAID")),
            )
        ).all()
        total = ZERO
        from app.database.models.sales import Payment

        for amount, invoice_id in rows:
            paid = db.scalar(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.invoice_id == invoice_id,
                    Payment.payment_status == "COMPLETED",
                )
            )
            total += to_money(amount) - to_money(paid or 0)
        return to_money(total)

    # -- follow-ups --------------------------------------------------------
    def add_follow_up(self, db: Session, follow_up: CustomerFollowUp) -> CustomerFollowUp:
        db.add(follow_up)
        db.flush()
        return follow_up

    def get_follow_up(self, db: Session, follow_up_id: int) -> CustomerFollowUp | None:
        return db.get(CustomerFollowUp, follow_up_id)

    def list_follow_ups(
        self,
        db: Session,
        *,
        customer_id: int | None = None,
        status: str | None = None,
        overdue_only: bool = False,
        assigned_to: int | None = None,
        now: datetime | None = None,
    ) -> list[CustomerFollowUp]:
        stmt = select(CustomerFollowUp).options(selectinload(CustomerFollowUp.customer))
        if customer_id is not None:
            stmt = stmt.where(CustomerFollowUp.customer_id == customer_id)
        if status:
            stmt = stmt.where(CustomerFollowUp.status == status)
        if assigned_to is not None:
            stmt = stmt.where(CustomerFollowUp.assigned_to == assigned_to)
        if overdue_only:
            from app.utils.date_utils import utcnow

            stmt = stmt.where(
                CustomerFollowUp.status == "PENDING",
                CustomerFollowUp.due_date < (now or utcnow()),
            )
        return list(
            db.scalars(stmt.order_by(CustomerFollowUp.due_date.asc())).unique().all()
        )
