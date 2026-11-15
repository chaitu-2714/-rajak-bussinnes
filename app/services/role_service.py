"""Role and permission management service."""

from __future__ import annotations

from collections import OrderedDict

from sqlalchemy.orm import Session, sessionmaker

from app.core.constants import (
    MODULE_ROLES,
    ROLE_SUPER_ADMIN,
    AuditAction,
)
from app.core.exceptions import (
    ConflictError,
    NotFoundError,
    ProtectedRecordError,
    ValidationError,
)
from app.core.logging_config import get_logger
from app.database.models.role import Role
from app.database.repositories.permission_repository import PermissionRepository
from app.database.repositories.role_repository import RoleRepository
from app.database.repositories.user_repository import UserRepository
from app.schemas.role_schema import (
    PermissionSummary,
    RoleCreateRequest,
    RoleSummary,
    RoleUpdateRequest,
)
from app.schemas.user_schema import UserSummary
from app.services.audit_service import AuditService
from app.services.base_service import AuthContext, BaseService, validate_payload

logger = get_logger("services.roles")


class RoleService(BaseService):
    """Role catalogue, permission assignment and custom roles."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        role_repository: RoleRepository,
        permission_repository: PermissionRepository,
        user_repository: UserRepository,
        audit_service: AuditService,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._roles = role_repository
        self._permissions = permission_repository
        self._users = user_repository
        self._audit = audit_service

    # -- queries -----------------------------------------------------------
    def list_roles(self) -> list[RoleSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "roles.view")
            roles = self._roles.list_all(db)
            return [
                RoleSummary.from_role(role, self._roles.count_users(db, role.id))
                for role in roles
            ]

    def get_role(self, role_id: int) -> RoleSummary:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "roles.view")
            role = self._roles.get(db, role_id)
            if role is None:
                raise NotFoundError(f"Role {role_id} was not found")
            return RoleSummary.from_role(role, self._roles.count_users(db, role.id))

    def list_permissions(self) -> list[PermissionSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "roles.view")
            return [
                PermissionSummary.from_permission(permission)
                for permission in self._permissions.list_all(db)
            ]

    def list_permissions_grouped(self) -> "OrderedDict[str, list[PermissionSummary]]":
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "roles.view")
            grouped = self._permissions.list_grouped(db)
            return OrderedDict(
                (
                    module,
                    [PermissionSummary.from_permission(p) for p in permissions],
                )
                for module, permissions in grouped.items()
            )

    def list_users_for_role(self, role_id: int) -> list[UserSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "roles.view")
            if self._roles.get(db, role_id) is None:
                raise NotFoundError(f"Role {role_id} was not found")
            users = self._users.list(db, role_id=role_id)
            return [UserSummary.from_user(user) for user in users]

    # -- mutations ---------------------------------------------------------
    def create_role(self, payload: dict | RoleCreateRequest) -> RoleSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "roles.create")
            data = validate_payload(RoleCreateRequest, payload)
            if self._roles.get_by_name(db, data.role_name) is not None:
                raise ConflictError(f"A role named '{data.role_name}' already exists")
            permissions = self._resolve_permissions(db, data.permission_keys)
            if not permissions:
                raise ValidationError(
                    "Select at least one permission.",
                    fields={"permission_keys": "Select at least one permission."},
                )

            role = Role(
                role_name=data.role_name,
                description=data.description,
                is_system_role=False,
            )
            self._roles.add(db, role)
            self._roles.set_permissions(db, role, {p.id for p in permissions})

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.CREATE_ROLE,
                module=MODULE_ROLES,
                entity_type="Role",
                entity_id=role.id,
                new_values={
                    "role_name": role.role_name,
                    "permissions": sorted(data.permission_keys),
                },
            )
            return RoleSummary.from_role(role, 0)

    def update_role(self, role_id: int, payload: dict | RoleUpdateRequest) -> RoleSummary:
        with self.unit_of_work() as db:
            actor = self._authorize(db, "roles.update")
            data = validate_payload(RoleUpdateRequest, payload)
            role = self._roles.get(db, role_id)
            if role is None:
                raise NotFoundError(f"Role {role_id} was not found")

            if role.is_system_role and data.role_name != role.role_name:
                raise ProtectedRecordError("System role names cannot be changed")

            existing = self._roles.get_by_name(db, data.role_name)
            if existing is not None and existing.id != role.id:
                raise ConflictError(f"A role named '{data.role_name}' already exists")

            old_values = {
                "role_name": role.role_name,
                "description": role.description,
                "permissions": role.permission_keys,
            }

            if role.role_name == ROLE_SUPER_ADMIN:
                # Super Admin must always retain every permission.
                permission_ids = {p.id for p in self._permissions.list_all(db)}
            else:
                permissions = self._resolve_permissions(db, data.permission_keys)
                if not permissions:
                    raise ValidationError(
                        "Select at least one permission.",
                        fields={"permission_keys": "Select at least one permission."},
                    )
                permission_ids = {p.id for p in permissions}

            role.role_name = data.role_name if not role.is_system_role else role.role_name
            role.description = data.description
            self._roles.set_permissions(db, role, permission_ids)

            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_ROLE_PERMISSIONS,
                module=MODULE_ROLES,
                entity_type="Role",
                entity_id=role.id,
                old_values=old_values,
                new_values={
                    "role_name": role.role_name,
                    "description": role.description,
                    "permissions": role.permission_keys,
                },
            )
            return RoleSummary.from_role(role, self._roles.count_users(db, role.id))

    def delete_role(self, role_id: int) -> None:
        """Delete a custom role that is not assigned to anyone."""
        with self.unit_of_work() as db:
            actor = self._authorize(db, "roles.update")
            role = self._roles.get(db, role_id)
            if role is None:
                raise NotFoundError(f"Role {role_id} was not found")
            if role.is_system_role:
                raise ProtectedRecordError("System roles cannot be deleted")
            assigned = self._roles.count_users(db, role.id)
            if assigned:
                raise ConflictError(
                    f"This role is assigned to {assigned} user(s); reassign them first"
                )
            role_name = role.role_name
            self._roles.delete(db, role)
            self._audit.record(
                db,
                actor_id=actor.id,
                action=AuditAction.UPDATE_ROLE,
                module=MODULE_ROLES,
                entity_type="Role",
                entity_id=role_id,
                old_values={"role_name": role_name, "deleted": False},
                new_values={"role_name": role_name, "deleted": True},
            )

    # -- helpers -----------------------------------------------------------
    def _resolve_permissions(self, db: Session, permission_keys: list[str]):
        permissions = self._permissions.get_by_keys(db, sorted(set(permission_keys)))
        unknown = set(permission_keys) - {p.permission_key for p in permissions}
        if unknown:
            raise ValidationError(f"Unknown permission(s): {', '.join(sorted(unknown))}")
        return permissions
