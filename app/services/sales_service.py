"""Sales service: orders, stock deduction, invoicing, payments, cancellation.

Accounting basis
----------------
* Revenue is recognised when an order is **completed** (not when it is drafted
  or confirmed), as a ``SALES_REVENUE`` financial transaction.
* Cash is recognised only when a **payment** is recorded against an invoice, as
  a separate ``PAYMENT_RECEIVED`` transaction. Unpaid invoices are therefore
  revenue but not cash.
* Cancelling a completed order reverses revenue (``SALES_REFUND``) and, when
  money had been collected, records a cash refund (``CASH_REFUND``). Original
  rows are never deleted.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    MODULE_FINANCE,
    MODULE_SALES,
    EventType,
    InvoiceStatus,
    MovementType,
    OrderStatus,
    PaymentStatus,
    TransactionCategory,
    TransactionType,
    AuditAction,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.catalog import Product
from app.database.models.crm import Customer
from app.database.models.inventory import Branch
from app.database.models.sales import Invoice, Payment, SalesOrder, SalesOrderItem
from app.database.repositories.catalog_repository import CatalogRepository
from app.database.repositories.crm_repository import CrmRepository
from app.database.repositories.inventory_repository import InventoryRepository
from app.database.repositories.sales_repository import SalesRepository
from app.database.types import ZERO, to_money
from app.schemas.sales_schema import (
    InvoiceView,
    PaymentCreateRequest,
    SalesDashboard,
    SalesOrderCreateRequest,
    SalesOrderSummary,
)
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload
from app.services.event_service import EventService
from app.services.export_service import ExportService
from app.services.finance_service import FinanceService
from app.services.inventory_service import InventoryService
from app.services.numbering import next_document_number
from app.utils.date_utils import utcnow

logger = get_logger("services.sales")

DEFAULT_INVOICE_DUE_DAYS = 15


class SalesService(BaseService):
    """Sales order lifecycle, invoicing and payment capture."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        sales_repository: SalesRepository,
        catalog_repository: CatalogRepository,
        crm_repository: CrmRepository,
        inventory_repository: InventoryRepository,
        inventory_service: InventoryService,
        finance_service: FinanceService,
        audit_service: AuditService,
        event_service: EventService,
        export_service: ExportService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._sales = sales_repository
        self._catalog = catalog_repository
        self._crm = crm_repository
        self._inventory = inventory_repository
        self._inventory_service = inventory_service
        self._finance = finance_service
        self._audit = audit_service
        self._events = event_service
        self._export = export_service

    # -- queries -----------------------------------------------------------
    def list_orders(
        self,
        *,
        search: str | None = None,
        status: str | None = None,
        customer_id: int | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[SalesOrderSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "sales.view")
            orders = self._sales.list_orders(
                db,
                search=search,
                status=status,
                customer_id=customer_id,
                date_from=date_from,
                date_to=date_to,
            )
            return [SalesOrderSummary.from_order(order) for order in orders]

    def get_order(self, order_id: int) -> SalesOrderSummary:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "sales.view")
            return SalesOrderSummary.from_order(self._load_order(db, order_id))

    def dashboard(self) -> SalesDashboard:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "sales.view")
            completed = self._sales.count_orders(db, status=OrderStatus.COMPLETED)
            total_value = self._sales.sales_total(db)
            average = to_money(total_value / completed) if completed else ZERO
            pending = self._sales.count_orders(db, status=OrderStatus.DRAFT) + self._sales.count_orders(
                db, status=OrderStatus.CONFIRMED
            )
            return SalesDashboard(
                total_orders=self._sales.count_orders(db),
                completed_orders=completed,
                pending_orders=pending,
                cancelled_orders=self._sales.count_orders(db, status=OrderStatus.CANCELLED),
                total_sales_value=total_value,
                average_order_value=average,
                paid_total=self._sales.payments_received(db),
                outstanding_total=self._sales.outstanding_total(db),
                top_products=[
                    {"product": name, "quantity": quantity, "revenue": str(revenue)}
                    for name, quantity, revenue in self._sales.top_products(db)
                ],
                monthly_sales=self._sales.monthly_sales(db),
                daily_sales=self._sales.daily_sales(db),
            )

    def list_invoices(
        self,
        *,
        status: str | None = None,
        customer_id: int | None = None,
        limit: int = 300,
    ) -> list[InvoiceView]:
        """Invoice rows for receivables, aging and follow-up work."""
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "sales.view")
            return [
                InvoiceView.from_invoice(invoice)
                for invoice in self._sales.list_invoices(
                    db, status=status, customer_id=customer_id, limit=limit
                )
            ]

    def invoice(self, invoice_id: int) -> InvoiceView:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "sales.view")
            invoice = self._sales.get_invoice(db, invoice_id)
            if invoice is None:
                raise NotFoundError(f"Invoice {invoice_id} was not found")
            return InvoiceView.from_invoice(invoice)

    def invoice_for_order(self, order_id: int) -> InvoiceView | None:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "sales.view")
            invoice = self._sales.get_invoice_for_order(db, order_id)
            return InvoiceView.from_invoice(invoice) if invoice else None

    # -- order creation ----------------------------------------------------
    def create_order(self, payload: dict | SalesOrderCreateRequest) -> SalesOrderSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "sales.create")
            data = validate_payload(SalesOrderCreateRequest, payload)

            customer = self._crm.get(db, data.customer_id)
            if customer is None:
                raise ValidationError("Select an existing customer.", fields={"customer_id": "Unknown"})
            if not customer.is_active:
                raise ValidationError(
                    "This customer is inactive.", fields={"customer_id": "Inactive customer"}
                )

            subtotal = ZERO
            line_discount = ZERO
            line_tax = ZERO
            total = ZERO
            prepared: list[tuple[Product, int, Decimal, Decimal, Decimal, Decimal]] = []

            for item in data.items:
                product = self._catalog.get_product(db, item.product_id)
                if product is None:
                    raise ValidationError(
                        f"Product {item.product_id} does not exist.",
                        fields={"items": "Unknown product"},
                    )
                if not product.is_active:
                    raise ValidationError(
                        f"{product.product_name} is inactive and cannot be sold.",
                        fields={"items": f"{product.sku} inactive"},
                    )
                unit_price = (
                    to_money(item.unit_price)
                    if item.unit_price is not None
                    else to_money(product.selling_price)
                )
                gross = to_money(unit_price * item.quantity)
                discount = to_money(item.discount_amount)
                if discount > gross:
                    raise ValidationError(
                        f"Discount for {product.product_name} exceeds the line value.",
                        fields={"items": "Discount too large"},
                    )
                tax = to_money(item.tax_amount)
                line_total = to_money(gross - discount + tax)
                prepared.append((product, item.quantity, unit_price, discount, tax, line_total))
                subtotal += gross
                line_discount += discount
                line_tax += tax
                total += line_total

            order_discount = to_money(data.discount_amount)
            if order_discount > total:
                raise ValidationError(
                    "Order discount exceeds the order value.",
                    fields={"discount_amount": "Too large"},
                )
            total = to_money(total - order_discount)

            order = SalesOrder(
                order_number=next_document_number(db, SalesOrder, "order_number", "SO"),
                customer_id=customer.id,
                subtotal=to_money(subtotal),
                discount_amount=to_money(line_discount + order_discount),
                tax_amount=to_money(line_tax),
                total_amount=total,
                paid_amount=ZERO,
                payment_status=PaymentStatus.UNPAID,
                order_status=OrderStatus.DRAFT,
                notes=data.notes,
                created_by=actor.id,
            )
            self._sales.add_order(db, order)

            for product, quantity, unit_price, discount, tax, line_total in prepared:
                order.items.append(
                    SalesOrderItem(
                        sales_order_id=order.id,
                        product_id=product.id,
                        quantity=quantity,
                        unit_price=unit_price,
                        cost_price_snapshot=to_money(product.cost_price),
                        discount_amount=discount,
                        tax_amount=tax,
                        line_total=line_total,
                    )
                )
            db.flush()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_SALES_ORDER,
                module=MODULE_SALES,
                entity_type="SalesOrder",
                entity_id=order.id,
                new_values={
                    "order_number": order.order_number,
                    "customer": customer.full_name,
                    "total_amount": str(order.total_amount),
                    "items": len(prepared),
                },
            )
            return SalesOrderSummary.from_order(self._load_order(db, order.id))

    def confirm_order(self, order_id: int) -> SalesOrderSummary:
        """Move a draft order to CONFIRMED after checking stock availability."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "sales.create")
            order = self._load_order(db, order_id)
            if order.order_status != OrderStatus.DRAFT:
                raise ConflictError(
                    f"Only draft orders can be confirmed (current status: {order.order_status})"
                )
            if not order.items:
                raise ValidationError("An order must contain at least one product.")
            self._assert_stock(db, order)

            order.order_status = OrderStatus.CONFIRMED
            order.updated_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CONFIRM_SALES_ORDER,
                module=MODULE_SALES,
                entity_type="SalesOrder",
                entity_id=order.id,
                old_values={"order_status": OrderStatus.DRAFT},
                new_values={"order_status": OrderStatus.CONFIRMED},
            )
            return SalesOrderSummary.from_order(order)

    # -- completion --------------------------------------------------------
    def complete_order(self, order_id: int) -> SalesOrderSummary:
        """Complete an order: stock out, invoice, revenue — one transaction."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "sales.create")
            order = self._load_order(db, order_id)

            if order.order_status == OrderStatus.COMPLETED:
                raise ConflictError("This order is already completed")
            if order.order_status == OrderStatus.CANCELLED:
                raise ConflictError("A cancelled order cannot be completed")
            if not order.items:
                raise ValidationError("An order must contain at least one product.")

            branch = self._default_branch(db)
            self._assert_stock(db, order, branch)

            for item in order.items:
                self._inventory_service.apply_change(
                    db,
                    product=item.product,
                    delta=-item.quantity,
                    movement_type=MovementType.SALE,
                    reference_type="SALES_ORDER",
                    reference_id=order.order_number,
                    notes=f"Sale to {order.customer.full_name if order.customer else ''}".strip(),
                    actor_id=actor.id,
                    branch=branch,
                )

            invoice = Invoice(
                invoice_number=next_document_number(db, Invoice, "invoice_number", "INV"),
                sales_order_id=order.id,
                customer_id=order.customer_id,
                invoice_date=utcnow(),
                due_date=utcnow() + timedelta(days=DEFAULT_INVOICE_DUE_DAYS),
                subtotal=order.subtotal,
                discount_amount=order.discount_amount,
                tax_amount=order.tax_amount,
                total_amount=order.total_amount,
                status=InvoiceStatus.UNPAID,
            )
            self._sales.add_invoice(db, invoice)
            # Keep the in-memory relationship consistent with the new row.
            order.invoice = invoice

            self._finance.post_transaction(
                db,
                transaction_type=TransactionType.INCOME,
                category=TransactionCategory.SALES_REVENUE,
                amount=order.total_amount,
                reference_type="SALES_ORDER",
                reference_id=order.order_number,
                description=f"Revenue recognised for {order.order_number}",
                actor_id=actor.id,
            )

            order.order_status = OrderStatus.COMPLETED
            order.updated_at = utcnow()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.COMPLETE_SALES_ORDER,
                module=MODULE_SALES,
                entity_type="SalesOrder",
                entity_id=order.id,
                old_values={"order_status": OrderStatus.CONFIRMED},
                new_values={
                    "order_status": OrderStatus.COMPLETED,
                    "invoice_number": invoice.invoice_number,
                    "total_amount": str(order.total_amount),
                },
            )
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_INVOICE,
                module=MODULE_FINANCE,
                entity_type="Invoice",
                entity_id=invoice.id,
                new_values={
                    "invoice_number": invoice.invoice_number,
                    "total_amount": str(invoice.total_amount),
                },
            )
            self._events.publish(
                db,
                EventType.SALE_COMPLETED,
                aggregate_type="SalesOrder",
                aggregate_id=order.id,
                payload={
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "customer_id": order.customer_id,
                    "invoice_number": invoice.invoice_number,
                    "total_amount": str(order.total_amount),
                    "item_count": len(order.items),
                },
            )
            summary = SalesOrderSummary.from_order(self._load_order(db, order.id))
        self._events.dispatch_pending()
        return summary

    # -- payments ----------------------------------------------------------
    def record_payment(self, payload: dict | PaymentCreateRequest) -> InvoiceView:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "sales.update")
            data = validate_payload(PaymentCreateRequest, payload)

            invoice = self._sales.get_invoice(db, data.invoice_id)
            if invoice is None:
                raise NotFoundError(f"Invoice {data.invoice_id} was not found")
            if invoice.status == InvoiceStatus.CANCELLED:
                raise ConflictError("A cancelled invoice cannot accept payments")

            amount = to_money(data.amount)
            outstanding = invoice.outstanding_amount
            if amount > outstanding:
                raise ValidationError(
                    f"Payment exceeds the outstanding amount of {outstanding:,.2f}. "
                    "Record a credit or refund workflow instead.",
                    fields={"amount": "Exceeds outstanding balance"},
                )

            payment = Payment(
                invoice_id=invoice.id,
                amount=amount,
                payment_method=data.payment_method,
                payment_reference=data.payment_reference,
                payment_date=utcnow(),
                payment_status="COMPLETED",
                created_by=actor.id,
            )
            # Append through the relationship so the in-memory invoice totals
            # (paid_amount / outstanding_amount) reflect the new payment.
            invoice.payments.append(payment)
            db.flush()

            paid_total = invoice.paid_amount
            invoice.status = (
                InvoiceStatus.PAID if paid_total >= to_money(invoice.total_amount) else InvoiceStatus.PARTIALLY_PAID
            )

            order = invoice.order
            if order is not None:
                order.paid_amount = paid_total
                order.payment_status = (
                    PaymentStatus.PAID
                    if paid_total >= to_money(order.total_amount)
                    else PaymentStatus.PARTIALLY_PAID
                )
                order.updated_at = utcnow()

            self._finance.post_transaction(
                db,
                transaction_type=TransactionType.INCOME,
                category=TransactionCategory.PAYMENT_RECEIVED,
                amount=amount,
                reference_type="PAYMENT",
                reference_id=payment.id,
                description=f"Payment received against {invoice.invoice_number}",
                actor_id=actor.id,
            )

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.RECORD_PAYMENT,
                module=MODULE_SALES,
                entity_type="Payment",
                entity_id=payment.id,
                new_values={
                    "invoice_number": invoice.invoice_number,
                    "amount": str(amount),
                    "method": data.payment_method,
                    "invoice_status": invoice.status,
                },
            )
            self._events.publish(
                db,
                EventType.PAYMENT_RECEIVED,
                aggregate_type="Invoice",
                aggregate_id=invoice.id,
                payload={
                    "invoice_id": invoice.id,
                    "invoice_number": invoice.invoice_number,
                    "amount": str(amount),
                    "method": data.payment_method,
                },
            )
            view = InvoiceView.from_invoice(self._sales.get_invoice(db, invoice.id))
        self._events.dispatch_pending()
        return view

    # -- cancellation ------------------------------------------------------
    def cancel_order(self, order_id: int, reason: str) -> SalesOrderSummary:
        """Cancel an order, reversing stock and financial entries exactly once."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "sales.cancel")
            order = self._load_order(db, order_id)

            if order.order_status == OrderStatus.CANCELLED:
                raise ConflictError("This order is already cancelled")
            if not reason or len(reason.strip()) < 3:
                raise ValidationError(
                    "Provide a cancellation reason.", fields={"reason": "Required"}
                )

            previous_status = order.order_status
            branch = self._default_branch(db)

            if previous_status == OrderStatus.COMPLETED:
                # 1. Return the stock that was deducted.
                for item in order.items:
                    if item.product is None:
                        continue
                    self._inventory_service.apply_change(
                        db,
                        product=item.product,
                        delta=item.quantity,
                        movement_type=MovementType.RETURN,
                        reference_type="SALES_ORDER_CANCEL",
                        reference_id=order.order_number,
                        notes=f"Cancellation: {reason.strip()}",
                        actor_id=actor.id,
                        branch=branch,
                    )

                # 2. Reverse revenue recognition.
                self._finance.post_transaction(
                    db,
                    transaction_type=TransactionType.REFUND,
                    category=TransactionCategory.SALES_REFUND,
                    amount=-to_money(order.total_amount),
                    reference_type="SALES_ORDER_CANCEL",
                    reference_id=order.order_number,
                    description=f"Revenue reversed for cancelled order {order.order_number}",
                    actor_id=actor.id,
                )

                # 3. Reverse collected cash, if any.
                invoice = self._sales.get_invoice_for_order(db, order.id)
                if invoice is not None:
                    paid = invoice.paid_amount
                    if paid > 0:
                        self._finance.post_transaction(
                            db,
                            transaction_type=TransactionType.REFUND,
                            category=TransactionCategory.CASH_REFUND,
                            amount=-to_money(paid),
                            reference_type="SALES_ORDER_CANCEL",
                            reference_id=order.order_number,
                            description=f"Cash refunded for cancelled order {order.order_number}",
                            actor_id=actor.id,
                        )
                        for payment in invoice.payments:
                            payment.payment_status = "REFUNDED"
                        order.payment_status = PaymentStatus.REFUNDED
                    invoice.status = InvoiceStatus.CANCELLED

            order.order_status = OrderStatus.CANCELLED
            order.updated_at = utcnow()

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CANCEL_SALES_ORDER,
                module=MODULE_SALES,
                entity_type="SalesOrder",
                entity_id=order.id,
                old_values={"order_status": previous_status},
                new_values={
                    "order_status": OrderStatus.CANCELLED,
                    "reason": reason.strip(),
                    "stock_returned": previous_status == OrderStatus.COMPLETED,
                },
            )
            self._events.publish(
                db,
                EventType.SALE_CANCELLED,
                aggregate_type="SalesOrder",
                aggregate_id=order.id,
                payload={
                    "order_id": order.id,
                    "order_number": order.order_number,
                    "reason": reason.strip(),
                    "previous_status": previous_status,
                },
            )
            summary = SalesOrderSummary.from_order(order)
        self._events.dispatch_pending()
        return summary

    # -- exports -----------------------------------------------------------
    def export_sales_csv(self) -> str:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "sales.export")
            headers, rows = self.export_rows()
            stamp = utcnow().strftime("%Y%m%d_%H%M%S")
            path = self._export.write_csv(f"sales_{stamp}.csv", headers, rows)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.EXPORT_REPORT,
                module=MODULE_SALES,
                entity_type="Report",
                entity_id="sales",
                new_values={"format": "csv", "path": str(path)},
            )
        return str(path)

    def export_rows(self) -> tuple[list[str], list[list[str]]]:
        orders = self.list_orders()
        headers = [
            "Order",
            "Date",
            "Customer",
            "Status",
            "Payment status",
            "Subtotal",
            "Discount",
            "Tax",
            "Total",
            "Paid",
            "Outstanding",
            "Invoice",
        ]
        rows = [
            [
                order.order_number,
                order.created_at.strftime("%d-%m-%Y"),
                order.customer_name,
                order.order_status,
                order.payment_status,
                f"{order.subtotal:.2f}",
                f"{order.discount_amount:.2f}",
                f"{order.tax_amount:.2f}",
                f"{order.total_amount:.2f}",
                f"{order.paid_amount:.2f}",
                f"{order.outstanding_amount:.2f}",
                order.invoice_number or "",
            ]
            for order in orders
        ]
        return headers, rows

    # -- helpers -----------------------------------------------------------
    def _load_order(self, db: Session, order_id: int) -> SalesOrder:
        order = self._sales.get_order(db, order_id)
        if order is None:
            raise NotFoundError(f"Sales order {order_id} was not found")
        return order

    def _default_branch(self, db: Session) -> Branch:
        branch = self._inventory.default_branch(db)
        if branch is None:
            raise ConflictError("No business location is configured for stock")
        return branch

    def _assert_stock(self, db: Session, order: SalesOrder, branch: Branch | None = None) -> None:
        branch = branch or self._default_branch(db)
        shortages: list[str] = []
        for item in order.items:
            stock = self._inventory.get_stock(db, item.product_id, branch.id)
            available = int(stock.available_quantity) if stock else 0
            if available < item.quantity:
                name = item.product.product_name if item.product else f"product {item.product_id}"
                shortages.append(f"{name}: available {available}, required {item.quantity}")
        if shortages:
            raise ConflictError("Insufficient stock — " + "; ".join(shortages))
