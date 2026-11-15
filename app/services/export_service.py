"""Offline report export: CSV files and PDF documents.

Everything is written to the local exports folder; no network access is used.
Each writer verifies the file it produced before returning the path.
"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.config import AppConfig
from app.core.exceptions import BizPilotError
from app.core.logging_config import get_logger
from app.schemas.finance_schema import ReportTable
from app.utils.date_utils import format_datetime, utcnow

logger = get_logger("services.export")


class ExportError(BizPilotError):
    default_user_message = "The report could not be written to disk."


class ExportService:
    """Writes CSV and PDF deliverables for reports and invoices."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def export_dir(self) -> Path:
        self._config.export_dir.mkdir(parents=True, exist_ok=True)
        return self._config.export_dir

    # -- CSV ---------------------------------------------------------------
    def write_csv(self, filename: str, headers: list[str], rows: list[list[str]]) -> Path:
        path = self.export_dir / filename
        try:
            with path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.writer(handle)
                writer.writerow(headers)
                writer.writerows(rows)
        except OSError as exc:
            raise ExportError(f"Could not write {filename}: {exc}") from exc
        return self._verify(path, minimum_bytes=32)

    def write_report_csv(self, report: ReportTable, filename: str) -> Path:
        rows = list(report.rows)
        if report.totals and any(cell for cell in report.totals):
            rows.append(report.totals)
        return self.write_csv(filename, report.headers, rows)

    # -- PDF ---------------------------------------------------------------
    def _styles(self) -> dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        return {
            "title": ParagraphStyle(
                "BPTitle", parent=base["Title"], fontSize=18, leading=22, alignment=0,
                textColor=colors.HexColor("#0F172A"), spaceAfter=4,
            ),
            "subtitle": ParagraphStyle(
                "BPSubtitle", parent=base["Normal"], fontSize=10, leading=14,
                textColor=colors.HexColor("#64748B"),
            ),
            "body": ParagraphStyle(
                "BPBody", parent=base["Normal"], fontSize=9, leading=12,
                textColor=colors.HexColor("#1F2937"),
            ),
            "small": ParagraphStyle(
                "BPSmall", parent=base["Normal"], fontSize=7.5, leading=10,
                textColor=colors.HexColor("#94A3B8"),
            ),
            "right": ParagraphStyle(
                "BPRight", parent=base["Normal"], fontSize=9, leading=12, alignment=TA_RIGHT,
            ),
            "h2": ParagraphStyle(
                "BPH2", parent=base["Heading2"], fontSize=12, leading=15,
                textColor=colors.HexColor("#0F172A"), spaceBefore=8, spaceAfter=6,
            ),
        }

    def _table(self, headers: list[str], rows: list[list[str]], totals: list[str] | None = None) -> Table:
        data = [headers] + rows
        if totals and any(cell for cell in totals):
            data.append(totals)
        table = Table(data, repeatRows=1, hAlign="LEFT")
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475569")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, -1), (-1, -1), 4),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E2E8F0")),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FBFCFE")]),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (0, -1), (-1, -1), 0.75, colors.HexColor("#CBD5E1")),
                ]
            )
        )
        return table

    def write_pdf_report(self, report: ReportTable, filename: str) -> Path:
        path = self.export_dir / filename
        styles = self._styles()
        story: list = [
            Paragraph(report.title, styles["title"]),
            Paragraph(report.subtitle or "", styles["subtitle"]),
            Paragraph(
                f"BizPilot AI · generated {format_datetime(report.generated_at or utcnow())}",
                styles["small"],
            ),
            Spacer(1, 6 * mm),
        ]
        if report.rows:
            story.append(self._table(report.headers, report.rows, report.totals))
        else:
            story.append(Paragraph("No records for this period.", styles["body"]))
        if report.basis:
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph("Accounting basis", styles["h2"]))
            story.append(Paragraph(report.basis, styles["small"]))
        return self._build_pdf(path, story)

    def write_invoice_pdf(
        self,
        *,
        invoice,
        business,
        filename: str | None = None,
    ) -> Path:
        """Render an invoice PDF from an :class:`InvoiceView`."""
        name = filename or f"{invoice.invoice_number}.pdf"
        path = self.export_dir / name
        styles = self._styles()

        header = Table(
            [
                [
                    Paragraph(f"<b>{business.business_name}</b>", styles["body"]),
                    Paragraph("INVOICE", styles["title"]),
                ],
                [
                    Paragraph(
                        f"{business.owner_name}<br/>{business.email}"
                        + (f"<br/>{business.phone}" if business.phone else "")
                        + (f"<br/>{business.address}" if business.address else ""),
                        styles["small"],
                    ),
                    Paragraph(
                        f"<b>{invoice.invoice_number}</b><br/>"
                        f"Date: {invoice.invoice_date:%d %b %Y}<br/>"
                        + (f"Due: {invoice.due_date:%d %b %Y}<br/>" if invoice.due_date else "")
                        + f"Order: {invoice.order_number}",
                        styles["right"],
                    ),
                ],
            ],
            colWidths=[95 * mm, 80 * mm],
        )
        header.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )

        story: list = [
            header,
            Spacer(1, 6 * mm),
            Paragraph("Billed to", styles["h2"]),
            Paragraph(
                f"{invoice.customer_name}"
                + (f"<br/>{invoice.customer_email}" if invoice.customer_email else "")
                + (f"<br/>{invoice.customer_phone}" if invoice.customer_phone else "")
                + (f"<br/>{invoice.customer_address}" if invoice.customer_address else ""),
                styles["body"],
            ),
            Spacer(1, 6 * mm),
        ]

        rows = [
            [
                str(index),
                line.product_name,
                line.sku,
                str(line.quantity),
                f"{line.unit_price:.2f}",
                f"{line.discount_amount:.2f}",
                f"{line.tax_amount:.2f}",
                f"{line.line_total:.2f}",
            ]
            for index, line in enumerate(invoice.lines, start=1)
        ]
        story.append(
            self._table(
                ["#", "Product", "SKU", "Qty", "Rate", "Discount", "Tax", "Line total"], rows
            )
        )

        totals = Table(
            [
                ["Subtotal", f"{invoice.subtotal:.2f}"],
                ["Discount", f"({invoice.discount_amount:.2f})"],
                ["Tax", f"{invoice.tax_amount:.2f}"],
                ["Total", f"{invoice.total_amount:.2f}"],
                ["Paid", f"{invoice.paid_amount:.2f}"],
                ["Outstanding", f"{invoice.outstanding_amount:.2f}"],
            ],
            colWidths=[40 * mm, 35 * mm],
            hAlign="RIGHT",
        )
        totals.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LINEABOVE", (0, 3), (-1, 3), 0.75, colors.HexColor("#CBD5E1")),
                    ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                    ("TOPPADDING", (0, 0), (-1, -1), 3),
                ]
            )
        )
        story.append(Spacer(1, 4 * mm))
        story.append(totals)
        story.append(Spacer(1, 6 * mm))
        story.append(
            Paragraph(
                f"Invoice status: {invoice.status}. Amounts in {business.currency}. "
                "Generated locally by BizPilot AI — no network connection was used.",
                styles["small"],
            )
        )
        return self._build_pdf(path, story)

    # -- internals ---------------------------------------------------------
    def _build_pdf(self, path: Path, story: list) -> Path:
        document = SimpleDocTemplate(
            str(path),
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
            title=path.stem,
            author="BizPilot AI",
        )
        try:
            document.build(story)
        except Exception as exc:  # reportlab raises various errors
            raise ExportError(f"Could not write {path.name}: {exc}") from exc
        return self._verify(path, minimum_bytes=200, require_pdf=True)

    @staticmethod
    def _verify(path: Path, *, minimum_bytes: int, require_pdf: bool = False) -> Path:
        if not path.exists() or path.stat().st_size < minimum_bytes:
            raise ExportError(f"{path.name} was not written correctly")
        if require_pdf:
            with path.open("rb") as handle:
                if handle.read(4) != b"%PDF":
                    raise ExportError(f"{path.name} is not a valid PDF file")
        logger.info("Export written: %s (%s bytes)", path.name, path.stat().st_size)
        return path
