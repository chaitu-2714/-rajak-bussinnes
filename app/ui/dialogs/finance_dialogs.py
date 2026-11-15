"""Finance dialogs: record and edit expenses."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFormLayout,
    QLineEdit,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import ExpenseCategory, PaymentMethod
from app.core.exceptions import BizPilotError
from app.schemas.finance_schema import ExpenseSummary
from app.ui.dialogs.catalog_dialogs import _BaseDialog


class ExpenseDialog(_BaseDialog):
    """Create or edit an operating expense."""

    def __init__(
        self,
        context: ApplicationContext,
        expense: ExpenseSummary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(context, "Edit expense" if expense else "Record expense", parent)
        self._expense = expense
        self.setMinimumWidth(480)

        form = QFormLayout()
        form.setSpacing(8)

        self.category_combo = QComboBox()
        for category in ExpenseCategory.ALL:
            self.category_combo.addItem(category.title(), category)
        form.addRow("Category *", self.category_combo)

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("What was this expense for?")
        form.addRow("Description *", self.description_input)

        self.vendor_input = QLineEdit()
        self.vendor_input.setPlaceholderText("Optional")
        form.addRow("Vendor", self.vendor_input)

        self.amount_input = QDoubleSpinBox()
        self.amount_input.setDecimals(2)
        self.amount_input.setMaximum(99_999_999.99)
        self.amount_input.setGroupSeparatorShown(True)
        form.addRow("Amount *", self.amount_input)

        self.method_combo = QComboBox()
        for method in PaymentMethod.ALL:
            self.method_combo.addItem(method.replace("_", " ").title(), method)
        form.addRow("Payment method", self.method_combo)

        self.date_input = QDateTimeEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDisplayFormat("dd MMM yyyy")
        self.date_input.setDateTime(QDateTime.currentDateTime())
        form.addRow("Expense date *", self.date_input)

        self._layout.addLayout(form)

        if expense:
            index = self.category_combo.findData(expense.expense_category)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
            self.description_input.setText(expense.description)
            self.vendor_input.setText(expense.vendor_name or "")
            self.amount_input.setValue(float(expense.amount))
            method_index = self.method_combo.findData(expense.payment_method)
            if method_index >= 0:
                self.method_combo.setCurrentIndex(method_index)
            self.date_input.setDateTime(QDateTime(expense.expense_date))

        self._add_buttons("Save expense")

    def _submit(self) -> None:
        self._error.setVisible(False)
        when: datetime = self.date_input.dateTime().toPython()
        payload = {
            "expense_category": self.category_combo.currentData(),
            "description": self.description_input.text().strip(),
            "vendor_name": self.vendor_input.text().strip() or None,
            "amount": f"{self.amount_input.value():.2f}",
            "payment_method": self.method_combo.currentData(),
            "expense_date": when,
        }
        try:
            if self._expense:
                self._context.finance_service.update_expense(self._expense.id, payload)
            else:
                self._context.finance_service.create_expense(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()
