"""Knowledge Center: document library, search, RAG assistant and AI settings."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
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
from app.core.constants import KnowledgeCategory
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

logger = get_logger("ui.knowledge")

SEARCH_MODES = (("Hybrid", "HYBRID"), ("Semantic", "SEMANTIC"), ("Keyword", "KEYWORD"))
ASK_MODES = (("Documents", "DOCUMENT"), ("Business + documents", "HYBRID"), ("Business records", "BUSINESS"))
POLICIES = (
    ("Local first", "LOCAL_FIRST"),
    ("Cloud first (needs cloud sharing)", "CLOUD_FIRST"),
    ("Task based", "TASK_BASED"),
    ("Offline only", "OFFLINE"),
)


class KnowledgeCenterPage(QWidget):
    """Upload, inspect, search and question business documents."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._workers: list[Any] = []
        self._documents: dict[str, dict] = {}
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
        self.card_total = StatCard("Documents", "0", "in the knowledge base")
        self.card_indexed = StatCard("Indexed", "0", "searchable")
        self.card_processing = StatCard("Processing", "0", "in progress")
        self.card_failed = StatCard("Failed", "0", "need attention")
        self.card_chunks = StatCard("Chunks", "0", "retrievable passages")
        for index, card in enumerate(
            (self.card_total, self.card_indexed, self.card_processing, self.card_failed, self.card_chunks)
        ):
            cards.addWidget(card, 0, index)
        layout.addLayout(cards)

        controls = QHBoxLayout()
        self.upload_button = primary_button("Upload document")
        self.upload_button.clicked.connect(self._upload)
        self.upload_button.setEnabled(self._can("knowledge.upload"))
        controls.addWidget(self.upload_button)
        self.refresh_button = secondary_button("Refresh")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        self.status_label = muted_label("")
        controls.addWidget(self.status_label)
        layout.addLayout(controls)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_library_tab(), "Document Library")
        self.tabs.addTab(self._build_search_tab(), "Knowledge Search")
        self.tabs.addTab(self._build_assistant_tab(), "RAG Assistant")
        self.tabs.addTab(self._build_settings_tab(), "AI Providers")
        layout.addWidget(self.tabs, 1)

    def _build_library_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        splitter = QSplitter(Qt.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.documents_table = DataTable(
            ["Title", "Category", "Status", "Pages", "Chunks", "Version", "Uploaded"],
            stretch_columns=(0,),
        )
        self.documents_table.table.itemSelectionChanged.connect(self._show_document)
        left_layout.addWidget(self.documents_table, 1)
        buttons = QHBoxLayout()
        self.reprocess_button = secondary_button("Reprocess")
        self.reprocess_button.clicked.connect(lambda: self._document_action("reprocess"))
        self.archive_button = secondary_button("Archive")
        self.archive_button.clicked.connect(lambda: self._document_action("archive"))
        self.delete_button = secondary_button("Delete")
        self.delete_button.clicked.connect(lambda: self._document_action("delete"))
        for button in (self.reprocess_button, self.archive_button, self.delete_button):
            button.setEnabled(self._can("knowledge.manage"))
            buttons.addWidget(button)
        buttons.addStretch(1)
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.document_text = QPlainTextEdit()
        self.document_text.setReadOnly(True)
        right_layout.addWidget(self.document_text, 1)
        self.extraction_table = DataTable(
            ["Field", "Value", "Page", "Confidence", "Status"], stretch_columns=(1,)
        )
        right_layout.addWidget(self.extraction_table, 1)
        verify_row = QHBoxLayout()
        self.verify_button = secondary_button("Verify selected field")
        self.verify_button.clicked.connect(self._verify_field)
        self.verify_button.setEnabled(self._can("knowledge.manage"))
        verify_row.addWidget(self.verify_button)
        verify_row.addStretch(1)
        right_layout.addLayout(verify_row)
        splitter.addWidget(right)
        splitter.setSizes([640, 760])
        layout.addWidget(splitter, 1)
        return page

    def _build_search_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        controls = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search documents, e.g. '30-day payment terms'…")
        self.search_input.returnPressed.connect(self._search)
        controls.addWidget(self.search_input, 1)
        self.search_mode = QComboBox()
        for label, value in SEARCH_MODES:
            self.search_mode.addItem(label, value)
        controls.addWidget(self.search_mode)
        self.search_category = QComboBox()
        self.search_category.addItem("All categories", None)
        for category in KnowledgeCategory.ALL:
            self.search_category.addItem(KnowledgeCategory.LABELS[category], category)
        controls.addWidget(self.search_category)
        self.search_button = primary_button("Search")
        self.search_button.clicked.connect(self._search)
        controls.addWidget(self.search_button)
        layout.addLayout(controls)

        self.search_table = DataTable(
            ["Score", "Type", "Document", "Page", "Section", "Passage"], stretch_columns=(5,)
        )
        self.search_table.table.itemSelectionChanged.connect(self._show_hit)
        layout.addWidget(self.search_table, 2)
        self.search_preview = QPlainTextEdit()
        self.search_preview.setReadOnly(True)
        layout.addWidget(self.search_preview, 1)
        return page

    def _build_assistant_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(
            muted_label(
                "Answers are built from retrieved passages and your business records. "
                "When nothing relevant is found the assistant says so instead of guessing."
            )
        )
        controls = QHBoxLayout()
        self.ask_input = QLineEdit()
        self.ask_input.setPlaceholderText(
            "Ask a question, e.g. 'What are the payment terms in our supplier agreement?'"
        )
        self.ask_input.returnPressed.connect(self._ask)
        controls.addWidget(self.ask_input, 1)
        self.ask_mode = QComboBox()
        for label, value in ASK_MODES:
            self.ask_mode.addItem(label, value)
        controls.addWidget(self.ask_mode)
        self.ask_button = primary_button("Ask")
        self.ask_button.clicked.connect(self._ask)
        self.ask_button.setEnabled(self._can("knowledge.ask"))
        controls.addWidget(self.ask_button)
        layout.addLayout(controls)

        self.answer_text = QPlainTextEdit()
        self.answer_text.setReadOnly(True)
        layout.addWidget(self.answer_text, 2)
        self.sources_table = DataTable(
            ["Source", "Page", "Section", "Similarity", "Excerpt"], stretch_columns=(4,)
        )
        layout.addWidget(self.sources_table, 1)
        return page

    def _build_settings_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(muted_label("Routing policy and provider health"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Policy"))
        self.policy_combo = QComboBox()
        for label, value in POLICIES:
            self.policy_combo.addItem(label, value)
        row.addWidget(self.policy_combo)
        self.offline_check = QCheckBox("Offline mode (cloud disabled)")
        row.addWidget(self.offline_check)
        self.cloud_check = QCheckBox("Allow cloud data sharing")
        row.addWidget(self.cloud_check)
        self.save_settings_button = primary_button("Save")
        self.save_settings_button.clicked.connect(self._save_settings)
        self.save_settings_button.setEnabled(self._can("agents.configure"))
        row.addWidget(self.save_settings_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.providers_table = DataTable(
            ["Provider", "Kind", "Model", "Available", "Enabled", "Detail"],
            stretch_columns=(5,),
        )
        layout.addWidget(self.providers_table, 1)
        layout.addWidget(muted_label("Recent AI usage"))
        self.usage_table = DataTable(
            ["Task", "Policy", "Provider", "Model", "Fallback", "Latency", "When"],
            stretch_columns=(0,),
        )
        layout.addWidget(self.usage_table, 1)
        self.index_text = QPlainTextEdit()
        self.index_text.setReadOnly(True)
        layout.addWidget(self.index_text, 1)
        return page

    # -- data --------------------------------------------------------------
    def refresh(self) -> None:
        service = self._context.knowledge_service
        self._run_worker(service.statistics, "Statistics", self._on_stats)
        self._run_worker(service.list_documents, "Documents", self._on_documents)
        if self._can("agents.configure") or self._can("knowledge.view"):
            self._run_worker(
                service.provider_configuration, "Providers", self._on_providers
            )

    def _on_stats(self, stats: Any) -> None:
        self.card_total.set_value(str(stats["total_documents"]), True)
        self.card_indexed.set_value(str(stats["indexed"]), True)
        self.card_processing.set_value(str(stats["processing"]), True)
        self.card_failed.set_value(str(stats["failed"]), True)
        self.card_chunks.set_value(str(stats["chunks"]), True)
        model = stats.get("embedding_model", {})
        ocr = stats.get("ocr", {})
        index = stats.get("vector_index", {})
        self.status_label.setText(
            f"{model.get('model_id', '?')} ({model.get('dimension', '?')} dims) · "
            f"index {index.get('total_vectors', 0)} vectors · "
            f"OCR {'available' if ocr.get('available') else 'unavailable'}"
        )
        self.index_text.setPlainText(
            f"Embedding model: {model.get('model_id')} v{model.get('version')} "
            f"({model.get('dimension')} dimensions, {model.get('kind')})\n"
            f"Neural model available: {model.get('neural_available')}"
            + (
                f" ({model.get('neural_unavailable_reason')})"
                if not model.get("neural_available")
                else ""
            )
            + f"\n\nVector index: {index.get('total_vectors')} vectors\n"
            f"Healthy: {index.get('healthy')}\n"
            f"Problems: {', '.join(index.get('problems') or []) or 'none'}\n\n"
            f"OCR: {'available' if ocr.get('available') else 'unavailable'} — "
            f"{ocr.get('reason') or ocr.get('engine') or 'ready'}"
        )

    def _on_documents(self, documents: Any) -> None:
        self._documents = {row["document_ref"]: row for row in documents}
        self.documents_table.set_rows(
            [
                [
                    row["title"][:52],
                    KnowledgeCategory.LABELS.get(row["category"], row["category"]),
                    row["status"],
                    str(row["page_count"]),
                    str(row["chunk_count"]),
                    f"v{row['current_version']}",
                    format_datetime(row["created_at"], "%d %b %I:%M"),
                ]
                for row in documents
            ],
            row_ids=[row["document_ref"] for row in documents],
        )

    def _on_providers(self, configuration: Any) -> None:
        index = self.policy_combo.findData(configuration["policy"])
        if index >= 0:
            self.policy_combo.setCurrentIndex(index)
        self.offline_check.setChecked(bool(configuration["offline_mode"]))
        self.cloud_check.setChecked(bool(configuration["cloud_sharing_enabled"]))
        self.providers_table.set_rows(
            [
                [
                    status["name"],
                    status["kind"],
                    status["model"],
                    "Yes" if status["available"] else "No",
                    "Yes" if status.get("enabled") else "No",
                    status["detail"][:70],
                ]
                for status in configuration["providers"]
            ]
        )
        self._run_worker(
            self._context.knowledge_service.provider_usage, "Usage", self._on_usage
        )

    def _on_usage(self, usage: Any) -> None:
        self.usage_table.set_rows(
            [
                [
                    row["task"],
                    row["policy"],
                    row["provider"],
                    row["model"],
                    "Yes" if row["fallback_used"] else "No",
                    f"{row['latency_ms']} ms",
                    format_datetime(row["created_at"], "%d %b %I:%M"),
                ]
                for row in usage
            ]
        )

    def _selected_ref(self, table: DataTable) -> str | None:
        row = table.table.currentRow()
        if row < 0:
            return None
        item = table.table.item(row, 0)
        return str(item.data(Qt.UserRole)) if item else None

    def _show_document(self) -> None:
        document_ref = self._selected_ref(self.documents_table)
        if not document_ref:
            return
        self._run_worker(
            self._context.knowledge_service.get_document,
            "Document",
            self._on_document,
            args=(document_ref,),
        )

    def _on_document(self, details: Any) -> None:
        lines = [
            f"{details['title']}  ({details['document_ref']})",
            f"File: {details['file_name']} · {details['file_type']} · "
            f"{details['file_size'] / 1024:.1f} KB",
            f"Category: {KnowledgeCategory.LABELS.get(details['category'], details['category'])} "
            f"({details['category_source']})",
            f"Status: {details['status']} · stage {details['processing_stage']} · "
            f"index {details['index_status']} · OCR {details['ocr_status']}",
            f"Pages: {details['page_count']} · chunks: {details['chunk_count']} · "
            f"version {details['current_version']} of {len(details['versions'])}",
            f"Embedding model: {details['embedding_model']}",
        ]
        if details.get("error"):
            lines.append(f"Error: {details['error']}")
        if details.get("summary"):
            lines.append("")
            lines.append(f"Summary: {details['summary']}")
        if details["entities"]:
            lines.append("")
            lines.append("Entities:")
            for entity in details["entities"]:
                lines.append(
                    f"  • {entity['type']}: {entity['value']} "
                    f"(confidence {entity['confidence']}"
                    + (", needs review" if entity["needs_review"] else "")
                    + ")"
                )
        if details["versions"]:
            lines.append("")
            lines.append("Versions:")
            for version in details["versions"]:
                lines.append(
                    f"  • v{version['version']} {version['file_name']} "
                    f"({version['chunk_count']} chunks) "
                    f"{'current' if version['is_current'] else ''}"
                )
        self.document_text.setPlainText("\n".join(lines))
        self.extraction_table.set_rows(
            [
                [
                    field["field"].replace("_", " ").title(),
                    str(field["value"])[:80],
                    str(field["page"] or "—"),
                    f"{field['confidence']:.2f}" if field["confidence"] is not None else "—",
                    field["status"],
                ]
                for field in details["extraction"]
            ],
            row_ids=[field["field"] for field in details["extraction"]],
        )

    def _show_hit(self) -> None:
        row = self.search_table.table.currentRow()
        if row < 0:
            return
        item = self.search_table.table.item(row, 0)
        if item is None:
            return
        hits = getattr(self, "_hits", [])
        if row < len(hits):
            hit = hits[row]
            self.search_preview.setPlainText(
                f"{hit['title']} — page {hit['page_number']}\n"
                f"Section: {hit['section_heading'] or '—'}\n"
                f"Score: {hit['score']:.3f} ({hit['match_type']})\n\n{hit['excerpt']}"
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

    def _upload(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload a business document",
            "",
            "Documents (*.pdf *.docx *.txt *.md *.csv *.xlsx *.pptx *.png *.jpg *.jpeg)",
        )
        if not path:
            return
        service = self._context.knowledge_service
        self.upload_button.setEnabled(False)

        def done(result: Any) -> None:
            self.upload_button.setEnabled(True)
            self.refresh()
            if result["status"] == "INDEXED":
                show_info(
                    self,
                    f"{result['title']} indexed: {result['chunk_count']} chunk(s), "
                    f"category {result['category']}.",
                )
            else:
                show_error(
                    self,
                    BizPilotError(f"{result['title']}: {result.get('error') or result['status']}"),
                )

        worker = ActionWorker(lambda: service.upload_document(path), "Upload")
        worker.finished_ok.connect(done)
        worker.failed.connect(
            lambda message: (
                self.upload_button.setEnabled(True),
                show_error(self, BizPilotError(message)),
            )
        )
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def _document_action(self, action: str) -> None:
        document_ref = self._selected_ref(self.documents_table)
        if not document_ref:
            show_info(self, "Select a document first.")
            return
        if action == "delete":
            if not confirm(
                self,
                "Delete this document?",
                "Its chunks and vectors are removed, so it can no longer be retrieved. "
                "The metadata row is kept for the audit trail.",
                confirm_text="Delete",
                destructive=True,
            ):
                return
        service = self._context.knowledge_service
        call = {
            "reprocess": service.reprocess_document,
            "archive": service.archive_document,
            "delete": service.delete_document,
        }[action]
        self._run_worker(call, action.title(), lambda _: self.refresh(), args=(document_ref,))

    def _verify_field(self) -> None:
        document_ref = self._selected_ref(self.documents_table)
        row = self.extraction_table.table.currentRow()
        if not document_ref or row < 0:
            show_info(self, "Select a document and an extracted field first.")
            return
        item = self.extraction_table.table.item(row, 0)
        field_name = str(item.data(Qt.UserRole)) if item else ""
        service = self._context.knowledge_service
        self._run_worker(
            lambda: service.verify_field(document_ref, field_name, status="VERIFIED"),
            "Verify",
            lambda _: (self._show_document(), show_info(self, "Field marked verified")),
        )

    def _search(self) -> None:
        query = self.search_input.text().strip()
        if not query:
            return
        service = self._context.knowledge_service
        mode = self.search_mode.currentData()
        category = self.search_category.currentData()

        def done(result: Any) -> None:
            self._hits = result["hits"]
            self.search_table.set_rows(
                [
                    [
                        f"{hit['score']:.3f}",
                        hit["match_type"],
                        hit["title"][:34],
                        str(hit["page_number"] or "—"),
                        (hit["section_heading"] or "—")[:28],
                        hit["excerpt"][:110],
                    ]
                    for hit in result["hits"]
                ]
            )
            if not result["hits"]:
                self.search_preview.setPlainText(
                    result.get("note") or "No passage matched this query."
                )

        self._run_worker(
            service.search, "Search", done, args=(query,)
        ) if category is None else self._run_worker(
            lambda: service.search(query, mode=mode, category=category), "Search", done
        )

    def _ask(self) -> None:
        question = self.ask_input.text().strip()
        if not question:
            return
        service = self._context.knowledge_service
        mode = self.ask_mode.currentData()
        self.ask_button.setEnabled(False)

        def done(answer: Any) -> None:
            self.ask_button.setEnabled(True)
            lines = [
                f"Question: {answer.question}",
                f"Evidence: {answer.evidence_status} · grounded: {answer.grounded}",
                f"Provider: {answer.provider} · model: {answer.model} · "
                f"{answer.latency_ms} ms · {answer.chunks_used} passage(s), "
                f"{answer.business_records} business record(s)",
                "",
                answer.answer,
            ]
            if answer.limitations:
                lines.extend(["", "Limitations:"])
                lines.extend(f"  • {item}" for item in answer.limitations)
            if answer.citations:
                lines.extend(["", "Sources:"])
                lines.extend(f"  • {citation}" for citation in answer.citations)
            self.answer_text.setPlainText("\n".join(lines))
            self.sources_table.set_rows(
                [
                    [
                        source.title[:40],
                        str(source.page_number or "—"),
                        (source.section_heading or "—")[:24],
                        f"{source.similarity:.3f}",
                        source.excerpt[:90],
                    ]
                    for source in answer.sources
                ]
            )

        worker = ActionWorker(lambda: service.ask(question, mode=mode), "Assistant")
        worker.finished_ok.connect(done)
        worker.failed.connect(
            lambda message: (
                self.ask_button.setEnabled(True),
                show_error(self, BizPilotError(message)),
            )
        )
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def _save_settings(self) -> None:
        service = self._context.knowledge_service
        self._run_worker(
            lambda: service.configure_providers(
                policy=self.policy_combo.currentData(),
                offline_mode=self.offline_check.isChecked(),
                cloud_sharing_enabled=self.cloud_check.isChecked(),
            ),
            "Settings",
            lambda configuration: (
                self._on_providers(configuration),
                show_info(self, f"Routing policy set to {configuration['policy']}"),
            ),
        )

    def shutdown(self) -> None:
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(5000)
            except RuntimeError:
                pass
