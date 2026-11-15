"""Inventory page: products, stock levels, low-stock alerts, movements."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.stat_card import StatCard
from app.ui.components.tables import DataTable
from app.ui.dialogs.catalog_dialogs import (
    CategoryDialog,
    ProductDialog,
    StockAdjustmentDialog,
)
from app.ui.ui_utils import (
    muted_label,
    primary_button,
    secondary_button,
    show_info,
)
from app.utils.date_utils import format_datetime

logger = get_logger("ui.inventory")


class InventoryPage(QWidget):
    """Catalogue and stock management."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._products = []
        self._stock = []
        self._categories = []
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
        self.card_products = StatCard("Total products", "—", "In the catalogue")
        self.card_quantity = StatCard("Stock on hand", "—", "Units across products")
        self.card_value = StatCard("Stock value", "—", "At recorded cost")
        self.card_low = StatCard("Low stock", "—", "At or below minimum")
        self.card_out = StatCard("Out of stock", "—", "Zero available")
        for card in (self.card_products, self.card_quantity, self.card_value, self.card_low, self.card_out):
            cards.addWidget(card)
        layout.addLayout(cards)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._products_tab(), "Products")
        self.tabs.addTab(self._stock_tab(), "Stock levels")
        self.tabs.addTab(self._low_stock_tab(), "Low stock")
        self.tabs.addTab(self._movements_tab(), "Stock movements")
        self.tabs.addTab(self._categories_tab(), "Categories")
        layout.addWidget(self.tabs, 1)

    def _products_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.product_search = QLineEdit()
        self.product_search.setPlaceholderText("Search products by name, SKU or barcode…")
        self.product_search.setClearButtonEnabled(True)
        self.product_search.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.product_search, 2)

        self.product_category_filter = QComboBox()
        self.product_category_filter.setMinimumWidth(150)
        self.product_category_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.product_category_filter)
        bar.addStretch(1)

        self.new_product_button = primary_button("New product")
        self.new_product_button.setEnabled(self._can("inventory.create"))
        self.new_product_button.clicked.connect(self._new_product)
        bar.addWidget(self.new_product_button)

        self.edit_product_button = secondary_button("Edit")
        self.edit_product_button.setEnabled(self._can("inventory.update"))
        self.edit_product_button.clicked.connect(self._edit_product)
        bar.addWidget(self.edit_product_button)

        self.adjust_button = secondary_button("Adjust stock")
        self.adjust_button.setEnabled(self._can("inventory.adjust"))
        self.adjust_button.clicked.connect(self._adjust_stock)
        bar.addWidget(self.adjust_button)

        self.export_button = secondary_button("Export CSV")
        self.export_button.setEnabled(self._can("inventory.export"))
        self.export_button.clicked.connect(self._export)
        bar.addWidget(self.export_button)
        layout.addLayout(bar)

        self.products_table = DataTable(
            ["SKU", "Product", "Category", "Unit", "Cost", "Selling", "Min", "Status"],
            stretch_columns=(1,),
            empty_title="No products yet",
            empty_body="Add your first product to start tracking stock and selling.",
        )
        self.products_table.table.doubleClicked.connect(lambda _: self._edit_product())
        layout.addWidget(self.products_table, 1)
        return page

    def _stock_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.stock_search = QLineEdit()
        self.stock_search.setPlaceholderText("Search stock…")
        self.stock_search.setClearButtonEnabled(True)
        self.stock_search.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.stock_search, 2)

        self.low_only_check = QCheckBox("Low stock only")
        self.low_only_check.toggled.connect(lambda _: self.refresh())
        bar.addWidget(self.low_only_check)

        self.out_only_check = QCheckBox("Out of stock only")
        self.out_only_check.toggled.connect(lambda _: self.refresh())
        bar.addWidget(self.out_only_check)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.stock_table = DataTable(
            ["SKU", "Product", "Category", "Available", "Reserved", "Minimum", "Stock value"],
            stretch_columns=(1,),
            empty_title="No stock records",
            empty_body="Stock records are created with each product.",
        )
        layout.addWidget(self.stock_table, 1)
        return page

    def _low_stock_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(
            muted_label(
                "Low stock = available quantity at or below the product's minimum stock. "
                "Purchase orders are not raised automatically in Phase 2."
            )
        )
        self.low_table = DataTable(
            ["Product", "SKU", "Available", "Minimum", "Suggested reorder"],
            stretch_columns=(0,),
            empty_title="Everything is above its minimum",
            empty_body="No product is at or below its low-stock threshold.",
        )
        layout.addWidget(self.low_table, 1)
        return page

    def _movements_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.movement_product_filter = QComboBox()
        self.movement_product_filter.setMinimumWidth(220)
        self.movement_product_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.movement_product_filter)

        self.movement_type_filter = QComboBox()
        self.movement_type_filter.addItem("All movement types", None)
        for movement_type in ("PURCHASE", "SALE", "RETURN", "ADJUSTMENT", "DAMAGE", "OPENING_STOCK"):
            self.movement_type_filter.addItem(movement_type.replace("_", " ").title(), movement_type)
        self.movement_type_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.movement_type_filter)
        bar.addStretch(1)
        layout.addLayout(bar)

        self.movements_table = DataTable(
            ["When", "Product", "SKU", "Type", "Qty", "Before", "After", "Reference", "By"],
            stretch_columns=(1,),
            empty_title="No stock movements yet",
            empty_body="Every stock change — opening stock, sale, purchase, adjustment — is logged here.",
        )
        layout.addWidget(self.movements_table, 1)
        return page

    def _categories_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(muted_label("Categories group products and drive the catalogue filters."))
        bar.addStretch(1)
        new_category = primary_button("New category")
        new_category.setEnabled(self._can("inventory.create"))
        new_category.clicked.connect(self._new_category)
        bar.addWidget(new_category)
        edit_category = secondary_button("Edit")
        edit_category.setEnabled(self._can("inventory.update"))
        edit_category.clicked.connect(self._edit_category)
        bar.addWidget(edit_category)
        layout.addLayout(bar)

        self.categories_table = DataTable(
            ["Category", "Description", "Products", "Status"],
            stretch_columns=(1,),
            empty_title="No categories yet",
            empty_body="Create a category to organise your products.",
        )
        self.categories_table.table.doubleClicked.connect(lambda _: self._edit_category())
        layout.addWidget(self.categories_table, 1)
        return page

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._error.setVisible(False)
        try:
            dashboard = self._context.inventory_service.dashboard()
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.card_products.set_value(str(dashboard.total_products), True, f"{dashboard.active_products} active")
        self.card_quantity.set_value(f"{dashboard.total_stock_quantity:,}", True, "Units on hand")
        self.card_value.set_value(f"{dashboard.stock_value:,.2f}", True, "Cost basis")
        self.card_low.set_value(str(dashboard.low_stock_count), True, "Reorder soon")
        self.card_out.set_value(str(dashboard.out_of_stock_count), True, "Unavailable")

        self._load_categories()
        self._load_products()
        self._load_stock()
        self._load_low_stock()
        self._load_movements()

    def _load_categories(self) -> None:
        try:
            self._categories = self._context.inventory_service.list_categories()
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        current_filter = self.product_category_filter.currentData()
        self.product_category_filter.blockSignals(True)
        self.product_category_filter.clear()
        self.product_category_filter.addItem("All categories", None)
        for category in self._categories:
            self.product_category_filter.addItem(category.category_name, category.id)
        index = self.product_category_filter.findData(current_filter)
        self.product_category_filter.setCurrentIndex(index if index >= 0 else 0)
        self.product_category_filter.blockSignals(False)

        self.categories_table.set_rows(
            [
                [
                    category.category_name,
                    category.description or "—",
                    str(category.product_count),
                    "Active" if category.is_active else "Inactive",
                ]
                for category in self._categories
            ],
            row_ids=[category.id for category in self._categories],
        )

    def _load_products(self) -> None:
        try:
            self._products = self._context.inventory_service.list_products(
                search=self.product_search.text().strip() or None,
                category_id=self.product_category_filter.currentData(),
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.products_table.set_rows(
            [
                [
                    product.sku,
                    product.product_name,
                    product.category_name,
                    product.unit,
                    f"{product.cost_price:,.2f}",
                    f"{product.selling_price:,.2f}",
                    str(product.minimum_stock),
                    "Active" if product.is_active else "Inactive",
                ]
                for product in self._products
            ],
            row_ids=[product.id for product in self._products],
        )

        current = self.movement_product_filter.currentData()
        self.movement_product_filter.blockSignals(True)
        self.movement_product_filter.clear()
        self.movement_product_filter.addItem("All products", None)
        for product in self._products:
            self.movement_product_filter.addItem(f"{product.product_name} ({product.sku})", product.id)
        index = self.movement_product_filter.findData(current)
        self.movement_product_filter.setCurrentIndex(index if index >= 0 else 0)
        self.movement_product_filter.blockSignals(False)

    def _load_stock(self) -> None:
        try:
            self._stock = self._context.inventory_service.list_stock(
                search=self.stock_search.text().strip() or None,
                low_stock_only=self.low_only_check.isChecked(),
                out_of_stock_only=self.out_only_check.isChecked(),
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.stock_table.set_rows(
            [
                [
                    row.sku,
                    row.product_name,
                    row.category_name,
                    str(row.available_quantity),
                    str(row.reserved_quantity),
                    str(row.minimum_stock),
                    f"{row.stock_value:,.2f}",
                ]
                for row in self._stock
            ],
            row_ids=[row.product_id for row in self._stock],
            sort_keys={
                3: [row.available_quantity for row in self._stock],
                6: [float(row.stock_value) for row in self._stock],
            },
        )

    def _load_low_stock(self) -> None:
        try:
            alerts = self._context.inventory_service.low_stock_alerts()
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.low_table.set_rows(
            [
                [
                    alert.product_name,
                    alert.sku,
                    str(alert.available_quantity),
                    str(alert.minimum_stock),
                    str(alert.suggested_reorder_quantity),
                ]
                for alert in alerts
            ],
            sort_keys={2: [alert.available_quantity for alert in alerts]},
        )

    def _load_movements(self) -> None:
        try:
            movements = self._context.inventory_service.movements(
                product_id=self.movement_product_filter.currentData(),
                movement_type=self.movement_type_filter.currentData(),
                limit=300,
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.movements_table.set_rows(
            [
                [
                    format_datetime(movement.created_at),
                    movement.product_name,
                    movement.sku,
                    movement.movement_type.replace("_", " ").title(),
                    str(movement.quantity),
                    str(movement.previous_quantity),
                    str(movement.new_quantity),
                    f"{movement.reference_type or '—'}"
                    + (f" {movement.reference_id}" if movement.reference_id else ""),
                    movement.user_name or "—",
                ]
                for movement in movements
            ],
            sort_keys={0: [movement.created_at for movement in movements]},
        )

    # -- actions -----------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _selected_product(self):
        product_id = self.products_table.selected_id()
        return next((product for product in self._products if product.id == product_id), None)

    def _new_product(self) -> None:
        dialog = ProductDialog(self._context, None, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The product was created.", "Product saved")

    def _edit_product(self) -> None:
        product = self._selected_product()
        if product is None:
            self._show_error("Select a product to edit.")
            return
        dialog = ProductDialog(self._context, product, self)
        if dialog.exec():
            self.refresh()

    def _adjust_stock(self) -> None:
        dialog = StockAdjustmentDialog(self._context, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The stock movement was recorded.", "Stock updated")

    def _new_category(self) -> None:
        dialog = CategoryDialog(self._context, None, self)
        if dialog.exec():
            self.refresh()

    def _edit_category(self) -> None:
        category_id = self.categories_table.selected_id()
        category = next((item for item in self._categories if item.id == category_id), None)
        if category is None:
            self._show_error("Select a category to edit.")
            return
        dialog = CategoryDialog(self._context, category, self)
        if dialog.exec():
            self.refresh()

    def _export(self) -> None:
        try:
            path = self._context.inventory_service.export_stock_csv()
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        show_info(self, f"Inventory export saved to:\n{path}", "Export complete")
