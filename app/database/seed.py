"""Reference-data bootstrap: permission catalogue and default roles.

The operation is idempotent and runs on every startup, which keeps the
catalogue in sync with :mod:`app.core.constants` without ever touching user
accounts, business data or audit history.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import (
    DEFAULT_BRANCH_NAME,
    DEFAULT_ROLES,
    PERMISSION_DEFINITIONS,
    ROLE_SUPER_ADMIN,
)
from app.core.logging_config import get_logger
from app.database.models.inventory import Branch
from app.database.models.permission import Permission
from app.database.models.role import Role
from app.database.models.role_permission import RolePermission

logger = get_logger("seed")


def ensure_permissions(db: Session) -> dict[str, Permission]:
    """Create missing permissions and keep names/descriptions current."""
    existing = {
        permission.permission_key: permission
        for permission in db.scalars(select(Permission)).all()
    }
    for definition in PERMISSION_DEFINITIONS:
        permission = existing.get(definition.key)
        if permission is None:
            permission = Permission(
                permission_key=definition.key,
                permission_name=definition.name,
                module=definition.module,
                description=definition.description,
            )
            db.add(permission)
            existing[definition.key] = permission
        else:
            permission.permission_name = definition.name
            permission.module = definition.module
            permission.description = definition.description
    db.flush()
    return existing


def ensure_roles(db: Session, permissions: dict[str, Permission]) -> dict[str, Role]:
    """Create default roles and align system-role permissions."""
    existing = {role.role_name: role for role in db.scalars(select(Role)).all()}
    for definition in DEFAULT_ROLES:
        role = existing.get(definition.name)
        if role is None:
            role = Role(
                role_name=definition.name,
                description=definition.description,
                is_system_role=True,
            )
            db.add(role)
            db.flush()
            existing[definition.name] = role
        else:
            role.is_system_role = True
            if not role.description:
                role.description = definition.description

        if definition.permissions == ("*",):
            target_keys = set(permissions)
        else:
            target_keys = {key for key in definition.permissions if key in permissions}

        current_ids = {link.permission_id for link in role.role_permissions}
        target_ids = {permissions[key].id for key in target_keys}

        for link in list(role.role_permissions):
            if link.permission_id not in target_ids:
                role.role_permissions.remove(link)
        for permission_id in target_ids - current_ids:
            role.role_permissions.append(
                RolePermission(role_id=role.id, permission_id=permission_id)
            )
    db.flush()
    return existing


def ensure_default_branch(db: Session) -> Branch:
    """Guarantee one default business location for inventory records."""
    branch = db.scalars(
        select(Branch).where(Branch.is_default.is_(True)).order_by(Branch.id)
    ).first()
    if branch is None:
        branch = db.scalars(select(Branch).order_by(Branch.id)).first()
    if branch is None:
        branch = Branch(branch_name=DEFAULT_BRANCH_NAME, is_default=True, is_active=True)
        db.add(branch)
        db.flush()
        logger.debug("Created default branch %s", DEFAULT_BRANCH_NAME)
    elif not branch.is_default:
        branch.is_default = True
        db.flush()
    return branch


def ensure_reference_data(db: Session) -> None:
    """Seed permissions, roles and the default branch; safe to call repeatedly."""
    permissions = ensure_permissions(db)
    roles = ensure_roles(db, permissions)
    ensure_default_branch(db)
    db.flush()
    logger.debug(
        "Reference data ready: %s permissions, %s roles",
        len(permissions),
        len(roles),
    )


def super_admin_role(db: Session) -> Role:
    """Return the Super Admin role, creating reference data if needed."""
    role = db.scalars(select(Role).where(Role.role_name == ROLE_SUPER_ADMIN)).first()
    if role is None:
        ensure_reference_data(db)
        role = db.scalars(select(Role).where(Role.role_name == ROLE_SUPER_ADMIN)).first()
    if role is None:  # pragma: no cover - defensive
        raise RuntimeError("Super Admin role could not be created")
    return role
