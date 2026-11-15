"""Customer relationship service: records, segmentation, profile, follow-ups."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    MODULE_CUSTOMERS,
    CustomerSegment,
    EventType,
    FollowUpStatus,
    OrderStatus,
    AuditAction,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.crm import Customer, CustomerFollowUp
from app.database.models.sales import Invoice, Payment, SalesOrder
from app.database.repositories.crm_repository import CrmRepository
from app.database.repositories.sales_repository import SalesRepository
from app.database.repositories.user_repository import UserRepository
from app.database.types import ZERO, to_money
from app.schemas.crm_schema import (
    CrmDashboard,
    CustomerCreateRequest,
    CustomerInvoiceRow,
    CustomerPaymentRow,
    CustomerProfile,
    CustomerSummary,
    CustomerUpdateRequest,
    FollowUpCreateRequest,
    FollowUpView,
)
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload
from app.services.event_service import EventService
from app.services.export_service import ExportService
from app.services.numbering import next_document_number
from app.utils.date_utils import utcnow

logger = get_logger("services.customers")

# --- Transparent, documented segmentation rules -----------------------------
HIGH_VALUE_THRESHOLD = Decimal("50000.00")
NEW_CUSTOMER_DAYS = 30
INACTIVE_DAYS = 90
REGULAR_MIN_ORDERS = 3

SEGMENTATION_RULES = [
    f"High value: lifetime purchases ≥ {HIGH_VALUE_THRESHOLD:,.2f}",
    f"New: created within the last {NEW_CUSTOMER_DAYS} days and at most one completed order",
    f"Regular: {REGULAR_MIN_ORDERS}+ completed orders with a purchase in the last {INACTIVE_DAYS} days",
    f"Inactive: no completed purchase in the last {INACTIVE_DAYS} days",
    "Occasional: at least one completed order that fits no other rule",
]


class CustomerService(BaseService):
    """Customers, purchase history, segmentation and follow-ups."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        crm_repository: CrmRepository,
        sales_repository: SalesRepository,
        user_repository: UserRepository,
        audit_service: AuditService,
        event_service: EventService,
        export_service: ExportService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._crm = crm_repository
        self._sales = sales_repository
        self._users = user_repository
        self._audit = audit_service
        self._events = event_service
        self._export = export_service

    # -- dashboard ---------------------------------------------------------
    def dashboard(self) -> CrmDashboard:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "customers.view")
            stats = self._crm.purchase_stats_map(db)
            customers = self._crm.list(db)
            segments = self._segment_counts(db, customers, stats)
            total_value = to_money(sum((stat.total_purchase for stat in stats.values()), ZERO))
            top = [
                self._summary(customer, stats.get(customer.id), db)
                for customer, _ in self._crm.top_customers(db, limit=5)
            ]
            return CrmDashboard(
                total_customers=len(customers),
                active_customers=sum(1 for customer in customers if customer.is_active),
                new_customers_30d=self._crm.new_since(db, utcnow() - timedelta(days=NEW_CUSTOMER_DAYS)),
                inactive_customers=sum(1 for customer in customers if not customer.is_active),
                total_purchase_value=total_value,
                top_customers=top,
                segments=segments,
                segmentation_rules=SEGMENTATION_RULES,
            )

    # -- customers ---------------------------------------------------------
    def list_customers(
        self,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        city: str | None = None,
        customer_type: str | None = None,
        segment: str | None = None,
    ) -> list[CustomerSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "customers.view")
            customers = self._crm.list(
                db, search=search, is_active=is_active, city=city, customer_type=customer_type
            )
            stats = self._crm.purchase_stats_map(db)
            summaries = [self._summary(customer, stats.get(customer.id), db) for customer in customers]
            if segment:
                summaries = [item for item in summaries if item.segment == segment]
            return summaries

    def get_customer(self, customer_id: int) -> CustomerSummary:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "customers.view")
            customer = self._crm.get(db, customer_id)
            if customer is None:
                raise NotFoundError(f"Customer {customer_id} was not found")
            return self._summary(customer, self._crm.purchase_stats(db, customer_id), db)

    def create_customer(self, payload: dict | CustomerCreateRequest) -> CustomerSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "customers.create")
            data = validate_payload(CustomerCreateRequest, payload)
            self._guard_duplicate(db, data)

            code = (data.customer_code or "").strip().upper() or next_document_number(
                db, Customer, "customer_code", "CUST", with_year=False, width=4
            )
            if self._crm.get_by_code(db, code):
                raise ConflictError(f"Customer code '{code}' is already in use")

            customer = Customer(
                customer_code=code,
                full_name=data.full_name,
                email=data.email,
                phone=data.phone,
                address=data.address,
                city=data.city,
                customer_type=data.customer_type,
                notes=data.notes,
                is_active=data.is_active,
            )
            self._crm.add(db, customer)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_CUSTOMER,
                module=MODULE_CUSTOMERS,
                entity_type="Customer",
                entity_id=customer.id,
                new_values={
                    "customer_code": customer.customer_code,
                    "full_name": customer.full_name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "city": customer.city,
                },
            )
            self._events.publish(
                db,
                EventType.CUSTOMER_CREATED,
                aggregate_type="Customer",
                aggregate_id=customer.id,
                payload={
                    "customer_id": customer.id,
                    "customer_code": customer.customer_code,
                    "full_name": customer.full_name,
                },
            )
            summary = self._summary(customer, None, db)
        self._events.dispatch_pending()
        return summary

    def update_customer(
        self, customer_id: int, payload: dict | CustomerUpdateRequest
    ) -> CustomerSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "customers.update")
            data = validate_payload(CustomerUpdateRequest, payload)
            customer = self._crm.get(db, customer_id)
            if customer is None:
                raise NotFoundError(f"Customer {customer_id} was not found")
            self._guard_duplicate(db, data, exclude_id=customer.id)

            if data.customer_code:
                code = data.customer_code.strip().upper()
                duplicate = self._crm.get_by_code(db, code)
                if duplicate is not None and duplicate.id != customer.id:
                    raise ConflictError(f"Customer code '{code}' is already in use")
                customer.customer_code = code

            old_values = {
                "full_name": customer.full_name,
                "email": customer.email,
                "phone": customer.phone,
                "address": customer.address,
                "city": customer.city,
                "customer_type": customer.customer_type,
                "notes": customer.notes,
                "is_active": customer.is_active,
            }
            customer.full_name = data.full_name
            customer.email = data.email
            customer.phone = data.phone
            customer.address = data.address
            customer.city = data.city
            customer.customer_type = data.customer_type
            customer.notes = data.notes
            customer.is_active = data.is_active
            customer.updated_at = utcnow()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_CUSTOMER,
                module=MODULE_CUSTOMERS,
                entity_type="Customer",
                entity_id=customer.id,
                old_values=old_values,
                new_values={
                    "full_name": customer.full_name,
                    "email": customer.email,
                    "phone": customer.phone,
                    "address": customer.address,
                    "city": customer.city,
                    "customer_type": customer.customer_type,
                    "notes": customer.notes,
                    "is_active": customer.is_active,
                },
            )
            return self._summary(customer, self._crm.purchase_stats(db, customer.id), db)

    def set_active(self, customer_id: int, is_active: bool) -> CustomerSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "customers.deactivate")
            customer = self._crm.get(db, customer_id)
            if customer is None:
                raise NotFoundError(f"Customer {customer_id} was not found")
            previous = customer.is_active
            customer.is_active = is_active
            customer.updated_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.DEACTIVATE_CUSTOMER,
                module=MODULE_CUSTOMERS,
                entity_type="Customer",
                entity_id=customer.id,
                old_values={"is_active": previous},
                new_values={"is_active": is_active},
            )
            return self._summary(customer, self._crm.purchase_stats(db, customer.id), db)

    # -- profile -----------------------------------------------------------
    def profile(self, customer_id: int) -> CustomerProfile:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "customers.view")
            customer = self._crm.get(db, customer_id)
            if customer is None:
                raise NotFoundError(f"Customer {customer_id} was not found")

            stats = self._crm.purchase_stats(db, customer_id)
            summary = self._summary(customer, stats, db)
            orders = self._sales.list_orders(db, customer_id=customer_id, limit=100)
            invoices = [
                CustomerInvoiceRow(
                    invoice_number=order.invoice.invoice_number,
                    invoice_date=order.invoice.invoice_date,
                    total_amount=order.invoice.total_amount,
                    paid_amount=order.invoice.paid_amount,
                    outstanding=order.invoice.outstanding_amount,
                    status=order.invoice.status,
                )
                for order in orders
                if order.invoice is not None
            ]
            payments: list[CustomerPaymentRow] = []
            for order in orders:
                if order.invoice is None:
                    continue
                for payment in order.invoice.payments:
                    payments.append(
                        CustomerPaymentRow(
                            payment_date=payment.payment_date,
                            amount=payment.amount,
                            payment_method=payment.payment_method,
                            reference=payment.payment_reference,
                            invoice_number=order.invoice.invoice_number,
                        )
                    )
            payments.sort(key=lambda row: row.payment_date, reverse=True)

            follow_ups = [
                FollowUpView.from_follow_up(item)
                for item in self._crm.list_follow_ups(db, customer_id=customer_id)
            ]
            return CustomerProfile(
                summary=summary,
                address=customer.address,
                notes=customer.notes,
                outstanding_amount=self._crm.outstanding_by_customer(db, customer_id),
                invoices=invoices,
                payments=payments,
                follow_ups=follow_ups,
                segment_reason=self._segment_reason(customer, stats),
            )

    # -- follow-ups --------------------------------------------------------
    def create_follow_up(self, payload: dict | FollowUpCreateRequest) -> FollowUpView:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "customers.update")
            data = validate_payload(FollowUpCreateRequest, payload)
            customer = self._crm.get(db, data.customer_id)
            if customer is None:
                raise NotFoundError(f"Customer {data.customer_id} was not found")
            if data.assigned_to is not None and self._users.get(db, data.assigned_to) is None:
                raise ValidationError(
                    "Select an existing user.", fields={"assigned_to": "Unknown user"}
                )

            follow_up = CustomerFollowUp(
                customer_id=customer.id,
                title=data.title,
                notes=data.notes,
                due_date=data.due_date,
                assigned_to=data.assigned_to or actor.id,
                status=FollowUpStatus.PENDING,
                created_by=actor.id,
            )
            self._crm.add_follow_up(db, follow_up)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_FOLLOW_UP,
                module=MODULE_CUSTOMERS,
                entity_type="CustomerFollowUp",
                entity_id=follow_up.id,
                new_values={
                    "customer": customer.full_name,
                    "title": follow_up.title,
                    "due_date": follow_up.due_date.isoformat(),
                },
            )
            return FollowUpView.from_follow_up(follow_up)

    def list_follow_ups(
        self, *, customer_id: int | None = None, overdue_only: bool = False, status: str | None = None
    ) -> list[FollowUpView]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "customers.view")
            items = self._crm.list_follow_ups(
                db, customer_id=customer_id, overdue_only=overdue_only, status=status
            )
            return [FollowUpView.from_follow_up(item) for item in items]

    def complete_follow_up(self, follow_up_id: int) -> FollowUpView:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "customers.update")
            follow_up = self._crm.get_follow_up(db, follow_up_id)
            if follow_up is None:
                raise NotFoundError(f"Follow-up {follow_up_id} was not found")
            if follow_up.status == FollowUpStatus.COMPLETED:
                raise ConflictError("This follow-up is already completed")
            follow_up.status = FollowUpStatus.COMPLETED
            follow_up.completed_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.COMPLETE_FOLLOW_UP,
                module=MODULE_CUSTOMERS,
                entity_type="CustomerFollowUp",
                entity_id=follow_up.id,
                old_values={"status": FollowUpStatus.PENDING},
                new_values={"status": FollowUpStatus.COMPLETED},
            )
            return FollowUpView.from_follow_up(follow_up)

    # -- segmentation ------------------------------------------------------
    def segment_of(self, customer: Customer, stats) -> str:
        now = utcnow()
        if stats.last_purchase_at is None:
            created_days = (now - customer.created_at).days if customer.created_at else 0
            return CustomerSegment.NEW if created_days <= NEW_CUSTOMER_DAYS else CustomerSegment.INACTIVE
        days_since = (now - stats.last_purchase_at).days
        if days_since > INACTIVE_DAYS:
            return CustomerSegment.INACTIVE
        if stats.total_purchase >= HIGH_VALUE_THRESHOLD:
            return CustomerSegment.HIGH_VALUE
        if stats.order_count >= REGULAR_MIN_ORDERS:
            return CustomerSegment.REGULAR
        if (now - customer.created_at).days <= NEW_CUSTOMER_DAYS and stats.order_count <= 1:
            return CustomerSegment.NEW
        return CustomerSegment.OCCASIONAL

    def _segment_reason(self, customer: Customer, stats) -> str:
        segment = self.segment_of(customer, stats)
        if segment == CustomerSegment.HIGH_VALUE:
            return f"Lifetime purchases {stats.total_purchase:,.2f} ≥ {HIGH_VALUE_THRESHOLD:,.2f}"
        if segment == CustomerSegment.REGULAR:
            return f"{stats.order_count} completed orders, last purchase {(utcnow() - stats.last_purchase_at).days} days ago"
        if segment == CustomerSegment.NEW:
            return f"Customer created {(utcnow() - customer.created_at).days} days ago"
        if segment == CustomerSegment.INACTIVE:
            if stats.last_purchase_at is None:
                return "No completed purchases yet"
            return f"No purchase in the last {(utcnow() - stats.last_purchase_at).days} days"
        return "Occasional buyer: completed orders below the regular threshold"

    def _segment_counts(self, db: Session, customers: list[Customer], stats: dict) -> dict[str, int]:
        counts = {segment: 0 for segment in CustomerSegment.ALL}
        for customer in customers:
            counts[self.segment_of(customer, stats.get(customer.id) or _empty_stats())] += 1
        return counts

    def _summary(self, customer: Customer, stats, db: Session | None) -> CustomerSummary:
        from app.database.repositories.crm_repository import CustomerPurchaseStats

        stats = stats or CustomerPurchaseStats()
        return CustomerSummary(
            id=customer.id,
            customer_code=customer.customer_code,
            full_name=customer.full_name,
            email=customer.email,
            phone=customer.phone,
            city=customer.city,
            customer_type=customer.customer_type,
            is_active=customer.is_active,
            created_at=customer.created_at,
            order_count=stats.order_count,
            total_purchase=stats.total_purchase,
            last_purchase_at=stats.last_purchase_at,
            segment=self.segment_of(customer, stats),
        )

    def _guard_duplicate(self, db: Session, data, *, exclude_id: int | None = None) -> None:
        existing = self._crm.find_by_contact(db, email=data.email, phone=data.phone)
        if existing is not None and existing.id != exclude_id:
            field = "email" if data.email and existing.email == data.email else "phone"
            raise ValidationError(
                f"A customer with this {field} already exists ({existing.full_name}).",
                fields={field: "Already registered"},
            )

    # -- exports -----------------------------------------------------------
    def export_customers_csv(self) -> str:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "customers.export")
            headers, rows = self.export_rows()
            stamp = utcnow().strftime("%Y%m%d_%H%M%S")
            path = self._export.write_csv(f"customers_{stamp}.csv", headers, rows)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.EXPORT_REPORT,
                module=MODULE_CUSTOMERS,
                entity_type="Report",
                entity_id="customers",
                new_values={"format": "csv", "path": str(path)},
            )
        return str(path)

    def export_rows(self) -> tuple[list[str], list[list[str]]]:
        """Header and rows for the customer CSV export."""
        summaries = self.list_customers()
        headers = [
            "Code",
            "Name",
            "Email",
            "Phone",
            "City",
            "Type",
            "Status",
            "Orders",
            "Total purchase",
            "Last purchase",
            "Segment",
        ]
        rows = [
            [
                item.customer_code,
                item.full_name,
                item.email or "",
                item.phone or "",
                item.city or "",
                item.customer_type,
                "Active" if item.is_active else "Inactive",
                str(item.order_count),
                f"{item.total_purchase:.2f}",
                item.last_purchase_at.strftime("%d-%m-%Y") if item.last_purchase_at else "",
                item.segment,
            ]
            for item in summaries
        ]
        return headers, rows


def _empty_stats():
    from app.database.repositories.crm_repository import CustomerPurchaseStats

    return CustomerPurchaseStats()
