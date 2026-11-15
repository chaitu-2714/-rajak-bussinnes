"""Supplier page: suppliers, purchase orders and goods receipts."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import PurchaseOrderStatus
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.confirmation_dialog import confirm
from app.ui.components.stat_card import StatCard
from app.ui.components.tables import DataTable
from app.ui.dialogs.sales_dialogs import ReasonDialog
from app.ui.dialogs.supply_dialogs import (
    GoodsReceiptDialog,
    PurchaseOrderDialog,
    SupplierDialog,
)
from app.ui.ui_utils import muted_label, primary_button, secondary_button, show_info
from app.utils.date_utils import format_datetime

logger = get_logger("ui.suppliers")


class SuppliersPage(QWidget):
    """Supplier directory plus purchase order and goods receipt workflow."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._suppliers = []
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
        self.card_suppliers = StatCard("Suppliers", "—", "All records")
        self.card_active = StatCard("Active", "—", "Orderable")
        self.card_open_orders = StatCard("Open purchase orders", "—", "Awaiting goods")
        self.card_received = StatCard("Received value", "—", "Goods received")
        for card in (self.card_suppliers, self.card_active, self.card_open_orders, self.card_received):
            cards.addWidget(card)
        layout.addLayout(cards)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._suppliers_tab(), "Suppliers")
        self.tabs.addTab(self._orders_tab(), "Purchase orders")
        self.tabs.addTab(self._receipts_tab(), "Goods receipts")
        layout.addWidget(self.tabs, 1)

    def _suppliers_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search suppliers…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.search_input, 2)

        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", None)
        self.status_filter.addItem("Active", True)
        self.status_filter.addItem("Inactive", False)
        self.status_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.status_filter)
        bar.addStretch(1)

        self.new_button = primary_button("New supplier")
        self.new_button.setEnabled(self._can("suppliers.create"))
        self.new_button.clicked.connect(self._new_supplier)
        bar.addWidget(self.new_button)

        self.edit_button = secondary_button("Edit")
        self.edit_button.setEnabled(self._can("suppliers.update"))
        self.edit_button.clicked.connect(self._edit_supplier)
        bar.addWidget(self.edit_button)

        self.toggle_button = secondary_button("Deactivate")
        self.toggle_button.setEnabled(self._can("suppliers.deactivate"))
        self.toggle_button.clicked.connect(self._toggle_supplier)
        bar.addWidget(self.toggle_button)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.table = DataTable(
            ["Code", "Supplier", "Contact", "Phone", "POs", "Ordered", "Received", "Status"],
            stretch_columns=(1,),
            empty_title="No suppliers yet",
            empty_body="Register a supplier to raise purchase orders.",
        )
        self.table.table.itemSelectionChanged.connect(self._show_profile)
        splitter.addWidget(self.table)

        profile = QFrame()
        profile.setObjectName("DetailPanel")
        profile_layout = QVBoxLayout(profile)
        profile_layout.setContentsMargins(18, 16, 18, 16)
        profile_layout.setSpacing(8)
        self.profile_name = QLabel("Select a supplier")
        self.profile_name.setObjectName("SectionTitle")
        profile_layout.addWidget(self.profile_name)
        self.profile_meta = QLabel("")
        self.profile_meta.setObjectName("Muted")
        self.profile_meta.setWordWrap(True)
        profile_layout.addWidget(self.profile_meta)
        self.profile_stats = QLabel("")
        self.profile_stats.setObjectName("Hint")
        self.profile_stats.setWordWrap(True)
        profile_layout.addWidget(self.profile_stats)
        profile_layout.addStretch(1)
        splitter.addWidget(profile)
        splitter.setSizes([860, 340])
        layout.addWidget(splitter, 1)
        return page

    def _orders_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.po_search = QLineEdit()
        self.po_search.setPlaceholderText("Search purchase orders…")
        self.po_search.setClearButtonEnabled(True)
        self.po_search.textChanged.connect(lambda _: self._load_orders())
        bar.addWidget(self.po_search, 2)

        self.po_status_filter = QComboBox()
        self.po_status_filter.addItem("All statuses", None)
        for status in PurchaseOrderStatus.ALL:
            self.po_status_filter.addItem(status.replace("_", " ").title(), status)
        self.po_status_filter.currentIndexChanged.connect(lambda _: self._load_orders())
        bar.addWidget(self.po_status_filter)
        bar.addStretch(1)

        self.new_po_button = primary_button("New purchase order")
        self.new_po_button.setEnabled(self._can("purchase_orders.create"))
        self.new_po_button.clicked.connect(self._new_order)
        bar.addWidget(self.new_po_button)
        layout.addLayout(bar)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addWidget(
            muted_label("Stock increases only when goods are received, never when an order is raised.")
        )
        actions.addStretch(1)

        self.approve_button = secondary_button("Approve")
        self.approve_button.setEnabled(self._can("purchase_orders.approve"))
        self.approve_button.clicked.connect(self._approve_order)
        actions.addWidget(self.approve_button)

        self.ordered_button = secondary_button("Mark ordered")
        self.ordered_button.setEnabled(self._can("purchase_orders.approve"))
        self.ordered_button.clicked.connect(self._mark_ordered)
        actions.addWidget(self.ordered_button)

        self.receive_button = secondary_button("Receive goods")
        self.receive_button.setEnabled(self._can("purchase_orders.receive"))
        self.receive_button.clicked.connect(self._receive_goods)
        actions.addWidget(self.receive_button)

        self.cancel_po_button = secondary_button("Cancel order")
        self.cancel_po_button.setEnabled(self._can("purchase_orders.approve"))
        self.cancel_po_button.clicked.connect(self._cancel_order)
        actions.addWidget(self.cancel_po_button)
        layout.addLayout(actions)

        self.orders_table = DataTable(
            ["PO number", "Supplier", "Status", "Total", "Ordered", "Received", "Created"],
            stretch_columns=(1,),
            empty_title="No purchase orders yet",
            empty_body="Raise a purchase order to buy stock from a supplier.",
        )
        self.orders_table.table.itemSelectionChanged.connect(self._update_order_actions)
        self.orders_table.table.doubleClicked.connect(lambda _: self._receive_goods())
        layout.addWidget(self.orders_table, 1)
        return page

    def _receipts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        self.receipts_table = DataTable(
            ["Receipt", "Purchase order", "Received at", "Total quantity", "Notes"],
            stretch_columns=(4,),
            empty_title="No goods receipts yet",
            empty_body="Receiving goods against a purchase order creates a receipt here.",
        )
        layout.addWidget(self.receipts_table, 1)
        return page

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._error.setVisible(False)
        self._load_suppliers()
        self._load_orders()
        self._load_receipts()

    def _load_suppliers(self) -> None:
        try:
            self._suppliers = self._context.purchasing_service.list_suppliers(
                search=self.search_input.text().strip() or None,
                is_active=self.status_filter.currentData(),
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.card_suppliers.set_value(str(len(self._suppliers)), True, "Matching filters")
        self.card_active.set_value(
            str(sum(1 for supplier in self._suppliers if supplier.is_active)), True, "Orderable"
        )

        self.table.set_rows(
            [
                [
                    supplier.supplier_code,
                    supplier.supplier_name,
                    supplier.contact_person or "—",
                    supplier.phone or "—",
                    str(supplier.order_count),
                    f"{supplier.total_order_value:,.2f}",
                    f"{supplier.received_value:,.2f}",
                    "Active" if supplier.is_active else "Inactive",
                ]
                for supplier in self._suppliers
            ],
            row_ids=[supplier.id for supplier in self._suppliers],
        )

    def _load_orders(self) -> None:
        try:
            self._orders = self._context.purchasing_service.list_purchase_orders(
                status=self.po_status_filter.currentData(),
                search=self.po_search.text().strip() or None,
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        open_orders = [
            order
            for order in self._orders
            if order.status in (PurchaseOrderStatus.APPROVED, PurchaseOrderStatus.ORDERED, PurchaseOrderStatus.PARTIALLY_RECEIVED)
        ]
        self.card_open_orders.set_value(str(len(open_orders)), True, "Awaiting goods")
        self.card_received.set_value(
            f"{sum((supplier.received_value for supplier in self._suppliers), start=0):,.2f}",
            True,
            "Goods received",
        )

        self.orders_table.set_rows(
            [
                [
                    order.purchase_order_number,
                    order.supplier_name,
                    order.status.replace("_", " ").title(),
                    f"{order.total_amount:,.2f}",
                    str(order.ordered_quantity),
                    str(order.received_quantity),
                    format_datetime(order.created_at, "%d %b %Y"),
                ]
                for order in self._orders
            ],
            row_ids=[order.id for order in self._orders],
        )
        self._update_order_actions()

    def _load_receipts(self) -> None:
        try:
            receipts = self._context.purchasing_service.list_receipts()
        except BizPilotError:
            receipts = []
        self.receipts_table.set_rows(
            [
                [
                    receipt.receipt_number,
                    receipt.purchase_order_number,
                    format_datetime(receipt.received_at),
                    str(receipt.total_quantity),
                    receipt.notes or "—",
                ]
                for receipt in receipts
            ]
        )

    def _show_profile(self) -> None:
        supplier_id = self.table.selected_id()
        supplier = next((item for item in self._suppliers if item.id == supplier_id), None)
        if supplier is None:
            return
        self.toggle_button.setText("Deactivate" if supplier.is_active else "Activate")
        self.profile_name.setText(f"{supplier.supplier_name} · {supplier.supplier_code}")
        self.profile_meta.setText(
            "\n".join(
                part
                for part in (
                    supplier.contact_person or "",
                    supplier.email or "",
                    supplier.phone or "",
                    supplier.address or "",
                    f"Tax ID: {supplier.tax_identifier}" if supplier.tax_identifier else "",
                )
                if part
            )
        )
        self.profile_stats.setText(
            f"Purchase orders {supplier.order_count} · Ordered value {supplier.total_order_value:,.2f} · "
            f"Received value {supplier.received_value:,.2f} · "
            f"Last order {format_datetime(supplier.last_order_at, '%d %b %Y')}"
        )

    def _selected_order(self):
        order_id = self.orders_table.selected_id()
        return next((order for order in self._orders if order.id == order_id), None)

    def _update_order_actions(self) -> None:
        order = self._selected_order()
        has_order = order is not None
        self.approve_button.setEnabled(
            has_order and order.status == PurchaseOrderStatus.DRAFT and self._can("purchase_orders.approve")
        )
        self.ordered_button.setEnabled(
            has_order and order.status == PurchaseOrderStatus.APPROVED and self._can("purchase_orders.approve")
        )
        self.receive_button.setEnabled(
            has_order
            and order.status in PurchaseOrderStatus.RECEIVABLE
            and self._can("purchase_orders.receive")
        )
        self.cancel_po_button.setEnabled(
            has_order
            and order.status not in (PurchaseOrderStatus.RECEIVED, PurchaseOrderStatus.CANCELLED)
            and self._can("purchase_orders.approve")
        )

    # -- actions -----------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _new_supplier(self) -> None:
        dialog = SupplierDialog(self._context, None, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The supplier was created.", "Supplier saved")

    def _edit_supplier(self) -> None:
        supplier_id = self.table.selected_id()
        supplier = next((item for item in self._suppliers if item.id == supplier_id), None)
        if supplier is None:
            self._show_error("Select a supplier to edit.")
            return
        dialog = SupplierDialog(self._context, supplier, self)
        if dialog.exec():
            self.refresh()

    def _toggle_supplier(self) -> None:
        supplier_id = self.table.selected_id()
        supplier = next((item for item in self._suppliers if item.id == supplier_id), None)
        if supplier is None:
            self._show_error("Select a supplier first.")
            return
        activating = not supplier.is_active
        if not activating and not confirm(
            self,
            title="Deactivate supplier",
            message=f"{supplier.supplier_name} will no longer be available for new purchase orders.",
            confirm_text="Deactivate",
            destructive=True,
        ):
            return
        try:
            self._context.purchasing_service.set_supplier_active(supplier.id, activating)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()

    def _new_order(self) -> None:
        if not self._suppliers:
            self._show_error("Register a supplier before raising a purchase order.")
            return
        dialog = PurchaseOrderDialog(self._context, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The purchase order was created as a draft.", "Purchase order saved")

    def _approve_order(self) -> None:
        order = self._selected_order()
        if order is None:
            self._show_error("Select a draft purchase order to approve.")
            return
        try:
            self._context.purchasing_service.approve_purchase_order(order.id)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()

    def _mark_ordered(self) -> None:
        order = self._selected_order()
        if order is None:
            self._show_error("Select an approved purchase order.")
            return
        try:
            self._context.purchasing_service.mark_ordered(order.id)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()

    def _receive_goods(self) -> None:
        order = self._selected_order()
        if order is None:
            self._show_error("Select a purchase order to receive against.")
            return
        if order.status not in PurchaseOrderStatus.RECEIVABLE:
            self._show_error(
                "Goods can only be received against an approved, ordered or partially "
                "received purchase order."
            )
            return
        dialog = GoodsReceiptDialog(self._context, order, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The goods receipt was recorded and stock updated.", "Goods received")

    def _cancel_order(self) -> None:
        order = self._selected_order()
        if order is None:
            self._show_error("Select a purchase order to cancel.")
            return
        dialog = ReasonDialog(
            "Cancel purchase order", f"Cancel {order.purchase_order_number}?", self
        )
        if not dialog.exec():
            return
        try:
            self._context.purchasing_service.cancel_purchase_order(order.id, dialog.reason())
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()
