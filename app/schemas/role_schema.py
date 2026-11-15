"""Pydantic schemas for roles and permissions."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RoleCreateRequest(BaseModel):
    """Payload for creating a custom role."""

    model_config = ConfigDict(str_strip_whitespace=True)

    role_name: str = Field(min_length=3, max_length=80)
    description: str | None = Field(default=None, max_length=255)
    permission_keys: list[str] = Field(default_factory=list)

    @field_validator("role_name")
    @classmethod
    def _name_shape(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not any(char.isalpha() for char in cleaned):
            raise ValueError("Role name must contain letters.")
        return cleaned


class RoleUpdateRequest(BaseModel):
    """Payload for editing a role."""

    model_config = ConfigDict(str_strip_whitespace=True)

    role_name: str = Field(min_length=3, max_length=80)
    description: str | None = Field(default=None, max_length=255)
    permission_keys: list[str] = Field(default_factory=list)

    @field_validator("role_name")
    @classmethod
    def _name_shape(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not any(char.isalpha() for char in cleaned):
            raise ValueError("Role name must contain letters.")
        return cleaned

    @model_validator(mode="after")
    def _permissions_present(self) -> "RoleUpdateRequest":
        if not self.permission_keys:
            raise ValueError("A role must grant at least one permission.")
        return self


class PermissionSummary(BaseModel):
    """One permission row in the RBAC UI."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    module: str
    description: str | None = None

    @classmethod
    def from_permission(cls, permission) -> "PermissionSummary":
        return cls(
            key=permission.permission_key,
            name=permission.permission_name,
            module=permission.module,
            description=permission.description,
        )


class RoleSummary(BaseModel):
    """Read model for a role."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    role_name: str
    description: str | None = None
    is_system_role: bool
    permission_keys: list[str] = Field(default_factory=list)
    user_count: int = 0
    created_at: datetime

    @classmethod
    def from_role(cls, role, user_count: int = 0) -> "RoleSummary":
        return cls(
            id=role.id,
            role_name=role.role_name,
            description=role.description,
            is_system_role=role.is_system_role,
            permission_keys=role.permission_keys,
            user_count=user_count,
            created_at=role.created_at,
        )
