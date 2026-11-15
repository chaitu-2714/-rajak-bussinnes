"""Finance tests: expenses, revenue/profit maths, reconciliation, duplicates."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.exceptions import ConflictError, ValidationError

from tests.conftest import completed_sale


def _expense(admin, **overrides) -> dict:
    payload = {
        "expense_category": "RENT",
        "description": "Shop rent",
        "vendor_name": "Landlord",
        "amount": "5000.00",
        "payment_method": "BANK_TRANSFER",
        "expense_date": "2026-11-01T09:00:00",
    }
    payload.update(overrides)
    return admin.finance_service.create_expense(payload)


def test_create_expense_posts_ledger_entry(admin, business) -> None:
    expense = _expense(admin)
    assert expense.expense_number.startswith("EXP-")
    assert expense.status == "RECORDED"

    transactions = admin.finance_service.list_transactions()
    assert any(t.category == "OPERATING_EXPENSE" for t in transactions)
    assert admin.finance_service.summary().operating_expenses == Decimal("5000.00")


def test_expense_validation(admin) -> None:
    with pytest.raises(ValidationError):
        _expense(admin, amount="0")
    with pytest.raises(ValidationError):
        _expense(admin, expense_category="NOT_A_CATEGORY")
    with pytest.raises(ValidationError):
        _expense(admin, description="")


def test_revenue_is_recognised_on_completion_only(admin, business) -> None:
    order = admin.sales_service.create_order(
        {
            "customer_id": business["customer"].id,
            "items": [{"product_id": business["tea"].id, "quantity": 2}],
        }
    )
    assert admin.finance_service.summary().revenue == Decimal("0.00")

    admin.sales_service.complete_order(order.id)
    summary = admin.finance_service.summary()
    assert summary.revenue == Decimal("300.00")
    # Revenue is not cash.
    assert summary.cash_received == Decimal("0.00")
    assert summary.outstanding_receivables == Decimal("300.00")


def test_cash_is_recognised_on_payment(admin, business) -> None:
    sale = completed_sale(admin, business, quantity=2)
    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "120.00"}
    )
    summary = admin.finance_service.summary()
    assert summary.revenue == Decimal("300.00")
    assert summary.cash_received == Decimal("120.00")
    assert summary.outstanding_receivables == Decimal("180.00")


def test_gross_and_net_profit_maths(admin, business) -> None:
    completed_sale(admin, business, quantity=2)  # revenue 300, COGS 200
    _expense(admin, amount="50.00", expense_category="UTILITIES")

    summary = admin.finance_service.summary()
    assert summary.revenue == Decimal("300.00")
    assert summary.cogs == Decimal("200.00")
    assert summary.gross_profit == Decimal("100.00")
    assert summary.operating_expenses == Decimal("50.00")
    assert summary.net_profit == Decimal("50.00")
    assert summary.total_expenses == Decimal("250.00")


def test_purchase_expenses_are_excluded_from_operating_costs(admin, business) -> None:
    """PURCHASE expenses are capitalised and must not double count with COGS."""
    _expense(admin, expense_category="PURCHASE", amount="1000.00")
    summary = admin.finance_service.summary()
    assert summary.operating_expenses == Decimal("0.00")
    assert summary.net_profit == Decimal("0.00")


def test_duplicate_transaction_prevented(admin, business) -> None:
    with admin.finance_service.unit_of_work() as db:
        admin.finance_service.post_transaction(
            db,
            transaction_type="INCOME",
            category="OTHER_INCOME",
            amount=Decimal("100.00"),
            reference_type="MANUAL",
            reference_id="42",
            description="Manual income",
        )
    with pytest.raises(ConflictError):
        with admin.finance_service.unit_of_work() as db:
            admin.finance_service.post_transaction(
                db,
                transaction_type="INCOME",
                category="OTHER_INCOME",
                amount=Decimal("100.00"),
                reference_type="MANUAL",
                reference_id="42",
                description="Duplicate",
            )


def test_expense_reversal_posts_counter_entry(admin) -> None:
    expense = _expense(admin, amount="200.00")
    admin.finance_service.reverse_expense(expense.id, "Duplicate entry")

    summary = admin.finance_service.summary()
    assert summary.operating_expenses == Decimal("0.00")

    with pytest.raises(ConflictError):
        admin.finance_service.reverse_expense(expense.id, "Again")


def test_reversed_expense_cannot_be_edited(admin) -> None:
    expense = _expense(admin, amount="200.00")
    admin.finance_service.reverse_expense(expense.id, "Mistake")
    with pytest.raises(ConflictError):
        admin.finance_service.update_expense(
            expense.id,
            {
                "expense_category": "RENT",
                "description": "Changed",
                "amount": "10.00",
                "payment_method": "CASH",
                "expense_date": "2026-11-02T09:00:00",
            },
        )


def test_expense_update_keeps_ledger_in_step(admin) -> None:
    expense = _expense(admin, amount="100.00")
    admin.finance_service.update_expense(
        expense.id,
        {
            "expense_category": "RENT",
            "description": "Shop rent (corrected)",
            "amount": "150.00",
            "payment_method": "CASH",
            "expense_date": "2026-11-01T09:00:00",
        },
    )
    assert admin.finance_service.summary().operating_expenses == Decimal("150.00")


@pytest.mark.parametrize(
    "report_type",
    ["income", "expense", "profit_and_loss", "cash_flow", "outstanding", "monthly_summary"],
)
def test_reports_build_with_real_data(admin, business, report_type) -> None:
    sale = completed_sale(admin, business, quantity=2)
    admin.sales_service.record_payment(
        {"invoice_id": sale["invoice"].id, "amount": "100.00"}
    )
    _expense(admin, amount="75.00")

    report = admin.finance_service.build_report(report_type)
    assert report.title
    assert report.rows
    assert report.basis


def test_unknown_report_rejected(admin) -> None:
    with pytest.raises(ValidationError):
        admin.finance_service.build_report("not_a_report")


def test_finance_csv_and_pdf_export(admin, business) -> None:
    from pathlib import Path

    completed_sale(admin, business, quantity=1)
    _expense(admin, amount="10.00")

    csv_path = Path(admin.finance_service.export_report("expense", file_format="csv"))
    pdf_path = Path(admin.finance_service.export_report("profit_and_loss", file_format="pdf"))

    assert csv_path.exists() and csv_path.stat().st_size > 0
    assert pdf_path.read_bytes()[:4] == b"%PDF"
    assert pdf_path.stat().st_size > 500


def test_invoice_pdf_export(admin, business) -> None:
    from pathlib import Path

    sale = completed_sale(admin, business, quantity=1)
    invoice = admin.sales_service.invoice(sale["invoice"].id)
    path = Path(
        admin.export_service.write_invoice_pdf(
            invoice=invoice, business=admin.business_service.get_business()
        )
    )
    assert path.exists()
    assert path.read_bytes()[:4] == b"%PDF"
    assert path.name == f"{invoice.invoice_number}.pdf"


def test_finance_summary_reports_its_basis(admin) -> None:
    summary = admin.finance_service.summary()
    assert "Revenue is recognised when a sales order completes" in summary.basis


def test_monthly_series_for_charts(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    _expense(admin, amount="25.00")
    series = admin.finance_service.monthly_series()
    assert series["labels"]
    assert series["income"][0] == Decimal("150.00")
    assert series["expenses"][0] == Decimal("25.00")
