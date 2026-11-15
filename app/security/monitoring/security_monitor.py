"""Security monitoring: indicators from real records, never accusations."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging_config import get_logger
from app.database.models.audit_log import AuditLog
from app.database.models.security import SecurityEvent, SecurityIncidentReview
from app.database.models.session import UserSession
from app.database.models.user import User
from app.utils.date_utils import utcnow

logger = get_logger("security.monitor")

THRESHOLDS = {
    "failed_logins_per_hour": 5,
    "exports_per_hour": 10,
    "denied_requests_per_hour": 5,
    "document_access_per_hour": 40,
}


class SecurityMonitoringService:
    """Turns audit and session records into reviewable security events."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- recording ---------------------------------------------------------
    def record_event(
        self,
        *,
        event_type: str,
        severity: str = "LOW",
        category: str = "ACCESS",
        user_id: int | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        description: str = "",
        evidence: dict[str, Any] | None = None,
        recommended_response: str | None = None,
        correlation_id: str | None = None,
        db: Session | None = None,
    ) -> dict[str, Any]:
        event_ref = f"sec-{uuid.uuid4().hex[:12]}"
        payload = {
            "event_ref": event_ref,
            "event_type": event_type,
            "severity": severity,
            "category": category,
            "user_id": user_id,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "description": description,
            "evidence": evidence or {},
            "recommended_response": recommended_response,
            "correlation_id": correlation_id,
        }
        if db is not None:
            db.add(SecurityEvent(**payload))
            db.flush()
        else:
            with self._session_factory() as session:
                session.add(SecurityEvent(**payload))
                session.commit()
        logger.info("Security event %s (%s, %s)", event_type, severity, event_ref)
        return payload

    # -- detection ---------------------------------------------------------
    def scan(self, *, window_minutes: int = 60) -> list[dict[str, Any]]:
        """Run the detectors and return the events they raised."""
        since = utcnow() - timedelta(minutes=window_minutes)
        raised: list[dict[str, Any]] = []
        with self._session_factory() as db:
            raised.extend(self._repeated_failures(db, since))
            raised.extend(self._denied_access(db, since))
            raised.extend(self._export_burst(db, since))
            raised.extend(self._role_changes(db, since))
            raised.extend(self._stale_sessions(db))
            db.commit()
        return raised

    def _count(self, db: Session, action: str, since) -> dict[int, int]:
        rows = db.execute(
            select(AuditLog.user_id, func.count(AuditLog.id))
            .where(AuditLog.action == action, AuditLog.created_at >= since)
            .group_by(AuditLog.user_id)
        ).all()
        return {row[0]: int(row[1]) for row in rows if row[0] is not None}

    def _repeated_failures(self, db: Session, since) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for user_id, count in self._count(db, "LOGIN_FAILED", since).items():
            if count >= THRESHOLDS["failed_logins_per_hour"]:
                events.append(
                    self.record_event(
                        event_type="REPEATED_FAILED_LOGINS",
                        severity="MEDIUM" if count < 10 else "HIGH",
                        category="AUTHENTICATION",
                        user_id=user_id,
                        description=(
                            f"{count} failed sign-in attempts in the last hour. This is an "
                            "indicator for review, not evidence of wrongdoing."
                        ),
                        evidence={"failed_attempts": count, "window_minutes": 60},
                        recommended_response=(
                            "Confirm with the user whether they were trying to sign in, and "
                            "consider requiring MFA."
                        ),
                        db=db,
                    )
                )
        return events

    def _denied_access(self, db: Session, since) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for user_id, count in self._count(db, "DOCUMENT_ACCESS_DENIED", since).items():
            if count >= THRESHOLDS["denied_requests_per_hour"]:
                events.append(
                    self.record_event(
                        event_type="REPEATED_ACCESS_DENIALS",
                        severity="MEDIUM",
                        category="AUTHORIZATION",
                        user_id=user_id,
                        description=(
                            f"{count} access denials in the last hour; the user may be "
                            "attempting to reach records outside their role."
                        ),
                        evidence={"denials": count},
                        recommended_response="Review the user's role and recent requests.",
                        db=db,
                    )
                )
        return events

    def _export_burst(self, db: Session, since) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for action in ("REPORT_EXPORTED", "ANALYTICS_REPORT_GENERATED", "KNOWLEDGE_EXPORTED"):
            for user_id, count in self._count(db, action, since).items():
                if count >= THRESHOLDS["exports_per_hour"]:
                    events.append(
                        self.record_event(
                            event_type="EXPORT_BURST",
                            severity="MEDIUM",
                            category="DATA_PROTECTION",
                            user_id=user_id,
                            description=f"{count} exports of type {action} in the last hour.",
                            evidence={"exports": count, "action": action},
                            recommended_response="Confirm the exports were expected.",
                            db=db,
                        )
                    )
        return events

    def _role_changes(self, db: Session, since) -> list[dict[str, Any]]:
        rows = db.scalars(
            select(AuditLog).where(
                AuditLog.action.in_(("ROLE_CREATED", "ROLE_UPDATED", "USER_CREATED")),
                AuditLog.created_at >= since,
            )
        ).all()
        events: list[dict[str, Any]] = []
        for row in rows:
            events.append(
                self.record_event(
                    event_type="ACCESS_CONTROL_CHANGED",
                    severity="LOW",
                    category="ADMINISTRATION",
                    user_id=row.user_id,
                    resource_type=row.entity_type,
                    resource_id=row.entity_id,
                    description=f"{row.action} recorded at {row.created_at}",
                    evidence={"action": row.action},
                    recommended_response="Confirm the change was authorised.",
                    db=db,
                )
            )
        return events

    def _stale_sessions(self, db: Session) -> list[dict[str, Any]]:
        cutoff = utcnow() - timedelta(hours=24)
        count = db.scalar(
            select(func.count(UserSession.id)).where(
                UserSession.revoked_at.is_(None),
                UserSession.expires_at > utcnow(),
                UserSession.created_at < cutoff,
            )
        )
        if not count:
            return []
        return [
            self.record_event(
                event_type="LONG_RUNNING_SESSIONS",
                severity="LOW",
                category="SESSION",
                description=f"{count} session(s) have been open for more than 24 hours.",
                evidence={"sessions": int(count)},
                recommended_response="Ask the user to sign in again and revoke stale sessions.",
                db=db,
            )
        ]

    # -- reads and review --------------------------------------------------
    def list_events(self, *, severity: str | None = None, status: str | None = None, limit: int = 100) -> list[dict]:
        with self._session_factory() as db:
            query = select(SecurityEvent).order_by(SecurityEvent.id.desc()).limit(limit)
            if severity:
                query = (
                    select(SecurityEvent)
                    .where(SecurityEvent.severity == severity)
                    .order_by(SecurityEvent.id.desc())
                    .limit(limit)
                )
            if status:
                query = (
                    select(SecurityEvent)
                    .where(SecurityEvent.status == status)
                    .order_by(SecurityEvent.id.desc())
                    .limit(limit)
                )
            rows = db.scalars(query).all()
            return [
                {
                    "event_ref": row.event_ref,
                    "event_type": row.event_type,
                    "severity": row.severity,
                    "category": row.category,
                    "user_id": row.user_id,
                    "resource_type": row.resource_type,
                    "resource_id": row.resource_id,
                    "description": row.description,
                    "evidence": row.evidence or {},
                    "recommended_response": row.recommended_response,
                    "status": row.status,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def review_event(self, event_ref: str, *, decision: str, note: str | None, reviewer_id: int | None) -> dict:
        decision = (decision or "").upper()
        if decision not in ("ACKNOWLEDGED", "DISMISSED", "CONFIRMED_INCIDENT", "RESOLVED"):
            raise ValueError("A review decision must be ACKNOWLEDGED, DISMISSED, CONFIRMED_INCIDENT or RESOLVED")
        with self._session_factory() as db:
            row = db.scalars(
                select(SecurityEvent).where(SecurityEvent.event_ref == event_ref)
            ).first()
            if row is None:
                raise ValueError(f"Security event '{event_ref}' was not found")
            row.status = decision
            row.is_confirmed_incident = decision == "CONFIRMED_INCIDENT"
            db.add(
                SecurityIncidentReview(
                    event_ref=event_ref, decision=decision, note=note, reviewed_by=reviewer_id
                )
            )
            db.commit()
            return {"event_ref": event_ref, "status": decision}

    def summary(self) -> dict[str, Any]:
        with self._session_factory() as db:
            open_events = db.scalar(
                select(func.count(SecurityEvent.id)).where(SecurityEvent.status == "OPEN")
            ) or 0
            by_severity = {
                row[0]: int(row[1])
                for row in db.execute(
                    select(SecurityEvent.severity, func.count(SecurityEvent.id)).group_by(
                        SecurityEvent.severity
                    )
                ).all()
            }
            confirmed = db.scalar(
                select(func.count(SecurityEvent.id)).where(
                    SecurityEvent.is_confirmed_incident.is_(True)
                )
            ) or 0
            active_sessions = db.scalar(
                select(func.count(UserSession.id)).where(
                    UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow()
                )
            ) or 0
            locked = db.scalar(
                select(func.count(User.id)).where(User.locked_until.is_not(None), User.locked_until > utcnow())
            ) if hasattr(User, "locked_until") else 0
            return {
                "open_events": int(open_events),
                "by_severity": by_severity,
                "confirmed_incidents": int(confirmed),
                "active_sessions": int(active_sessions),
                "locked_accounts": int(locked or 0),
            }
