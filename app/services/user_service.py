"""User management service."""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    MODULE_USERS,
    ROLE_SUPER_ADMIN,
    STATUS_FAILURE,
    AuditAction,
)
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    DuplicateEmailError,
    NotFoundError,
    ProtectedRecordError,
    ValidationError,
)
from app.core.logging_config import get_logger
from app.database.models.user import User
from app.database.repositories.role_repository import RoleRepository
from app.database.repositories.session_repository import SessionRepository
from app.database.repositories.user_repository import UserRepository
from app.schemas.user_schema import (
    PasswordResetRequest,
    ProfileUpdateRequest,
    UserCreateRequest,
    UserSummary,
    UserUpdateRequest,
)
from app.security.authentication import Authenticator
from app.security.authorization import get_user_roles
from app.security.password_manager import PasswordManager
from app.security.session_manager import SessionManager
from app.security.validators import PasswordPolicy
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload
from app.utils.date_utils import utcnow

logger = get_logger("services.users")


class UserService(BaseService):
    """Create, edit, deactivate and inspect user accounts."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        user_repository: UserRepository,
        role_repository: RoleRepository,
        session_repository: SessionRepository,
        password_manager: PasswordManager,
        password_policy: PasswordPolicy,
        session_manager: SessionManager,
        authenticator: Authenticator,
        audit_service: AuditService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._users = user_repository
        self._roles = role_repository
        self._sessions = session_repository
        self._passwords = password_manager
        self._policy = password_policy
        self._session_manager = session_manager
        self._authenticator = authenticator
        self._audit = audit_service

    # -- queries -----------------------------------------------------------
    def list_users(
        self,
        *,
        search: str | None = None,
        role_id: int | None = None,
        is_active: bool | None = None,
    ) -> list[UserSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "users.view")
            users = self._users.list(db, search=search, role_id=role_id, is_active=is_active)
            return [UserSummary.from_user(user) for user in users]

    def get_user(self, user_id: int) -> UserSummary:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "users.view")
            return UserSummary.from_user(self._load_user(db, user_id))

    def count_users(self) -> int:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "users.view")
            return self._users.count(db)

    # -- mutations ---------------------------------------------------------
    def create_user(self, payload: dict | UserCreateRequest) -> UserSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "users.create")
            data = validate_payload(UserCreateRequest, payload)
            problems = self._policy.violations(data.password)
            if problems:
                raise ValidationError(
                    " ".join(problems), fields={"password": " ".join(problems)}
                )
            if self._users.email_exists(db, data.email):
                raise DuplicateEmailError(f"Email already registered: {data.email}")
            self._guard_role_escalation(db, actor, data.role_ids)

            user = User(
                full_name=data.full_name,
                email=data.email,
                phone=data.phone,
                password_hash=self._passwords.hash_password(data.password),
                is_active=data.is_active,
                is_superuser=False,
            )
            self._users.add(db, user)
            self._users.set_roles(db, user, data.role_ids, assigned_by=actor.id)
            self._sync_superuser_flag(db, user)

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_USER,
                module=MODULE_USERS,
                entity_type="User",
                entity_id=user.id,
                new_values={
                    "full_name": user.full_name,
                    "email": user.email,
                    "roles": user.role_names,
                    "is_active": user.is_active,
                },
            )
            return UserSummary.from_user(user)

    def update_user(self, user_id: int, payload: dict | UserUpdateRequest) -> UserSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "users.update")
            data = validate_payload(UserUpdateRequest, payload)
            user = self._load_user(db, user_id)
            if self._users.email_exists(db, data.email, exclude_user_id=user.id):
                raise DuplicateEmailError(f"Email already registered: {data.email}")
            self._guard_role_escalation(db, actor, data.role_ids)

            old_values = {
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "roles": user.role_names,
            }
            was_superuser = bool(user.is_superuser)

            user.full_name = data.full_name
            user.email = data.email
            user.phone = data.phone
            user.updated_at = utcnow()
            self._users.set_roles(db, user, data.role_ids, assigned_by=actor.id)
            self._sync_superuser_flag(db, user)
            self._guard_last_super_admin(db, user, was_superuser=was_superuser)

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_USER,
                module=MODULE_USERS,
                entity_type="User",
                entity_id=user.id,
                old_values=old_values,
                new_values={
                    "full_name": user.full_name,
                    "email": user.email,
                    "phone": user.phone,
                    "roles": user.role_names,
                },
            )
            return UserSummary.from_user(user)

    def set_active(self, user_id: int, is_active: bool) -> UserSummary:
        """Activate or deactivate an account."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "users.deactivate")
            user = self._load_user(db, user_id)
            if user.id == actor.id and not is_active:
                raise ProtectedRecordError("You cannot deactivate your own account")

            previous = user.is_active
            was_superuser = bool(user.is_superuser)
            user.is_active = is_active
            user.updated_at = utcnow()
            if not is_active:
                revoked = self._session_manager.revoke_all_for_user(db, user.id)
            else:
                revoked = 0

            self._guard_last_super_admin(
                db, user, was_superuser=was_superuser, now_active=is_active
            )
            self._audit.record(
                db,
                actor_id=actor.id,
                action=(
                    AuditAction.ACTIVATE_USER if is_active else AuditAction.DEACTIVATE_USER
                ),
                module=MODULE_USERS,
                entity_type="User",
                entity_id=user.id,
                old_values={"is_active": previous},
                new_values={"is_active": is_active, "sessions_revoked": revoked},
            )
            return UserSummary.from_user(user)

    def assign_roles(self, user_id: int, role_ids: list[int]) -> UserSummary:
        """Replace a user's role assignments."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "roles.assign")
            user = self._load_user(db, user_id)
            if not role_ids:
                raise ValidationError("Assign at least one role.", fields={"role_ids": "Required"})
            self._guard_role_escalation(db, actor, role_ids)

            previous = user.role_names
            was_superuser = bool(user.is_superuser)
            self._users.set_roles(db, user, role_ids, assigned_by=actor.id)
            self._sync_superuser_flag(db, user)
            self._guard_last_super_admin(db, user, was_superuser=was_superuser)

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.ASSIGN_ROLE,
                module=MODULE_USERS,
                entity_type="User",
                entity_id=user.id,
                old_values={"roles": previous},
                new_values={"roles": user.role_names},
            )
            return UserSummary.from_user(user)

    def reset_password(
        self, user_id: int, new_password: str, confirm_password: str
    ) -> None:
        """Administrative password reset; revokes the target's sessions."""
        db = self._session_factory()
        try:
            actor = self._authorize(db, "users.reset_password")
            data = validate_payload(
                PasswordResetRequest,
                {"new_password": new_password, "confirm_password": confirm_password},
            )
            problems = self._policy.violations(data.new_password)
            if problems:
                raise ValidationError(
                    " ".join(problems), fields={"new_password": " ".join(problems)}
                )
            user = self._load_user(db, user_id)
            if user.is_superuser and not actor.is_superuser:
                raise AuthorizationError("Only a Super Admin may reset another Super Admin's password")

            user.password_hash = self._passwords.hash_password(data.new_password)
            user.updated_at = utcnow()
            self._authenticator.unlock(db, user)
            revoked = self._session_manager.revoke_all_for_user(db, user.id)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.RESET_PASSWORD,
                module=MODULE_USERS,
                entity_type="User",
                entity_id=user.id,
                new_values={"sessions_revoked": revoked, "email": user.email},
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def update_own_profile(self, payload: dict | ProfileUpdateRequest) -> UserSummary:
        """A signed-in user editing their own name and phone number."""
        data = validate_payload(ProfileUpdateRequest, payload)
        with self.unit_of_work() as db:
            user = self._current_user(db)
            old_values = {"full_name": user.full_name, "phone": user.phone}
            user.full_name = data.full_name
            user.phone = data.phone
            user.updated_at = utcnow()
            self._audit.record(
                db,
                actor_id=user.id,
                action=AuditAction.UPDATE_USER,
                module=MODULE_USERS,
                entity_type="User",
                entity_id=user.id,
                old_values=old_values,
                new_values={"full_name": user.full_name, "phone": user.phone},
            )
            return UserSummary.from_user(user)

    # -- guards ------------------------------------------------------------
    def _sync_superuser_flag(self, db: Session, user: User) -> None:
        """Keep ``is_superuser`` consistent with the Super Admin role."""
        db.flush()
        roles = get_user_roles(db, user)
        user.is_superuser = any(role.role_name == ROLE_SUPER_ADMIN for role in roles)
        db.flush()

    def _guard_last_super_admin(
        self,
        db: Session,
        user: User,
        *,
        was_superuser: bool,
        now_active: bool | None = None,
    ) -> None:
        """Refuse changes that would remove the last active Super Admin.

        ``was_superuser`` must be captured before the roles are mutated; the
        current flag is read after the mutation has been applied.
        """
        if not was_superuser:
            return
        still_superuser = bool(user.is_superuser)
        still_active = user.is_active if now_active is None else now_active
        if still_superuser and still_active:
            return
        others = self._users.count_active_superusers(db, exclude_user_id=user.id)
        if others == 0:
            raise ProtectedRecordError(
                "At least one active Super Admin must remain in the workspace"
            )

    def _guard_role_escalation(self, db: Session, actor: User, role_ids: list[int]) -> None:
        """Prevent a user from granting roles (or escalation) they do not hold."""
        if actor.is_superuser:
            return
        allowed = {role.id for role in get_user_roles(db, actor)}
        requested = set(role_ids)
        if not requested.issubset(allowed):
            raise AuthorizationError(
                "You cannot assign a role that you do not hold yourself"
            )
