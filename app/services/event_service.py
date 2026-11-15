"""Transactional outbox + local event bus.

Services write a :class:`BusinessEvent` row **inside** the same transaction as
the business change, so an event can never be lost or announced before the
change is committed. :meth:`EventService.dispatch_pending` runs after the
commit, delivers the event to any registered in-process handlers, and leaves
failures retryable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import EventStatus
from app.core.logging_config import get_logger
from app.database.models.events import BusinessEvent
from app.database.repositories.event_repository import EventRepository
from app.services.base_service import AuthContext, BaseService
from app.utils.date_utils import utcnow

logger = get_logger("services.events")

Handler = Callable[[dict[str, Any]], None]


class EventService(BaseService):
    """Publishes business events reliably and dispatches them locally."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        event_repository: EventRepository,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._events = event_repository
        self._handlers: dict[str, list[Handler]] = {}
        self._register_default_handlers()

    # -- publishing --------------------------------------------------------
    def publish(
        self,
        db: Session,
        event_type: str,
        *,
        aggregate_type: str | None = None,
        aggregate_id: str | int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> BusinessEvent:
        """Queue an event inside the caller's transaction (outbox pattern)."""
        event = BusinessEvent(
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id) if aggregate_id is not None else None,
            payload=payload or {},
            status=EventStatus.PENDING,
            attempts=0,
            created_at=utcnow(),
        )
        self._events.add(db, event)
        logger.debug("Queued business event %s", event_type)
        return event

    # -- handlers ----------------------------------------------------------
    def register_handler(self, event_type: str, handler: Handler) -> None:
        """Register an in-process subscriber for an event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    def _register_default_handlers(self) -> None:
        def _log(payload: dict[str, Any]) -> None:
            logger.info("Business event dispatched: %s", payload.get("event_type"))

        for event_type in (
            "SaleCompleted",
            "SaleCancelled",
            "StockBelowMinimum",
            "ExpenseRecorded",
            "PaymentReceived",
            "CustomerCreated",
            "PurchaseOrderCreated",
            "GoodsReceived",
        ):
            self.register_handler(event_type, _log)

    # -- dispatching -------------------------------------------------------
    def dispatch_pending(self, limit: int = 100) -> int:
        """Deliver queued events; returns how many were dispatched."""
        dispatched = 0
        with self.unit_of_work() as db:
            for event in self._events.list_pending(db, limit=limit):
                handlers = self._handlers.get(event.event_type, [])
                payload = dict(event.payload or {})
                payload.setdefault("event_type", event.event_type)
                payload.setdefault("aggregate_id", event.aggregate_id)
                try:
                    for handler in handlers:
                        handler(payload)
                except Exception as exc:  # noqa: BLE001 - retried later
                    event.attempts += 1
                    event.last_error = str(exc)[:500]
                    event.status = (
                        EventStatus.FAILED if event.attempts >= 5 else EventStatus.PENDING
                    )
                    logger.warning("Event %s delivery failed: %s", event.event_type, exc)
                else:
                    event.status = EventStatus.DISPATCHED
                    event.dispatched_at = utcnow()
                    dispatched += 1
        return dispatched

    def retry_failed(self) -> int:
        """Reset failed events so the next dispatch attempts them again."""
        with self.unit_of_work() as db:
            events = self._events.list_events(db, status=EventStatus.FAILED, limit=500)
            for event in events:
                event.status = EventStatus.PENDING
                event.attempts = 0
            return len(events)

    # -- inspection --------------------------------------------------------
    def pending_count(self) -> int:
        with self.unit_of_work(write=False) as db:
            self._current_user(db)
            return len(self._events.list_pending(db, limit=1000))

    def list_events(self, *, status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Event history for administrators."""
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "audit.view")
            return [
                {
                    "id": event.id,
                    "event_type": event.event_type,
                    "aggregate": f"{event.aggregate_type or '—'}#{event.aggregate_id or '—'}",
                    "status": event.status,
                    "attempts": event.attempts,
                    "created_at": event.created_at,
                    "dispatched_at": event.dispatched_at,
                    "payload": event.payload,
                }
                for event in self._events.list_events(db, status=status, limit=limit)
            ]
