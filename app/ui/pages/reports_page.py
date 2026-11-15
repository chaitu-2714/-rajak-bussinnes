"""Reports page: generate real exports from the existing services."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.application import ApplicationContext
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.ui.components.tables import DataTable
from app.ui.ui_utils import muted_label, primary_button, secondary_button, show_error, show_info
from app.ui.workers.orchestration_worker import ActionWorker
from app.utils.date_utils import format_datetime

logger = get_logger("ui.reports")

REPORT_SOURCES = (
    ("Financial summary (PDF)", "FINANCE_PDF"),
    ("Financial summary (CSV)", "FINANCE_CSV"),
    ("Expense ledger (CSV)", "EXPENSES_CSV"),
    ("Sales register (CSV)", "SALES_CSV"),
    ("Executive performance (PDF)", "ANALYTICS_EXECUTIVE_PERFORMANCE"),
    ("Financial analytics (PDF)", "ANALYTICS_FINANCIAL_ANALYTICS"),
    ("Sales performance (PDF)", "ANALYTICS_SALES_PERFORMANCE"),
    ("Customer analytics (PDF)", "ANALYTICS_CUSTOMER_ANALYTICS"),
    ("Inventory health (PDF)", "ANALYTICS_INVENTORY_HEALTH"),
    ("Supplier performance (PDF)", "ANALYTICS_SUPPLIER_PERFORMANCE"),
    ("Anomaly investigation (PDF)", "ANALYTICS_ANOMALY_INVESTIGATION"),
    ("Forecast report (PDF)", "ANALYTICS_FORECAST"),
    ("Business risk (PDF)", "ANALYTICS_BUSINESS_RISK"),
)
PERIODS = (("This month", "MONTHLY"), ("This quarter", "QUARTERLY"), ("This year", "YEARLY"))


class ReportsPage(QWidget):
    """One place to produce every report the application can generate."""

    def __init__(self, context: ApplicationContext, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._context = context
        self._principal = context.auth_context.principal
        self._workers: list[Any] = []
        self._generated: list[dict[str, Any]] = []
        self._build()
        self.refresh()

    def _can(self, permission: str) -> bool:
        return bool(self._principal and permission in self._principal.permissions)

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(
            muted_label(
                "Every report is generated from your recorded business data. "
                "Forecasts are labelled as estimates; nothing here is sample data."
            )
        )

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Report"))
        self.report_combo = QComboBox()
        for label, value in REPORT_SOURCES:
            self.report_combo.addItem(label, value)
        controls.addWidget(self.report_combo, 1)
        controls.addWidget(QLabel("Period"))
        self.period_combo = QComboBox()
        for label, value in PERIODS:
            self.period_combo.addItem(label, value)
        controls.addWidget(self.period_combo)
        self.generate_button = primary_button("Generate")
        self.generate_button.clicked.connect(self._generate)
        self.generate_button.setEnabled(self._can("reports.view"))
        controls.addWidget(self.generate_button)
        self.open_folder_button = secondary_button("Show exports folder")
        self.open_folder_button.clicked.connect(self._show_folder)
        controls.addWidget(self.open_folder_button)
        layout.addLayout(controls)

        self.table = DataTable(
            ["Generated", "Report", "Format", "File", "Size"], stretch_columns=(3,)
        )
        self.table.table.itemSelectionChanged.connect(self._show_detail)
        layout.addWidget(self.table, 2)

        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(120)
        layout.addWidget(self.detail)
        self.summary_label = muted_label("")
        layout.addWidget(self.summary_label)

    # -- actions -----------------------------------------------------------
    def refresh(self) -> None:
        self.summary_label.setText(
            f"Exports are written to {self._context.config.export_dir}"
        )

    def _generate(self) -> None:
        kind = self.report_combo.currentData()
        period = self.period_combo.currentData()
        self.generate_button.setEnabled(False)

        def produce() -> dict[str, Any]:
            return self._produce(kind, period)

        worker = ActionWorker(produce, "Report")
        worker.finished_ok.connect(self._on_generated)
        worker.failed.connect(
            lambda message: (
                self.generate_button.setEnabled(True),
                show_error(self, BizPilotError(message)),
            )
        )
        worker.finished.connect(
            lambda: self._workers.remove(worker) if worker in self._workers else None
        )
        self._workers.append(worker)
        worker.start()

    def _produce(self, kind: str, period: str) -> dict[str, Any]:
        services = self._context
        if kind == "FINANCE_PDF":
            path = services.finance_service.export_report("monthly_summary", file_format="pdf")
            return {"report": "Financial summary", "format": "PDF", "path": str(path)}
        if kind == "FINANCE_CSV":
            path = services.finance_service.export_report("monthly_summary", file_format="csv")
            return {"report": "Financial summary", "format": "CSV", "path": str(path)}
        if kind == "EXPENSES_CSV":
            path = services.finance_service.export_expenses_csv()
            return {"report": "Expense ledger", "format": "CSV", "path": str(path)}
        if kind == "SALES_CSV":
            path = services.sales_service.export_sales_csv()
            return {"report": "Sales register", "format": "CSV", "path": str(path)}
        report_type = kind.replace("ANALYTICS_", "")
        result = services.analytics_service.generate_report(
            report_type, file_format="PDF", granularity=period
        )
        return {
            "report": report_type.replace("_", " ").title(),
            "format": result.get("format", "PDF"),
            "path": str(result.get("path")),
            "period": result.get("period"),
        }

    def _on_generated(self, result: Any) -> None:
        self.generate_button.setEnabled(True)
        self._generated.insert(
            0,
            {
                "when": result.get("generated_at"),
                "report": result["report"],
                "format": result["format"],
                "path": result["path"],
            },
        )
        self.table.set_rows(
            [
                [
                    format_datetime(row["when"], "%d %b %I:%M") if row["when"] else "just now",
                    row["report"],
                    row["format"],
                    row["path"].split("/")[-1],
                    self._size(row["path"]),
                ]
                for row in self._generated
            ]
        )
        show_info(self, f"{result['report']} written to:\n{result['path']}")

    def _size(self, path: str) -> str:
        from pathlib import Path

        try:
            return f"{Path(path).stat().st_size / 1024:.1f} KB"
        except OSError:
            return "—"

    def _show_detail(self) -> None:
        row = self.table.table.currentRow()
        if 0 <= row < len(self._generated):
            self.detail.setPlainText(self._generated[row]["path"])

    def _show_folder(self) -> None:
        show_info(self, f"Reports are saved in:\n{self._context.config.export_dir}")

    def wait_for_idle(self, timeout_ms: int = 120000) -> bool:
        from PySide6.QtWidgets import QApplication

        for worker in list(self._workers):
            try:
                worker.wait(timeout_ms)
            except RuntimeError:
                continue
            QApplication.processEvents()
        QApplication.processEvents()
        return True

    def shutdown(self) -> None:
        for worker in list(self._workers):
            try:
                if worker.isRunning():
                    worker.wait(5000)
            except RuntimeError:
                pass
