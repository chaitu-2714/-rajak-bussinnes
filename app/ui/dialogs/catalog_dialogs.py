"""Product, category and stock adjustment dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import MovementType
from app.core.exceptions import BizPilotError
from app.schemas.catalog_schema import CategorySummary, ProductSummary
from app.ui.ui_utils import (
    muted_label,
    primary_button,
    secondary_button,
)


def _money_box() -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(2)
    box.setMaximum(99_999_999.99)
    box.setSingleStep(10.0)
    box.setGroupSeparatorShown(True)
    return box


class _BaseDialog(QDialog):
    def __init__(self, context: ApplicationContext, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.setWindowTitle(title)
        self.setModal(True)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(24, 22, 24, 20)
        self._layout.setSpacing(10)
        self._error = QLabel("")
        self._error.setObjectName("FormError")
        self._error.setWordWrap(True)
        self._error.setVisible(False)

    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _add_buttons(self, save_text: str = "Save") -> None:
        self._layout.addWidget(self._error)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.reject)
        save = primary_button(save_text)
        save.clicked.connect(self._submit)
        row.addWidget(cancel)
        row.addWidget(save)
        self._layout.addLayout(row)

    def _submit(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError


class CategoryDialog(_BaseDialog):
    """Create or edit a product category."""

    def __init__(
        self,
        context: ApplicationContext,
        category: CategorySummary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(context, "Edit category" if category else "New category", parent)
        self._category = category
        self.setMinimumWidth(420)

        self._layout.addWidget(muted_label("Categories group products in the catalogue."))
        form = QFormLayout()
        form.setSpacing(8)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("e.g. Beverages")
        form.addRow("Category name *", self.name_input)

        self.description_input = QLineEdit()
        self.description_input.setPlaceholderText("Optional")
        form.addRow("Description", self.description_input)

        self.active_check = QCheckBox("Category is active")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        self._layout.addLayout(form)

        if category:
            self.name_input.setText(category.category_name)
            self.description_input.setText(category.description or "")
            self.active_check.setChecked(category.is_active)
        self._add_buttons("Save category")

    def _submit(self) -> None:
        self._error.setVisible(False)
        payload = {
            "category_name": self.name_input.text().strip(),
            "description": self.description_input.text().strip() or None,
            "is_active": self.active_check.isChecked(),
        }
        try:
            if self._category:
                self._context.inventory_service.update_category(self._category.id, payload)
            else:
                self._context.inventory_service.create_category(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()


class ProductDialog(_BaseDialog):
    """Create or edit a product."""

    def __init__(
        self,
        context: ApplicationContext,
        product: ProductSummary | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(context, "Edit product" if product else "New product", parent)
        self._product = product
        self.setMinimumWidth(520)

        form = QFormLayout()
        form.setSpacing(8)

        sku_row = QHBoxLayout()
        self.sku_input = QLineEdit()
        self.sku_input.setPlaceholderText("Leave blank to generate")
        sku_row.addWidget(self.sku_input, 1)
        generate = secondary_button("Generate")
        generate.clicked.connect(self._generate_sku)
        sku_row.addWidget(generate)
        form.addRow("SKU", sku_row)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Product name")
        form.addRow("Product name *", self.name_input)

        self.category_combo = QComboBox()
        form.addRow("Category", self.category_combo)

        self.unit_input = QLineEdit("pcs")
        form.addRow("Unit", self.unit_input)

        self.cost_input = _money_box()
        form.addRow("Cost price", self.cost_input)

        self.price_input = _money_box()
        form.addRow("Selling price", self.price_input)

        self.minimum_input = QSpinBox()
        self.minimum_input.setMaximum(1_000_000)
        self.minimum_input.setToolTip("Low-stock alert threshold")
        form.addRow("Minimum stock", self.minimum_input)

        self.barcode_input = QLineEdit()
        self.barcode_input.setPlaceholderText("Optional")
        form.addRow("Barcode", self.barcode_input)

        self.description_input = QPlainTextEdit()
        self.description_input.setMaximumHeight(60)
        form.addRow("Description", self.description_input)

        self.active_check = QCheckBox("Product is active")
        self.active_check.setChecked(True)
        form.addRow("", self.active_check)
        self._layout.addLayout(form)

        self._load_categories()
        if product:
            self.sku_input.setText(product.sku)
            self.name_input.setText(product.product_name)
            index = self.category_combo.findData(product.category_id)
            if index >= 0:
                self.category_combo.setCurrentIndex(index)
            self.unit_input.setText(product.unit)
            self.cost_input.setValue(float(product.cost_price))
            self.price_input.setValue(float(product.selling_price))
            self.minimum_input.setValue(product.minimum_stock)
            self.barcode_input.setText(product.barcode or "")
            self.active_check.setChecked(product.is_active)
        else:
            self._generate_sku()

        self._add_buttons("Save product")

    def _load_categories(self) -> None:
        self.category_combo.addItem("Uncategorised", None)
        try:
            for category in self._context.inventory_service.list_categories():
                self.category_combo.addItem(category.category_name, category.id)
        except BizPilotError:
            pass

    def _generate_sku(self) -> None:
        try:
            self.sku_input.setText(self._context.inventory_service.generate_sku())
        except BizPilotError:
            pass

    def _submit(self) -> None:
        self._error.setVisible(False)
        payload = {
            "sku": self.sku_input.text().strip() or None,
            "product_name": self.name_input.text().strip(),
            "category_id": self.category_combo.currentData(),
            "description": self.description_input.toPlainText().strip() or None,
            "unit": self.unit_input.text().strip() or "pcs",
            "cost_price": f"{self.cost_input.value():.2f}",
            "selling_price": f"{self.price_input.value():.2f}",
            "minimum_stock": self.minimum_input.value(),
            "barcode": self.barcode_input.text().strip() or None,
            "is_active": self.active_check.isChecked(),
        }
        try:
            if self._product:
                self._context.inventory_service.update_product(self._product.id, payload)
            else:
                self._context.inventory_service.create_product(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()


class StockAdjustmentDialog(_BaseDialog):
    """Record opening stock, an addition, a reduction or damaged stock."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(context, "Stock adjustment", parent)
        self.setMinimumWidth(460)

        self._layout.addWidget(
            muted_label(
                "Every adjustment writes a stock movement so the ledger stays auditable. "
                "Stock can never go negative."
            )
        )

        form = QFormLayout()
        form.setSpacing(8)

        self.product_combo = QComboBox()
        self.product_combo.setMinimumWidth(300)
        form.addRow("Product *", self.product_combo)

        self.type_combo = QComboBox()
        for label, value in (
            ("Opening stock", MovementType.OPENING_STOCK),
            ("Adjustment", MovementType.ADJUSTMENT),
            ("Damaged stock", MovementType.DAMAGE),
            ("Customer return", MovementType.RETURN),
        ):
            self.type_combo.addItem(label, value)
        self.type_combo.currentIndexChanged.connect(self._sync_direction)
        form.addRow("Movement type *", self.type_combo)

        self.direction_combo = QComboBox()
        self.direction_combo.addItem("Add to stock", 1)
        self.direction_combo.addItem("Remove from stock", -1)
        form.addRow("Direction *", self.direction_combo)

        self.quantity_input = QSpinBox()
        self.quantity_input.setRange(1, 1_000_000)
        form.addRow("Quantity *", self.quantity_input)

        self.reason_input = QLineEdit()
        self.reason_input.setPlaceholderText("Why is the stock changing?")
        form.addRow("Reason *", self.reason_input)

        self._layout.addLayout(form)
        self._load_products()
        self._sync_direction()
        self._add_buttons("Record adjustment")

    def _load_products(self) -> None:
        try:
            for product in self._context.inventory_service.list_products(active_only=True):
                self.product_combo.addItem(
                    f"{product.product_name} ({product.sku})", product.id
                )
        except BizPilotError:
            pass

    def _sync_direction(self) -> None:
        is_damage = self.type_combo.currentData() == MovementType.DAMAGE
        self.direction_combo.setCurrentIndex(1 if is_damage else 0)
        self.direction_combo.setEnabled(not is_damage)

    def _submit(self) -> None:
        self._error.setVisible(False)
        product_id = self.product_combo.currentData()
        if product_id is None:
            self._show_error("Add a product before adjusting stock.")
            return
        payload = {
            "product_id": product_id,
            "quantity": self.quantity_input.value(),
            "movement_type": self.type_combo.currentData(),
            "reason": self.reason_input.text().strip(),
            "direction": self.direction_combo.currentData(),
        }
        try:
            self._context.inventory_service.adjust_stock(payload)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.accept()
