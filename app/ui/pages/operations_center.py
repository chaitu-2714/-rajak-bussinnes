"""Autonomous Operations Center: workflows, approvals and autonomy settings."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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

logger = get_logger("ui.autonomy")

MODES = (("Automatic", "AUTOMATIC"), ("Approval required", "APPROVAL"), ("Restricted", "RESTRICTED"))


class OperationsCenterPage(QWidget):
    """Dashboard, workflow detail, approval center and autonomy settings."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._workers: list[Any] = []
        self._selected_workflow: str | None = None
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
        self.card_total = StatCard("Workflows", "0", "recorded runs")
        self.card_active = StatCard("Active", "0", "pending or running")
        self.card_completed = StatCard("Completed", "0", "verified runs")
        self.card_failed = StatCard("Failed", "0", "need attention")
        self.card_approvals = StatCard("Pending approvals", "0", "waiting for a human")
        for index, card in enumerate(
            (self.card_total, self.card_active, self.card_completed, self.card_failed, self.card_approvals)
        ):
            cards.addWidget(card, 0, index)
        layout.addLayout(cards)

        starter = QHBoxLayout()
        starter.addWidget(QLabel("Workflow"))
        self.type_combo = QComboBox()
        for entry in self._context.autonomy_service.workflow_catalogue():
            self.type_combo.addItem(entry["label"], entry["workflow_type"])
        starter.addWidget(self.type_combo)
        self.objective_input = QLineEdit()
        self.objective_input.setPlaceholderText("Objective (optional)…")
        starter.addWidget(self.objective_input, 1)
        self.start_button = primary_button("Start workflow")
        self.start_button.setEnabled(self._can("automation.execute"))
        self.start_button.clicked.connect(self._start_workflow)
        starter.addWidget(self.start_button)
        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        starter.addWidget(self.refresh_button)
        layout.addLayout(starter)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_workflows_tab(), "Workflows")
        self.tabs.addTab(self._build_approvals_tab(), "Approval Center")
        self.tabs.addTab(self._build_autonomy_tab(), "Autonomy Settings")
        layout.addWidget(self.tabs, 1)

    def _build_workflows_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)

        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.workflows_table = DataTable(
            ["Objective", "Type", "Status", "Tasks", "Created"],
            stretch_columns=(0,),
        )
        self.workflows_table.table.itemSelectionChanged.connect(self._on_workflow_selected)
        left_layout.addWidget(self.workflows_table, 1)

        buttons = QHBoxLayout()
        self.resume_button = secondary_button("Resume")
        self.resume_button.clicked.connect(lambda: self._workflow_action("resume"))
        self.retry_button = secondary_button("Retry")
        self.retry_button.clicked.connect(lambda: self._workflow_action("retry"))
        self.cancel_button = secondary_button("Cancel")
        self.cancel_button.clicked.connect(lambda: self._workflow_action("cancel"))
        self.rollback_button = secondary_button("Roll back")
        self.rollback_button.clicked.connect(lambda: self._workflow_action("rollback"))
        for button in (
            self.resume_button,
            self.retry_button,
            self.cancel_button,
            self.rollback_button,
        ):
            button.setEnabled(self._can("automation.execute"))
            buttons.addWidget(button)
        buttons.addStretch(1)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_text = QPlainTextEdit()
        self.detail_text.setReadOnly(True)
        right_layout.addWidget(self.detail_text, 1)
        self.tasks_table = DataTable(
            ["Task", "Type", "Agent / action", "Status", "Risk", "Retries", "Error"],
            stretch_columns=(0,),
        )
        right_layout.addWidget(self.tasks_table, 1)
        splitter.addWidget(right)
        splitter.setSizes([640, 760])
        layout.addWidget(splitter, 1)
        return page

    def _build_approvals_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        self.approvals_table = DataTable(
            ["Requested", "Action", "Impact", "Risk", "Requested by", "Expires", "Status"],
            stretch_columns=(1,),
        )
        self.approvals_table.table.itemSelectionChanged.connect(self._show_approval_details)
        layout.addWidget(self.approvals_table, 1)
        self.approval_details = QPlainTextEdit()
        self.approval_details.setReadOnly(True)
        layout.addWidget(self.approval_details, 1)

        row = QHBoxLayout()
        self.note_input = QLineEdit()
        self.note_input.setPlaceholderText("Decision note (required to reject)…")
        row.addWidget(self.note_input, 1)
        self.approve_button = primary_button("Approve")
        self.approve_button.clicked.connect(lambda: self._decide("approve"))
        self.reject_button = secondary_button("Reject")
        self.reject_button.clicked.connect(lambda: self._decide("reject"))
        self.expire_button = secondary_button("Expire stale")
        self.expire_button.clicked.connect(self._expire_approvals)
        for button in (self.approve_button, self.reject_button):
            button.setEnabled(self._can("approvals.approve"))
        self.expire_button.setEnabled(self._can("automation.execute"))
        for button in (self.approve_button, self.reject_button, self.expire_button):
            row.addWidget(button)
        layout.addLayout(row)
        return page

    def _build_autonomy_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(
            muted_label(
                "Autonomy is default-deny: an action runs only if a policy allows it, "
                "and business-changing actions always need a human approval."
            )
        )
        self.policies_table = DataTable(
            ["Action", "Mode", "Max amount", "Approval", "Daily limit", "Enabled"],
            stretch_columns=(0,),
        )
        self.policies_table.table.itemSelectionChanged.connect(self._show_policy_editor)
        layout.addWidget(self.policies_table, 1)

        editor = QHBoxLayout()
        editor.addWidget(QLabel("Mode"))
        self.mode_combo = QComboBox()
        for label, value in MODES:
            self.mode_combo.addItem(label, value)
        editor.addWidget(self.mode_combo)
        editor.addWidget(QLabel("Max amount"))
        self.max_amount_input = QLineEdit()
        self.max_amount_input.setPlaceholderText("e.g. 5000")
        self.max_amount_input.setMaximumWidth(120)
        editor.addWidget(self.max_amount_input)
        editor.addWidget(QLabel("Daily limit"))
        self.daily_limit_input = QLineEdit()
        self.daily_limit_input.setPlaceholderText("e.g. 20")
        self.daily_limit_input.setMaximumWidth(90)
        editor.addWidget(self.daily_limit_input)
        self.enabled_check = QCheckBox("Enabled")
        editor.addWidget(self.enabled_check)
        self.save_policy_button = primary_button("Save policy")
        self.save_policy_button.clicked.connect(self._save_policy)
        self.save_policy_button.setEnabled(self._can("agents.configure"))
        editor.addWidget(self.save_policy_button)
        editor.addStretch(1)
        layout.addLayout(editor)

        layout.addWidget(muted_label("Schedules"))
        self.schedules_table = DataTable(
            ["Schedule", "Workflow", "Frequency", "Time", "Next run", "Last run", "Status"],
            stretch_columns=(0,),
        )
        layout.addWidget(self.schedules_table, 1)
        schedule_row = QHBoxLayout()
        self.schedule_enable_button = secondary_button("Enable / disable selected")
        self.schedule_enable_button.clicked.connect(self._toggle_schedule)
        self.schedule_enable_button.setEnabled(self._can("agents.configure"))
        schedule_row.addWidget(self.schedule_enable_button)
        self.run_schedules_button = secondary_button("Run due schedules now")
        self.run_schedules_button.clicked.connect(self._run_schedules)
        self.run_schedules_button.setEnabled(self._can("automation.execute"))
        schedule_row.addWidget(self.run_schedules_button)
        self.process_events_button = secondary_button("Process business events")
        self.process_events_button.clicked.connect(self._process_events)
        self.process_events_button.setEnabled(self._can("automation.execute"))
        schedule_row.addWidget(self.process_events_button)
        schedule_row.addStretch(1)
        layout.addLayout(schedule_row)
        return page

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        try:
            stats = self._context.autonomy_service.dashboard_stats()
            workflows = self._context.autonomy_service.list_workflows(limit=50)
        except BizPilotError as exc:
            show_error(self, exc)
            return
        # A read-only role may not see approvals, policies or schedules.
        try:
            approvals = self._context.autonomy_service.all_approvals(limit=50)
        except BizPilotError:
            approvals = []
        try:
            policies = self._context.autonomy_service.policies()
        except BizPilotError:
            policies = []
        try:
            schedules = self._context.autonomy_service.schedules()
        except BizPilotError:
            schedules = []

        self.card_total.set_value(str(stats["total"]), True)
        self.card_active.set_value(str(stats["active"]), True)
        self.card_completed.set_value(str(stats["completed"]), True)
        self.card_failed.set_value(str(stats["failed"]), True)
        self.card_approvals.set_value(str(stats["pending_approvals"]), True)

        self.workflows_table.set_rows(
            [
                [
                    view.objective[:52],
                    view.workflow_type.replace("_", " ").title(),
                    view.status,
                    f"{view.tasks_completed}/{view.tasks_total}",
                    format_datetime(view.created_at, "%d %b %I:%M"),
                ]
                for view in workflows
            ],
            row_ids=[view.workflow_ref for view in workflows],
        )
        self._workflows = {view.workflow_ref: view for view in workflows}

        self.approvals_table.set_rows(
            [
                [
                    format_datetime(approval.created_at, "%d %b %I:%M"),
                    approval.requested_action.replace("_", " "),
                    approval.financial_impact or "—",
                    approval.risk_level,
                    approval.requested_by_name or str(approval.requested_by or "—"),
                    format_datetime(approval.expires_at, "%d %b %I:%M"),
                    approval.status,
                ]
                for approval in approvals
            ],
            row_ids=[approval.approval_ref for approval in approvals],
        )
        self._approvals = {approval.approval_ref: approval for approval in approvals}

        self.policies_table.set_rows(
            [
                [
                    policy.action_name,
                    policy.execution_mode.replace("_", " ").title(),
                    policy.maximum_amount or "—",
                    "Yes" if policy.approval_required else "No",
                    str(policy.daily_execution_limit or "—"),
                    "Yes" if policy.enabled else "No",
                ]
                for policy in policies
            ],
            row_ids=[policy.action_name for policy in policies],
        )
        self._policies = {policy.action_name: policy for policy in policies}

        self.schedules_table.set_rows(
            [
                [
                    schedule["name"],
                    schedule["workflow_type"].replace("_", " ").title(),
                    schedule["frequency"].replace("_", " ").title(),
                    schedule["time_of_day"],
                    format_datetime(schedule["next_run_at"], "%d %b %I:%M"),
                    format_datetime(schedule["last_run_at"], "%d %b %I:%M"),
                    "Enabled" if schedule["enabled"] else "Disabled",
                ]
                for schedule in schedules
            ],
            row_ids=[schedule["schedule_key"] for schedule in schedules],
        )
        self._schedules = {schedule["schedule_key"]: schedule for schedule in schedules}

        if self._selected_workflow:
            self._show_workflow(self._selected_workflow)

    # -- workflow detail ---------------------------------------------------
    def _on_workflow_selected(self) -> None:
        row = self.workflows_table.table.currentRow()
        if row < 0:
            return
        item = self.workflows_table.table.item(row, 0)
        if item is not None and item.data(Qt.UserRole):
            self._show_workflow(str(item.data(Qt.UserRole)))

    def _show_workflow(self, workflow_ref: str) -> None:
        try:
            detail = self._context.autonomy_service.get_workflow(workflow_ref)
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self._selected_workflow = workflow_ref
        view = detail.workflow
        lines = [
            f"Objective: {view.objective}",
            f"Type: {view.workflow_type}   Trigger: {view.trigger_type} ({view.trigger_ref or 'manual'})",
            f"Status: {view.status}   Phase: {view.phase or '-'}   Retries: {view.retry_count}",
            f"Tasks: {view.tasks_completed}/{view.tasks_total} completed, {view.tasks_failed} failed",
            f"Pending approvals: {view.pending_approvals}",
            f"Created: {format_datetime(view.created_at, '%d %b %Y %I:%M %p')}",
            f"Started: {format_datetime(view.started_at, '%d %b %Y %I:%M %p')}",
            f"Completed: {format_datetime(view.completed_at, '%d %b %Y %I:%M %p')}",
        ]
        if view.error:
            lines.append(f"Error: {view.error}")
        if detail.verification:
            lines.append(
                f"Verification: {'passed' if detail.verification.get('verified') else 'not passed'}"
            )
            for check in detail.verification.get("checks", []):
                lines.append(
                    f"  • {check['record_type']} #{check['record_id']}: "
                    f"{'found' if check['verified'] else 'MISSING'} ({check['detail']})"
                )
        if detail.approvals:
            lines.append("Approvals:")
            for approval in detail.approvals:
                lines.append(
                    f"  • {approval['action']} — {approval['status']}"
                    f" (impact {approval['financial_impact'] or '—'})"
                )
        if detail.logs:
            lines.append("Recent activity:")
            for entry in detail.logs[-8:]:
                lines.append(f"  • [{entry['level']}] {entry['event']}: {entry['message'][:90]}")
        self.detail_text.setPlainText("\n".join(lines))

        self.tasks_table.set_rows(
            [
                [
                    task.task_key,
                    task.task_type.replace("_", " ").title(),
                    task.assigned_agent or (task.action_name or "—"),
                    task.status,
                    task.risk_level,
                    str(task.retry_count),
                    (task.error or "")[:60],
                ]
                for task in detail.tasks
            ],
            row_ids=[task.task_key for task in detail.tasks],
        )

    # -- approval detail ---------------------------------------------------
    def _show_approval_details(self) -> None:
        row = self.approvals_table.table.currentRow()
        if row < 0:
            return
        item = self.approvals_table.table.item(row, 0)
        if item is None:
            return
        approval_ref = item.data(Qt.UserRole)
        approval = self._approvals.get(str(approval_ref))
        if approval is None:
            return
        lines = [
            f"Approval: {approval.approval_ref}   Status: {approval.status}",
            f"Action: {approval.requested_action}   Risk: {approval.risk_level}",
            f"Financial impact: {approval.financial_impact or 'not calculable'}",
            f"Requested by: {approval.requested_by_name or approval.requested_by}",
            f"Workflow: {approval.workflow_ref or '—'}   Task: {approval.task_key or '—'}",
            f"Expires: {format_datetime(approval.expires_at, '%d %b %Y %I:%M %p')}",
            "",
            f"Reason: {approval.reason}",
            "",
            "Proposed action details:",
            *[f"  {key}: {value}" for key, value in approval.action_details.items()],
            "",
            "Supporting evidence:",
            *[
                f"  {item.get('task', 'task')}: {item.get('summary', '')[:100]}"
                for item in (approval.evidence.get("task_summaries") or [])
            ],
        ]
        if approval.decision_note:
            lines.append(f"\nDecision note: {approval.decision_note}")
        if approval.execution_result:
            lines.append(f"Execution: {approval.execution_result.get('summary', '')}")
        self.approval_details.setPlainText("\n".join(lines))

    # -- actions -----------------------------------------------------------
    def _run_worker(self, callable_, label: str, on_success=None) -> None:
        worker = ActionWorker(callable_, label)
        if on_success is not None:
            worker.finished_ok.connect(on_success)
        worker.failed.connect(lambda message: show_error(self, BizPilotError(message)))
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def _start_workflow(self) -> None:
        workflow_type = self.type_combo.currentData()
        objective = self.objective_input.text().strip() or None
        service = self._context.autonomy_service
        self.start_button.setEnabled(False)
        self._run_worker(
            lambda: service.start_workflow(
                service.create_workflow(workflow_type, objective=objective).workflow_ref
            ),
            "Workflow",
            self._on_workflow_finished,
        )

    def _on_workflow_finished(self, detail: Any) -> None:
        self.start_button.setEnabled(self._can("automation.execute"))
        self.refresh()
        if detail is not None:
            self._show_workflow(detail.workflow.workflow_ref)
            show_info(
                self,
                f"Workflow {detail.workflow.status} · "
                f"{detail.workflow.tasks_completed}/{detail.workflow.tasks_total} tasks completed"
                + (
                    f"\nWaiting for {detail.workflow.pending_approvals} approval(s)."
                    if detail.workflow.pending_approvals
                    else ""
                ),
                title="Workflow finished",
            )

    def _workflow_action(self, action: str) -> None:
        if not self._selected_workflow:
            show_info(self, "Select a workflow first.")
            return
        workflow_ref = self._selected_workflow
        service = self._context.autonomy_service
        if action == "rollback":
            if not confirm(
                self,
                "Roll back this workflow?",
                "Only reversible actions are compensated; everything else is left untouched "
                "and listed in the result.",
                confirm_text="Roll back",
                destructive=True,
            ):
                return
            self._run_worker(
                lambda: service.rollback_workflow(workflow_ref, reason="Operator rollback"),
                "Rollback",
                lambda result: (self.refresh(), show_info(self, str(result))),
            )
            return
        call = {
            "resume": service.resume_workflow,
            "retry": service.retry_workflow,
            "cancel": service.cancel_workflow,
        }[action]
        self._run_worker(lambda: call(workflow_ref), action.title(), lambda _: self.refresh())

    def _decide(self, decision: str) -> None:
        row = self.approvals_table.table.currentRow()
        if row < 0:
            show_info(self, "Select an approval first.")
            return
        item = self.approvals_table.table.item(row, 0)
        approval_ref = str(item.data(Qt.UserRole)) if item else ""
        note = self.note_input.text().strip()
        service = self._context.autonomy_service
        if decision == "approve":
            if not confirm(
                self,
                "Approve this action?",
                "Approving executes the action immediately through the business service.",
                confirm_text="Approve",
            ):
                return
            self._run_worker(
                lambda: service.approve(approval_ref, note=note or None),
                "Approve",
                lambda result: (self.refresh(), show_info(self, f"Approval {result.status}")),
            )
        else:
            if len(note) < 3:
                show_info(self, "A rejection reason is required.")
                return
            self._run_worker(
                lambda: service.reject(approval_ref, reason=note),
                "Reject",
                lambda result: (self.refresh(), show_info(self, f"Approval {result.status}")),
            )

    def _expire_approvals(self) -> None:
        service = self._context.autonomy_service
        self._run_worker(
            service.expire_approvals,
            "Expire",
            lambda count: (self.refresh(), show_info(self, f"{count} approval(s) expired")),
        )

    def _show_policy_editor(self) -> None:
        row = self.policies_table.table.currentRow()
        if row < 0:
            return
        item = self.policies_table.table.item(row, 0)
        policy = self._policies.get(str(item.data(Qt.UserRole))) if item else None
        if policy is None:
            return
        index = self.mode_combo.findData(policy.execution_mode)
        if index >= 0:
            self.mode_combo.setCurrentIndex(index)
        self.max_amount_input.setText((policy.maximum_amount or "").replace(",", ""))
        self.daily_limit_input.setText(
            str(policy.daily_execution_limit) if policy.daily_execution_limit else ""
        )
        self.enabled_check.setChecked(policy.enabled)

    def _save_policy(self) -> None:
        row = self.policies_table.table.currentRow()
        if row < 0:
            show_info(self, "Select an action policy first.")
            return
        item = self.policies_table.table.item(row, 0)
        action_name = str(item.data(Qt.UserRole)) if item else ""
        changes = {
            "execution_mode": self.mode_combo.currentData(),
            "maximum_amount": self.max_amount_input.text().strip() or None,
            "daily_execution_limit": self.daily_limit_input.text().strip() or None,
            "enabled": self.enabled_check.isChecked(),
        }
        service = self._context.autonomy_service
        self._run_worker(
            lambda: service.update_policy(action_name, changes=changes),
            "Policy",
            lambda policy: (
                self.refresh(),
                show_info(self, f"{policy.action_name}: {policy.execution_mode}"),
            ),
        )

    def _toggle_schedule(self) -> None:
        row = self.schedules_table.table.currentRow()
        if row < 0:
            show_info(self, "Select a schedule first.")
            return
        item = self.schedules_table.table.item(row, 0)
        key = str(item.data(Qt.UserRole)) if item else ""
        schedule = self._schedules.get(key)
        if schedule is None:
            return
        service = self._context.autonomy_service
        self._run_worker(
            lambda: service.update_schedule(key, changes={"enabled": not schedule["enabled"]}),
            "Schedule",
            lambda _: self.refresh(),
        )

    def _run_schedules(self) -> None:
        service = self._context.autonomy_service
        self._run_worker(
            service.run_due_schedules,
            "Schedules",
            lambda result: (
                self.refresh(),
                show_info(self, f"Ran {len(result.get('ran', []))} schedule(s)"),
            ),
        )

    def _process_events(self) -> None:
        service = self._context.autonomy_service
        self._run_worker(
            service.process_events,
            "Events",
            lambda result: (
                self.refresh(),
                show_info(
                    self,
                    f"Created {result.get('created', 0)} workflow(s), "
                    f"skipped {result.get('skipped', 0)}.",
                ),
            ),
        )

    # -- lifecycle ---------------------------------------------------------
    def shutdown(self) -> None:
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(5000)
            except RuntimeError:
                pass
