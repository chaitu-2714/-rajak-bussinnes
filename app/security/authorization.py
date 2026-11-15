"""Centralised Role-Based Access Control.

Authorisation is always evaluated against the database, never against a
hard-coded role name and never by the UI alone. Every protected service call
goes through :func:`require_permission`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AuthorizationError
from app.core.logging_config import get_logger
from app.database.models.permission import Permission
from app.database.models.role import Role
from app.database.models.role_permission import RolePermission
from app.database.models.user import User
from app.database.models.user_role import UserRole

logger = get_logger("security.rbac")


@dataclass(frozen=True)
class Principal:
    """Immutable snapshot of the signed-in user used by the UI layer."""

    user_id: int
    full_name: str
    email: str
    is_superuser: bool
    roles: tuple[str, ...] = ()
    permissions: frozenset[str] = field(default_factory=frozenset)
    business_name: str | None = None

    def has(self, permission_key: str) -> bool:
        return self.is_superuser or permission_key in self.permissions

    @property
    def primary_role(self) -> str:
        return self.roles[0] if self.roles else "No role"


def get_user_roles(db: Session, user: User) -> list[Role]:
    """Roles assigned to ``user`` (ordered by name)."""
    return list(
        db.scalars(
            select(Role)
            .join(UserRole, UserRole.role_id == Role.id)
            .where(UserRole.user_id == user.id)
            .order_by(Role.role_name)
        )
        .unique()
        .all()
    )


def get_user_permissions(db: Session, user: User) -> set[str]:
    """Effective permission keys for ``user``.

    A superuser implicitly holds every permission in the catalogue; everyone
    else gets the union of the permissions of their assigned roles.
    """
    if user.is_superuser:
        return set(db.scalars(select(Permission.permission_key)).all())

    rows = db.scalars(
        select(Permission.permission_key)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user.id)
    ).all()
    return {key for key in rows if key}


def has_permission(db: Session, user: User, permission_key: str) -> bool:
    """True when ``user`` holds ``permission_key``."""
    if not user.is_active:
        return False
    return permission_key in get_user_permissions(db, user)


def require_permission(db: Session, user: User, permission_key: str) -> None:
    """Raise :class:`AuthorizationError` unless the user holds the permission."""
    if not has_permission(db, user, permission_key):
        logger.warning(
            "Permission denied: user=%s permission=%s", getattr(user, "id", None), permission_key
        )
        raise AuthorizationError(f"Missing permission: {permission_key}")


def build_principal(
    db: Session, user: User, business_name: str | None = None
) -> Principal:
    """Build the UI-facing principal snapshot for ``user``."""
    roles = tuple(role.role_name for role in get_user_roles(db, user))
    permissions = frozenset(get_user_permissions(db, user))
    return Principal(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        is_superuser=bool(user.is_superuser),
        roles=roles,
        permissions=permissions,
        business_name=business_name,
    )
