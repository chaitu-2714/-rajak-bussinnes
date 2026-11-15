"""Inventory tests: products, stock movements, low stock and valuation."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    ValidationError,
)

from tests.conftest import seed_business


def test_create_product_with_category(admin) -> None:
    category = admin.inventory_service.create_category({"category_name": "Drinks"})
    product = admin.inventory_service.create_product(
        {
            "product_name": "Cola 500ml",
            "category_id": category.id,
            "cost_price": "20.00",
            "selling_price": "35.00",
            "minimum_stock": 4,
        }
    )
    assert product.sku.startswith("SKU-")
    assert product.category_name == "Drinks"
    assert product.cost_price == Decimal("20.00")


def test_duplicate_category_rejected(admin) -> None:
    admin.inventory_service.create_category({"category_name": "Snacks"})
    with pytest.raises(ConflictError):
        admin.inventory_service.create_category({"category_name": "snacks"})


def test_duplicate_sku_rejected(admin) -> None:
    admin.inventory_service.create_product({"product_name": "One", "sku": "SKU-ABC"})
    with pytest.raises(ConflictError):
        admin.inventory_service.create_product({"product_name": "Two", "sku": "SKU-ABC"})


def test_negative_price_rejected(admin) -> None:
    with pytest.raises(ValidationError):
        admin.inventory_service.create_product(
            {"product_name": "Bad", "cost_price": "-5.00"}
        )


def test_opening_stock_creates_movement(admin, business) -> None:
    movements = admin.inventory_service.movements(product_id=business["tea"].id)
    assert movements
    opening = [m for m in movements if m.movement_type == "OPENING_STOCK"]
    assert opening[0].previous_quantity == 0
    assert opening[0].new_quantity == 10
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10


def test_stock_addition_and_reduction(admin, business) -> None:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 5,
            "movement_type": "ADJUSTMENT",
            "reason": "Found extra stock",
            "direction": 1,
        }
    )
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 15

    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 3,
            "movement_type": "ADJUSTMENT",
            "reason": "Stock count correction",
            "direction": -1,
        }
    )
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 12


def test_stock_cannot_go_negative(admin, business) -> None:
    with pytest.raises(ConflictError):
        admin.inventory_service.adjust_stock(
            {
                "product_id": business["tea"].id,
                "quantity": 999,
                "movement_type": "ADJUSTMENT",
                "reason": "Too much",
                "direction": -1,
            }
        )
    assert admin.inventory_service.stock_for_product(business["tea"].id) == 10


def test_damaged_stock_always_reduces(admin, business) -> None:
    movement = admin.inventory_service.adjust_stock(
        {
            "product_id": business["coffee"].id,
            "quantity": 2,
            "movement_type": "DAMAGE",
            "reason": "Water damage",
        }
    )
    assert movement.movement_type == "DAMAGE"
    assert movement.new_quantity == 18


def test_low_stock_detection_and_event(admin, business) -> None:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 6,
            "movement_type": "ADJUSTMENT",
            "reason": "Counted",
            "direction": -1,
        }
    )
    alerts = admin.inventory_service.low_stock_alerts()
    assert any(alert.product_id == business["tea"].id for alert in alerts)
    tea_alert = next(a for a in alerts if a.product_id == business["tea"].id)
    assert tea_alert.available_quantity == 4
    assert tea_alert.minimum_stock == 5
    assert tea_alert.suggested_reorder_quantity >= 1

    events = admin.event_service.list_events()
    assert any(event["event_type"] == "StockBelowMinimum" for event in events)


def test_out_of_stock_detection(admin, business) -> None:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["coffee"].id,
            "quantity": 20,
            "movement_type": "ADJUSTMENT",
            "reason": "Sold out",
            "direction": -1,
        }
    )
    rows = admin.inventory_service.list_stock(out_of_stock_only=True)
    assert [row.product_id for row in rows] == [business["coffee"].id]
    assert rows[0].is_out_of_stock is True


def test_stock_valuation_uses_cost_not_selling_price(admin, business) -> None:
    dashboard = admin.inventory_service.dashboard()
    expected = Decimal("10") * Decimal("100.00") + Decimal("20") * Decimal("50.00")
    assert dashboard.stock_value == expected
    assert admin.inventory_service.stock_valuation() == expected


def test_stock_rows_report_low_flags(admin, business) -> None:
    rows = admin.inventory_service.list_stock()
    tea = next(row for row in rows if row.product_id == business["tea"].id)
    assert tea.is_low is False
    assert tea.stock_value == Decimal("1000.00")


def test_movement_history_is_filterable(admin, business) -> None:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 1,
            "movement_type": "DAMAGE",
            "reason": "Torn pack",
        }
    )
    damage = admin.inventory_service.movements(movement_type="DAMAGE")
    assert len(damage) == 1
    assert damage[0].product_id == business["tea"].id


def test_unknown_product_raises(admin) -> None:
    with pytest.raises(NotFoundError):
        admin.inventory_service.get_product(4242)


def test_product_export_rows(admin, business) -> None:
    headers, rows = admin.inventory_service.export_rows()
    assert "SKU" in headers
    assert len(rows) == 2


def test_csv_export_writes_file(admin, business) -> None:
    path = admin.inventory_service.export_stock_csv()
    from pathlib import Path

    file = Path(path)
    assert file.exists() and file.stat().st_size > 0
    assert file.read_text(encoding="utf-8-sig").startswith("SKU,")
