"""Event-driven workflow triggers.

Business events from the Phase 2 outbox become workflows — once. Every trigger is
recorded with a unique key, so a replayed event never creates a second workflow,
and an event that cannot be handled is written to the dead-letter table.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.autonomy.engine import AutonomousWorkflowEngine
from app.core.constants import WorkflowTriggerType, WorkflowType
from app.core.logging_config import get_logger
from app.database.models.autonomy import WorkflowDeadLetter, WorkflowTrigger
from app.database.models.events import BusinessEvent
from app.utils.date_utils import utcnow

logger = get_logger("ai.autonomy.triggers")

# Event → workflow mapping. Deliberately excludes PurchaseOrderCreated and
# GoodsReceived so a purchase order can never re-trigger purchase automation.
EVENT_WORKFLOW_MAP: dict[str, str] = {
    "StockBelowMinimum": WorkflowType.LOW_STOCK_REPLENISHMENT,
    "ExpenseRecorded": WorkflowType.UNUSUAL_EXPENSE_REVIEW,
}

DEFAULT_EXPENSE_THRESHOLD = Decimal("10000.00")
MAX_EVENT_ATTEMPTS = 3


class WorkflowTriggerManager:
    """Turns business events into workflow runs, exactly once each."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        engine: AutonomousWorkflowEngine,
        expense_threshold: Decimal = DEFAULT_EXPENSE_THRESHOLD,
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine
        self._expense_threshold = expense_threshold

    # -- mapping -----------------------------------------------------------
    def workflow_for_event(self, event_type: str, payload: dict[str, Any]) -> str | None:
        workflow_type = EVENT_WORKFLOW_MAP.get(event_type)
        if workflow_type is None:
            return None
        if event_type == "ExpenseRecorded":
            amount = _dec(payload.get("amount"))
            if amount is None or amount < self._expense_threshold:
                return None
        return workflow_type

    def trigger_key(self, event_id: int, workflow_type: str) -> str:
        return f"EVENT:{event_id}:{workflow_type}"

    # -- processing --------------------------------------------------------
    def process_pending(self, limit: int = 20) -> dict[str, int]:
        """Scan unprocessed business events and create workflows for them."""
        created = 0
        skipped = 0
        dead = 0
        with self._session_factory() as db:
            events = db.scalars(
                select(BusinessEvent).order_by(BusinessEvent.id).limit(limit)
            ).all()
            seen = {
                row.trigger_key for row in db.scalars(select(WorkflowTrigger)).all()
            }
            pending = [
                event
                for event in events
                if not any(key.startswith(f"EVENT:{event.id}:") for key in seen)
            ]

        for event in pending:
            payload = dict(event.payload or {})
            workflow_type = self.workflow_for_event(event.event_type, payload)
            key = self.trigger_key(event.id, workflow_type or event.event_type)
            if workflow_type is None:
                skipped += 1
                self._record_trigger(key, event, None, None, payload)
                continue
            try:
                view = self._engine.create_workflow(
                    workflow_type,
                    payload=payload,
                    trigger_type=WorkflowTriggerType.EVENT,
                    trigger_ref=key,
                    objective=self._objective(event.event_type, payload),
                    requested_by=self._business_owner_id(),
                    business_id=event.business_id if hasattr(event, "business_id") else None,
                )
                self._record_trigger(key, event, workflow_type, view.workflow_ref, payload)
                self._engine.execute_workflow(view.workflow_ref)
                created += 1
            except Exception as exc:  # noqa: BLE001 - one bad event must not stop the scan
                logger.exception("Event %s could not be turned into a workflow", event.id)
                self._dead_letter(key, event, str(exc))
                dead += 1
        return {"created": created, "skipped": skipped, "dead_letters": dead}

    def _record_trigger(
        self,
        key: str,
        event: BusinessEvent,
        workflow_type: str | None,
        workflow_ref: str | None,
        payload: dict,
    ) -> None:
        with self._session_factory() as db:
            db.add(
                WorkflowTrigger(
                    trigger_key=key,
                    trigger_type=WorkflowTriggerType.EVENT,
                    event_type=event.event_type,
                    event_id=event.id,
                    workflow_type=workflow_type or "IGNORED",
                    workflow_id=self._workflow_id(db, workflow_ref),
                    payload=payload,
                    status="CONSUMED" if workflow_type else "IGNORED",
                )
            )
            try:
                db.commit()
            except IntegrityError:  # pragma: no cover - duplicate guard
                db.rollback()

    def _dead_letter(self, key: str, event: BusinessEvent, error: str) -> None:
        with self._session_factory() as db:
            db.add(
                WorkflowDeadLetter(
                    source="EVENT",
                    reference=key,
                    event_type=event.event_type,
                    payload=dict(event.payload or {}),
                    error_message=error[:1000],
                    attempts=1,
                    status="OPEN",
                )
            )
            db.commit()

    def list_dead_letters(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(WorkflowDeadLetter).order_by(WorkflowDeadLetter.id.desc()).limit(limit)
            ).all()
            return [
                {
                    "reference": row.reference,
                    "event_type": row.event_type,
                    "error": row.error_message,
                    "attempts": row.attempts,
                    "status": row.status,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def retry_dead_letters(self) -> int:
        """Re-open dead letters so the next scan retries them."""
        retried = 0
        with self._session_factory() as db:
            rows = db.scalars(
                select(WorkflowDeadLetter).where(WorkflowDeadLetter.status == "OPEN")
            ).all()
            for row in rows:
                if row.attempts >= MAX_EVENT_ATTEMPTS:
                    row.status = "ABANDONED"
                    continue
                row.attempts += 1
                row.status = "RETRYING"
                trigger = db.scalars(
                    select(WorkflowTrigger).where(WorkflowTrigger.trigger_key == row.reference)
                ).first()
                if trigger is not None:
                    db.delete(trigger)
                retried += 1
            db.commit()
        return retried

    # -- helpers -----------------------------------------------------------
    def _workflow_id(self, db: Session, workflow_ref: str | None) -> int | None:
        if not workflow_ref:
            return None
        from app.database.models.autonomy import AutonomousWorkflow

        return db.scalars(
            select(AutonomousWorkflow.id).where(
                AutonomousWorkflow.workflow_ref == workflow_ref
            )
        ).first()

    def _business_owner_id(self) -> int | None:
        from app.database.models.user import User

        with self._session_factory() as db:
            return db.scalars(
                select(User.id)
                .where(User.is_superuser.is_(True), User.is_active.is_(True))
                .order_by(User.id)
            ).first()

    def _objective(self, event_type: str, payload: dict[str, Any]) -> str:
        if event_type == "StockBelowMinimum":
            return f"Replenish {payload.get('product_name', 'a low-stock product')}."
        if event_type == "ExpenseRecorded":
            return f"Review the unusual expense of {payload.get('amount', 'an unknown amount')}."
        return f"Automated workflow for {event_type}"


def _dec(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
