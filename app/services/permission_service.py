"""Read-only permission catalogue service."""

from __future__ import annotations

from collections import OrderedDict

from sqlalchemy.orm import Session, sessionmaker

from app.database.repositories.permission_repository import PermissionRepository
from app.schemas.role_schema import PermissionSummary
from app.services.base_service import AuthContext, BaseService


class PermissionService(BaseService):
    """Exposes the permission catalogue to the UI."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        auth_context: AuthContext,
        *,
        permission_repository: PermissionRepository,
    ) -> None:
        super().__init__(session_factory, auth_context)
        self._permissions = permission_repository

    def list_all(self) -> list[PermissionSummary]:
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "roles.view")
            return [
                PermissionSummary.from_permission(permission)
                for permission in self._permissions.list_all(db)
            ]

    def grouped(self) -> "OrderedDict[str, list[PermissionSummary]]":
        with self.unit_of_work(write=False) as db:
            self._authorize(db, "roles.view")
            return OrderedDict(
                (
                    module,
                    [PermissionSummary.from_permission(p) for p in permissions],
                )
                for module, permissions in self._permissions.list_grouped(db).items()
            )

    def keys_for_principal(self) -> list[str]:
        """Permission keys of the signed-in user (no RBAC check needed)."""
        with self.unit_of_work(write=False) as db:
            user = self._current_user(db)
            from app.security.authorization import get_user_permissions

            return sorted(get_user_permissions(db, user))
