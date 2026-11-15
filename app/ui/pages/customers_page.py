"""Customer page: list, profile, purchase history, segmentation, follow-ups."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.constants import CustomerSegment, CustomerType
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.confirmation_dialog import confirm
from app.ui.components.stat_card import StatCard
from app.ui.components.tables import DataTable
from app.ui.dialogs.crm_dialogs import CustomerDialog, FollowUpDialog
from app.ui.ui_utils import muted_label, primary_button, secondary_button, show_info
from app.utils.date_utils import format_datetime

logger = get_logger("ui.customers")


class CustomersPage(QWidget):
    """CRM: records, history, segmentation and local follow-ups."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._customers = []
        self._follow_ups = []
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
        self.card_total = StatCard("Total customers", "—", "All records")
        self.card_active = StatCard("Active", "—", "Can be sold to")
        self.card_new = StatCard("New (30 days)", "—", "Recently added")
        self.card_inactive = StatCard("Inactive", "—", "Deactivated")
        self.card_value = StatCard("Total purchases", "—", "Completed orders")
        for card in (self.card_total, self.card_active, self.card_new, self.card_inactive, self.card_value):
            cards.addWidget(card)
        layout.addLayout(cards)

        self._error = QLabel("")
        self._error.setObjectName("ErrorText")
        self._error.setWordWrap(True)
        self._error.setVisible(False)
        layout.addWidget(self._error)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._customers_tab(), "Customers")
        self.tabs.addTab(self._follow_ups_tab(), "Follow-ups")
        self.tabs.addTab(self._segments_tab(), "Segmentation")
        layout.addWidget(self.tabs, 1)

    def _customers_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name, code, email, phone or city…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.search_input, 2)

        self.type_filter = QComboBox()
        self.type_filter.addItem("All types", None)
        for value in CustomerType.ALL:
            self.type_filter.addItem(value.title(), value)
        self.type_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.type_filter)

        self.status_filter = QComboBox()
        self.status_filter.addItem("All statuses", None)
        self.status_filter.addItem("Active", True)
        self.status_filter.addItem("Inactive", False)
        self.status_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.status_filter)

        self.segment_filter = QComboBox()
        self.segment_filter.addItem("All segments", None)
        for segment in CustomerSegment.ALL:
            self.segment_filter.addItem(segment, segment)
        self.segment_filter.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.segment_filter)
        bar.addStretch(1)

        self.new_button = primary_button("New customer")
        self.new_button.setEnabled(self._can("customers.create"))
        self.new_button.clicked.connect(self._new_customer)
        bar.addWidget(self.new_button)

        self.edit_button = secondary_button("Edit")
        self.edit_button.setEnabled(self._can("customers.update"))
        self.edit_button.clicked.connect(self._edit_customer)
        bar.addWidget(self.edit_button)

        self.toggle_button = secondary_button("Deactivate")
        self.toggle_button.setEnabled(self._can("customers.deactivate"))
        self.toggle_button.clicked.connect(self._toggle_customer)
        bar.addWidget(self.toggle_button)

        self.export_button = secondary_button("Export CSV")
        self.export_button.setEnabled(self._can("customers.export"))
        self.export_button.clicked.connect(self._export)
        bar.addWidget(self.export_button)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)

        self.table = DataTable(
            ["Code", "Name", "Orders", "Spend", "Last purchase", "Segment", "Status"],
            stretch_columns=(1,),
            empty_title="No customers yet",
            empty_body="Add a customer before recording your first sale.",
        )
        self.table.table.itemSelectionChanged.connect(self._show_profile)
        splitter.addWidget(self.table)

        profile = QFrame()
        profile.setObjectName("DetailPanel")
        profile_layout = QVBoxLayout(profile)
        profile_layout.setContentsMargins(18, 16, 18, 16)
        profile_layout.setSpacing(8)

        self.profile_name = QLabel("Select a customer")
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

        profile_layout.addWidget(muted_label("Recent invoices"))
        self.invoice_list = QListWidget()
        self.invoice_list.setFrameShape(QFrame.NoFrame)
        self.invoice_list.setMaximumHeight(140)
        profile_layout.addWidget(self.invoice_list)

        profile_layout.addWidget(muted_label("Recent payments"))
        self.payment_list = QListWidget()
        self.payment_list.setFrameShape(QFrame.NoFrame)
        self.payment_list.setMaximumHeight(110)
        profile_layout.addWidget(self.payment_list)

        profile_layout.addWidget(muted_label("Follow-ups"))
        self.follow_up_list = QListWidget()
        self.follow_up_list.setFrameShape(QFrame.NoFrame)
        profile_layout.addWidget(self.follow_up_list, 1)

        follow_row = QHBoxLayout()
        follow_row.addStretch(1)
        add_follow = secondary_button("New follow-up")
        add_follow.setEnabled(self._can("customers.update"))
        add_follow.clicked.connect(self._new_follow_up)
        follow_row.addWidget(add_follow)
        self.complete_follow_button = secondary_button("Mark complete")
        self.complete_follow_button.setEnabled(self._can("customers.update"))
        self.complete_follow_button.clicked.connect(self._complete_follow_up)
        follow_row.addWidget(self.complete_follow_button)
        profile_layout.addLayout(follow_row)

        splitter.addWidget(profile)
        splitter.setSizes([880, 360])
        layout.addWidget(splitter, 1)
        return page

    def _follow_ups_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.addWidget(
            muted_label("Reminders are stored locally; no email is sent in Phase 2.")
        )
        bar.addStretch(1)
        new_follow = primary_button("New follow-up")
        new_follow.setEnabled(self._can("customers.update"))
        new_follow.clicked.connect(self._new_follow_up)
        bar.addWidget(new_follow)
        layout.addLayout(bar)

        self.follow_table = DataTable(
            ["Due", "Customer", "Title", "Assigned to", "Status"],
            stretch_columns=(2,),
            empty_title="No follow-ups scheduled",
            empty_body="Create a reminder to follow up with a customer.",
        )
        layout.addWidget(self.follow_table, 1)
        return page

    def _segments_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)
        layout.addWidget(muted_label("Segments are computed from real completed orders."))
        self.segment_summary = QLabel("")
        self.segment_summary.setObjectName("Body")
        self.segment_summary.setWordWrap(True)
        layout.addWidget(self.segment_summary)
        self.segment_rules = QLabel("")
        self.segment_rules.setObjectName("Hint")
        self.segment_rules.setWordWrap(True)
        layout.addWidget(self.segment_rules)
        layout.addStretch(1)
        return page

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._error.setVisible(False)
        try:
            dashboard = self._context.customer_service.dashboard()
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.card_total.set_value(str(dashboard.total_customers), True, "All records")
        self.card_active.set_value(str(dashboard.active_customers), True, "Can be sold to")
        self.card_new.set_value(str(dashboard.new_customers_30d), True, "Last 30 days")
        self.card_inactive.set_value(str(dashboard.inactive_customers), True, "Deactivated")
        self.card_value.set_value(f"{dashboard.total_purchase_value:,.2f}", True, "Lifetime value")

        self._load_customers()
        self._load_follow_ups()

        counts = " · ".join(f"{segment}: {count}" for segment, count in dashboard.segments.items())
        self.segment_summary.setText(counts)
        self.segment_rules.setText(
            "Rules: " + "; ".join(dashboard.segmentation_rules)
        )

    def _load_customers(self) -> None:
        try:
            self._customers = self._context.customer_service.list_customers(
                search=self.search_input.text().strip() or None,
                is_active=self.status_filter.currentData(),
                customer_type=self.type_filter.currentData(),
                segment=self.segment_filter.currentData(),
            )
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.table.set_rows(
            [
                [
                    customer.customer_code,
                    customer.full_name,
                    str(customer.order_count),
                    f"{customer.total_purchase:,.2f}",
                    format_datetime(customer.last_purchase_at, "%d %b %Y"),
                    customer.segment,
                    "Active" if customer.is_active else "Inactive",
                ]
                for customer in self._customers
            ],
            row_ids=[customer.id for customer in self._customers],
            sort_keys={2: [customer.order_count for customer in self._customers]},
        )

    def _load_follow_ups(self) -> None:
        try:
            self._follow_ups = self._context.customer_service.list_follow_ups()
        except BizPilotError:
            self._follow_ups = []

        self.follow_table.set_rows(
            [
                [
                    format_datetime(item.due_date, "%d %b %Y, %I:%M %p")
                    + (" · overdue" if item.is_overdue else ""),
                    item.customer_name,
                    item.title,
                    item.assignee_name or "Unassigned",
                    item.status.title(),
                ]
                for item in self._follow_ups
            ],
            row_ids=[item.id for item in self._follow_ups],
        )

    def _show_profile(self) -> None:
        customer_id = self.table.selected_id()
        if customer_id is None:
            return
        customer = next((item for item in self._customers if item.id == customer_id), None)
        if customer is None:
            return
        self.toggle_button.setText("Deactivate" if customer.is_active else "Activate")

        try:
            profile = self._context.customer_service.profile(customer_id)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return

        self.profile_name.setText(f"{profile.summary.full_name} · {profile.summary.customer_code}")
        self.profile_meta.setText(
            "\n".join(
                part
                for part in (
                    profile.summary.email or "",
                    profile.summary.phone or "",
                    profile.address or "",
                    profile.summary.city or "",
                    f"Segment: {profile.summary.segment} — {profile.segment_reason}",
                )
                if part
            )
        )
        self.profile_stats.setText(
            f"Orders {profile.summary.order_count} · Lifetime {profile.summary.total_purchase:,.2f} · "
            f"Outstanding {profile.outstanding_amount:,.2f} · "
            f"Last purchase {format_datetime(profile.summary.last_purchase_at, '%d %b %Y')}"
        )

        self.invoice_list.clear()
        for invoice in profile.invoices:
            self.invoice_list.addItem(
                f"{invoice.invoice_number} · {invoice.invoice_date:%d %b %Y} · "
                f"total {invoice.total_amount:,.2f} · outstanding {invoice.outstanding:,.2f} · {invoice.status}"
            )
        if not profile.invoices:
            self.invoice_list.addItem("No invoices yet")

        self.payment_list.clear()
        for payment in profile.payments:
            self.payment_list.addItem(
                f"{payment.payment_date:%d %b %Y} · {payment.amount:,.2f} · "
                f"{payment.payment_method} · {payment.invoice_number}"
            )
        if not profile.payments:
            self.payment_list.addItem("No payments recorded")

        self.follow_up_list.clear()
        for item in profile.follow_ups:
            self.follow_up_list.addItem(
                f"{item.due_date:%d %b %Y} · {item.title} · {item.status}"
            )
        if not profile.follow_ups:
            self.follow_up_list.addItem("No follow-ups")

    # -- actions -----------------------------------------------------------
    def _show_error(self, message: str) -> None:
        self._error.setText(message)
        self._error.setVisible(True)

    def _selected_customer(self):
        customer_id = self.table.selected_id()
        return next((item for item in self._customers if item.id == customer_id), None)

    def _new_customer(self) -> None:
        dialog = CustomerDialog(self._context, None, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The customer was created.", "Customer saved")

    def _edit_customer(self) -> None:
        customer = self._selected_customer()
        if customer is None:
            self._show_error("Select a customer to edit.")
            return
        dialog = CustomerDialog(self._context, customer, self)
        if dialog.exec():
            self.refresh()

    def _toggle_customer(self) -> None:
        customer = self._selected_customer()
        if customer is None:
            self._show_error("Select a customer first.")
            return
        activating = not customer.is_active
        if not activating and not confirm(
            self,
            title="Deactivate customer",
            message=(
                f"{customer.full_name} will no longer be selectable on new sales orders. "
                "History and invoices are preserved."
            ),
            confirm_text="Deactivate",
            destructive=True,
        ):
            return
        try:
            self._context.customer_service.set_active(customer.id, activating)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()

    def _new_follow_up(self) -> None:
        customer = self._selected_customer()
        dialog = FollowUpDialog(self._context, customer.id if customer else None, self)
        if dialog.exec():
            self.refresh()
            show_info(self, "The follow-up reminder was created.", "Reminder saved")

    def _complete_follow_up(self) -> None:
        follow_up_id = self.follow_table.selected_id()
        if follow_up_id is None:
            self._show_error("Select a follow-up in the Follow-ups tab first.")
            return
        try:
            self._context.customer_service.complete_follow_up(follow_up_id)
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        self.refresh()

    def _export(self) -> None:
        try:
            path = self._context.customer_service.export_customers_csv()
        except BizPilotError as exc:
            self._show_error(exc.user_message)
            return
        show_info(self, f"Customer list exported to:\n{path}", "Export complete")
