"""Data access for roles and role-permission assignments."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database.models.permission import Permission
from app.database.models.role import Role
from app.database.models.role_permission import RolePermission
from app.database.models.user_role import UserRole


class RoleRepository:
    """All SQL touching the ``roles`` and ``role_permissions`` tables."""

    @staticmethod
    def _with_permissions():
        return selectinload(Role.role_permissions).selectinload(RolePermission.permission)

    def get(self, db: Session, role_id: int) -> Role | None:
        return db.scalars(
            select(Role).options(self._with_permissions()).where(Role.id == role_id)
        ).first()

    def get_by_name(self, db: Session, role_name: str) -> Role | None:
        return db.scalars(
            select(Role).options(self._with_permissions()).where(Role.role_name == role_name)
        ).first()

    def list_all(self, db: Session) -> list[Role]:
        return list(
            db.scalars(
                select(Role).options(self._with_permissions()).order_by(
                    Role.is_system_role.desc(), Role.role_name.asc()
                )
            )
            .unique()
            .all()
        )

    def add(self, db: Session, role: Role) -> Role:
        db.add(role)
        db.flush()
        return role

    def delete(self, db: Session, role: Role) -> None:
        db.delete(role)
        db.flush()

    def count_users(self, db: Session, role_id: int) -> int:
        return int(
            db.scalar(select(func.count(UserRole.id)).where(UserRole.role_id == role_id)) or 0
        )

    def set_permissions(
        self, db: Session, role: Role, permission_ids: set[int]
    ) -> None:
        """Replace a role's permission set."""
        existing = {link.permission_id: link for link in role.role_permissions}
        for permission_id, link in list(existing.items()):
            if permission_id not in permission_ids:
                role.role_permissions.remove(link)
        db.flush()
        for permission_id in permission_ids:
            if permission_id in existing:
                continue
            permission = db.get(Permission, permission_id)
            if permission is None:
                continue
            role.role_permissions.append(
                RolePermission(role_id=role.id, permission_id=permission.id)
            )
        db.flush()
        db.refresh(role)
