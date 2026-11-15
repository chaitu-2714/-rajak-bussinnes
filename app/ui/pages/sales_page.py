"""Sales page: orders, completion, payments and invoices."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import OrderStatus
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.confirmation_dialog import confirm
from app.ui.components.stat_card import StatCard
from app.ui.components.tables import DataTable
from app.ui.dialogs.sales_dialogs import (
    InvoiceDialog,
    PaymentDialog,
    ReasonDialog,
    SalesOrderDialog,
)
from app.ui.ui_utils import muted_label, primary_button, secondary_button, show_info
from app.utils.date_utils import format_datetime

logger = get_logger("ui.sales")


class SalesPage(QWidget):
    """Order pipeline with stock-aware completion and payment capture."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._orders = []
        self.setObjectName("PageSurface")
        self._build()
        self.refresh()

    def _can(self, permission: str) -> bool:
        return bool(self._principal and self._principal.has(permission))

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)

        cards = QHBoxLayout()
        cards.setSpacing(10)
        self.card_orders = StatCard("Total orders", "—", "All statuses")
        self.card_completed = StatCard("Completed", "—", "Revenue recognised")
        self.card_pending = StatCard("Open orders", "—", "Draft + confirmed")
        self.card_value = StatCard("Total sales", "—", "Completed order value")
        self.card_average = StatCard("Average order", "—", "Per completed order")
        self.card_outstanding = StatCard("Outstanding", "—", "Unpaid invoice balance")
        for card in (
            self.card_orders,
            self.card_completed,
            self.card_pending,
            self.card_value,
            self.card_average,
            self.card_outstanding,
        ):
            cards.addWidget(card)
        layout.addLayout(cards)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by order number or customer…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.search_input, 2)

        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", None)
        for status in OrderStatus.ALL:
            self.status_filter.addItem(status.title(), status)
        self.status_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.status_filter)
        bar.addStretch(1)

        self.new_button = primary_button("New order")
        self.new_button.setEnabled(self._can("sales.create"))
        self.new_button.clicked.connect(self._new_order)
        bar.addWidget(self.new_button)

        self.confirm_button = secondary_button("Confirm")
        self.confirm_button.setEnabled(self._can("sales.create"))
        self.confirm_button.clicked.connect(self._confirm_order)
        bar.addWidget(self.confirm_button)

        self.complete_button = secondary_button("Complete sale")
        self.complete_button.setEnabled(self._can("sales.create"))
        self.complete_button.clicked.connect(self._complete_order)
        bar.addWidget(self.complete_button)

        self.cancel_button = secondary_button("Cancel order")
        self.cancel_button.setEnabled(self._can("sales.cancel"))
        self.cancel_button.clicked.connect(self._cancel_order)
        bar.addWidget(self.cancel_button)
        layout.addLayout(bar)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(
            muted_label(
                "Completing an order deducts stock, raises an invoice and records revenue in "
                "one transaction. Cancelling reverses all three."
            )
        )
        actions.addStretch(1)

        self.payment_button = secondary_button("Record payment")
        self.payment_button.setEnabled(self._can("sales.update"))
        self.payment_button.clicked.connect(self._record_payment)
        actions.addWidget(self.payment_button)

        self.invoice_button = secondary_button("View invoice")
        self.invoice_button.clicked.connect(self._view_invoice)
        actions.addWidget(self.invoice_button)

        self.export_button = secondary_button("Export CSV")
        self.export_button.setEnabled(self._can("sales.export"))
        self.export_button.clicked.connect(self._export)
        actions.addWidget(self.export_button)
        layout.addLayout(actions)

        self.table = DataTable(
            [
                "Order",
                "Date",
                "Customer",
                "Status",
                "Payment",
                "Total",
                "Paid",
                "Outstanding",
                "Invoice",
            ],
            stretch_columns=(2,),
            empty_title="No sales orders yet",
            empty_body="Create an order to sell products from your inventory.",
        )
        self.table.table.itemSelectionChanged.connect(self._update_actions)
        self.table.table.doubleClicked.connect(lambda _: self._view_invoice())
        layout.addWidget(self.table, 1)

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._error.setVisible(False)
        try:
            dashboard = self._context.sales_service.dashboard()
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.card_orders.set_value(str(dashboard.total_orders), True, f"{dashboard.cancelled_orders} cancelled")
        self.card_completed.set_value(str(dashboard.completed_orders), True, "Revenue recognised")
        self.card_pending.set_value(str(dashboard.pending_orders), True, "Draft + confirmed")
        self.card_value.set_value(f"{dashboard.total_sales_value:,.2f}", True, "Completed orders")
        self.card_average.set_value(f"{dashboard.average_order_value:,.2f}", True, "Per completed order")
        self.card_outstanding.set_value(f"{dashboard.outstanding_total:,.2f}", True, "Unpaid invoices")

        try:
            self._orders = self._context.sales_service.list_orders(
                search=self.search_input.text().strip() or None,
                status=self.status_filter.currentData(),
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.table.set_rows(
            [
                [
                    order.order_number,
                    format_datetime(order.created_at, "%d %b %Y"),
                    order.customer_name,
                    order.order_status.title(),
                    order.payment_status.replace("_", " ").title(),
                    f"{order.total_amount:,.2f}",
                    f"{order.paid_amount:,.2f}",
                    f"{order.outstanding_amount:,.2f}",
                    order.invoice_number or "—",
                ]
                for order in self._orders
            ],
            row_ids=[order.id for order in self._orders],
            sort_keys={
                0: [order.created_at for order in self._orders],
                5: [float(order.total_amount) for order in self._orders],
            },
        )
        self._update_actions()

    def _update_actions(self) -> None:
        order = self._selected_order()
        has_order = order is not None
        self.confirm_button.setEnabled(
            has_order and order.order_status == OrderStatus.DRAFT and self._can("sales.create")
        )
        self.complete_button.setEnabled(
            has_order
            and order.order_status in (OrderStatus.DRAFT, OrderStatus.CONFIRMED)
            and self._can("sales.create")
        )
        self.cancel_button.setEnabled(
            has_order and order.order_status != OrderStatus.CANCELLED and self._can("sales.cancel")
        )
        self.payment_button.setEnabled(
            has_order
            and order.invoice_id is not None
            and order.order_status == OrderStatus.COMPLETED
            and order.outstanding_amount > 0
            and self._can("sales.update")
        )
        self.invoice_button.setEnabled(has_order and order.invoice_id is not None)

    # -- actions -----------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _selected_order(self):
        order_id = self.table.selected_id()
        return next((order for order in self._orders if order.id == order_id), None)

    def _new_order(self) -> None:
        if not self._context.inventory_service.list_products(active_only=True):
            self._show_error("Add a product in Inventory before creating a sales order.")
            return
        if not self._context.customer_service.list_customers(is_active=True):
            self._show_error("Add a customer before creating a sales order.")
            return
        dialog = SalesOrderDialog(self._context, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The draft order was created.", "Order saved")

    def _confirm_order(self) -> None:
        order = self._selected_order()
        if order is None:
            self._show_error("Select a draft order to confirm.")
            return
        try:
            self._context.sales_service.confirm_order(order.id)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()

    def _complete_order(self) -> None:
        order = self._selected_order()
        if order is None:
            self._show_error("Select an order to complete.")
            return
        if not confirm(
            self,
            title="Complete sale",
            message=(
                f"Complete {order.order_number} for {order.customer_name}?\n\n"
                f"Stock will be deducted, invoice raised and {order.total_amount:,.2f} "
                "recorded as revenue."
            ),
            confirm_text="Complete sale",
        ):
            return
        try:
            result = self._context.sales_service.complete_order(order.id)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()
        show_info(
            self,
            f"Order {result.order_number} completed.\nInvoice: {result.invoice_number}",
            "Sale completed",
        )

    def _cancel_order(self) -> None:
        order = self._selected_order()
        if order is None:
            self._show_error("Select an order to cancel.")
            return
        dialog = ReasonDialog(
            "Cancel order",
            f"Cancel {order.order_number}? Stock and financial entries are reversed "
            "and the original history is preserved.",
            self,
        )
        if not dialog.exec():
            return
        try:
            self._context.sales_service.cancel_order(order.id, dialog.reason())
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()
        show_info(self, f"Order {order.order_number} was cancelled.", "Order cancelled")

    def _record_payment(self) -> None:
        order = self._selected_order()
        if order is None or order.invoice_id is None:
            self._show_error("Select a completed order with an invoice.")
            return
        try:
            invoice = self._context.sales_service.invoice(order.invoice_id)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        dialog = PaymentDialog(self._context, invoice, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The payment was recorded.", "Payment saved")

    def _view_invoice(self) -> None:
        order = self._selected_order()
        if order is None or order.invoice_id is None:
            self._show_error("This order has no invoice yet. Complete the sale first.")
            return
        try:
            invoice = self._context.sales_service.invoice(order.invoice_id)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        InvoiceDialog(self._context, invoice, self).exec()

    def _export(self) -> None:
        try:
            path = self._context.sales_service.export_sales_csv()
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        show_info(self, f"Sales export saved to:\n{path}", "Export complete")
