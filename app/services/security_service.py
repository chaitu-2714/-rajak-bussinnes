"""Security administration service: the UI's single entry point for governance."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import MODULE_SECURITY, AuditAction
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.audit_log import AuditLog
from app.database.models.security import SecurityEvent, UserMfaSetting
from app.database.models.session import UserSession
from app.database.models.user import User
from app.security.authz.authorization_service import Actor, AuthorizationService
from app.security.backup.secure_backup import SecureBackupService
from app.security.governance.ai_agent_security import AIAgentSecurityPolicyService
from app.security.governance.ai_data_governance import AIDataGovernanceService
from app.security.governance.approval_governance import ApprovalGovernanceService
from app.security.mfa.mfa_service import MfaService
from app.security.monitoring.security_monitor import SecurityMonitoringService
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService
from app.utils.date_utils import utcnow

logger = get_logger("services.security")


class SecurityService(BaseService):
    """Security overview, MFA, governance, audit verification and backups."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        authorization: AuthorizationService,
        mfa: MfaService,
        agent_policies: AIAgentSecurityPolicyService,
        data_governance: AIDataGovernanceService,
        approvals: ApprovalGovernanceService,
        monitor: SecurityMonitoringService,
        backups: SecureBackupService,
        audit_service: AuditService,
        audit_integrity: Any,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._authorization = authorization
        self._mfa = mfa
        self._agents = agent_policies
        self._governance = data_governance
        self._approvals = approvals
        self._monitor = monitor
        self._backups = backups
        self._audit = audit_service
        self._audit_integrity = audit_integrity

    # -- actor -------------------------------------------------------------
    def _actor(self, db: Session) -> Actor:
        user = self._current_user(db)
        from app.security.authorization import get_user_permissions, get_user_roles

        roles = tuple(role.role_name for role in get_user_roles(db, user))
        permissions = frozenset(get_user_permissions(db, user))
        return Actor(
            user_id=user.id,
            roles=roles,
            permissions=permissions,
            business_id=self._business_id(db),
            is_superuser=bool(getattr(user, "is_superuser", False)),
        )

    def _business_id(self, db: Session) -> int | None:
        from app.database.models.business import Business

        return db.scalars(select(Business.id).order_by(Business.id)).first()

    def actor(self) -> Actor:
        with self.unit_of_work(write=False) as db:
            return self._actor(db)

    # -- overview ----------------------------------------------------------
    def overview(self) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "security.view")
            summary = self._monitor.summary()
            failed = db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action.in_(("LOGIN_FAILED", "LOGIN_BLOCKED"))
                )
            ) or 0
            mfa_enabled = db.scalar(
                select(func.count(UserMfaSetting.id)).where(UserMfaSetting.is_enabled.is_(True))
            ) or 0
            total_users = db.scalar(select(func.count(User.id))) or 0
            locked = db.scalar(
                select(func.count(User.id)).where(
                    User.locked_until.is_not(None), User.locked_until > utcnow()
                )
            ) or 0
            recent_changes = db.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.action.in_(
                        ("ROLE_UPDATED", "USER_CREATED", "USER_UPDATED", "AUTONOMY_POLICY_UPDATED")
                    )
                )
            ) or 0
        integrity = self._audit_integrity.verify_chain(limit=500)
        return {
            "failed_logins": int(failed),
            "active_sessions": summary["active_sessions"],
            "locked_accounts": int(locked),
            "open_security_events": summary["open_events"],
            "confirmed_incidents": summary["confirmed_incidents"],
            "events_by_severity": summary["by_severity"],
            "mfa_enabled_users": int(mfa_enabled),
            "total_users": int(total_users),
            "recent_access_changes": int(recent_changes),
            "audit_integrity": integrity.as_dict(),
        }

    # -- MFA ---------------------------------------------------------------
    def mfa_status(self, user_id: int | None = None) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            user = self._current_user(db)
            target = user_id or user.id
            if target != user.id:
                self._authorize(db, "security.manage")
            return self._mfa.status(target)

    def start_mfa_enrollment(self) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            user = self._current_user(db)
            label = getattr(user, "email", "user")
            user_id = user.id
        result = self._mfa.start_enrollment(user_id, account_label=label)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=user_id,
                action=AuditAction.MFA_ENROLLMENT_STARTED,
                module=MODULE_SECURITY,
                entity_type="User",
                entity_id=str(user_id),
            )
        return {
            "secret": result.secret,
            "provisioning_uri": result.provisioning_uri,
            "qr_png": result.qr_png,
            "recovery_codes": result.recovery_codes,
        }

    def verify_mfa_enrollment(self, code: str) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            user_id = self._current_user(db).id
        ok = self._mfa.verify_enrollment(user_id, code)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=user_id,
                action=AuditAction.MFA_ENABLED if ok else AuditAction.MFA_VERIFICATION_FAILED,
                module=MODULE_SECURITY,
                entity_type="User",
                entity_id=str(user_id),
            )
        return {"enabled": ok}

    def disable_mfa(self, code: str) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            user_id = self._current_user(db).id
        result = self._mfa.disable(user_id, code=code)
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=user_id,
                action=AuditAction.MFA_DISABLED,
                module=MODULE_SECURITY,
                entity_type="User",
                entity_id=str(user_id),
            )
        return result

    def enforce_mfa(self, user_id: int, *, enforced: bool) -> dict[str, Any]:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "security.manage")
            result = self._mfa.enforce_for_user(user_id, enforced=enforced)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.MFA_POLICY_CHANGED,
                module=MODULE_SECURITY,
                entity_type="User",
                entity_id=str(user_id),
                new_values={"enforced": enforced},
            )
            return result

    def mfa_roster(self) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "security.manage")
            users = db.scalars(select(User).order_by(User.full_name)).all()
            settings = {
                row.user_id: row
                for row in db.scalars(select(UserMfaSetting)).all()
            }
            return [
                {
                    "user_id": user.id,
                    "name": user.full_name,
                    "email": user.email,
                    "is_active": user.is_active,
                    "is_superuser": getattr(user, "is_superuser", False),
                    "mfa_enabled": bool(
                        settings.get(user.id) and settings[user.id].is_enabled
                    ),
                    "mfa_enforced": bool(
                        settings.get(user.id) and settings[user.id].enforced
                    ),
                }
                for user in users
            ]

    # -- sessions ----------------------------------------------------------
    def active_sessions(self) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "security.view")
            rows = db.scalars(
                select(UserSession)
                .where(UserSession.revoked_at.is_(None), UserSession.expires_at > utcnow())
                .order_by(UserSession.id.desc())
            ).all()
            names = {
                user.id: user.full_name
                for user in db.scalars(select(User)).all()
            }
            return [
                {
                    "session_id": row.id,
                    "user": names.get(row.user_id, str(row.user_id)),
                    "created_at": row.created_at,
                    "expires_at": row.expires_at,
                    "last_activity_at": row.last_activity_at,
                }
                for row in rows
            ]

    def revoke_session(self, session_id: int) -> dict[str, Any]:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "security.manage")
            session = db.get(UserSession, session_id)
            if session is None:
                raise NotFoundError("Session not found")
            session.revoked_at = utcnow()
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.SESSION_REVOKED,
                module=MODULE_SECURITY,
                entity_type="UserSession",
                entity_id=str(session_id),
            )
            return {"session_id": session_id, "revoked": True}

    # -- governance --------------------------------------------------------
    def agent_policies(self) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "security.view")
            return self._agents.list_policies()

    def update_agent_policy(self, agent_code: str, *, changes: dict[str, Any]) -> dict[str, Any]:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "security.manage")
            result = self._agents.update_policy(agent_code, changes=changes, actor_id=actor.id)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.AGENT_POLICY_UPDATED,
                module=MODULE_SECURITY,
                entity_type="AgentSecurityPolicy",
                entity_id=agent_code,
                new_values=changes,
            )
            return result

    def data_governance_policies(self) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "security.view")
            return self._governance.policies()

    def update_data_governance(
        self, classification: str, provider: str, *, changes: dict[str, Any]
    ) -> dict[str, Any]:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "security.manage")
            result = self._governance.update_policy(classification, provider, changes=changes)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.DATA_GOVERNANCE_UPDATED,
                module=MODULE_SECURITY,
                entity_type="AIDataGovernancePolicy",
                entity_id=f"{classification}:{provider}",
                new_values=changes,
            )
            return result

    def classify_text(self, text: str) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "security.view")
        result = self._governance.classify(text)
        return {"classification": result.level, "reasons": result.reasons}

    # -- audit -------------------------------------------------------------
    def audit_integrity(self, *, limit: int | None = None) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "audit.view")
        return self._audit_integrity.verify_chain(limit=limit).as_dict()

    def audit_chain_head(self) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "audit.view")
        return self._audit_integrity.chain_head()

    def backfill_audit_chain(self) -> int:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "security.manage")
        appended = self._audit_integrity.backfill()
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.AUDIT_CHAIN_BACKFILLED,
                module=MODULE_SECURITY,
                entity_type="AuditLog",
                entity_id="chain",
                new_values={"appended": appended},
            )
        return appended

    def export_audit(self, destination: Path, *, limit: int = 5000) -> dict[str, Any]:
        """Export the audit trail (with its chain) for off-box retention."""
        import csv
        import json

        with self.unit_of_work(write=False) as db:
            self._authorize(db, "audit.export")
            rows = db.scalars(
                select(AuditLog).order_by(AuditLog.id).limit(limit)
            ).all()
            head = self._audit_integrity.chain_head()
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with open(destination, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(
                    ["id", "created_at", "user_id", "action", "module", "entity_type",
                     "entity_id", "status", "new_values"]
                )
                for row in rows:
                    writer.writerow(
                        [row.id, row.created_at, row.user_id, row.action, row.module,
                         row.entity_type, row.entity_id, row.status,
                         json.dumps(row.new_values or {}, default=str)]
                    )
            manifest = destination.with_suffix(".chain.json")
            manifest.write_text(json.dumps(head, indent=2), encoding="utf-8")
        return {
            "file": destination.name,
            "rows": len(rows),
            "chain_head": head["head_hash"],
            "manifest": manifest.name,
        }

    # -- monitoring --------------------------------------------------------
    def security_events(self, *, severity: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "security.view")
        return self._monitor.list_events(severity=severity, limit=limit)

    def scan_security(self) -> list[dict[str, Any]]:
        with self.unit_of_work() as db:
            self._authorize(db, "security.manage")
        return self._monitor.scan()

    def review_event(self, event_ref: str, *, decision: str, note: str | None = None) -> dict[str, Any]:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "security.manage")
            result = self._monitor.review_event(
                event_ref, decision=decision, note=note, reviewer_id=actor.id
            )
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.SECURITY_EVENT_REVIEWED,
                module=MODULE_SECURITY,
                entity_type="SecurityEvent",
                entity_id=event_ref,
                new_values={"decision": decision},
            )
            return result

    # -- backups -----------------------------------------------------------
    def backup_history(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "backup.view")
        return self._backups.history(limit=limit)

    def create_backup(self, *, include_knowledge: bool = False) -> dict[str, Any]:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "backup.create")
            actor_id = actor.id
        result = self._backups.create_backup(
            performed_by=actor_id, include_knowledge=include_knowledge
        )
        with self.unit_of_work() as db:
            self._audit.record(
                db,
                actor_id=actor_id,
                action=AuditAction.BACKUP_CREATED,
                module=MODULE_SECURITY,
                entity_type="Backup",
                entity_id=result["backup_ref"],
                new_values={"file": result["file_name"], "verified": result["integrity_status"]},
            )
        return result

    def validate_backup(self, path: str | Path) -> dict[str, Any]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "backup.view")
        return self._backups.preview_restore(Path(path))

    def restore_backup(self, path: str | Path, *, confirm: bool = False) -> dict[str, Any]:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "backup.restore")
            actor_id = actor.id
        result = self._backups.restore_backup(
            Path(path), performed_by=actor_id, confirm=confirm
        )
        try:
            with self.unit_of_work() as db:
                self._audit.record(
                    db,
                    actor_id=actor_id,
                    action=AuditAction.BACKUP_RESTORED,
                    module=MODULE_SECURITY,
                    entity_type="Backup",
                    entity_id=result["restored"],
                    new_values=result,
                )
        except Exception:  # noqa: BLE001 - the database was just replaced
            logger.warning("Could not write the restore audit entry after replacing the database")
        return result

    # -- authorisation helpers --------------------------------------------
    def check(
        self, permission: str, *, resource_type: str | None = None, resource_id: str | None = None
    ) -> dict[str, Any]:
        """Expose a single authorization decision for the UI to display."""
        with self.unit_of_work(write=False) as db:
            actor = self._actor(db)
            decision = self._authorization.authorize(
                actor, permission, resource_type=resource_type, resource_id=resource_id, db=db
            )
        return {
            "allowed": decision.allowed,
            "reason": decision.reason,
            "classification": decision.classification,
            "requires_approval": decision.requires_approval,
        }
