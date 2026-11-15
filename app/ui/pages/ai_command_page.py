"""AI Command Center: the conversational front end of the orchestrator."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from app.ai.schemas.workflow_schema import MessageView, WorkflowResult
from app.core.application import ApplicationContext
from app.core.config import APP_VERSION
from app.core.constants import AIWorkflowStatus
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.dialogs.ai_settings_dialog import AISettingsDialog
from app.ui.theme import load_icon
from app.ui.ui_utils import (
    muted_label,
    primary_button,
    secondary_button,
    show_error,
)
from app.ui.workers.orchestration_worker import ActionWorker, CommandWorker
from app.utils.date_utils import format_datetime

logger = get_logger("ui.ai_page")

SAVED_COMMANDS = (
    "Show this month's revenue.",
    "What are my expenses this month?",
    "Calculate my business profit.",
    "Which products are selling the most?",
    "Find products running out of stock.",
    "Show customers who haven't purchased recently.",
    "Show my cash flow.",
    "Prepare my monthly financial report.",
    "Generate an inventory report.",
)


class MessageBubble(QFrame):
    """One chat message."""

    details_requested = Signal(str)
    approve_requested = Signal(str)

    def __init__(self, message: MessageView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        is_user = message.sender_type == "USER"
        self.setObjectName("ChatBubbleUser" if is_user else "ChatBubbleAssistant")
        # A fixed width keeps heightForWidth stable inside the scroll area, so
        # wrapped answers are never clipped.
        self.setFixedWidth(520 if is_user else 660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(6)

        body = QLabel(message.content)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setObjectName("ChatText")
        # QLabel reports a single-line size hint when wrapping, so the wrapped
        # height is measured with QFontMetrics for the known content width. This
        # is deterministic and keeps long answers from being clipped.
        content_width = (520 if is_user else 660) - 32
        body.setFixedWidth(content_width)
        body.ensurePolished()
        metrics = body.fontMetrics()
        measured = metrics.boundingRect(
            QRect(0, 0, content_width, 100_000), Qt.TextWordWrap, message.content
        )
        body.setFixedHeight(max(measured.height() + 4, metrics.height() + 2))
        layout.addWidget(body)

        meta = message.meta or {}
        footer_bits: list[str] = []
        if meta.get("intent"):
            footer_bits.append(str(meta["intent"]).replace("_", " ").title())
        if meta.get("provider"):
            footer_bits.append(str(meta["provider"]))
        if meta.get("status"):
            footer_bits.append(str(meta["status"]).replace("_", " ").title())
        footer_bits.append(format_datetime(message.created_at, "%d %b, %I:%M %p"))

        footer_row = QHBoxLayout()
        footer_row.setContentsMargins(0, 0, 0, 0)
        footer = muted_label(" · ".join(footer_bits))
        footer_row.addWidget(footer)
        footer_row.addStretch(1)

        workflow_id = meta.get("workflow_id")
        if workflow_id and not is_user:
            details = QPushButton("Details")
            details.setProperty("variant", "ghost")
            details.setCursor(Qt.PointingHandCursor)
            details.clicked.connect(lambda: self.details_requested.emit(str(workflow_id)))
            footer_row.addWidget(details)
        if workflow_id and meta.get("requires_approval"):
            approve = QPushButton("Approve")
            approve.setProperty("variant", "primary")
            approve.setCursor(Qt.PointingHandCursor)
            approve.clicked.connect(lambda: self.approve_requested.emit(str(workflow_id)))
            footer_row.addWidget(approve)

        layout.addLayout(footer_row)

        # Pin the frame to exactly the height its contents need. Qt otherwise
        # squeezes the bubble when the scroll area recalculates, which clips
        # the wrapped answer under the footer line.
        layout.activate()
        # +8 px absorbs the small difference between the pre-polish size hint
        # and the final styled height of the footer line.
        self.setFixedHeight(layout.sizeHint().height() + 8)

class AICommandPage(QWidget):
    """Chat panel wired to the real orchestration service."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._conversation_id: int | None = None
        self._active_workflow: str | None = None
        self._worker: CommandWorker | None = None
        self._workers: list[Any] = []
        self._build()
        self._refresh_conversations()
        self._refresh_status()
        self._start_event_timer()

    # -- capability checks -------------------------------------------------
    def _can(self, permission: str) -> bool:
        return bool(self._principal and permission in self._principal.permissions)

    # -- UI ----------------------------------------------------------------
    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_left_panel())
        splitter.addWidget(self._build_chat_panel())
        splitter.addWidget(self._build_right_panel())
        splitter.setSizes([240, 760, 300])
        layout.addWidget(splitter)

    def _build_left_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        panel.setMinimumWidth(210)
        panel.setMaximumWidth(280)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.new_button = primary_button("New conversation")
        self.new_button.clicked.connect(self._new_conversation)
        self.new_button.setEnabled(self._can("agents.execute"))
        layout.addWidget(self.new_button)

        layout.addWidget(self._section_label("Conversations"))
        self.conversation_list = QListWidget()
        self.conversation_list.setObjectName("PlainList")
        self.conversation_list.setTextElideMode(Qt.ElideRight)
        self.conversation_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.conversation_list.itemSelectionChanged.connect(self._on_conversation_selected)
        layout.addWidget(self.conversation_list, 2)

        layout.addWidget(self._section_label("Saved commands"))
        self.saved_list = QListWidget()
        self.saved_list.setObjectName("PlainList")
        self.saved_list.setTextElideMode(Qt.ElideRight)
        self.saved_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for command in SAVED_COMMANDS:
            item = QListWidgetItem(command)
            item.setToolTip(command)
            self.saved_list.addItem(item)
        self.saved_list.itemClicked.connect(self._use_saved_command)
        layout.addWidget(self.saved_list, 2)
        return panel

    def _build_chat_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setObjectName("ChatHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 10, 16, 10)
        self.chat_title = QLabel("AI Command Center")
        self.chat_title.setObjectName("CardTitle")
        header_layout.addWidget(self.chat_title)
        header_layout.addStretch(1)
        self.status_chip = QLabel("Offline · deterministic")
        self.status_chip.setObjectName("Badge")
        header_layout.addWidget(self.status_chip)
        self.copy_button = secondary_button("Copy")
        self.copy_button.setToolTip("Copy the last answer")
        self.copy_button.clicked.connect(self._copy_last)
        header_layout.addWidget(self.copy_button)
        self.clear_button = secondary_button("Clear")
        self.clear_button.clicked.connect(self._clear_conversation)
        header_layout.addWidget(self.clear_button)
        layout.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setObjectName("ChatScroll")
        container = QWidget()
        self.messages_layout = QVBoxLayout(container)
        self.messages_layout.setContentsMargins(16, 16, 16, 16)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        input_row = QFrame()
        input_row.setObjectName("ChatInputRow")
        input_layout = QHBoxLayout(input_row)
        input_layout.setContentsMargins(16, 12, 16, 12)
        input_layout.setSpacing(10)
        self.input = QLineEdit()
        self.input.setPlaceholderText(
            "Ask about revenue, stock, customers… e.g. “Show this month's revenue”"
        )
        self.input.returnPressed.connect(self._send)
        input_layout.addWidget(self.input, 1)
        self.send_button = primary_button("Send")
        self.send_button.clicked.connect(self._send)
        self.stop_button = secondary_button("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._stop)
        input_layout.addWidget(self.send_button)
        input_layout.addWidget(self.stop_button)
        layout.addWidget(input_row)

        self._status_label = muted_label("")
        self._status_label.setContentsMargins(16, 0, 16, 8)
        layout.addWidget(self._status_label)
        return panel

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Card")
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(340)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        layout.addWidget(self._section_label("AI provider"))
        self.provider_label = QLabel("—")
        self.provider_label.setWordWrap(True)
        layout.addWidget(self.provider_label)

        layout.addWidget(self._section_label("Agent registry"))
        self.agent_label = QLabel("—")
        self.agent_label.setWordWrap(True)
        layout.addWidget(self.agent_label)

        layout.addWidget(self._section_label("Workflows"))
        self.workflow_label = QLabel("—")
        self.workflow_label.setWordWrap(True)
        layout.addWidget(self.workflow_label)

        layout.addWidget(self._section_label("System"))
        self.system_label = QLabel("—")
        self.system_label.setWordWrap(True)
        layout.addWidget(self.system_label)

        layout.addStretch(1)
        self.refresh_button = secondary_button("Refresh status")
        self.refresh_button.clicked.connect(self._refresh_status)
        layout.addWidget(self.refresh_button)
        self.settings_button = secondary_button("AI settings")
        self.settings_button.clicked.connect(self._open_settings)
        self.settings_button.setEnabled(self._can("agents.configure"))
        layout.addWidget(self.settings_button)
        return panel

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("FieldLabel")
        return label

    # -- conversations -----------------------------------------------------
    def refresh(self) -> None:
        self._refresh_conversations()
        self._refresh_status()

    def _refresh_conversations(self) -> None:
        try:
            conversations = self._context.ai_service.list_conversations()
        except BizPilotError as exc:
            self._status_label.setText(exc.user_message)
            return
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()
        for conversation in conversations:
            item = QListWidgetItem(conversation.title)
            item.setData(Qt.UserRole, conversation.id)
            item.setToolTip(f"{conversation.message_count} message(s)")
            self.conversation_list.addItem(item)
            if conversation.id == self._conversation_id:
                item.setSelected(True)
        self.conversation_list.blockSignals(False)

        if self._conversation_id is None and conversations:
            self._select_conversation(conversations[0].id)

    def _on_conversation_selected(self) -> None:
        item = self.conversation_list.currentItem()
        if item is not None:
            self._select_conversation(int(item.data(Qt.UserRole)))

    def _select_conversation(self, conversation_id: int) -> None:
        self._conversation_id = conversation_id
        try:
            messages = self._context.ai_service.messages(conversation_id)
        except BizPilotError as exc:
            self._status_label.setText(exc.user_message)
            return
        self._clear_messages()
        for message in messages:
            self._add_bubble(message)
        self._scroll_to_bottom()

    def _new_conversation(self) -> None:
        try:
            conversation = self._context.ai_service.create_conversation()
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self._conversation_id = conversation.id
        self._clear_messages()
        self._refresh_conversations()
        self.input.setFocus()

    # -- chat --------------------------------------------------------------
    def _clear_messages(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _add_bubble(self, message: MessageView) -> MessageBubble:
        bubble = MessageBubble(message)
        bubble.details_requested.connect(self._show_details)
        bubble.approve_requested.connect(self._approve)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        if message.sender_type == "USER":
            row.addStretch(1)
            row.addWidget(bubble)
        else:
            row.addWidget(bubble)
            row.addStretch(1)
        container = QWidget()
        container.setLayout(row)
        self.messages_layout.insertWidget(self.messages_layout.count() - 1, container)
        return bubble

    def _append_message(
        self,
        text: str,
        sender: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        from app.utils.date_utils import utcnow

        self._add_bubble(
            MessageView(
                id=0,
                sender_type=sender,
                content=text,
                created_at=utcnow(),
                meta=meta or {},
            )
        )
        self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        # Let the layout settle before scrolling, otherwise the maximum is stale.
        self.messages_layout.activate()
        QTimer.singleShot(0, self._scroll_now)

    def _scroll_now(self) -> None:
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    # -- actions -----------------------------------------------------------
    def _send(self) -> None:
        command = self.input.text().strip()
        if not command:
            return
        if self._conversation_id is None:
            self._new_conversation()
            if self._conversation_id is None:
                return

        self.input.clear()
        self._append_message(command, "USER")
        self._set_busy(True, "Classifying the request…")

        self._worker = CommandWorker(
            self._context.ai_service, self._conversation_id, command
        )
        self._worker.workflow_started.connect(self._on_workflow_started)
        self._worker.progress.connect(lambda text: self._set_busy(True, text))
        self._worker.completed.connect(self._on_completed)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_workflow_started(self, workflow_id: str, intent: str) -> None:
        self._active_workflow = workflow_id
        self.stop_button.setEnabled(True)
        self._status_label.setText(f"Running {intent.replace('_', ' ').title()}…")

    def _on_completed(self, result: WorkflowResult) -> None:
        self._set_busy(False, "")
        self._status_label.setText(
            f"Finished · {result.status.replace('_', ' ').title()} · {result.provider}"
        )
        self._active_workflow = None
        self.stop_button.setEnabled(False)
        self._append_message(
            result.response_text,
            "ASSISTANT",
            {
                "workflow_id": result.workflow_id,
                "intent": result.intent.value,
                "status": result.status,
                "provider": result.provider,
                "requires_approval": result.requires_approval,
            },
        )
        self._refresh_status()
        self._refresh_conversations()

    def _on_failed(self, message: str) -> None:
        self._set_busy(False, "")
        self._status_label.setText("Request failed — see the message above.")
        self.stop_button.setEnabled(False)
        self._active_workflow = None
        self._append_message(message, "ASSISTANT", {"status": "FAILED"})

    def _set_busy(self, busy: bool, status: str) -> None:
        self.progress.setVisible(busy)
        self.send_button.setEnabled(not busy and self._can("agents.execute"))
        self.input.setEnabled(not busy)
        self.stop_button.setEnabled(busy and self._active_workflow is not None)
        if status:
            self._status_label.setText(status)

    def _stop(self) -> None:
        if not self._active_workflow:
            return
        workflow_id = self._active_workflow
        self._status_label.setText("Cancelling…")
        worker = ActionWorker(
            lambda: self._context.ai_service.cancel_workflow(workflow_id), "Cancel"
        )
        worker.finished_ok.connect(lambda _: self._on_cancelled(workflow_id))
        worker.failed.connect(self._on_failed)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _on_cancelled(self, workflow_id: str) -> None:
        self._set_busy(False, "")
        self.stop_button.setEnabled(False)
        self._active_workflow = None
        self._append_message(
            "Workflow cancelled. No further steps will run.",
            "ASSISTANT",
            {"workflow_id": workflow_id, "status": AIWorkflowStatus.CANCELLED},
        )
        self._refresh_status()

    def _approve(self, workflow_id: str) -> None:
        self._set_busy(True, "Applying the approved action…")
        worker = ActionWorker(
            lambda: self._context.ai_service.approve_workflow(workflow_id), "Approve"
        )
        worker.finished_ok.connect(self._on_completed)
        worker.failed.connect(self._on_failed)
        worker.finished.connect(lambda: self._workers.remove(worker) if worker in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _clear_conversation(self) -> None:
        if self._conversation_id is None:
            return
        try:
            self._context.ai_service.clear_conversation(self._conversation_id)
        except BizPilotError as exc:
            show_error(self, exc)
            return
        self._clear_messages()
        self._refresh_conversations()

    def _copy_last(self) -> None:
        for index in range(self.messages_layout.count() - 1, -1, -1):
            container = self.messages_layout.itemAt(index).widget()
            if container is None:
                continue
            for child in container.findChildren(QLabel):
                if child.objectName() == "ChatText":
                    QGuiApplication.clipboard().setText(child.text())
                    self._status_label.setText("Last answer copied to the clipboard.")
                    return

    def _use_saved_command(self, item: QListWidgetItem) -> None:
        self.input.setText(item.text())
        self.input.setFocus()

    # -- details -----------------------------------------------------------
    def _show_details(self, workflow_id: str) -> None:
        try:
            detail = self._context.ai_service.workflow_detail(workflow_id)
        except BizPilotError as exc:
            show_error(self, exc)
            return
        from PySide6.QtWidgets import QDialog, QPlainTextEdit

        dialog = QDialog(self)
        dialog.setWindowTitle(f"Execution details · {workflow_id}")
        dialog.resize(680, 520)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(16, 16, 16, 16)

        summary = QLabel(
            f"Intent: {detail['intent']} · Status: {detail['status']} · "
            f"Provider: {detail['provider'] or 'fallback'} · Trigger: {detail['trigger']}"
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        lines: list[str] = []
        for step in detail["steps"]:
            lines.append(
                f"[{step['number']}] {step['tool']} — {step['status']} "
                f"({step['risk']}, {step['duration_ms'] or 0} ms)"
            )
            if step["error"]:
                lines.append(f"    error: {step['error']}")
            output = step["output"] or {}
            summary_text = output.get("summary")
            if summary_text:
                lines.append(f"    {summary_text}")
            for finding in (output.get("findings") or [])[:5]:
                lines.append(
                    f"    • [{finding.get('severity')}] {finding.get('description')}"
                )
                for item in (finding.get("evidence") or [])[:2]:
                    lines.append(
                        f"        evidence: {item.get('source')} · {item.get('metric')} = "
                        f"{item.get('value')}"
                    )
            for recommendation in (output.get("recommendations") or [])[:5]:
                lines.append(
                    f"    → [{recommendation.get('priority')}] "
                    f"{recommendation.get('recommendation')}"
                )
            if output.get("data_gaps"):
                lines.append(f"    data gaps: {', '.join(output['data_gaps'])}")
            if output.get("confidence") is not None:
                lines.append(
                    f"    confidence: {output.get('confidence')} "
                    f"({output.get('confidence_basis', '')})"
                )
        if detail["error"]:
            lines.append(f"\nWorkflow error: {detail['error']}")
        text.setPlainText("\n".join(lines) or "No steps recorded.")
        layout.addWidget(text, 1)

        close = secondary_button("Close")
        close.clicked.connect(dialog.accept)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        layout.addLayout(row)
        dialog.exec()

    # -- status ------------------------------------------------------------
    def _apply_status(self, health: dict, agents: list, stats: dict, connected: bool) -> None:
        lines = []
        for provider in health.get("providers", []):
            mark = "●" if provider["available"] else "○"
            lines.append(f"{mark} {provider['name']} — {provider['model']}")
        active = health.get("active", "fallback")
        lines.append(f"Active: {active}")
        lines.append(
            "Cloud sharing: " + ("enabled" if health.get("cloud_enabled") else "disabled (offline only)")
        )
        self.provider_label.setText("\n".join(lines))
        self.status_chip.setText(
            "Online · " + active if active != "fallback" else "Offline · deterministic"
        )

        self.agent_label.setText(
            "\n".join(
                f"{'●' if agent['status'] == 'ready' else '○'} {agent['name']} "
                f"({agent['tools']} tools)"
                for agent in agents
            )
        )
        self.workflow_label.setText(
            f"{stats.get('total', 0)} total · {stats.get('completed', 0)} completed\n"
            f"{stats.get('waiting', 0)} awaiting approval · {stats.get('failed', 0)} failed"
        )
        self.system_label.setText(
            f"Database: {'connected' if connected else 'unavailable'}\n"
            f"Tools registered: {len(self._context.tool_registry.names())}\n"
            f"Version: {APP_VERSION}"
        )

    def _refresh_status(self) -> None:
        try:
            health = self._context.ai_service.provider_health()
            agents = self._context.ai_service.agent_health()
            stats = self._context.ai_service.workflow_stats()
            try:
                connected = self._context.database.check_connection()
            except Exception:
                connected = False
            self._apply_status(health, agents, stats, connected)
        except BizPilotError as exc:
            self.provider_label.setText(exc.user_message)
            return

    def _async_refresh_status(self) -> None:
        def _fetch():
            health = self._context.ai_service.provider_health()
            agents = self._context.ai_service.agent_health()
            stats = self._context.ai_service.workflow_stats()
            try:
                connected = self._context.database.check_connection()
            except Exception:
                connected = False
            return health, agents, stats, connected

        worker = ActionWorker(_fetch, "AI Status Refresh")
        worker.finished_ok.connect(lambda bundle: self._apply_status(*bundle))
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def _open_settings(self) -> None:
        dialog = AISettingsDialog(self._context, self)
        if dialog.exec():
            self._async_refresh_status()

    # -- lifecycle ---------------------------------------------------------
    def shutdown(self) -> None:
        """Stop timers and wait for background workers before the window closes."""
        timer = getattr(self, "_event_timer", None)
        if timer is not None:
            timer.stop()
        for worker in list(self._workers) + ([self._worker] if self._worker else []):
            try:
                if worker is not None and worker.isRunning():
                    worker.wait(3000)
            except RuntimeError:  # already deleted
                pass

    # -- background event processing --------------------------------------
    def _start_event_timer(self) -> None:
        if not self._can("agents.execute"):
            return
        self._event_timer = QTimer(self)
        self._event_timer.setInterval(60_000)
        self._event_timer.timeout.connect(self._process_events)
        self._event_timer.start()
        QTimer.singleShot(3_000, self._process_events)

    def _process_events(self) -> None:
        if not self._can("agents.execute"):
            return
        worker = ActionWorker(
            lambda: self._context.ai_service.process_pending_events(3), "Event processing"
        )
        worker.finished_ok.connect(lambda _: self._async_refresh_status())
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()
