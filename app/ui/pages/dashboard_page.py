"""Overview dashboard.

Everything shown here is either a real database figure or an explicit empty
state. No invented financial numbers are displayed in Phase 1.
"""

from __future__ import annotations

from datetime import datetime

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedLayout,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.config import APP_VERSION
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.services.dashboard_service import AuditEntryView, DashboardSummary
from app.ui.components.stat_card import StatCard
from app.ui.ui_utils import muted_label, section_title
from app.utils.date_utils import format_datetime

logger = get_logger("ui.dashboard")

pg.setConfigOptions(antialias=True, background="w", foreground="#64748B")


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


class ChartCard(QFrame):
    """Chart container that shows an empty state until data exists."""

    def __init__(self, title: str, empty_message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ChartCard")
        self.setMinimumHeight(212)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setObjectName("ChartTitle")
        header.addWidget(title_label)
        header.addStretch(1)
        self._badge = QLabel("No data yet")
        self._badge.setObjectName("Badge")
        header.addWidget(self._badge)
        layout.addLayout(header)

        self._empty = QWidget()
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(0, 0, 0, 0)
        empty_layout.addStretch(1)
        empty_label = QLabel(empty_message)
        empty_label.setObjectName("ChartEmpty")
        empty_label.setAlignment(Qt.AlignCenter)
        empty_label.setWordWrap(True)
        empty_layout.addWidget(empty_label)
        empty_layout.addStretch(1)

        self._plot = pg.PlotWidget()
        self._plot.setBackground("w")
        self._plot.showGrid(x=True, y=True, alpha=0.12)
        self._plot.setMenuEnabled(False)
        self._plot.setMouseEnabled(x=False, y=False)
        self._plot.hideButtons()
        self._plot.getAxis("left").setPen(pg.mkPen("#DCE3EC"))
        self._plot.getAxis("bottom").setPen(pg.mkPen("#DCE3EC"))

        self._stack = QStackedLayout()
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._empty)
        self._stack.addWidget(self._plot)
        self._stack.setCurrentWidget(self._empty)
        layout.addLayout(self._stack, 1)

    def set_series(
        self, xs: list[float], ys: list[float], labels: list[str] | None = None
    ) -> None:
        """Draw real data; falls back to the empty state when there is none."""
        if not xs or not ys or not any(value != 0 for value in ys):
            self.show_empty()
            return
        self._plot.clear()
        self._plot.plot(
            xs,
            ys,
            pen=pg.mkPen("#2563EB", width=2),
            symbol="o",
            symbolSize=5,
            symbolBrush="#2563EB",
            fillLevel=0,
            brush=pg.mkBrush(37, 99, 235, 28),
        )
        if labels:
            self._plot.getAxis("bottom").setTicks(
                [[(index, label) for index, label in enumerate(labels)]]
            )
        self._badge.setText("Live data")
        self._stack.setCurrentWidget(self._plot)

    def show_empty(self) -> None:
        self._plot.clear()
        self._badge.setText("No data yet")
        self._stack.setCurrentWidget(self._empty)


class DashboardPage(QWidget):
    """Phase 1 dashboard shell."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self.setObjectName("PageSurface")
        self._stat_cards: list[StatCard] = []
        self._build()
        self.refresh()

    # -- construction ------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("PageSurface")
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(24, 22, 24, 24)
        self._layout.setSpacing(16)

        self._welcome_card = self._build_welcome()
        self._layout.addWidget(self._welcome_card)

        self._empty_banner = self._build_empty_banner()
        self._layout.addWidget(self._empty_banner)

        self._layout.addWidget(self._build_stats())
        self._layout.addWidget(section_title("Business trends"))
        self._layout.addWidget(self._build_charts())
        self._layout.addWidget(self._build_bottom_row())
        self._layout.addWidget(section_title("AI, automation and security"))
        self._layout.addWidget(self._build_system_overview())
        self._layout.addStretch(1)

        scroll.setWidget(content)

    def _build_welcome(self) -> QWidget:
        card = QFrame()
        card.setObjectName("Card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(22, 18, 22, 18)
        layout.setSpacing(16)

        text = QVBoxLayout()
        text.setSpacing(4)

        self._greeting_label = QLabel("Welcome back")
        self._greeting_label.setObjectName("PageTitle")
        self._date_label = QLabel("")
        self._date_label.setObjectName("Muted")

        chips = QHBoxLayout()
        chips.setSpacing(8)
        self._business_chip = QLabel("")
        self._business_chip.setObjectName("PhaseBadge")
        self._role_chip = QLabel("")
        self._role_chip.setObjectName("Badge")
        chips.addWidget(self._business_chip)
        chips.addWidget(self._role_chip)
        chips.addStretch(1)

        text.addWidget(self._greeting_label)
        text.addWidget(self._date_label)
        text.addSpacing(6)
        text.addLayout(chips)

        layout.addLayout(text, 1)
        return card

    def _build_empty_banner(self) -> QWidget:
        frame = QFrame()
        frame.setObjectName("EmptyState")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        icon = QLabel("◆")
        icon.setObjectName("ComingSoonGlyph")
        icon.setAlignment(Qt.AlignCenter)
        icon.setFixedSize(34, 34)
        layout.addWidget(icon)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel("Workspace status")
        title.setObjectName("EmptyTitle")
        self._empty_body = QLabel("")
        self._empty_body.setObjectName("EmptyBody")
        self._empty_body.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(self._empty_body)
        layout.addLayout(text, 1)

        phase = QLabel(f"Version {APP_VERSION} · all modules live")
        phase.setObjectName("PhaseBadge")
        layout.addWidget(phase)
        return frame

    def _build_stats(self) -> QWidget:
        self._stats_container = QWidget()
        self._stats_container.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        grid = QGridLayout(self._stats_container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)
        self._stats_grid = grid
        return self._stats_container

    def _build_charts(self) -> QWidget:
        container = QWidget()
        grid = QGridLayout(container)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(12)

        self._revenue_chart = ChartCard(
            "Revenue trends", "Revenue chart appears once Finance records exist."
        )
        self._expense_chart = ChartCard(
            "Expense trends", "Expense chart appears once Finance records exist."
        )
        self._sales_chart = ChartCard(
            "Sales performance", "Sales chart appears once Sales records exist."
        )
        self._inventory_chart = ChartCard(
            "Inventory movement", "Inventory chart appears once Inventory records exist."
        )

        grid.addWidget(self._revenue_chart, 0, 0)
        grid.addWidget(self._expense_chart, 0, 1)
        grid.addWidget(self._sales_chart, 1, 0)
        grid.addWidget(self._inventory_chart, 1, 1)
        return container

    def _build_bottom_row(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        activity_card = QFrame()
        activity_card.setObjectName("Card")
        activity_layout = QVBoxLayout(activity_card)
        activity_layout.setContentsMargins(18, 16, 18, 16)
        activity_layout.setSpacing(8)
        activity_layout.addWidget(section_title("Recent activity"))
        self._activity_container = QVBoxLayout()
        self._activity_container.setSpacing(0)
        activity_layout.addLayout(self._activity_container)
        activity_layout.addStretch(1)

        status_card = QFrame()
        status_card.setObjectName("Card")
        status_card.setFixedWidth(360)
        status_layout = QVBoxLayout(status_card)
        status_layout.setContentsMargins(18, 16, 18, 16)
        status_layout.setSpacing(8)
        status_layout.addWidget(section_title("System status"))
        self._status_container = QVBoxLayout()
        self._status_container.setSpacing(0)
        status_layout.addLayout(self._status_container)
        status_layout.addStretch(1)

        layout.addWidget(activity_card, 3)
        layout.addWidget(status_card, 2)
        return container

    def _build_system_overview(self) -> QWidget:
        container = QFrame()
        container.setObjectName("CardSurface")
        grid = QGridLayout(container)
        grid.setContentsMargins(16, 16, 16, 16)
        grid.setSpacing(12)
        self._system_cards: list[StatCard] = []
        specs = (
            ("ai_agents", "AI agents", "enabled agents"),
            ("workflows", "Active workflows", "running now"),
            ("approvals", "Pending approvals", "awaiting a decision"),
            ("documents", "Documents", "indexed in the knowledge base"),
            ("alerts", "Security alerts", "open for review"),
        )
        for index, (key, title, caption) in enumerate(specs):
            card = StatCard(title, "—", caption, available=False)
            card.setProperty("systemKey", key)
            self._system_cards.append(card)
            grid.addWidget(card, 0, index)
        return container

    def _render_system_overview(self) -> None:
        """Real counts from the AI, automation, knowledge and security services."""
        values: dict[str, tuple[str, bool]] = {}
        context = self._context
        try:
            agents = context.agent_manager.list_agents()
            enabled = sum(1 for agent in agents if agent.get("is_enabled", True))
            values["ai_agents"] = (f"{enabled}/{len(agents)}", True)
        except Exception:  # noqa: BLE001 - a missing module must not break the page
            values["ai_agents"] = ("—", False)
        try:
            stats = context.autonomy_service.dashboard_stats()
            values["workflows"] = (str(stats.get("running", 0)), True)
            values["approvals"] = (str(stats.get("pending_approvals", 0)), True)
        except Exception:  # noqa: BLE001
            values["workflows"] = ("—", False)
            values["approvals"] = ("—", False)
        try:
            knowledge = context.knowledge_service.statistics()
            values["documents"] = (str(knowledge.get("indexed", 0)), True)
        except Exception:  # noqa: BLE001
            values["documents"] = ("—", False)
        try:
            security = context.security_service.overview()
            values["alerts"] = (str(security.get("open_security_events", 0)), True)
        except Exception:  # noqa: BLE001
            values["alerts"] = ("—", False)

        for card in self._system_cards:
            key = card.property("systemKey")
            value, available = values.get(key, ("—", False))
            card.set_value(value, available)

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        """Reload every value from the database."""
        try:
            summary = self._context.dashboard_service.get_summary()
            activity = self._context.dashboard_service.recent_activity(limit=6)
        except BizPilotError as exc:
            logger.warning("Dashboard refresh failed: %s", exc.message)
            self._empty_body.setText(exc.user_message)
            return

        self._apply(summary, activity)

    def _apply(self, summary: DashboardSummary, activity: list[AuditEntryView]) -> None:
        self._greeting_label.setText(f"{_greeting()}, {summary.user_name.split()[0]}")
        self._date_label.setText(f"{summary.today} · {summary.business_name}")
        self._business_chip.setText(summary.business_name)
        self._role_chip.setText(summary.user_roles)
        self._empty_body.setText(summary.empty_state_message)

        self._render_stats(summary)
        self._render_charts(summary)
        self._render_activity(activity)
        self._render_status(summary)
        self._render_system_overview()

    def _render_stats(self, summary: DashboardSummary) -> None:
        for card in self._stat_cards:
            card.setParent(None)
        self._stat_cards.clear()

        columns = 4
        for index, stat in enumerate(summary.stat_cards):
            card = StatCard(
                title=stat.title,
                value=stat.value,
                caption=stat.caption,
                available=stat.available,
            )
            row, column = index // columns, index % columns
            self._stats_grid.addWidget(card, row, column)
            self._stats_grid.setRowMinimumHeight(row, 112)
            self._stat_cards.append(card)
        self._stats_container.updateGeometry()

    def _render_charts(self, summary: DashboardSummary) -> None:
        cards = {
            "revenue": self._revenue_chart,
            "expenses": self._expense_chart,
            "sales": self._sales_chart,
            "inventory": self._inventory_chart,
        }
        for key, card in cards.items():
            series = summary.charts.get(key)
            if series is not None and series.has_data:
                card.set_series(
                    list(range(len(series.values))), series.values, series.labels
                )
            else:
                card.show_empty()

    def _render_activity(self, entries: list[AuditEntryView]) -> None:
        while self._activity_container.count():
            item = self._activity_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        if not entries:
            empty = QLabel("No activity has been recorded yet.")
            empty.setObjectName("EmptyBody")
            self._activity_container.addWidget(empty)
            return

        for entry in entries:
            row = QFrame()
            row.setObjectName("ActivityRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 8, 0, 8)
            row_layout.setSpacing(10)

            text = QVBoxLayout()
            text.setSpacing(1)
            action = QLabel(entry.action.replace("_", " ").title())
            action.setObjectName("ActivityAction")
            meta = QLabel(
                f"{entry.user_name} · {entry.module} · {format_datetime(entry.created_at)}"
            )
            meta.setObjectName("ActivityMeta")
            text.addWidget(action)
            text.addWidget(meta)
            row_layout.addLayout(text, 1)

            badge = QLabel(entry.status.title())
            badge.setObjectName(
                "BadgeSuccess" if entry.status == "SUCCESS" else "BadgeDanger"
            )
            row_layout.addWidget(badge)
            self._activity_container.addWidget(row)

    def _render_status(self, summary: DashboardSummary) -> None:
        while self._status_container.count():
            item = self._status_container.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        status = summary.system_status
        if status is None:
            return

        rows = [
            (
                "Database",
                "Connected" if status.database_connected else "Unavailable",
                status.database_connected,
                status.database_detail,
            ),
            ("Schema version", status.schema_version, None, ""),
            ("Application version", status.app_version, None, ""),
            ("Signed in as", status.signed_in_user, None, ""),
            ("Authentication", status.authentication_status, True, ""),
        ]
        for key, value, ok, tooltip in rows:
            row = QFrame()
            row.setObjectName("StatusRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 8, 0, 8)
            key_label = QLabel(key)
            key_label.setObjectName("StatusKey")
            value_label = QLabel(value)
            value_label.setObjectName("StatusValue")
            if ok is not None:
                value_label.setProperty("ok", "true" if ok else "false")
            if tooltip:
                value_label.setToolTip(tooltip)
            row_layout.addWidget(key_label)
            row_layout.addStretch(1)
            row_layout.addWidget(value_label)
            self._status_container.addWidget(row)
