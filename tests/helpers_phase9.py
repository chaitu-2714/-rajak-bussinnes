"""Helpers for the Phase 9 security tests."""

from __future__ import annotations

from typing import Any

from tests.conftest import completed_sale


def create_pending_approval(admin: Any, business: dict) -> tuple[str, int]:
    """Run a low-stock workflow until it waits for a purchase-order approval."""
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 9,
            "movement_type": "ADJUSTMENT",
            "reason": "Breakage",
            "direction": -1,
        }
    )
    completed_sale(admin, business, quantity=1)
    view = admin.autonomy_service.create_workflow(
        "LOW_STOCK_REPLENISHMENT",
        payload={
            "product_id": business["tea"].id,
            "supplier_id": business["supplier"].id,
            "items": [
                {
                    "product_id": business["tea"].id,
                    "ordered_quantity": 10,
                    "unit_cost": "100.00",
                }
            ],
        },
    )
    admin.autonomy_service.start_workflow(view.workflow_ref)
    approval = admin.autonomy_service.pending_approvals()[0]
    requester = admin.auth_context.principal.user_id
    return approval.approval_ref, requester
