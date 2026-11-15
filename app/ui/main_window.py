"""Main application window: sidebar, header and page stack."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.config import APP_VERSION
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.header import Header
from app.ui.components.notification_panel import NotificationPanel
from app.ui.components.sidebar import Sidebar
from app.ui.dialogs.password_dialog import PasswordChangeDialog
from app.ui.dialogs.profile_dialog import ProfileDialog
from app.ui.navigation import NAV_BY_KEY
from app.ui.pages.audit_page import AuditPage
from app.ui.pages.agents_page import AgentsPage
from app.ui.pages.collaboration_center import CollaborationCenterPage
from app.ui.pages.operations_center import OperationsCenterPage
from app.ui.pages.business_intelligence import BusinessIntelligencePage
from app.ui.pages.knowledge_center import KnowledgeCenterPage
from app.ui.pages.reports_page import ReportsPage
from app.ui.pages.security_center import SecurityCenterPage
from app.ui.pages.ai_command_page import AICommandPage
from app.ui.pages.coming_soon_page import ComingSoonPage
from app.ui.pages.customers_page import CustomersPage
from app.ui.pages.dashboard_page import DashboardPage
from app.ui.pages.finance_page import FinancePage
from app.ui.pages.inventory_page import InventoryPage
from app.ui.pages.roles_page import RolesPage
from app.ui.pages.sales_page import SalesPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.pages.suppliers_page import SuppliersPage
from app.ui.pages.users_page import UsersPage
from app.ui.theme import load_icon
from app.ui.ui_utils import show_info

logger = get_logger("ui.main_window")

# Pages that exist in Phase 1; everything else resolves to a ComingSoonPage.
PAGE_FACTORIES = {
    "overview": DashboardPage,
    "command_center": AICommandPage,
    "agents": AgentsPage,
    "collaboration": CollaborationCenterPage,
    "automation": OperationsCenterPage,
    "analytics": BusinessIntelligencePage,
    "knowledge": KnowledgeCenterPage,
    "security": SecurityCenterPage,
    "reports": ReportsPage,
    "finance": FinancePage,
    "sales": SalesPage,
    "customers": CustomersPage,
    "inventory": InventoryPage,
    "suppliers": SuppliersPage,
    "audit": AuditPage,
    "users": UsersPage,
    "roles": RolesPage,
    "settings": SettingsPage,
}


class MainWindow(QMainWindow):
    """The signed-in workspace shell."""

    logout_requested = Signal()

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._pages: dict[str, QWidget] = {}
        self._current_key: str | None = None

        principal = context.auth_context.principal
        if principal is None:  # pragma: no cover - guarded by the controller
            raise RuntimeError("MainWindow requires an authenticated principal")

        self.setWindowTitle(f"BizPilot AI — {principal.business_name or 'Workspace'}")
        self.setWindowIcon(load_icon(context.config, "app_icon"))
        self.resize(1440, 900)
        self.setMinimumSize(1180, 720)

        root = QWidget()
        root.setObjectName("AppRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(context.config, principal)
        self.sidebar.navigate.connect(self.navigate_to)
        layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)

        self.header = Header(context.config)
        self.header.set_context(principal, principal.business_name or "")
        self.header.profile_requested.connect(self._open_profile)
        self.header.password_requested.connect(self._open_password)
        self.header.logout_requested.connect(self.logout_requested.emit)
        self.header.notifications_requested.connect(self._show_notifications)
        right_layout.addWidget(self.header)

        self.stack = QStackedWidget()
        right_layout.addWidget(self.stack, 1)
        layout.addWidget(right, 1)

        self.setCentralWidget(root)

        self._notifications = NotificationPanel(self)
        self.statusBar().showMessage(
            f"Signed in as {principal.email} · Local SQLite database · Version {APP_VERSION}"
        )

        self._open_initial_page()

    # -- navigation --------------------------------------------------------
    def _open_initial_page(self) -> None:
        first_key = "overview" if self.sidebar.has_item("overview") else None
        if first_key is None:
            visible = self.sidebar.visible_keys()
            first_key = visible[0] if visible else "settings"
        self.navigate_to(first_key)

    def navigate_to(self, key: str) -> None:
        """Switch to a page, enforcing the permission a second time."""
        item = NAV_BY_KEY.get(key)
        principal = self._context.auth_context.principal
        if item is None or principal is None:
            return
        if not principal.has(item.permission):
            show_info(
                self,
                f"Your role does not include access to {item.label}.",
                "Permission required",
            )
            self.sidebar.set_active(self._current_key or "overview")
            return

        page = self._pages.get(key)
        is_new = page is None
        if is_new:
            page = self._create_page(key)
            self._pages[key] = page
            self.stack.addWidget(page)

        self.stack.setCurrentWidget(page)
        self._current_key = key
        self.sidebar.set_active(key)
        self.header.set_page_title(item.label)

        if not is_new:
            refresh = getattr(page, "refresh", None)
            if callable(refresh):
                try:
                    refresh()
                except BizPilotError as exc:
                    logger.warning("Page refresh failed for %s: %s", key, exc.message)
        self._update_notification_count()

    def _create_page(self, key: str) -> QWidget:
        factory = PAGE_FACTORIES.get(key)
        if factory is None:
            item = NAV_BY_KEY[key]
            return ComingSoonPage(item, self)

        page = factory(self._context, self)
        if key == "settings" and isinstance(page, SettingsPage):
            page.session_invalidated.connect(self.logout_requested.emit)
        return page

    def _update_notification_count(self) -> None:
        try:
            entries = self._context.audit_service.recent_activity(limit=8)
        except BizPilotError:
            entries = []
        self._notifications.populate(entries)
        self.header.set_notification_count(len(entries))

    def _show_notifications(self) -> None:
        self._update_notification_count()
        button = self.header.notification_button()
        self._notifications.exec(button.mapToGlobal(button.rect().bottomLeft()))

    # -- account actions ---------------------------------------------------
    def _open_profile(self) -> None:
        dialog = ProfileDialog(self._context, self)
        if dialog.exec():
            principal = self._context.auth_context.principal
            if principal is not None:
                self.header.set_context(principal, principal.business_name or "")
            show_info(self, "Your profile was updated.", "Profile saved")

    def _open_password(self) -> None:
        dialog = PasswordChangeDialog(self._context, self)
        if dialog.exec():
            show_info(self, "Your password was changed.", "Password updated")

    # -- lifecycle ---------------------------------------------------------
    def refresh_current(self) -> None:
        if self._current_key is None:
            return
        page = self._pages.get(self._current_key)
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def page_for(self, key: str) -> QWidget | None:
        return self._pages.get(key)

    def current_key(self) -> str | None:
        return self._current_key

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        logger.info("Main window closed")
        super().closeEvent(event)
