"""Audit integrity: a hash chain over the audit log, plus verification.

The chain detects modification of any record after the fact. It does **not**
prevent a privileged administrator who can rewrite the whole database from
recomputing the chain; for that, export the chain head to separate storage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.logging_config import get_logger
from app.database.models.audit_log import AuditLog
from app.database.models.security import AuditIntegrityRecord
from app.utils.date_utils import utcnow

logger = get_logger("security.audit_integrity")

GENESIS = "0" * 64


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    checked: int
    broken_at: int | None = None
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checked": self.checked,
            "broken_at": self.broken_at,
            "reason": self.reason,
        }


class AuditIntegrityService:
    """Appends a chained hash for every audit record and verifies the chain."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    # -- hashing -----------------------------------------------------------
    def _record_digest(self, row: AuditLog, previous_hash: str) -> str:
        payload = {
            "id": row.id,
            "user_id": row.user_id,
            "action": row.action,
            "module": row.module,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "old_values": row.old_values,
            "new_values": row.new_values,
            "status": row.status,
            "device": row.ip_or_device_info,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "previous": previous_hash,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _last_hash(self, db: Session) -> tuple[str, int]:
        row = db.scalars(
            select(AuditIntegrityRecord).order_by(AuditIntegrityRecord.sequence.desc())
        ).first()
        if row is None:
            return GENESIS, 0
        return row.record_hash, row.sequence

    # -- appending ---------------------------------------------------------
    def append(self, db: Session, audit_row: AuditLog) -> AuditIntegrityRecord:
        previous_hash, sequence = self._last_hash(db)
        digest = self._record_digest(audit_row, previous_hash)
        record = AuditIntegrityRecord(
            audit_id=audit_row.id,
            sequence=sequence + 1,
            previous_hash=previous_hash,
            record_hash=digest,
        )
        db.add(record)
        db.flush()
        return record

    def backfill(self) -> int:
        """Chain any audit rows that predate Phase 9."""
        appended = 0
        with self._session_factory() as db:
            chained = {
                row.audit_id for row in db.scalars(select(AuditIntegrityRecord)).all()
            }
            rows = db.scalars(select(AuditLog).order_by(AuditLog.id)).all()
            for row in rows:
                if row.id in chained:
                    continue
                self.append(db, row)
                appended += 1
            db.commit()
        if appended:
            logger.info("Chained %d pre-existing audit records", appended)
        return appended

    # -- verification ------------------------------------------------------
    def verify_chain(self, *, limit: int | None = None) -> VerificationResult:
        with self._session_factory() as db:
            records = db.scalars(
                select(AuditIntegrityRecord).order_by(AuditIntegrityRecord.sequence)
            ).all()
            if limit:
                records = records[:limit]
            previous = GENESIS
            checked = 0
            for record in records:
                if record.previous_hash != previous:
                    return VerificationResult(
                        False, checked, record.sequence,
                        "The chain link does not match the previous record",
                    )
                audit_row = db.get(AuditLog, record.audit_id)
                if audit_row is None:
                    return VerificationResult(
                        False, checked, record.sequence,
                        "An audit record referenced by the chain is missing",
                    )
                expected = self._record_digest(audit_row, record.previous_hash)
                if expected != record.record_hash:
                    return VerificationResult(
                        False, checked, record.sequence,
                        "An audit record was modified after it was written",
                    )
                previous = record.record_hash
                checked += 1
            return VerificationResult(True, checked, None, "Chain intact")

    def chain_head(self) -> dict[str, Any]:
        with self._session_factory() as db:
            last_hash, sequence = self._last_hash(db)
            return {
                "sequence": sequence,
                "head_hash": last_hash,
                "verified_at": utcnow().isoformat(),
            }

    # -- protection --------------------------------------------------------
    def guard_audit_write(self, db: Session, *, operation: str, actor_type: str = "USER") -> None:
        """Audit rows may only ever be inserted."""
        if operation.upper() not in ("INSERT", "APPEND"):
            raise PermissionError(
                "Audit records are append-only; update and delete are not permitted"
            )
