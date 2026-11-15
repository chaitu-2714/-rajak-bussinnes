"""Security and Governance Center."""

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

logger = get_logger("ui.security")


class SecurityCenterPage(QWidget):
    """Overview, access, AI governance, audit, monitoring and backups."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._workers: list[Any] = []
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
        self.card_failed = StatCard("Failed logins", "0", "recorded attempts")
        self.card_sessions = StatCard("Active sessions", "0", "signed in now")
        self.card_locked = StatCard("Locked accounts", "0", "temporarily blocked")
        self.card_events = StatCard("Open alerts", "0", "awaiting review")
        self.card_mfa = StatCard("MFA users", "0", "second factor enabled")
        for index, card in enumerate(
            (self.card_failed, self.card_sessions, self.card_locked, self.card_events, self.card_mfa)
        ):
            cards.addWidget(card, 0, index)
        layout.addLayout(cards)

        controls = QHBoxLayout()
        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        self.scan_button = primary_button("Run security scan")
        self.scan_button.clicked.connect(self._scan)
        self.scan_button.setEnabled(self._can("security.manage"))
        controls.addWidget(self.scan_button)
        controls.addStretch(1)
        self.integrity_label = muted_label("")
        controls.addWidget(self.integrity_label)
        layout.addLayout(controls)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_access_tab(), "Users & MFA")
        self.tabs.addTab(self._build_agent_tab(), "AI Governance")
        self.tabs.addTab(self._build_audit_tab(), "Audit Trail")
        self.tabs.addTab(self._build_monitoring_tab(), "Monitoring")
        self.tabs.addTab(self._build_backup_tab(), "Backup & Recovery")
        layout.addWidget(self.tabs, 1)

    def _build_access_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Users and MFA status"))
        self.users_table = DataTable(
            ["User", "Email", "Active", "MFA", "Enforced"], stretch_columns=(0,)
        )
        left_layout.addWidget(self.users_table, 1)
        row = QHBoxLayout()
        self.enforce_button = secondary_button("Enforce MFA for selected")
        self.enforce_button.clicked.connect(self._enforce_mfa)
        self.enforce_button.setEnabled(self._can("security.manage"))
        row.addWidget(self.enforce_button)
        row.addStretch(1)
        left_layout.addLayout(row)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(QLabel("Active sessions"))
        self.sessions_table = DataTable(
            ["User", "Started", "Expires", "Last activity"], stretch_columns=(0,)
        )
        right_layout.addWidget(self.sessions_table, 1)
        self.revoke_button = secondary_button("Revoke selected session")
        self.revoke_button.clicked.connect(self._revoke_session)
        self.revoke_button.setEnabled(self._can("security.manage"))
        right_layout.addWidget(self.revoke_button)

        right_layout.addWidget(QLabel("Your multi-factor authentication"))
        self.mfa_status_label = muted_label("")
        right_layout.addWidget(self.mfa_status_label)
        mfa_row = QHBoxLayout()
        self.mfa_code_input = QLineEdit()
        self.mfa_code_input.setPlaceholderText("6-digit code or recovery code")
        self.mfa_code_input.setMaximumWidth(220)
        mfa_row.addWidget(self.mfa_code_input)
        self.enroll_button = secondary_button("Start enrolment")
        self.enroll_button.clicked.connect(self._start_enrollment)
        mfa_row.addWidget(self.enroll_button)
        self.verify_button = secondary_button("Verify code")
        self.verify_button.clicked.connect(self._verify_enrollment)
        mfa_row.addWidget(self.verify_button)
        mfa_row.addStretch(1)
        right_layout.addLayout(mfa_row)
        self.mfa_detail = QPlainTextEdit()
        self.mfa_detail.setReadOnly(True)
        self.mfa_detail.setMaximumHeight(120)
        right_layout.addWidget(self.mfa_detail)
        splitter.addWidget(right)
        splitter.setSizes([620, 780])
        layout.addWidget(splitter, 1)
        return page

    def _build_agent_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(
            muted_label(
                "Agents can only use the tools, data categories and limits set here. "
                "They can never hold administrative permissions or approve actions."
            )
        )
        self.agent_table = DataTable(
            ["Agent", "Enabled", "Risk", "Allowed tools", "Cloud", "Depth", "Tasks", "Seconds"],
            stretch_columns=(3,),
        )
        layout.addWidget(self.agent_table, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Cloud AI eligible"))
        self.agent_cloud = QCheckBox()
        row.addWidget(self.agent_cloud)
        row.addWidget(QLabel("Allowed tools (comma separated)"))
        self.agent_tools = QLineEdit()
        self.agent_tools.setPlaceholderText("leave blank to inherit the user's tool permissions")
        row.addWidget(self.agent_tools, 1)
        self.save_agent_button = primary_button("Save agent policy")
        self.save_agent_button.clicked.connect(self._save_agent_policy)
        self.save_agent_button.setEnabled(self._can("security.manage"))
        row.addWidget(self.save_agent_button)
        layout.addLayout(row)

        layout.addWidget(QLabel("AI data governance (per classification and provider)"))
        self.governance_table = DataTable(
            ["Classification", "Provider", "Allowed", "Redaction", "Opt-in", "Notes"],
            stretch_columns=(5,),
        )
        layout.addWidget(self.governance_table, 1)
        return page

    def _build_audit_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(
            muted_label(
                "Audit records are append-only and hash-chained. The chain detects "
                "modification; it does not stop an administrator who controls the database."
            )
        )
        row = QHBoxLayout()
        self.verify_chain_button = primary_button("Verify audit chain")
        self.verify_chain_button.clicked.connect(self._verify_chain)
        row.addWidget(self.verify_chain_button)
        self.backfill_button = secondary_button("Chain existing records")
        self.backfill_button.clicked.connect(self._backfill_chain)
        self.backfill_button.setEnabled(self._can("security.manage"))
        row.addWidget(self.backfill_button)
        self.export_audit_button = secondary_button("Export audit trail")
        self.export_audit_button.clicked.connect(self._export_audit)
        self.export_audit_button.setEnabled(self._can("audit.export"))
        row.addWidget(self.export_audit_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.audit_table = DataTable(
            ["When", "User", "Action", "Module", "Entity", "Status"], stretch_columns=(2,)
        )
        layout.addWidget(self.audit_table, 1)
        self.integrity_text = QPlainTextEdit()
        self.integrity_text.setReadOnly(True)
        self.integrity_text.setMaximumHeight(110)
        layout.addWidget(self.integrity_text)
        return page

    def _build_monitoring_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(
            muted_label(
                "Alerts are indicators for review, not accusations. Confirm an incident "
                "only after checking the evidence."
            )
        )
        self.events_table = DataTable(
            ["When", "Type", "Severity", "User", "Description", "Status"], stretch_columns=(4,)
        )
        self.events_table.table.itemSelectionChanged.connect(self._show_event)
        layout.addWidget(self.events_table, 2)
        self.event_detail = QPlainTextEdit()
        self.event_detail.setReadOnly(True)
        layout.addWidget(self.event_detail, 1)
        row = QHBoxLayout()
        self.event_note = QLineEdit()
        self.event_note.setPlaceholderText("Review note (optional)…")
        row.addWidget(self.event_note, 1)
        self.ack_button = secondary_button("Acknowledge")
        self.ack_button.clicked.connect(lambda: self._review_event("ACKNOWLEDGED"))
        self.dismiss_button = secondary_button("Dismiss")
        self.dismiss_button.clicked.connect(lambda: self._review_event("DISMISSED"))
        self.confirm_button = secondary_button("Confirm incident")
        self.confirm_button.clicked.connect(lambda: self._review_event("CONFIRMED_INCIDENT"))
        for button in (self.ack_button, self.dismiss_button, self.confirm_button):
            button.setEnabled(self._can("security.manage"))
            row.addWidget(button)
        layout.addLayout(row)
        return page

    def _build_backup_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(
            muted_label(
                "Backups are verified before they are recorded, and a restore refuses any "
                "backup that fails validation. The current database is copied first."
            )
        )
        row = QHBoxLayout()
        self.backup_button = primary_button("Create verified backup")
        self.backup_button.clicked.connect(self._create_backup)
        self.backup_button.setEnabled(self._can("backup.create"))
        row.addWidget(self.backup_button)
        self.include_knowledge = QCheckBox("Include knowledge documents")
        row.addWidget(self.include_knowledge)
        row.addWidget(QLabel("Backup file"))
        self.backup_path = QLineEdit()
        self.backup_path.setPlaceholderText("path to a backup file to validate or restore")
        row.addWidget(self.backup_path, 1)
        self.validate_button = secondary_button("Validate")
        self.validate_button.clicked.connect(self._validate_backup)
        row.addWidget(self.validate_button)
        self.restore_button = secondary_button("Restore")
        self.restore_button.clicked.connect(self._restore_backup)
        self.restore_button.setEnabled(self._can("backup.restore"))
        row.addWidget(self.restore_button)
        layout.addLayout(row)

        self.backup_table = DataTable(
            ["Reference", "Operation", "File", "Size", "Integrity", "When"],
            stretch_columns=(2,),
        )
        layout.addWidget(self.backup_table, 1)
        self.backup_detail = QPlainTextEdit()
        self.backup_detail.setReadOnly(True)
        self.backup_detail.setMaximumHeight(110)
        layout.addWidget(self.backup_detail)
        return page

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        service = self._context.security_service
        self._run_worker(service.overview, "Overview", self._on_overview)
        if self._can("security.manage"):
            self._run_worker(service.mfa_roster, "Users", self._on_users)
        self._run_worker(service.active_sessions, "Sessions", self._on_sessions)
        self._run_worker(service.security_events, "Events", self._on_events)
        self._run_worker(service.agent_policies, "Agents", self._on_agents)
        self._run_worker(service.data_governance_policies, "Governance", self._on_governance)
        self._run_worker(service.backup_history, "Backups", self._on_backups)
        self._run_worker(self._mfa_status, "MFA", self._on_mfa_status)

    def _mfa_status(self) -> dict:
        return self._context.security_service.mfa_status()

    def _on_overview(self, data: Any) -> None:
        self.card_failed.set_value(str(data["failed_logins"]), True)
        self.card_sessions.set_value(str(data["active_sessions"]), True)
        self.card_locked.set_value(str(data["locked_accounts"]), True)
        self.card_events.set_value(str(data["open_security_events"]), True)
        self.card_mfa.set_value(f"{data['mfa_enabled_users']}/{data['total_users']}", True)
        integrity = data["audit_integrity"]
        self.integrity_label.setText(
            f"Audit chain: {'intact' if integrity['ok'] else 'BROKEN'} "
            f"({integrity['checked']} records checked)"
        )

    def _on_users(self, rows: Any) -> None:
        self._users = {row["user_id"]: row for row in rows}
        self.users_table.set_rows(
            [
                [
                    row["name"],
                    row["email"],
                    "Yes" if row["is_active"] else "No",
                    "Enabled" if row["mfa_enabled"] else "Not set",
                    "Yes" if row["mfa_enforced"] else "No",
                ]
                for row in rows
            ],
            row_ids=[row["user_id"] for row in rows],
        )

    def _on_sessions(self, rows: Any) -> None:
        self._sessions = {row["session_id"]: row for row in rows}
        self.sessions_table.set_rows(
            [
                [
                    row["user"],
                    format_datetime(row["created_at"], "%d %b %I:%M"),
                    format_datetime(row["expires_at"], "%d %b %I:%M"),
                    format_datetime(row["last_activity_at"], "%d %b %I:%M"),
                ]
                for row in rows
            ],
            row_ids=[row["session_id"] for row in rows],
        )

    def _on_mfa_status(self, status: Any) -> None:
        if status.get("enabled"):
            self.mfa_status_label.setText(
                f"MFA is enabled · recovery codes left: {status.get('recovery_codes_remaining')}"
            )
        else:
            self.mfa_status_label.setText("MFA is not enabled for your account")

    def _on_agents(self, rows: Any) -> None:
        self._agents = {row["agent_code"]: row for row in rows}
        self.agent_table.set_rows(
            [
                [
                    row["agent_code"].replace("_", " ").title(),
                    "Yes" if row["is_enabled"] else "No",
                    row["risk_classification"],
                    ", ".join(row["allowed_tools"]) or "inherits user tools",
                    "Yes" if row["cloud_ai_eligible"] else "No",
                    str(row["max_execution_depth"]),
                    str(row["max_task_count"]),
                    str(row["max_duration_seconds"]),
                ]
                for row in rows
            ],
            row_ids=[row["agent_code"] for row in rows],
        )

    def _on_governance(self, rows: Any) -> None:
        self.governance_table.set_rows(
            [
                [
                    row["classification"],
                    row["provider"],
                    "Yes" if row["allowed"] else "No",
                    "Yes" if row["requires_redaction"] else "No",
                    "Yes" if row["requires_opt_in"] else "No",
                    row["notes"] or "",
                ]
                for row in rows
            ]
        )

    def _on_events(self, rows: Any) -> None:
        self._events = {row["event_ref"]: row for row in rows}
        self.events_table.set_rows(
            [
                [
                    format_datetime(row["created_at"], "%d %b %I:%M"),
                    row["event_type"].replace("_", " ").title(),
                    row["severity"],
                    str(row["user_id"] or "—"),
                    row["description"][:90],
                    row["status"],
                ]
                for row in rows
            ],
            row_ids=[row["event_ref"] for row in rows],
        )

    def _show_event(self) -> None:
        row = self.events_table.table.currentRow()
        if row < 0:
            return
        item = self.events_table.table.item(row, 0)
        event = self._events.get(str(item.data(Qt.UserRole))) if item else None
        if event is None:
            return
        lines = [
            f"{event['event_type']} · {event['severity']} · {event['status']}",
            f"Category: {event['category']}   User: {event['user_id'] or '—'}",
            f"Recorded: {format_datetime(event['created_at'])}",
            "",
            event["description"],
            "",
            f"Recommended response: {event['recommended_response'] or '—'}",
            "",
            "Evidence:",
            *[f"  {key}: {value}" for key, value in (event["evidence"] or {}).items()],
        ]
        self.event_detail.setPlainText("\n".join(lines))

    def _on_backups(self, rows: Any) -> None:
        self.backup_table.set_rows(
            [
                [
                    row["backup_ref"],
                    row["operation"],
                    row["file_name"][:40],
                    f"{row['file_size'] / 1024:.0f} KB",
                    row["integrity_status"],
                    format_datetime(row["created_at"], "%d %b %I:%M"),
                ]
                for row in rows
            ]
        )

    # -- actions -----------------------------------------------------------
    def _run_worker(self, callable_, label: str, on_success, args: tuple = ()) -> None:
        worker = ActionWorker(lambda: callable_(*args), label)
        worker.finished_ok.connect(on_success)
        worker.failed.connect(lambda message: show_error(self, BizPilotError(message)))
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def wait_for_idle(self, timeout_ms: int = 120000) -> bool:
        from PySide6.QtWidgets import QApplication

        idle = True
        for worker in list(self._workers):
            try:
                if not worker.wait(timeout_ms):
                    idle = False
            except RuntimeError:
                continue
            QApplication.processEvents()
        QApplication.processEvents()
        return idle

    def _scan(self) -> None:
        service = self._context.security_service
        self._run_worker(
            service.scan_security,
            "Scan",
            lambda events: (
                self.refresh(),
                show_info(self, f"{len(events)} security event(s) raised by this scan"),
            ),
        )

    def _start_enrollment(self) -> None:
        service = self._context.security_service
        self._run_worker(service.start_mfa_enrollment, "MFA", self._on_enrollment)

    def _on_enrollment(self, data: Any) -> None:
        codes = "\n".join(data["recovery_codes"])
        self.mfa_detail.setPlainText(
            "1. Add this secret to your authenticator app:\n"
            f"   {data['secret']}\n"
            f"   (or scan the provisioning URI: {data['provisioning_uri'][:80]}…)\n\n"
            "2. Enter the 6-digit code and press Verify.\n\n"
            f"Recovery codes (store them safely, each works once):\n{codes}"
        )

    def _verify_enrollment(self) -> None:
        code = self.mfa_code_input.text().strip()
        if not code:
            show_info(self, "Enter the 6-digit code from your authenticator app.")
            return
        service = self._context.security_service
        self._run_worker(
            service.verify_mfa_enrollment,
            "MFA",
            lambda result: (
                self.refresh(),
                show_info(self, "MFA enabled" if result["enabled"] else "The code was not accepted"),
            ),
            args=(code,),
        )

    def _enforce_mfa(self) -> None:
        row = self.users_table.table.currentRow()
        if row < 0:
            show_info(self, "Select a user first.")
            return
        item = self.users_table.table.item(row, 0)
        user_id = int(item.data(Qt.UserRole)) if item else 0
        current = self._users.get(user_id, {}).get("mfa_enforced", False)
        service = self._context.security_service
        self._run_worker(
            service.enforce_mfa, "MFA", lambda _: self.refresh(), args=(user_id, not current)
        )

    def _revoke_session(self) -> None:
        row = self.sessions_table.table.currentRow()
        if row < 0:
            show_info(self, "Select a session first.")
            return
        item = self.sessions_table.table.item(row, 0)
        session_id = int(item.data(Qt.UserRole)) if item else 0
        service = self._context.security_service
        self._run_worker(service.revoke_session, "Session", lambda _: self.refresh(), args=(session_id,))

    def _save_agent_policy(self) -> None:
        row = self.agent_table.table.currentRow()
        if row < 0:
            show_info(self, "Select an agent first.")
            return
        item = self.agent_table.table.item(row, 0)
        agent_code = str(item.data(Qt.UserRole)) if item else ""
        tools = [tool.strip() for tool in self.agent_tools.text().split(",") if tool.strip()]
        changes = {
            "cloud_ai_eligible": self.agent_cloud.isChecked(),
            "allowed_tools": tools or None,
        }
        service = self._context.security_service
        self._run_worker(
            service.update_agent_policy, "Policy", lambda _: self.refresh(), args=(agent_code,)
        ) if False else self._run_worker(
            lambda: service.update_agent_policy(agent_code, changes=changes),
            "Policy",
            lambda _: (self.refresh(), show_info(self, f"{agent_code} policy saved")),
        )

    def _verify_chain(self) -> None:
        service = self._context.security_service
        self._run_worker(service.audit_integrity, "Audit", self._on_integrity)

    def _on_integrity(self, result: Any) -> None:
        self.integrity_text.setPlainText(
            f"Chain {'intact' if result['ok'] else 'BROKEN'}\n"
            f"Records checked: {result['checked']}\n"
            f"Broken at sequence: {result['broken_at'] or '—'}\n"
            f"{result['reason']}"
        )

    def _backfill_chain(self) -> None:
        service = self._context.security_service
        self._run_worker(
            service.backfill_audit_chain,
            "Chain",
            lambda count: (
                self.refresh(),
                show_info(self, f"{count} existing audit record(s) added to the chain"),
            ),
        )

    def _export_audit(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(self, "Export audit trail", "audit_export.csv", "CSV (*.csv)")
        if not path:
            return
        service = self._context.security_service
        self._run_worker(
            service.export_audit,
            "Export",
            lambda result: show_info(self, f"{result['rows']} audit rows exported to {result['file']}"),
            args=(Path(path),),
        )

    def _review_event(self, decision: str) -> None:
        row = self.events_table.table.currentRow()
        if row < 0:
            show_info(self, "Select an event first.")
            return
        item = self.events_table.table.item(row, 0)
        event_ref = str(item.data(Qt.UserRole)) if item else ""
        note = self.event_note.text().strip() or None
        service = self._context.security_service
        self._run_worker(
            lambda: service.review_event(event_ref, decision=decision, note=note),
            "Review",
            lambda _: (self.refresh(), show_info(self, f"Event {decision.lower().replace('_', ' ')}")),
        )

    def _create_backup(self) -> None:
        service = self._context.security_service
        include = self.include_knowledge.isChecked()
        self.backup_button.setEnabled(False)

        def done(result: Any) -> None:
            self.backup_button.setEnabled(True)
            self.backup_detail.setPlainText(
                f"{result['backup_ref']} · {result['integrity_status']}\n"
                f"{result['validation_detail']}\n{result['path']}"
            )
            self.backup_path.setText(result["path"])
            self.refresh()

        worker = ActionWorker(lambda: service.create_backup(include_knowledge=include), "Backup")
        worker.finished_ok.connect(done)
        worker.failed.connect(
            lambda message: (
                self.backup_button.setEnabled(True),
                show_error(self, BizPilotError(message)),
            )
        )
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def _validate_backup(self) -> None:
        path = self.backup_path.text().strip()
        if not path:
            show_info(self, "Enter the path of a backup file first.")
            return
        service = self._context.security_service
        self._run_worker(service.validate_backup, "Validate", self._on_backup_validated, args=(path,))

    def _on_backup_validated(self, result: Any) -> None:
        self.backup_detail.setPlainText(
            f"{'Valid backup' if result['valid'] else 'Invalid backup'}\n"
            f"{result['detail']}\n{result['note']}"
        )

    def _restore_backup(self) -> None:
        path = self.backup_path.text().strip()
        if not path:
            show_info(self, "Enter the path of a backup file first.")
            return
        if not confirm(
            self,
            "Restore this backup?",
            "The active database will be replaced. A safety copy of the current data is "
            "taken first, and the backup must pass validation.",
            confirm_text="Restore",
            destructive=True,
        ):
            return
        service = self._context.security_service
        self._run_worker(
            lambda: service.restore_backup(path, confirm=True),
            "Restore",
            lambda result: (
                self.refresh(),
                show_info(self, f"Restored {result['restored']}"),
            ),
        )

    def shutdown(self) -> None:
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(5000)
            except RuntimeError:
                pass
