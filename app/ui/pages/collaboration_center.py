"""AI Collaboration Center: run and inspect multi-agent collaborations."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.confirmation_dialog import confirm
from app.ui.components.stat_card import StatCard
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

logger = get_logger("ui.collaboration")

PERIOD_OPTIONS = (
    ("This month", "this_month"),
    ("Last month", "last_month"),
    ("This year", "this_year"),
    ("All time", None),
)


class CollaborationCenterPage(QWidget):
    """Dashboard plus detail view for multi-agent collaborations."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._workers: list[Any] = []
        self._selected: str | None = None
        self._build()
        self.refresh()

    # -- permissions -------------------------------------------------------
    def _can(self, permission: str) -> bool:
        return bool(self._principal and permission in self._principal.permissions)

    # -- UI ----------------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        cards = QGridLayout()
        cards.setSpacing(10)
        self.card_total = StatCard("Collaborations", "0", "recorded runs")
        self.card_active = StatCard("Active", "0", "pending or running")
        self.card_completed = StatCard("Completed", "0", "final decisions")
        self.card_partial = StatCard("Partial / failed", "0", "need attention")
        self.card_conflicts = StatCard("Open conflicts", "0", "unresolved disagreements")
        for index, card in enumerate(
            (self.card_total, self.card_active, self.card_completed, self.card_partial, self.card_conflicts)
        ):
            cards.addWidget(card, 0, index)
        layout.addLayout(cards)

        starter = QHBoxLayout()
        starter.addWidget(QLabel("Scenario"))
        self.scenario_combo = QComboBox()
        for scenario in self._context.collaboration_service.scenarios():
            self.scenario_combo.addItem(scenario["label"], scenario["key"])
        self.scenario_combo.currentIndexChanged.connect(self._sync_objective)
        starter.addWidget(self.scenario_combo)

        self.period_combo = QComboBox()
        for label, value in PERIOD_OPTIONS:
            self.period_combo.addItem(label, value)
        starter.addWidget(self.period_combo)

        self.objective_input = QLineEdit()
        self.objective_input.setPlaceholderText("Business objective…")
        starter.addWidget(self.objective_input, 1)

        self.start_button = primary_button("Start collaboration")
        self.start_button.setEnabled(self._can("agents.execute"))
        self.start_button.clicked.connect(self._start)
        starter.addWidget(self.start_button)
        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        starter.addWidget(self.refresh_button)
        layout.addLayout(starter)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(muted_label("Collaboration history"))
        self.table = DataTable(
            ["Objective", "Scenario", "Status", "Progress", "Findings", "Conflicts", "Created"],
            stretch_columns=(0,),
        )
        self.table.selection_changed = self._on_selection
        self.table.table.itemSelectionChanged.connect(self._on_selection)
        left_layout.addWidget(self.table, 1)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_overview_tab(), "Overview")
        self.tabs.addTab(self._build_messages_tab(), "Messages")
        self.tabs.addTab(self._build_findings_tab(), "Findings")
        self.tabs.addTab(self._build_conflicts_tab(), "Conflicts")
        self.tabs.addTab(self._build_decision_tab(), "Decision")
        right_layout.addWidget(self.tabs)
        splitter.addWidget(right)
        splitter.setSizes([560, 840])
        layout.addWidget(splitter, 1)

        self._sync_objective()

    def _build_overview_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.overview_text = QPlainTextEdit()
        self.overview_text.setReadOnly(True)
        layout.addWidget(self.overview_text, 1)
        self.tasks_table = DataTable(
            ["Task", "Agent", "Status", "Depends on", "Attempts", "Duration (ms)", "Error"],
            stretch_columns=(0,),
        )
        layout.addWidget(self.tasks_table, 1)
        return page

    def _build_messages_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.messages_table = DataTable(
            ["Time", "From", "To", "Type", "Task"], stretch_columns=(1,)
        )
        layout.addWidget(self.messages_table)
        return page

    def _build_findings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.findings_table = DataTable(
            ["Agent", "Type", "Severity", "Validation", "Finding", "Period"],
            stretch_columns=(4,),
        )
        layout.addWidget(self.findings_table)
        return page

    def _build_conflicts_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.conflicts_table = DataTable(
            ["Type", "Agents", "Status", "Description"], stretch_columns=(3,)
        )
        layout.addWidget(self.conflicts_table, 1)
        self.resolution_text = QPlainTextEdit()
        self.resolution_text.setReadOnly(True)
        layout.addWidget(self.resolution_text, 1)
        return page

    def _build_decision_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.decision_text = QPlainTextEdit()
        self.decision_text.setReadOnly(True)
        layout.addWidget(self.decision_text, 1)
        self.actions_table = DataTable(
            ["Priority", "Action", "Cost", "Approvals"],
            stretch_columns=(1,),
        )
        layout.addWidget(self.actions_table, 1)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.csv_button = secondary_button("Export CSV")
        self.csv_button.clicked.connect(lambda: self._export("csv"))
        self.pdf_button = secondary_button("Export PDF")
        self.pdf_button.clicked.connect(lambda: self._export("pdf"))
        for button in (self.csv_button, self.pdf_button):
            button.setEnabled(self._can("agents.execute"))
            actions.addWidget(button)
        layout.addLayout(actions)
        return page

    # -- data --------------------------------------------------------------
    def _sync_objective(self) -> None:
        for scenario in self._context.collaboration_service.scenarios():
            if scenario["key"] == self.scenario_combo.currentData():
                self.objective_input.setText(scenario["objective"])
                return

    def refresh(self) -> None:
        try:
            stats = self._context.collaboration_service.dashboard_stats()
            rows = self._context.collaboration_service.list_collaborations(limit=50)
        except BizPilotError as exc:
            show_error(self, exc)
            return

        self.card_total.set_value(str(stats["total"]), True)
        self.card_active.set_value(str(stats["active"]), True)
        self.card_completed.set_value(str(stats["completed"]), True)
        self.card_partial.set_value(
            str(stats["partial"] + stats["failed"] + stats["cancelled"]), True
        )
        self.card_conflicts.set_value(str(stats["unresolved_conflicts"]), True)

        self.table.set_rows(
            [
                [
                    view.objective[:60],
                    view.scenario.replace("_", " ").title(),
                    view.status,
                    f"{view.tasks_completed}/{view.tasks_total}",
                    str(view.findings),
                    str(view.conflicts),
                    format_datetime(view.created_at, "%d %b %I:%M"),
                ]
                for view in rows
            ],
            row_ids=[view.collaboration_id for view in rows],
        )
        if rows and self._selected is None:
            self.table.table.selectRow(0)
            self._select(rows[0].collaboration_id)
        elif self._selected:
            self._select(self._selected)

    def _on_selection(self) -> None:
        collaboration_id = self._selected_by_row()
        if collaboration_id:
            self._select(collaboration_id)

    def _selected_by_row(self) -> str | None:
        row = self.table.table.currentRow()
        if row < 0:
            return None
        item = self.table.table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        return str(value) if value is not None else None

    def _select(self, collaboration_id: str | None) -> None:
        if not collaboration_id:
            return
        self._selected = collaboration_id
        try:
            detail = self._context.collaboration_service.get_detail(collaboration_id)
        except BizPilotError as exc:
            show_error(self, exc)
            return

        view = detail.collaboration
        lines = [
            f"Objective: {view.objective}",
            f"Scenario: {view.scenario}   Strategy: {view.strategy}   Status: {view.status}",
            f"Period: {view.reporting_period or 'all time'}   Phase: {view.phase or '-'}",
            f"Agents: {', '.join(view.agents)}",
            f"Tasks: {view.tasks_completed}/{view.tasks_total} completed, "
            f"{view.tasks_failed} failed or skipped",
            f"Messages exchanged: {len(detail.messages)}",
            f"Findings recorded: {len(detail.findings)}   Conflicts: {len(detail.conflicts)}",
            f"Created: {format_datetime(view.created_at, '%d %b %Y %I:%M %p')}",
        ]
        if view.error:
            lines.append(f"Error: {view.error}")
        context = detail.shared_context or {}
        if context:
            lines.extend(
                [
                    "",
                    "Shared business context:",
                    f"  Revenue: {context.get('financial_context', {}).get('revenue', 'n/a')}",
                    f"  Available cash: {context.get('available_budget', 'n/a')}",
                    f"  Low-stock products: {context.get('inventory_context', {}).get('low_stock_products', 'n/a')}",
                ]
            )
            for constraint in context.get("constraints", []):
                lines.append(f"  Constraint: {constraint}")
        if detail.dependencies:
            lines.append("")
            lines.append("Dependency graph (task ← depends on):")
            for task_key, depends_on in detail.dependencies:
                lines.append(f"  {task_key} ← {depends_on}")
        self.overview_text.setPlainText("\n".join(lines))

        self.tasks_table.set_rows(
            [
                [
                    task.task_key,
                    task.assigned_agent,
                    task.status,
                    ", ".join(task.dependencies) or "—",
                    str(task.attempts),
                    f"{task.execution_ms:.0f}" if task.execution_ms else "—",
                    (task.error or "")[:60],
                ]
                for task in detail.tasks
            ],
            row_ids=[task.task_key for task in detail.tasks],
        )

        self.messages_table.set_rows(
            [
                [
                    format_datetime(message["created_at"], "%d %b %I:%M:%S"),
                    message["sender"],
                    message["receiver"],
                    message["type"],
                    message["task_key"] or "—",
                ]
                for message in detail.messages
            ],
            row_ids=[index for index in range(len(detail.messages))],
        )

        self.findings_table.set_rows(
            [
                [
                    finding["agent_id"],
                    finding["finding_type"],
                    finding["severity"],
                    finding["validation_status"],
                    finding["description"],
                    finding["reporting_period"] or "—",
                ]
                for finding in detail.findings
            ],
            row_ids=[index for index in range(len(detail.findings))],
        )

        self.conflicts_table.set_rows(
            [
                [
                    conflict["conflict_type"],
                    ", ".join(conflict["agents"]),
                    conflict["status"],
                    conflict["description"],
                ]
                for conflict in detail.conflicts
            ],
            row_ids=[index for index in range(len(detail.conflicts))],
        )
        resolution_lines: list[str] = []
        for conflict in detail.conflicts:
            resolution = conflict.get("resolution") or {}
            resolution_lines.append(
                f"[{conflict['status']}] {conflict['conflict_type']}: "
                f"{resolution.get('explanation', 'no resolution recorded')}"
            )
        self.resolution_text.setPlainText("\n\n".join(resolution_lines) or "No conflicts detected.")

        decision = detail.decision
        if decision is None:
            self.decision_text.setPlainText("No decision yet for this collaboration.")
            self.actions_table.set_rows([])
            return

        operational = [
            f"  • {line}" for line in decision.operational_impact
        ] or ["  none recorded"]
        conflict_lines = [
            f"  • [{item.get('status')}] {item.get('description')}"
            for item in decision.conflicting_findings
        ] or ["  none"]
        approval_lines = [
            f"  • {approval}" for approval in decision.approval_requirements
        ] or ["  none"]

        lines = [
            f"DECISION STATUS: {decision.status}   Confidence: {decision.confidence}",
            "",
            "Executive summary",
            decision.executive_summary,
            "",
            f"Participating agents: {', '.join(decision.participating_agents)}",
            "",
            "Financial impact",
            *[f"  {key}: {value}" for key, value in decision.financial_impact.items()],
            "",
            "Operational impact",
            *operational,
            "",
            f"Risks identified: {len(decision.identified_risks)}",
            *[f"  • [{risk.severity}] {risk.description}" for risk in decision.identified_risks[:5]],
            "",
            "Conflicts",
            *conflict_lines,
            "",
            "Approvals required",
            *approval_lines,
            "",
            "Assumptions and limitations",
            *[f"  • {line}" for line in decision.assumptions],
            *[f"  • {line}" for line in decision.limitations],
        ]
        self.decision_text.setPlainText("\n".join(lines))
        self.actions_table.set_rows(
            [
                [
                    action.priority,
                    action.action,
                    str(action.estimated_cost or "—"),
                    ", ".join(action.required_approvals) or "—",
                ]
                for action in decision.recommended_actions
            ],
            row_ids=[index for index in range(len(decision.recommended_actions))],
        )

    # -- actions -----------------------------------------------------------
    def _start(self) -> None:
        objective = self.objective_input.text().strip()
        if len(objective) < 5:
            show_info(self, "Enter a business objective first.")
            return
        scenario = self.scenario_combo.currentData()
        period = self.period_combo.currentData()
        service = self._context.collaboration_service

        self.start_button.setEnabled(False)
        worker = ActionWorker(
            lambda: service.run_collaboration(objective, scenario=scenario, period=period),
            "Collaboration",
        )
        worker.finished_ok.connect(self._on_finished)
        worker.failed.connect(lambda message: self._on_failed(message))
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def _on_finished(self, detail: Any) -> None:
        self.start_button.setEnabled(self._can("agents.execute"))
        self.refresh()
        self._select(detail.collaboration.collaboration_id)
        decision = detail.decision
        if decision is None:
            show_info(
                self,
                f"Collaboration finished with status {detail.collaboration.status} and no decision.",
                title="Collaboration finished",
            )
            return
        show_info(
            self,
            f"Status: {detail.collaboration.status} · decision {decision.status} · "
            f"confidence {decision.confidence}\n\n{decision.executive_summary}",
            title="Collaboration finished",
        )

    def _on_failed(self, message: str) -> None:
        self.start_button.setEnabled(self._can("agents.execute"))
        show_error(self, BizPilotError(message))

    def _export(self, kind: str) -> None:
        if not self._selected:
            show_info(self, "Select a collaboration first.")
            return
        try:
            if kind == "csv":
                path = self._context.collaboration_service.export_decision_csv(self._selected)
            else:
                path = self._context.collaboration_service.export_decision_pdf(self._selected)
        except BizPilotError as exc:
            show_error(self, exc)
            return
        show_info(self, f"Exported to:\n{path}", title="Decision exported")

    # -- lifecycle ---------------------------------------------------------
    def shutdown(self) -> None:
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(5000)
            except RuntimeError:
                pass
