"""UI tests: the Knowledge Center reflects real documents and answers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ui.main_window import MainWindow
from app.ui.pages.knowledge_center import KnowledgeCenterPage


def _close(widget) -> None:
    shutdown = getattr(widget, "shutdown", None)
    if callable(shutdown):
        shutdown()
    widget.close()
    widget.deleteLater()


def _page(admin) -> KnowledgeCenterPage:
    page = KnowledgeCenterPage(admin)
    page.wait_for_idle()
    return page


@pytest.fixture()
def uploaded(admin, tmp_path: Path) -> str:
    path = tmp_path / "supplier_agreement.txt"
    path.write_text(
        "SUPPLIER AGREEMENT\nPayment terms: 30 days from invoice date\n"
        "Delivery terms: Delivery within 7 days of purchase order\n",
        encoding="utf-8",
    )
    return admin.knowledge_service.upload_document(path)["document_ref"]


def test_page_is_registered_and_reachable(qapp, admin) -> None:
    window = MainWindow(admin)
    try:
        window.navigate_to("knowledge")
        page = window.page_for("knowledge")
        assert isinstance(page, KnowledgeCenterPage)
        assert "knowledge" in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_library_shows_real_documents(qapp, admin, uploaded) -> None:
    page = _page(admin)
    try:
        assert page.documents_table.row_count() == 1
        assert page.card_total.value_text == "1"
        assert page.card_indexed.value_text == "1"
        page.documents_table.table.selectRow(0)
        page._show_document()
        page.wait_for_idle()
        assert "SUPPLIER AGREEMENT" in page.document_text.toPlainText()
        assert page.extraction_table.row_count() >= 2
    finally:
        _close(page)


def test_search_tab_returns_passages(qapp, admin, uploaded) -> None:
    page = _page(admin)
    try:
        page.search_input.setText("payment terms 30 days")
        page._search()
        page.wait_for_idle()
        assert page.search_table.row_count() >= 1
        page.search_table.table.selectRow(0)
        page._show_hit()
        assert "page 1" in page.search_preview.toPlainText()
    finally:
        _close(page)


def test_assistant_tab_shows_answer_and_sources(qapp, admin, uploaded) -> None:
    page = _page(admin)
    try:
        page.ask_input.setText("What are the payment terms in the supplier agreement?")
        page._ask()
        page.wait_for_idle()
        text = page.answer_text.toPlainText()
        assert "30 days" in text
        assert "grounded: True" in text
        assert page.sources_table.row_count() >= 1
    finally:
        _close(page)


def test_employee_cannot_see_the_knowledge_center(qapp, employee_context) -> None:
    window = MainWindow(employee_context)
    try:
        assert "knowledge" not in window.sidebar.visible_keys()
    finally:
        _close(window)


def test_settings_tab_lists_providers(qapp, admin) -> None:
    page = _page(admin)
    try:
        page.wait_for_idle()
        assert page.providers_table.row_count() >= 2
        assert page.save_settings_button.isEnabled() is True
        assert "lexical-hashing" in page.status_label.text() or "dims" in page.status_label.text()
    finally:
        _close(page)
