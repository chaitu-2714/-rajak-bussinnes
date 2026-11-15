"""Customer and follow-up dialogs."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDate, QDateTime, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import CustomerType
from app.core.exceptions import BizPilotError
from app.schemas.crm_schema import CustomerSummary
from app.ui.dialogs.catalog_dialogs import _BaseDialog
from app.ui.ui_utils import muted_label, primary_button, secondary_button


class CustomerDialog(_BaseDialog):
    """Create or edit a customer."""

    def __init__(
        self,
        context: ApplicationContext,
        customer: CustomerSummary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(context, "Edit customer" if customer else "New customer", parent)
        self._customer = customer
        self.setMinimumWidth(520)

        form = QFormLayout()
        form.setSpacing(8)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Customer name")
        form.addRow("Full name *", self.name_input)

        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("Leave blank to generate (CUST-0001)")
        form.addRow("Customer code", self.code_input)

        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("Optional")
        form.addRow("Email", self.email_input)

        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("Optional")
        form.addRow("Phone", self.phone_input)

        self.city_input = QLineEdit()
        form.addRow("City", self.city_input)

        self.type_combo = QComboBox()
        for value in CustomerType.ALL:
            self.type_combo.addItem(value.title(), value)
        form.addRow("Customer type", self.type_combo)

        self.address_input = QPlainTextEdit()
        self.address_input.setMaximumHeight(60)
        form.addRow("Address", self.address_input)

        self.notes_input = QPlainTextEdit()
        self.notes_input.setMaximumHeight(60)
        form.addRow("Notes", self.notes_input)

        self.active_check = QCheckBox("Customer is active")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        self._layout.addLayout(form)

        if customer:
            self.name_input.setText(customer.full_name)
            self.code_input.setText(customer.customer_code)
            self.email_input.setText(customer.email or "")
            self.phone_input.setText(customer.phone or "")
            self.city_input.setText(customer.city or "")
            index = self.type_combo.findData(customer.customer_type)
            if index >= 0:
                self.type_combo.setCurrentIndex(index)
            self.active_check.setChecked(customer.is_active)
        self._add_buttons("Save customer")

    def _submit(self) -> None:
        self._error.setVisible(False)
        payload = {
            "customer_code": self.code_input.text().strip() or None,
            "full_name": self.name_input.text().strip(),
            "email": self.email_input.text().strip() or None,
            "phone": self.phone_input.text().strip() or None,
            "address": self.address_input.toPlainText().strip() or None,
            "city": self.city_input.text().strip() or None,
            "customer_type": self.type_combo.currentData(),
            "notes": self.notes_input.toPlainText().strip() or None,
            "is_active": self.active_check.isChecked(),
        }
        try:
            if self._customer:
                self._context.customer_service.update_customer(self._customer.id, payload)
            else:
                self._context.customer_service.create_customer(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()


class FollowUpDialog(_BaseDialog):
    """Create a local follow-up reminder."""

    def __init__(
        self,
        context: ApplicationContext,
        customer_id: int | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(context, "New follow-up", parent)
        self.setMinimumWidth(460)

        self._layout.addWidget(
            muted_label(
                "Reminders are stored locally and shown on the customer profile. "
                "No email is sent in Phase 2."
            )
        )
        form = QFormLayout()
        form.setSpacing(8)

        self.customer_combo = QComboBox()
        form.addRow("Customer *", self.customer_combo)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("e.g. Call about repeat order")
        form.addRow("Title *", self.title_input)

        self.due_input = QDateTimeEdit()
        self.due_input.setCalendarPopup(True)
        self.due_input.setDisplayFormat("dd MMM yyyy, hh:mm AP")
        self.due_input.setDateTime(QDateTime.currentDateTime().addDays(3))
        form.addRow("Due date *", self.due_input)

        self.notes_input = QPlainTextEdit()
        self.notes_input.setMaximumHeight(70)
        form.addRow("Notes", self.notes_input)

        self._layout.addLayout(form)
        self._load_customers(customer_id)
        self._add_buttons("Create reminder")

    def _load_customers(self, preselected: int | None) -> None:
        try:
            customers = self._context.customer_service.list_customers(is_active=True)
        except BizPilotError:
            customers = []
        for customer in customers:
            self.customer_combo.addItem(f"{customer.full_name} ({customer.customer_code})", customer.id)
        if preselected is not None:
            index = self.customer_combo.findData(preselected)
            if index >= 0:
                self.customer_combo.setCurrentIndex(index)

    def _submit(self) -> None:
        self._error.setVisible(False)
        customer_id = self.customer_combo.currentData()
        if customer_id is None:
            self._show_error("Add a customer first.")
            return
        due: datetime = self.due_input.dateTime().toPython()
        payload = {
            "customer_id": customer_id,
            "title": self.title_input.text().strip(),
            "notes": self.notes_input.toPlainText().strip() or None,
            "due_date": due,
            "assigned_to": None,
        }
        try:
            self._context.customer_service.create_follow_up(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()
