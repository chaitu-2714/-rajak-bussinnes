"""Authentication service: initial setup, login, logout, password change.

This service owns the ``AuthContext`` that every other service reads to learn
who is acting. All credential handling is delegated to the security layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import SecuritySettings
from app.core.constants import (
    MODULE_AUTHENTICATION,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    AuditAction,
)
from app.core.exceptions import (
    BizPilotError,
    ConflictError,
    InvalidCredentialsError,
    SessionExpiredError,
    ValidationError,
)
from app.core.logging_config import get_logger
from app.database.models.business import Business
from app.database.models.user import User
from app.database.repositories.business_repository import BusinessRepository
from app.database.repositories.permission_repository import PermissionRepository
from app.database.repositories.role_repository import RoleRepository
from app.database.repositories.session_repository import SessionRepository
from app.database.repositories.user_repository import UserRepository
from app.database.seed import ensure_reference_data, super_admin_role
from app.schemas.auth_schema import InitialSetupRequest, LoginRequest, PasswordChangeRequest
from app.security.authentication import Authenticator
from app.security.authorization import Principal, build_principal
from app.security.password_manager import PasswordManager
from app.security.session_manager import SessionManager
from app.security.validators import PasswordPolicy
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload
from app.utils.date_utils import utcnow
from app.utils.validators import normalise_email

logger = get_logger("services.auth")


@dataclass(frozen=True)
class AuthResult:
    """Result of a successful authentication."""

    principal: Principal
    token: str
    session_id: int
    expires_at: datetime


@dataclass(frozen=True)
class SessionSnapshot:
    """Read-only description of the active session for the settings page."""

    session_id: int
    created_at: datetime
    expires_at: datetime
    last_activity_at: datetime


class AuthService(BaseService):
    """Local authentication and first-run provisioning."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        business_repository: BusinessRepository,
        permission_repository: PermissionRepository,
        session_repository: SessionRepository,
        authenticator: Authenticator,
        session_manager: SessionManager,
        password_manager: PasswordManager,
        password_policy: PasswordPolicy,
        audit_service: AuditService,
        security_settings: SecuritySettings,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._users = user_repository
        self._roles = role_repository
        self._business = business_repository
        self._permissions = permission_repository
        self._sessions = session_repository
        self._authenticator = authenticator
        self._session_manager = session_manager
        self._passwords = password_manager
        self._policy = password_policy
        self._audit = audit_service
        self._settings = security_settings

    # -- first run ---------------------------------------------------------
    def needs_initial_setup(self) -> bool:
        """True when the workspace has not been provisioned yet."""
        with self.unit_of_work(write=False) as db:
            return self._users.count(db) == 0 or self._business.count(db) == 0

    def run_initial_setup(self, payload: dict | InitialSetupRequest) -> AuthResult:
        """Create the business, reference data, first Super Admin and a session."""
        data = validate_payload(InitialSetupRequest, payload)
        problems = self._policy.violations(data.password)
        if problems:
            raise ValidationError(" ".join(problems), fields={"password": " ".join(problems)})

        db = self._session_factory()
        try:
            if self._users.count(db) > 0 or self._business.count(db) > 0:
                raise ConflictError("BizPilot AI has already been initialised")

            ensure_reference_data(db)
            admin_role = super_admin_role(db)

            business = Business(
                business_name=data.business_name,
                owner_name=data.owner_name,
                email=data.email,
                phone=data.phone,
                address=None,
                currency=data.currency,
                timezone=data.timezone,
                financial_year_start=data.financial_year_start,
            )
            self._business.add(db, business)

            admin = User(
                full_name=data.owner_name,
                email=data.email,
                password_hash=self._passwords.hash_password(data.password),
                phone=data.phone,
                is_active=True,
                is_superuser=True,
            )
            self._users.add(db, admin)
            self._users.set_roles(db, admin, [admin_role.id], assigned_by=admin.id)

            token, session = self._session_manager.create_session(db, admin)
            principal = build_principal(db, admin, business.business_name)

            self._audit.record(
                db,
                actor_id=admin.id,
                action=AuditAction.SETUP_COMPLETE,
                module=MODULE_AUTHENTICATION,
                entity_type="Business",
                entity_id=business.id,
                new_values={
                    "business_name": business.business_name,
                    "admin_email": admin.email,
                    "roles_created": 6,
                },
            )
            self._audit.record(
                db,
                actor_id=admin.id,
                action=AuditAction.LOGIN_SUCCESS,
                module=MODULE_AUTHENTICATION,
                entity_type="User",
                entity_id=admin.id,
                new_values={"email": admin.email, "first_run": True},
            )
            db.commit()
            result = AuthResult(
                principal=principal,
                token=token,
                session_id=session.id,
                expires_at=session.expires_at,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        self._auth_context.set(
            result.principal, result.token, result.session_id, result.expires_at
        )
        logger.info("Initial setup completed for business %s", data.business_name)
        return result

    # -- login / logout ----------------------------------------------------
    def login(self, email: str, password: str) -> AuthResult:
        """Authenticate and open a new session."""
        data = validate_payload(LoginRequest, {"email": email, "password": password})
        db = self._session_factory()
        try:
            try:
                user = self._authenticator.authenticate(db, data.email, data.password)
            except BizPilotError as exc:
                self._audit.record(
                    db,
                    actor_id=None,
                    action=AuditAction.LOGIN_FAILURE,
                    module=MODULE_AUTHENTICATION,
                    entity_type="User",
                    entity_id=None,
                    new_values={"email": data.email, "reason": type(exc).__name__},
                    status=STATUS_FAILURE,
                )
                db.commit()
                raise

            token, session = self._session_manager.create_session(db, user)
            business = self._business.get_primary(db)
            principal = build_principal(
                db, user, business.business_name if business else None
            )
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.LOGIN_SUCCESS,
                module=MODULE_AUTHENTICATION,
                entity_type="User",
                entity_id=user.id,
                new_values={"email": user.email},
                status=STATUS_SUCCESS,
            )
            db.commit()
            result = AuthResult(
                principal=principal,
                token=token,
                session_id=session.id,
                expires_at=session.expires_at,
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

        self._auth_context.set(
            result.principal, result.token, result.session_id, result.expires_at
        )
        logger.info("Login success for %s", data.email)
        return result

    def logout(self) -> None:
        """Revoke the active session and clear the in-memory context."""
        token = self._auth_context.token
        principal = self._auth_context.principal
        if token is None:
            self._auth_context.clear()
            return

        db = self._session_factory()
        try:
            try:
                session = self._session_manager.resolve_session(db, token)
            except BizPilotError:
                session = None
            if session is not None:
                self._session_manager.revoke(db, session)
            if principal is not None:
                self._audit.record(
                    db,
                    actor_id=principal.user_id,
                    action=AuditAction.LOGOUT,
                    module=MODULE_AUTHENTICATION,
                    entity_type="Session",
                    entity_id=session.id if session else None,
                )
            db.commit()
        except Exception:
            db.rollback()
            logger.exception("Logout could not be recorded")
        finally:
            db.close()
        self._auth_context.clear()

    # -- session helpers ---------------------------------------------------
    def validate_active_session(self) -> bool:
        """Check the live session against the database and refresh activity."""
        token = self._auth_context.token
        if not token:
            return False
        with self.unit_of_work() as db:
            try:
                session = self._session_manager.resolve_session(db, token)
            except SessionExpiredError:
                self._auth_context.clear()
                return False
            self._session_manager.touch(db, session)
            return True

    def session_snapshot(self) -> SessionSnapshot | None:
        token = self._auth_context.token
        if not token:
            return None
        with self.unit_of_work(write=False) as db:
            session = self._sessions.get_by_token_hash(db, __import__("hashlib").sha256(token.encode()).hexdigest())
            if session is None:
                return None
            return SessionSnapshot(
                session_id=session.id,
                created_at=session.created_at,
                expires_at=session.expires_at,
                last_activity_at=session.last_activity_at,
            )

    # -- password ----------------------------------------------------------
    def change_password(
        self, current_password: str, new_password: str, confirm_password: str
    ) -> None:
        """Change the signed-in user's password and revoke other sessions."""
        data = validate_payload(
            PasswordChangeRequest,
            {
                "current_password": current_password,
                "new_password": new_password,
                "confirm_password": confirm_password,
            },
        )
        problems = self._policy.violations(data.new_password)
        if problems:
            raise ValidationError(" ".join(problems), fields={"new_password": " ".join(problems)})

        db = self._session_factory()
        try:
            user = self._authorize(db, "auth.change_password")
            if not self._passwords.verify_password(user.password_hash, data.current_password):
                self._audit.record(
                    db,
                    actor_id=user.id,
                    action=AuditAction.CHANGE_PASSWORD,
                    module=MODULE_AUTHENTICATION,
                    entity_type="User",
                    entity_id=user.id,
                    status=STATUS_FAILURE,
                    new_values={"reason": "current password mismatch"},
                )
                db.commit()
                raise ValidationError(
                    "Current password is incorrect.",
                    fields={"current_password": "Current password is incorrect."},
                )

            user.password_hash = self._passwords.hash_password(data.new_password)
            user.updated_at = utcnow()
            self._authenticator.unlock(db, user)
            revoked = self._session_manager.revoke_all_for_user(
                db, user.id, except_id=self._auth_context.session_id
            )
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.CHANGE_PASSWORD,
                module=MODULE_AUTHENTICATION,
                entity_type="User",
                entity_id=user.id,
                new_values={"sessions_revoked": revoked},
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        logger.info("Password changed for user id=%s", user.id)

    def verify_own_password(self, password: str) -> bool:
        """Re-authentication helper for sensitive UI actions."""
        with self.unit_of_work(write=False) as db:
            user = self._current_user(db)
            return self._passwords.verify_password(user.password_hash, password)

    def require_authentication(self) -> Principal:
        """Return the principal or raise an authentication error."""
        if self._auth_context.principal is None:
            raise InvalidCredentialsError("Not signed in")
        return self._auth_context.principal

    def current_email(self) -> str | None:
        principal = self._auth_context.principal
        return principal.email if principal else None

    @staticmethod
    def normalise(email: str) -> str:
        return normalise_email(email)
