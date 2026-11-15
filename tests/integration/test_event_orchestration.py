"""Integration tests: event-driven orchestration."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select

from app.core.constants import AIWorkflowStatus
from app.core.exceptions import BizPilotError
from app.database.models.ai import AIWorkflow
from app.database.models.events import BusinessEvent

from tests.conftest import completed_sale


def _workflows_for_event(context, event_id: int) -> list[AIWorkflow]:
    with context.database.session_factory() as db:
        return list(
            db.scalars(
                select(AIWorkflow).where(AIWorkflow.source_event_id == event_id)
            ).all()
        )


def _latest_event(context, event_type: str) -> BusinessEvent:
    with context.database.session_factory() as db:
        return db.scalars(
            select(BusinessEvent)
            .where(BusinessEvent.event_type == event_type)
            .order_by(BusinessEvent.id.desc())
        ).first()


def test_sale_completed_triggers_an_analysis(admin, business) -> None:
    completed_sale(admin, business, quantity=2)
    event = _latest_event(admin, "SaleCompleted")
    assert event is not None

    report = admin.ai_service.process_pending_events(limit=5)
    assert report.processed >= 1

    workflows = _workflows_for_event(admin, event.id)
    assert len(workflows) == 1
    assert workflows[0].trigger_type == "EVENT"
    assert workflows[0].intent == "ANALYZE_SALES"
    assert workflows[0].status == AIWorkflowStatus.COMPLETED


def test_duplicate_events_are_not_processed_twice(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    event = _latest_event(admin, "SaleCompleted")

    admin.ai_service.process_pending_events(limit=5)
    admin.ai_service.process_pending_events(limit=5)

    assert len(_workflows_for_event(admin, event.id)) == 1


def test_stock_below_minimum_triggers_low_stock_analysis(admin, business) -> None:
    admin.inventory_service.adjust_stock(
        {
            "product_id": business["tea"].id,
            "quantity": 8,
            "movement_type": "ADJUSTMENT",
            "reason": "Bulk breakage",
            "direction": -1,
        }
    )
    event = _latest_event(admin, "StockBelowMinimum")
    assert event is not None

    admin.ai_service.process_pending_events(limit=5)
    workflows = _workflows_for_event(admin, event.id)
    assert len(workflows) == 1
    assert workflows[0].intent == "LOW_STOCK_ANALYSIS"


def test_event_workflow_failure_is_recorded_and_retryable(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    event = _latest_event(admin, "SaleCompleted")

    original = admin.tool_registry.get("run_sales_agent").handler

    def boom(context, args):
        raise BizPilotError("Sales service offline")

    definition = admin.tool_registry.get("run_sales_agent")
    admin.tool_registry.unregister("run_sales_agent")
    admin.tool_registry.register(
        type(definition)(
            name=definition.name,
            description=definition.description,
            category=definition.category,
            input_model=definition.input_model,
            required_permission=definition.required_permission,
            risk_level=definition.risk_level,
            timeout_seconds=definition.timeout_seconds,
            handler=boom,
        )
    )

    admin.ai_service.process_pending_events(limit=5)
    workflows = _workflows_for_event(admin, event.id)
    assert len(workflows) == 1
    assert workflows[0].status == AIWorkflowStatus.FAILED

    admin.tool_registry.unregister("run_sales_agent")
    admin.tool_registry.register(
        type(definition)(
            name=definition.name,
            description=definition.description,
            category=definition.category,
            input_model=definition.input_model,
            required_permission=definition.required_permission,
            risk_level=definition.risk_level,
            timeout_seconds=definition.timeout_seconds,
            handler=original,
        )
    )
    retried = admin.ai_service.retry_workflow(workflows[0].workflow_id)
    assert retried.status == AIWorkflowStatus.COMPLETED


def test_event_subscriber_lists_supported_events(admin) -> None:
    from app.ai.events.event_processor import EventSubscriber

    subscriber = EventSubscriber(admin.orchestrator)
    supported = subscriber.subscribed_events
    assert set(supported) == {
        "SaleCompleted",
        "SaleCancelled",
        "StockBelowMinimum",
        "ExpenseRecorded",
        "PaymentReceived",
        "CustomerCreated",
        "PurchaseOrderCreated",
        "GoodsReceived",
    }
    assert subscriber.is_subscribed("SaleCompleted") is True
    assert subscriber.is_subscribed("UnknownEvent") is False


def test_event_dispatcher_drains_outbox_then_analyses(admin, business) -> None:
    from app.ai.events.event_processor import EventDispatcher

    completed_sale(admin, business, quantity=1)
    dispatcher = EventDispatcher(
        event_service=admin.event_service, processor=admin.event_processor
    )
    report = dispatcher.dispatch_once()
    assert report.processed >= 1

    with admin.database.session_factory() as db:
        pending = db.scalar(
            select(func.count(BusinessEvent.id)).where(BusinessEvent.status == "PENDING")
        )
    assert (pending or 0) == 0


def test_events_survive_a_restart(admin, business) -> None:
    completed_sale(admin, business, quantity=1)
    event = _latest_event(admin, "SaleCompleted")

    admin.database.dispose()
    admin.database.initialize()
    admin.orchestrator.recover()

    admin.ai_service.process_pending_events(limit=5)
    assert len(_workflows_for_event(admin, event.id)) == 1
