"""Persistent scheduler for recurring autonomous workflows.

One scheduler instance per desktop application. Each slot is claimed through a
unique trigger key, so a restart or a double tick cannot run the same slot twice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.ai.autonomy.engine import AutonomousWorkflowEngine
from app.core.constants import (
    ScheduleFrequency,
    WorkflowStatus,
    WorkflowTriggerType,
    WorkflowType,
)
from app.core.logging_config import get_logger
from app.database.models.autonomy import ScheduledWorkflow, WorkflowTrigger
from app.utils.date_utils import utcnow

logger = get_logger("ai.autonomy.scheduler")

DEFAULT_SCHEDULES: tuple[dict[str, Any], ...] = (
    {
        "schedule_key": "daily_summary",
        "name": "Daily business summary",
        "workflow_type": WorkflowType.DAILY_SUMMARY,
        "frequency": ScheduleFrequency.DAILY,
        "time_of_day": "08:00",
    },
    {
        "schedule_key": "payment_followup",
        "name": "Overdue invoice follow-up",
        "workflow_type": WorkflowType.PENDING_PAYMENT_FOLLOWUP,
        "frequency": ScheduleFrequency.DAILY,
        "time_of_day": "09:30",
    },
    {
        "schedule_key": "sales_watch",
        "name": "Weekly sales review",
        "workflow_type": WorkflowType.SALES_RECOVERY,
        "frequency": ScheduleFrequency.WEEKLY,
        "time_of_day": "18:00",
        "weekday": 0,
    },
)


class WorkflowScheduler:
    """Runs due schedules; safe against duplicates and restarts."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        engine: AutonomousWorkflowEngine,
        timezone_name: str = "Asia/Kolkata",
    ) -> None:
        self._session_factory = session_factory
        self._engine = engine
        self._timezone_name = timezone_name

    # -- defaults ----------------------------------------------------------
    def seed_defaults(self) -> int:
        created = 0
        with self._session_factory() as db:
            existing = {row.schedule_key for row in db.scalars(select(ScheduledWorkflow)).all()}
            for spec in DEFAULT_SCHEDULES:
                if spec["schedule_key"] in existing:
                    continue
                schedule = ScheduledWorkflow(
                    schedule_key=spec["schedule_key"],
                    name=spec["name"],
                    workflow_type=spec["workflow_type"],
                    frequency=spec["frequency"],
                    time_of_day=spec["time_of_day"],
                    weekday=spec.get("weekday"),
                    timezone=self._timezone_name,
                    enabled=True,
                )
                schedule.next_run_at = self.next_run_time(schedule)
                db.add(schedule)
                created += 1
            db.commit()
        return created

    # -- reads and edits ---------------------------------------------------
    def list_schedules(self) -> list[dict[str, Any]]:
        with self._session_factory() as db:
            rows = db.scalars(
                select(ScheduledWorkflow).order_by(ScheduledWorkflow.schedule_key)
            ).all()
            return [
                {
                    "schedule_key": row.schedule_key,
                    "name": row.name,
                    "workflow_type": row.workflow_type,
                    "frequency": row.frequency,
                    "time_of_day": row.time_of_day,
                    "weekday": row.weekday,
                    "timezone": row.timezone,
                    "enabled": row.enabled,
                    "last_run_at": row.last_run_at,
                    "next_run_at": row.next_run_at,
                    "last_status": row.last_status,
                }
                for row in rows
            ]

    def update_schedule(self, schedule_key: str, *, changes: dict[str, Any]) -> dict[str, Any]:
        with self._session_factory() as db:
            row = db.scalars(
                select(ScheduledWorkflow).where(ScheduledWorkflow.schedule_key == schedule_key)
            ).first()
            if row is None:
                raise ValueError(f"Unknown schedule '{schedule_key}'")
            if "enabled" in changes:
                row.enabled = bool(changes["enabled"])
            if "time_of_day" in changes and changes["time_of_day"]:
                row.time_of_day = str(changes["time_of_day"])
            if "frequency" in changes and changes["frequency"] in ScheduleFrequency.ALL:
                row.frequency = changes["frequency"]
            if "weekday" in changes:
                row.weekday = changes["weekday"]
            row.next_run_at = self.next_run_time(row) if row.enabled else None
            db.commit()
            return {
                "schedule_key": row.schedule_key,
                "enabled": row.enabled,
                "frequency": row.frequency,
                "time_of_day": row.time_of_day,
                "next_run_at": row.next_run_at,
            }

    # -- scheduling maths --------------------------------------------------
    def next_run_time(
        self, schedule: ScheduledWorkflow, *, now: datetime | None = None
    ) -> datetime:
        """Next run in naive UTC, computed in the schedule's timezone."""
        tz = ZoneInfo(schedule.timezone or self._timezone_name)
        local_now = (now or datetime.now(timezone.utc)).astimezone(tz)
        hour, minute = (int(part) for part in (schedule.time_of_day or "08:00").split(":"))

        if schedule.frequency == ScheduleFrequency.INTERVAL_HOURS:
            candidate = local_now + timedelta(hours=schedule.interval_hours or 24)
        else:
            candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if candidate <= local_now:
                candidate += timedelta(days=1)
            if schedule.frequency == ScheduleFrequency.WEEKLY:
                target = schedule.weekday if schedule.weekday is not None else 0
                while candidate.weekday() != target:
                    candidate += timedelta(days=1)
                if candidate <= local_now:
                    candidate += timedelta(days=7)
        return candidate.astimezone(timezone.utc).replace(tzinfo=None)

    # -- execution ---------------------------------------------------------
    def tick(self, *, now: datetime | None = None, limit: int = 5) -> dict[str, Any]:
        """Run every schedule whose slot is due. Returns a small report."""
        current = now or utcnow()
        ran: list[dict[str, Any]] = []
        skipped = 0
        with self._session_factory() as db:
            due = db.scalars(
                select(ScheduledWorkflow).where(
                    ScheduledWorkflow.enabled.is_(True),
                    ScheduledWorkflow.next_run_at.is_not(None),
                    ScheduledWorkflow.next_run_at <= current,
                )
            ).all()
            due_specs = [
                {
                    "id": row.id,
                    "schedule_key": row.schedule_key,
                    "workflow_type": row.workflow_type,
                    "name": row.name,
                    "slot": row.next_run_at.isoformat(),
                }
                for row in due[:limit]
            ]

        for spec in due_specs:
            slot_key = f"SCHEDULE:{spec['schedule_key']}:{spec['slot']}"
            if not self._claim_slot(slot_key, spec):
                skipped += 1
                continue
            try:
                view = self._engine.create_workflow(
                    spec["workflow_type"],
                    payload={"schedule_key": spec["schedule_key"]},
                    trigger_type=WorkflowTriggerType.SCHEDULE,
                    trigger_ref=slot_key,
                    objective=f"Scheduled run: {spec['name']}",
                    requested_by=self._owner_id(),
                )
                self._engine.execute_workflow(view.workflow_ref)
                self._mark_run(spec["id"], WorkflowStatus.COMPLETED, slot_key)
                ran.append(
                    {
                        "schedule_key": spec["schedule_key"],
                        "workflow_ref": view.workflow_ref,
                        "slot": spec["slot"],
                    }
                )
            except Exception as exc:  # noqa: BLE001 - a failing schedule must not stop the tick
                logger.exception("Scheduled workflow %s failed", spec["schedule_key"])
                self._mark_run(spec["id"], WorkflowStatus.FAILED, slot_key, error=str(exc))
                ran.append(
                    {"schedule_key": spec["schedule_key"], "error": str(exc)[:200], "slot": spec["slot"]}
                )
        return {"ran": ran, "skipped": skipped, "checked_at": current.isoformat()}

    def _claim_slot(self, slot_key: str, spec: dict[str, Any]) -> bool:
        with self._session_factory() as db:
            db.add(
                WorkflowTrigger(
                    trigger_key=slot_key,
                    trigger_type=WorkflowTriggerType.SCHEDULE,
                    workflow_type=spec["workflow_type"],
                    payload={"schedule_key": spec["schedule_key"], "slot": spec["slot"]},
                    status="CLAIMED",
                )
            )
            try:
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                return False

    def _mark_run(
        self, schedule_id: int, status: str, slot_key: str, *, error: str | None = None
    ) -> None:
        with self._session_factory() as db:
            row = db.get(ScheduledWorkflow, schedule_id)
            if row is None:
                return
            row.last_run_at = utcnow()
            row.last_status = status
            row.next_run_at = self.next_run_time(row)
            trigger = db.scalars(
                select(WorkflowTrigger).where(WorkflowTrigger.trigger_key == slot_key)
            ).first()
            if trigger is not None:
                trigger.status = "CONSUMED" if status == WorkflowStatus.COMPLETED else "FAILED"
            db.commit()

    def _owner_id(self) -> int | None:
        from app.database.models.user import User

        with self._session_factory() as db:
            return db.scalars(
                select(User.id)
                .where(User.is_superuser.is_(True), User.is_active.is_(True))
                .order_by(User.id)
            ).first()
