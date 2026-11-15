"""Supplier, purchase order and goods receipt dialogs."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.database.types import to_money
from app.schemas.purchasing_schema import PurchaseOrderSummary, SupplierSummary
from app.ui.dialogs.catalog_dialogs import _BaseDialog
from app.ui.ui_utils import muted_label, show_error


class SupplierDialog(_BaseDialog):
    """Create or edit a supplier."""

    def __init__(
        self,
        context: ApplicationContext,
        supplier: SupplierSummary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(context, "Edit supplier" if supplier else "New supplier", parent)
        self._supplier = supplier
        self.setMinimumWidth(500)

        form = QFormLayout()
        form.setSpacing(8)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Supplier business name")
        form.addRow("Supplier name *", self.name_input)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Leave blank to generate (SUP-0001)")
        form.addRow("Supplier code", self.code_input)

        self.contact_input = QLineEdit()
        form.addRow("Contact person", self.contact_input)

        self.email_input = QLineEdit()
        form.addRow("Email", self.email_input)

        self.phone_input = QLineEdit()
        form.addRow("Phone", self.phone_input)

        self.tax_input = QLineEdit()
        self.tax_input.setPlaceholderText("GSTIN / VAT number")
        form.addRow("Tax identifier", self.tax_input)

        self.address_input = QPlainTextEdit()
        self.address_input.setMaximumHeight(60)
        form.addRow("Address", self.address_input)

        self.active_check = QCheckBox("Supplier is active")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        self._layout.addLayout(form)

        if supplier:
            self.name_input.setText(supplier.supplier_name)
            self.code_input.setText(supplier.supplier_code)
            self.contact_input.setText(supplier.contact_person or "")
            self.email_input.setText(supplier.email or "")
            self.phone_input.setText(supplier.phone or "")
            self.tax_input.setText(supplier.tax_identifier or "")
            self.address_input.setPlainText(supplier.address or "")
            self.active_check.setChecked(supplier.is_active)
        self._add_buttons("Save supplier")

    def _submit(self) -> None:
        self._error.setVisible(False)
        payload = {
            "supplier_code": self.code_input.text().strip() or None,
            "supplier_name": self.name_input.text().strip(),
            "contact_person": self.contact_input.text().strip() or None,
            "email": self.email_input.text().strip() or None,
            "phone": self.phone_input.text().strip() or None,
            "address": self.address_input.toPlainText().strip() or None,
            "tax_identifier": self.tax_input.text().strip() or None,
            "is_active": self.active_check.isChecked(),
        }
        try:
            if self._supplier:
                self._context.purchasing_service.update_supplier(self._supplier.id, payload)
            else:
                self._context.purchasing_service.create_supplier(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()


class PurchaseOrderDialog(_BaseDialog):
    """Raise a purchase order with one or more products."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(context, "New purchase order", parent)
        self.setMinimumSize(720, 600)
        self._lines: list[dict] = []
        self._products: dict[int, object] = {}

        self._layout.addWidget(
            muted_label(
                "Stock is not increased here. Inventory only changes when goods are "
                "received against this order."
            )
        )

        top = QFormLayout()
        self.supplier_combo = QComboBox()
        self.supplier_combo.setMinimumWidth(320)
        top.addRow("Supplier *", self.supplier_combo)
        self._layout.addLayout(top)

        add_row = QHBoxLayout()
        self.product_combo = QComboBox()
        self.product_combo.setMinimumWidth(260)
        self.product_combo.currentIndexChanged.connect(self._fill_cost)
        add_row.addWidget(self.product_combo, 3)

        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 100_000)
        self.quantity_input.setPrefix("Qty ")
        add_row.addWidget(self.quantity_input)

        self.cost_input = QDoubleSpinBox()
        self.cost_input.setDecimals(2)
        self.cost_input.setMaximum(99_999_999.99)
        self.cost_input.setPrefix("Unit cost ")
        add_row.addWidget(self.cost_input)

        add_button = QLabel()
        from app.ui.ui_utils import secondary_button

        add_button = secondary_button("Add line")
        add_button.clicked.connect(self._add_line)
        add_row.addWidget(add_button)
        self._layout.addLayout(add_row)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Product", "Qty", "Unit cost", "Line total"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._layout.addWidget(self.table, 1)

        tools = QHBoxLayout()
        remove = secondary_button("Remove selected line")
        remove.clicked.connect(self._remove_line)
        tools.addWidget(remove)
        tools.addStretch(1)
        self._layout.addLayout(tools)

        bottom = QFormLayout()
        self.tax_input = QDoubleSpinBox()
        self.tax_input.setDecimals(2)
        self.tax_input.setMaximum(99_999_999.99)
        self.tax_input.setPrefix("Tax ")
        self.tax_input.valueChanged.connect(self._refresh_totals)
        bottom.addRow("Tax", self.tax_input)

        self.delivery_input = QDateTimeEdit()
        self.delivery_input.setCalendarPopup(True)
        self.delivery_input.setDisplayFormat("dd MMM yyyy")
        self.delivery_input.setDateTime(QDateTime.currentDateTime().addDays(7))
        bottom.addRow("Expected delivery", self.delivery_input)

        self.notes_input = QPlainTextEdit()
        self.notes_input.setMaximumHeight(50)
        bottom.addRow("Notes", self.notes_input)
        self._layout.addLayout(bottom)

        self.totals_label = QLabel("")
        self.totals_label.setObjectName("SectionTitle")
        self._layout.addWidget(self.totals_label)

        self._load_suppliers()
        self._load_products()
        self._refresh_totals()
        self._add_buttons("Create purchase order")

    def _load_suppliers(self) -> None:
        try:
            for supplier in self._context.purchasing_service.list_suppliers(is_active=True):
                self.supplier_combo.addItem(
                    f"{supplier.supplier_name} ({supplier.supplier_code})", supplier.id
                )
        except BizPilotError:
            pass

    def _load_products(self) -> None:
        try:
            products = self._context.inventory_service.list_products(active_only=True)
        except BizPilotError:
            products = []
        for product in products:
            self._products[product.id] = product
            self.product_combo.addItem(f"{product.product_name} ({product.sku})", product.id)
        self._fill_cost()

    def _fill_cost(self) -> None:
        product = self._products.get(self.product_combo.currentData())
        if product is not None:
            self.cost_input.setValue(float(product.cost_price))

    def _add_line(self) -> None:
        product = self._products.get(self.product_combo.currentData())
        if product is None:
            return
        quantity = self.quantity_input.value()
        unit_cost = to_money(self.cost_input.value())
        self._lines.append(
            {
                "product_id": product.id,
                "product_name": product.product_name,
                "ordered_quantity": quantity,
                "unit_cost": unit_cost,
                "line_total": to_money(unit_cost * quantity),
            }
        )
        self._render_lines()

    def _remove_line(self) -> None:
        row = self.table.currentRow()
        if 0 <= row < len(self._lines):
            del self._lines[row]
            self._render_lines()

    def _render_lines(self) -> None:
        self.table.setRowCount(0)
        for index, line in enumerate(self._lines):
            self.table.insertRow(index)
            values = (
                line["product_name"],
                str(line["ordered_quantity"]),
                f"{line['unit_cost']:.2f}",
                f"{line['line_total']:.2f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(index, column, item)
        self._refresh_totals()

    def _refresh_totals(self) -> None:
        subtotal = sum((line["line_total"] for line in self._lines), Decimal("0.00"))
        tax = to_money(self.tax_input.value())
        self.totals_label.setText(
            f"Subtotal {subtotal:,.2f}   ·   Tax {tax:,.2f}   ·   Total {to_money(subtotal + tax):,.2f}"
        )

    def _submit(self) -> None:
        self._error.setVisible(False)
        if self.supplier_combo.currentData() is None:
            self._show_error("Select a supplier.")
            return
        if not self._lines:
            self._show_error("Add at least one product line.")
            return
        payload = {
            "supplier_id": self.supplier_combo.currentData(),
            "items": [
                {
                    "product_id": line["product_id"],
                    "ordered_quantity": line["ordered_quantity"],
                    "unit_cost": str(line["unit_cost"]),
                }
                for line in self._lines
            ],
            "tax_amount": f"{self.tax_input.value():.2f}",
            "expected_delivery_date": self.delivery_input.dateTime().toPython(),
            "notes": self.notes_input.toPlainText().strip() or None,
        }
        try:
            self._context.purchasing_service.create_purchase_order(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()


class GoodsReceiptDialog(_BaseDialog):
    """Receive all or part of a purchase order."""

    def __init__(
        self, context: ApplicationContext, order: PurchaseOrderSummary, parent: QWidget | None = None
    ) -> None:
        super().__init__(context, "Receive goods", parent)
        self._order = order
        self.setMinimumSize(620, 520)
        self._spins: dict[int, QSpinBox] = {}

        self._layout.addWidget(
            muted_label(
                f"{order.purchase_order_number} · {order.supplier_name} · status {order.status}\n"
                "Enter the quantity actually delivered. Stock increases only for what you receive."
            )
        )

        self.table = QTableWidget(len(order.lines), 4)
        self.table.setHorizontalHeaderLabels(["Product", "Ordered", "Already received", "Receive now"])
        self.table.verticalHeader().setVisible(False)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for row, line in enumerate(order.lines):
            self.table.setItem(row, 0, QTableWidgetItem(f"{line.product_name} ({line.sku})"))
            self.table.setItem(row, 1, QTableWidgetItem(str(line.ordered_quantity)))
            self.table.setItem(row, 2, QTableWidgetItem(str(line.received_quantity)))
            spin = QSpinBox()
            spin.setRange(0, max(line.outstanding_quantity, 0))
            spin.setValue(max(line.outstanding_quantity, 0))
            self.table.setCellWidget(row, 3, spin)
            self._spins[line.id] = spin
        self._layout.addWidget(self.table, 1)

        form = QFormLayout()
        self.notes_input = QPlainTextEdit()
        self.notes_input.setMaximumHeight(60)
        form.addRow("Notes", self.notes_input)
        self._layout.addLayout(form)

        self._add_buttons("Record receipt")

    def _submit(self) -> None:
        self._error.setVisible(False)
        items = [
            {"purchase_order_item_id": item_id, "quantity": spin.value()}
            for item_id, spin in self._spins.items()
            if spin.value() > 0
        ]
        if not items:
            self._show_error("Enter a quantity for at least one line.")
            return
        payload = {
            "purchase_order_id": self._order.id,
            "items": items,
            "notes": self.notes_input.toPlainText().strip() or None,
        }
        try:
            self._context.purchasing_service.receive_goods(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()
