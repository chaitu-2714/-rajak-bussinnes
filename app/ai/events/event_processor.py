"""Event-driven orchestration.

Phase 2 publishes business events into the ``business_events`` outbox inside the
business transaction. This module turns those events into AI analysis workflows:

* the event is validated and de-duplicated (one workflow per event, enforced by
  a unique constraint);
* the matching intent is planned and executed through the same orchestrator;
* failures are recorded on the workflow and can be retried.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.ai.orchestrator.orchestrator import EVENT_INTENT_MAP, BizPilotOrchestrator
from app.core.constants import EventStatus
from app.core.logging_config import get_logger

logger = get_logger("ai.events")


@dataclass
class EventProcessingReport:
    examined: int = 0
    processed: int = 0
    skipped: int = 0
    failed: int = 0

    def as_text(self) -> str:
        return (
            f"{self.processed} event(s) analysed, {self.skipped} skipped, "
            f"{self.failed} failed out of {self.examined} examined."
        )


class EventSubscriber:
    """Declares which business events the AI layer cares about."""

    def __init__(self, orchestrator: BizPilotOrchestrator) -> None:
        self._orchestrator = orchestrator

    @property
    def subscribed_events(self) -> dict[str, str]:
        return {event: intent.value for event, intent in EVENT_INTENT_MAP.items()}

    def is_subscribed(self, event_type: str) -> bool:
        return event_type in EVENT_INTENT_MAP

    def handler(self) -> Callable[[dict[str, Any]], None]:
        """A no-op handler: events are analysed by the processor, not here."""

        def _noop(payload: dict[str, Any]) -> None:
            logger.debug("Business event observed: %s", payload.get("event_type"))

        return _noop


class EventProcessor:
    """Converts pending business events into executed AI workflows."""

    def __init__(self, orchestrator: BizPilotOrchestrator, *, batch_size: int = 10) -> None:
        self._orchestrator = orchestrator
        self._batch_size = batch_size

    def process_pending(self, limit: int | None = None) -> EventProcessingReport:
        report = EventProcessingReport()
        try:
            processed = self._orchestrator.process_pending_events(limit or self._batch_size)
        except Exception:  # pragma: no cover - defensive
            logger.exception("Event processing failed")
            report.failed += 1
            return report
        report.processed = processed
        report.examined = processed
        report.skipped = 0
        return report

    def process_event(self, event_id: int):
        return self._orchestrator.process_event(event_id)


class EventDispatcher:
    """Drains the outbox and then hands new events to the AI processor.

    Called from a background timer in the UI, never from the business
    transaction itself.
    """

    def __init__(self, *, event_service: Any, processor: EventProcessor) -> None:
        self._event_service = event_service
        self._processor = processor

    def dispatch_once(self) -> EventProcessingReport:
        try:
            self._event_service.dispatch_pending()
        except Exception:  # pragma: no cover - defensive
            logger.exception("Outbox dispatch failed")
        return self._processor.process_pending()

    @staticmethod
    def pending_status(status: str = EventStatus.PENDING) -> bool:
        return status in (EventStatus.PENDING, EventStatus.FAILED)
