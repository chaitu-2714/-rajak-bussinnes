"""Sales dialogs: order builder, payment capture, invoice preview, reasons."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
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
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import PaymentMethod
from app.core.exceptions import BizPilotError
from app.database.types import to_money
from app.schemas.sales_schema import InvoiceView, SalesOrderSummary
from app.ui.dialogs.catalog_dialogs import _BaseDialog
from app.ui.ui_utils import muted_label, primary_button, secondary_button, show_error, show_info
from app.utils.formatters import format_currency
from app.utils.date_utils import format_datetime


class ReasonDialog(QDialog):
    """Ask for a short free-text reason (cancellations, reversals)."""

    def __init__(self, title: str, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("SectionTitle")
        layout.addWidget(heading)
        layout.addWidget(muted_label(message))

        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("Reason (required)")
        layout.addWidget(self.reason_input)

        self._error = QLabel("")
        self._error.setObjectName("FormError")
        self._error.setVisible(False)
        layout.addWidget(self._error)

        row = QHBoxLayout()
        row.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.reject)
        confirm = primary_button("Confirm")
        confirm.clicked.connect(self._submit)
        row.addWidget(cancel)
        row.addWidget(confirm)
        layout.addLayout(row)

    def _submit(self) -> None:
        if len(self.reason_input.text().strip()) < 3:
            self._error.setText("Enter a reason (at least 3 characters).")
            self._error.setVisible(True)
            return
        self.accept()

    def reason(self) -> str:
        return self.reason_input.text().strip()


class SalesOrderDialog(_BaseDialog):
    """Interactive order builder: multiple products, live totals."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(context, "New sales order", parent)
        self.setMinimumSize(760, 640)
        self._lines: list[dict] = []
        self._products: dict[int, object] = {}

        self._layout.addWidget(
            muted_label(
                "Prices default to the product's selling price and are snapshotted onto the "
                "order, so later price changes never alter this sale."
            )
        )

        top = QFormLayout()
        top.setSpacing(8)
        self.customer_combo = QComboBox()
        self.customer_combo.setMinimumWidth(320)
        top.addRow("Customer *", self.customer_combo)
        self._layout.addLayout(top)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.product_combo = QComboBox()
        self.product_combo.setMinimumWidth(240)
        self.product_combo.currentIndexChanged.connect(self._fill_price)
        add_row.addWidget(self.product_combo, 3)

        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 100_000)
        self.quantity_input.setPrefix("Qty ")
        add_row.addWidget(self.quantity_input)

        self.price_input = QDoubleSpinBox()
        self.price_input.setDecimals(2)
        self.price_input.setMaximum(99_999_999.99)
        self.price_input.setPrefix("Rate ")
        add_row.addWidget(self.price_input)

        self.discount_input = QDoubleSpinBox()
        self.discount_input.setDecimals(2)
        self.discount_input.setMaximum(99_999_999.99)
        self.discount_input.setPrefix("Disc ")
        add_row.addWidget(self.discount_input)

        self.tax_input = QDoubleSpinBox()
        self.tax_input.setDecimals(2)
        self.tax_input.setMaximum(99_999_999.99)
        self.tax_input.setPrefix("Tax ")
        add_row.addWidget(self.tax_input)

        add_button = secondary_button("Add line")
        add_button.clicked.connect(self._add_line)
        add_row.addWidget(add_button)
        self._layout.addLayout(add_row)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Product", "Qty", "Rate", "Discount", "Tax", "Line total"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._layout.addWidget(self.table, 1)

        line_tools = QHBoxLayout()
        remove_button = secondary_button("Remove selected line")
        remove_button.clicked.connect(self._remove_line)
        line_tools.addWidget(remove_button)
        line_tools.addStretch(1)
        self._layout.addLayout(line_tools)

        bottom = QFormLayout()
        self.order_discount_input = QDoubleSpinBox()
        self.order_discount_input.setDecimals(2)
        self.order_discount_input.setMaximum(99_999_999.99)
        self.order_discount_input.setPrefix("Discount ")
        self.order_discount_input.valueChanged.connect(self._refresh_totals)
        bottom.addRow("Order discount", self.order_discount_input)

        self.notes_input = QPlainTextEdit()
        self.notes_input.setMaximumHeight(56)
        bottom.addRow("Notes", self.notes_input)
        self._layout.addLayout(bottom)

        self.totals_label = QLabel("")
        self.totals_label.setObjectName("SectionTitle")
        self._layout.addWidget(self.totals_label)

        self._load_customers()
        self._load_products()
        self._refresh_totals()
        self._add_buttons("Save draft order")

    # -- data --------------------------------------------------------------
    def _load_customers(self) -> None:
        try:
            for customer in self._context.customer_service.list_customers(is_active=True):
                self.customer_combo.addItem(
                    f"{customer.full_name} ({customer.customer_code})", customer.id
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
            self.product_combo.addItem(
                f"{product.product_name} ({product.sku}) · {product.selling_price:.2f}",
                product.id,
            )
        self._fill_price()

    def _fill_price(self) -> None:
        product = self._products.get(self.product_combo.currentData())
        if product is not None:
            self.price_input.setValue(float(product.selling_price))

    def _add_line(self) -> None:
        product = self._products.get(self.product_combo.currentData())
        if product is None:
            return
        quantity = self.quantity_input.value()
        rate = to_money(self.price_input.value())
        discount = to_money(self.discount_input.value())
        tax = to_money(self.tax_input.value())
        gross = to_money(rate * quantity)
        if discount > gross:
            show_error(self, "The discount cannot exceed the line value.", "Check the line")
            return
        line_total = to_money(gross - discount + tax)
        self._lines.append(
            {
                "product_id": product.id,
                "product_name": product.product_name,
                "quantity": quantity,
                "unit_price": rate,
                "discount_amount": discount,
                "tax_amount": tax,
                "line_total": line_total,
            }
        )
        self._render_lines()
        self.discount_input.setValue(0.0)
        self.tax_input.setValue(0.0)
        self.quantity_input.setValue(1)

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
                str(line["quantity"]),
                f"{line['unit_price']:.2f}",
                f"{line['discount_amount']:.2f}",
                f"{line['tax_amount']:.2f}",
                f"{line['line_total']:.2f}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(index, column, item)
        self._refresh_totals()

    def _refresh_totals(self) -> None:
        subtotal = sum((to_money(line["unit_price"] * line["quantity"]) for line in self._lines), Decimal("0.00"))
        discount = sum((line["discount_amount"] for line in self._lines), Decimal("0.00"))
        tax = sum((line["tax_amount"] for line in self._lines), Decimal("0.00"))
        order_discount = to_money(self.order_discount_input.value())
        total = to_money(subtotal - discount - order_discount + tax)
        self.totals_label.setText(
            f"Subtotal {subtotal:,.2f}   ·   Discount {discount + order_discount:,.2f}   ·   "
            f"Tax {tax:,.2f}   ·   Total {total:,.2f}"
        )

    def _submit(self) -> None:
        self._error.setVisible(False)
        if self.customer_combo.currentData() is None:
            self._show_error("Select a customer.")
            return
        if not self._lines:
            self._show_error("Add at least one product line.")
            return
        payload = {
            "customer_id": self.customer_combo.currentData(),
            "items": [
                {
                    "product_id": line["product_id"],
                    "quantity": line["quantity"],
                    "unit_price": str(line["unit_price"]),
                    "discount_amount": str(line["discount_amount"]),
                    "tax_amount": str(line["tax_amount"]),
                }
                for line in self._lines
            ],
            "discount_amount": f"{self.order_discount_input.value():.2f}",
            "notes": self.notes_input.toPlainText().strip() or None,
        }
        try:
            self._context.sales_service.create_order(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()


class PaymentDialog(_BaseDialog):
    """Record a full or partial payment against an invoice."""

    def __init__(
        self, context: ApplicationContext, invoice: InvoiceView, parent: QWidget | None = None
    ) -> None:
        super().__init__(context, "Record payment", parent)
        self._invoice = invoice
        self.setMinimumWidth(460)

        self._layout.addWidget(
            muted_label(
                f"Invoice {invoice.invoice_number} · {invoice.customer_name}\n"
                f"Total {invoice.total_amount:,.2f} · Paid {invoice.paid_amount:,.2f} · "
                f"Outstanding {invoice.outstanding_amount:,.2f}"
            )
        )

        form = QFormLayout()
        form.setSpacing(8)
        self.amount_input = QDoubleSpinBox()
        self.amount_input.setDecimals(2)
        self.amount_input.setMaximum(float(invoice.outstanding_amount))
        self.amount_input.setValue(float(invoice.outstanding_amount))
        self.amount_input.setGroupSeparatorShown(True)
        form.addRow("Amount *", self.amount_input)

        self.method_combo = QComboBox()
        for method in PaymentMethod.ALL:
            self.method_combo.addItem(method.replace("_", " ").title(), method)
        form.addRow("Method", self.method_combo)

        self.reference_input = QLineEdit()
        self.reference_input.setPlaceholderText("UPI ref / cheque no. (optional)")
        form.addRow("Reference", self.reference_input)
        self._layout.addLayout(form)

        self._add_buttons("Record payment")

    def _submit(self) -> None:
        self._error.setVisible(False)
        payload = {
            "invoice_id": self._invoice.id,
            "amount": f"{self.amount_input.value():.2f}",
            "payment_method": self.method_combo.currentData(),
            "payment_reference": self.reference_input.text().strip() or None,
        }
        try:
            self._context.sales_service.record_payment(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()


class InvoiceDialog(QDialog):
    """Read-only invoice preview with PDF export."""

    def __init__(
        self, context: ApplicationContext, invoice: InvoiceView, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._context = context
        self._invoice = invoice
        self.setWindowTitle(f"Invoice {invoice.invoice_number}")
        self.setModal(True)
        self.setMinimumSize(620, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(10)

        self.viewer = QTextBrowser()
        self.viewer.setHtml(self._render_html())
        layout.addWidget(self.viewer, 1)

        row = QHBoxLayout()
        row.addStretch(1)
        close = secondary_button("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        self.save_button = primary_button("Save PDF")
        self.save_button.clicked.connect(self._save_pdf)
        row.addWidget(self.save_button)
        layout.addLayout(row)

    def _render_html(self) -> str:
        invoice = self._invoice
        rows = "".join(
            f"<tr><td>{line.product_name}</td><td align='right'>{line.quantity}</td>"
            f"<td align='right'>{line.unit_price:,.2f}</td>"
            f"<td align='right'>{line.discount_amount:,.2f}</td>"
            f"<td align='right'>{line.tax_amount:,.2f}</td>"
            f"<td align='right'>{line.line_total:,.2f}</td></tr>"
            for line in invoice.lines
        )
        payments = "".join(
            f"<li>{format_datetime(payment['date'])} · {payment['amount']:,.2f} · "
            f"{payment['method']}</li>"
            for payment in invoice.payments
        ) or "<li>No payments recorded</li>"
        return f"""
        <h2 style="margin-bottom:0">{invoice.invoice_number}</h2>
        <p style="color:#64748B;margin-top:2px">
          Order {invoice.order_number} · Issued {format_datetime(invoice.invoice_date)}
          {f" · Due {format_datetime(invoice.due_date)}" if invoice.due_date else ""}
        </p>
        <p><b>{invoice.customer_name}</b><br/>
        {invoice.customer_email or ""}<br/>{invoice.customer_phone or ""}</p>
        <table width="100%" cellspacing="0" cellpadding="6" border="1"
               style="border-collapse:collapse;border-color:#E2E8F0">
          <tr style="background:#F1F5F9"><th align="left">Product</th><th>Qty</th><th>Rate</th>
          <th>Discount</th><th>Tax</th><th>Total</th></tr>
          {rows}
        </table>
        <p align="right" style="margin-top:10px">
          Subtotal {invoice.subtotal:,.2f}<br/>
          Discount {invoice.discount_amount:,.2f}<br/>
          Tax {invoice.tax_amount:,.2f}<br/>
          <b>Total {invoice.total_amount:,.2f}</b><br/>
          Paid {invoice.paid_amount:,.2f}<br/>
          <b>Outstanding {invoice.outstanding_amount:,.2f}</b>
        </p>
        <p><b>Status:</b> {invoice.status}</p>
        <p><b>Payments</b></p><ul>{payments}</ul>
        """

    def _save_pdf(self) -> None:
        try:
            business = self._context.business_service.get_business()
            path = self._context.export_service.write_invoice_pdf(
                invoice=self._invoice, business=business
            )
        except BizPilotError as exc:
            show_error(self, exc.user_message)
            return
        show_info(self, f"Invoice PDF saved to:\n{path}", "Invoice exported")
