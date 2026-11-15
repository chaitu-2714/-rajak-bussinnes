"""Data access for the permission catalogue."""

from __future__ import annotations

from collections import OrderedDict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import PERMISSION_MODULES
from app.database.models.permission import Permission


class PermissionRepository:
    """Read-only access to the seeded permission catalogue."""

    def get_by_key(self, db: Session, permission_key: str) -> Permission | None:
        return db.scalars(
            select(Permission).where(Permission.permission_key == permission_key)
        ).first()

    def get_by_keys(self, db: Session, keys: list[str]) -> list[Permission]:
        if not keys:
            return []
        return list(
            db.scalars(select(Permission).where(Permission.permission_key.in_(keys))).all()
        )

    def list_all(self, db: Session) -> list[Permission]:
        return list(db.scalars(select(Permission).order_by(Permission.permission_key)).all())

    def list_grouped(self, db: Session) -> "OrderedDict[str, list[Permission]]":
        """Permissions grouped by module in catalogue order."""
        grouped: OrderedDict[str, list[Permission]] = OrderedDict()
        permissions = self.list_all(db)
        for module in PERMISSION_MODULES:
            module_permissions = [p for p in permissions if p.module == module]
            if module_permissions:
                grouped[module] = module_permissions
        # Any module not in the canonical order is appended rather than lost.
        for permission in permissions:
            if permission.module not in grouped:
                grouped.setdefault(permission.module, []).append(permission)
        return grouped

    def count(self, db: Session) -> int:
        return len(self.list_all(db))
