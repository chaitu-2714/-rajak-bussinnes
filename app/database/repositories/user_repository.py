"""Data access for user accounts."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.database.models.role import Role
from app.database.models.user import User
from app.database.models.user_role import UserRole


class UserRepository:
    """All SQL touching the ``users`` and ``user_roles`` tables lives here."""

    @staticmethod
    def _with_roles():
        return selectinload(User.user_roles).selectinload(UserRole.role)

    def get(self, db: Session, user_id: int) -> User | None:
        return db.scalars(
            select(User).options(self._with_roles()).where(User.id == user_id)
        ).first()

    def get_by_email(self, db: Session, email: str) -> User | None:
        normalised = email.strip().lower()
        return db.scalars(
            select(User).options(self._with_roles()).where(func.lower(User.email) == normalised)
        ).first()

    def email_exists(self, db: Session, email: str, exclude_user_id: int | None = None) -> bool:
        normalised = email.strip().lower()
        stmt = select(User.id).where(func.lower(User.email) == normalised)
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        return db.scalars(stmt).first() is not None

    def list(
        self,
        db: Session,
        *,
        search: str | None = None,
        role_id: int | None = None,
        is_active: bool | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[User]:
        stmt = select(User).options(self._with_roles())
        if search:
            pattern = f"%{search.strip().lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(User.full_name).like(pattern),
                    func.lower(User.email).like(pattern),
                    func.lower(func.coalesce(User.phone, "")).like(pattern),
                )
            )
        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        if role_id is not None:
            stmt = stmt.where(
                User.id.in_(select(UserRole.user_id).where(UserRole.role_id == role_id))
            )
        stmt = stmt.order_by(User.full_name.asc())
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(db.scalars(stmt).unique().all())

    def count(self, db: Session, *, is_active: bool | None = None) -> int:
        stmt = select(func.count(User.id))
        if is_active is not None:
            stmt = stmt.where(User.is_active.is_(is_active))
        return int(db.scalar(stmt) or 0)

    def count_active_superusers(self, db: Session, exclude_user_id: int | None = None) -> int:
        stmt = select(func.count(User.id)).where(
            User.is_superuser.is_(True), User.is_active.is_(True)
        )
        if exclude_user_id is not None:
            stmt = stmt.where(User.id != exclude_user_id)
        return int(db.scalar(stmt) or 0)

    def add(self, db: Session, user: User) -> User:
        db.add(user)
        db.flush()
        return user

    def set_roles(
        self, db: Session, user: User, role_ids: list[int], assigned_by: int | None
    ) -> None:
        """Replace the user's role assignments with ``role_ids``."""
        desired = set(role_ids)
        existing = {link.role_id: link for link in user.user_roles}

        for role_id, link in list(existing.items()):
            if role_id not in desired:
                user.user_roles.remove(link)
        db.flush()

        for role_id in desired:
            if role_id in existing:
                continue
            role = db.get(Role, role_id)
            if role is None:
                continue
            user.user_roles.append(
                UserRole(user_id=user.id, role_id=role.id, assigned_by=assigned_by)
            )
        db.flush()
        db.refresh(user)
