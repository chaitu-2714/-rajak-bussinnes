"""Role model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.date_utils import utcnow


class Role(Base):
    """A named collection of permissions."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    role_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255))
    is_system_role: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)

    role_permissions: Mapped[list["RolePermission"]] = relationship(  # noqa: F821
        back_populates="role", cascade="all, delete-orphan"
    )
    user_roles: Mapped[list["UserRole"]] = relationship(  # noqa: F821
        back_populates="role", cascade="all, delete-orphan"
    )

    @property
    def permission_keys(self) -> list[str]:
        return sorted(link.permission.permission_key for link in self.role_permissions if link.permission)

    @property
    def user_count(self) -> int:
        return len(self.user_roles)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Role id={self.id} name={self.role_name!r} system={self.is_system_role}>"
