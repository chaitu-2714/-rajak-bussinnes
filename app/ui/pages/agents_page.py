"""AI Agents monitoring dashboard."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ai.agent_workflows.task_catalogue import tasks_for
from app.core.application import ApplicationContext
from app.core.constants import RecommendationStatus
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.confirmation_dialog import confirm
from app.ui.components.tables import DataTable
from app.ui.ui_utils import (
    muted_label,
    primary_button,
    secondary_button,
    show_error,
    show_info,
)
from app.ui.workers.orchestration_worker import ActionWorker
from app.utils.date_utils import format_datetime

logger = get_logger("ui.agents_page")

PERIOD_OPTIONS = (
    ("This month", "this_month"),
    ("Last month", "last_month"),
    ("This year", "this_year"),
    ("Last 30 days", "last_30_days"),
    ("All time", "all_time"),
)


class AgentCard(QFrame):
    """One agent summary card."""

    selected = Signal(str)

    def __init__(self, data: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatCard")
        self.setCursor(Qt.PointingHandCursor)
        self._agent_code = data["info"]["agent_code"]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        header = QHBoxLayout()
        name = QLabel(data["info"]["agent_name"])
        name.setObjectName("CardTitle")
        header.addWidget(name)
        header.addStretch(1)
        status = QLabel(data.get("status", "idle").title())
        status.setObjectName("Badge")
        header.addWidget(status)
        layout.addLayout(header)

        info = data["info"]
        tool_count = len(set(info["data_tools"]) | set(info["capabilities"]))
        stats = QLabel(
            f"{data.get('completed', 0)} completed · {data.get('failed', 0)} failed\n"
            f"Last run: {format_datetime(data.get('last_execution_at'), '%d %b %Y, %I:%M %p')}\n"
            f"{tool_count} tools · {data.get('open_recommendations', 0)} open recommendations"
        )
        stats.setObjectName("MutedLabel")
        stats.setWordWrap(True)
        layout.addWidget(stats)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        self.selected.emit(self._agent_code)
        super().mousePressEvent(event)


class RunAgentDialog(QFrame):
    """Small inline dialog for choosing a task and period."""

    def __init__(self, agent_code: str, parent: QWidget | None = None) -> None:
        from PySide6.QtWidgets import QDialog

        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Run agent")
        self.dialog.setMinimumWidth(420)
        layout = QVBoxLayout(self.dialog)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        layout.addWidget(QLabel("Task"))
        self.task_combo = QComboBox()
        for spec in tasks_for(agent_code):
            self.task_combo.addItem(spec.label, spec.task_type)
        layout.addWidget(self.task_combo)

        layout.addWidget(QLabel("Period"))
        self.period_combo = QComboBox()
        for label, value in PERIOD_OPTIONS:
            self.period_combo.addItem(label, value)
        layout.addWidget(self.period_combo)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = secondary_button("Cancel")
        cancel.clicked.connect(self.dialog.reject)
        run = primary_button("Run analysis")
        run.clicked.connect(self.dialog.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(run)
        layout.addLayout(buttons)

    def exec(self) -> bool:
        return bool(self.dialog.exec())

    def selection(self) -> tuple[str, str]:
        return str(self.task_combo.currentData()), str(self.period_combo.currentData())


class AgentsPage(QWidget):
    """Live monitoring of the five specialist agents."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._selected: str | None = None
        self._workers: list[Any] = []
        self._agents: list[dict[str, Any]] = []
        self._build()
        self.refresh()

    # -- UI ----------------------------------------------------------------
    def _can(self, permission: str) -> bool:
        return bool(self._principal and permission in self._principal.permissions)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        toolbar = QHBoxLayout()
        toolbar.addWidget(muted_label("Five specialist agents run on real business records."))
        toolbar.addStretch(1)
        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        toolbar.addWidget(self.refresh_button)
        self.run_button = primary_button("Run agent")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self._run_selected)
        toolbar.addWidget(self.run_button)
        layout.addLayout(toolbar)

        self.cards_grid = QGridLayout()
        self.cards_grid.setSpacing(12)
        layout.addLayout(self.cards_grid)

        self.detail_tabs = QTabWidget()
        self.detail_tabs.addTab(self._build_overview_tab(), "Overview")
        self.detail_tabs.addTab(self._build_findings_tab(), "Findings")
        self.detail_tabs.addTab(self._build_recommendations_tab(), "Recommendations")
        self.detail_tabs.addTab(self._build_executions_tab(), "Executions")
        layout.addWidget(self.detail_tabs, 1)

    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        self.overview_title = QLabel("Select an agent")
        self.overview_title.setObjectName("CardTitle")
        layout.addWidget(self.overview_title)

        self.overview_body = QPlainTextEdit()
        self.overview_body.setReadOnly(True)
        layout.addWidget(self.overview_body, 1)
        return page

    def _build_findings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        self.findings_table = DataTable(
            ["When", "Type", "Severity", "Finding", "Period"], stretch_columns=(3,)
        )
        layout.addWidget(self.findings_table)
        return page

    def _build_recommendations_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        self.recommendations_table = DataTable(
            ["When", "Priority", "Status", "Recommendation", "Reason"], stretch_columns=(3, 4)
        )
        layout.addWidget(self.recommendations_table)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.accept_button = secondary_button("Accept")
        self.accept_button.clicked.connect(lambda: self._set_status(RecommendationStatus.ACCEPTED))
        self.dismiss_button = secondary_button("Dismiss")
        self.dismiss_button.clicked.connect(lambda: self._set_status(RecommendationStatus.DISMISSED))
        self.done_button = secondary_button("Mark done")
        self.done_button.clicked.connect(lambda: self._set_status(RecommendationStatus.DONE))
        for button in (self.accept_button, self.dismiss_button, self.done_button):
            button.setEnabled(self._can("agents.execute"))
            actions.addWidget(button)
        layout.addLayout(actions)
        return page

    def _build_executions_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        self.executions_table = DataTable(
            ["When", "Task", "Status", "Confidence", "Duration (ms)", "Summary"],
            stretch_columns=(5,),
        )
        layout.addWidget(self.executions_table)
        return page

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        try:
            self._agents = self._context.agent_manager.list_agents()
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self._render_cards()
        if self._selected is None and self._agents:
            self._select(self._agents[0]["info"]["agent_code"])
        elif self._selected:
            self._select(self._selected)

    def _render_cards(self) -> None:
        while self.cards_grid.count():
            item = self.cards_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for index, data in enumerate(self._agents):
            card = AgentCard(data)
            card.selected.connect(self._select)
            self.cards_grid.addWidget(card, 0, index)

    def _select(self, agent_code: str) -> None:
        self._selected = agent_code
        self.run_button.setEnabled(self._can("agents.execute"))
        try:
            detail = self._context.agent_manager.agent_detail(agent_code)
            memory = self._context.agent_manager.memory(agent_code, limit=5)
        except BizPilotError as exc:
            show_error(self, exc)
            return

        info = detail["info"]
        stats = detail["stats"]
        self.overview_title.setText(info["agent_name"])
        self.overview_body.setPlainText(
            "\n".join(
                [
                    info["description"],
                    "",
                    f"Executions: {stats['executions']} "
                    f"({stats['completed']} completed, {stats['failed']} failed)",
                    f"Average duration: {stats['avg_execution_ms']} ms",
                    f"Last run: {format_datetime(stats['last_execution_at'], '%d %b %Y, %I:%M %p')}",
                    f"Open recommendations: {stats['open_recommendations']}",
                    "",
                    "Supported intents:",
                    *[f"  • {intent}" for intent in info["intents"]],
                    "",
                    "Data tools:",
                    *[f"  • {tool}" for tool in info["data_tools"]],
                    "",
                    "Analysis capabilities:",
                    *[f"  • {capability}" for capability in info["capabilities"]],
                    "",
                    "Recent memory:",
                    *[
                        f"  • {entry['memory_type']} at {format_datetime(entry['created_at'], '%d %b %Y %I:%M %p')}"
                        for entry in memory
                    ],
                ]
            )
        )

        findings = detail["findings"]
        self.findings_table.set_rows(
            [
                [
                    format_datetime(finding["created_at"], "%d %b %Y %I:%M"),
                    finding["finding_type"].replace("_", " ").title(),
                    finding["severity"],
                    finding["description"],
                    finding["reporting_period"] or "—",
                ]
                for finding in findings
            ],
            row_ids=[finding["id"] for finding in findings],
            sort_keys={0: [finding["created_at"] for finding in findings]},
        )

        recommendations = detail["recommendations"]
        self.recommendations_table.set_rows(
            [
                [
                    format_datetime(item["created_at"], "%d %b %Y %I:%M"),
                    item["priority"],
                    item["status"],
                    item["recommendation"],
                    item["reason"],
                ]
                for item in recommendations
            ],
            row_ids=[item["id"] for item in recommendations],
        )

        executions = detail["executions"]
        self.executions_table.set_rows(
            [
                [
                    format_datetime(execution["completed_at"], "%d %b %Y %I:%M"),
                    execution["task_type"].replace("_", " ").title(),
                    execution["status"],
                    f"{execution['confidence']:.2f}" if execution["confidence"] else "—",
                    f"{execution['execution_time']:.0f}" if execution["execution_time"] else "—",
                    (execution["summary"] or execution["error"] or "")[:160],
                ]
                for execution in executions
            ],
            row_ids=[execution["id"] for execution in executions],
        )

    # -- actions -----------------------------------------------------------
    def _run_selected(self) -> None:
        if not self._selected:
            return
        dialog = RunAgentDialog(self._selected, self)
        if not dialog.exec():
            return
        task_type, period = dialog.selection()
        agent_code = self._selected
        worker = ActionWorker(
            lambda: self._context.agent_manager.run_agent(
                agent_code,
                period=None if period == "all_time" else period,
                task_type=task_type,
            ),
            "Agent run",
        )
        worker.finished_ok.connect(lambda result: self._on_run_finished(result))
        worker.failed.connect(lambda message: show_error(self, BizPilotError(message)))
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        self.run_button.setEnabled(False)
        worker.start()

    def _on_run_finished(self, result: Any) -> None:
        self.run_button.setEnabled(self._can("agents.execute"))
        self.refresh()
        show_info(
            self,
            f"{result.agent_id} finished: {result.status}\n"
            f"Confidence {result.confidence:.2f} · {len(result.findings)} finding(s) · "
            f"{len(result.recommendations)} recommendation(s)\n\n{result.summary}",
            title="Agent run complete",
        )

    def _set_status(self, status: str) -> None:
        recommendation_id = self.recommendations_table.selected_id()
        if recommendation_id is None:
            show_info(self, "Select a recommendation first.")
            return
        try:
            self._context.agent_manager.update_recommendation(int(recommendation_id), status)
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self._select(self._selected or "")

    # -- lifecycle ---------------------------------------------------------
    def shutdown(self) -> None:
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(3000)
            except RuntimeError:
                pass
