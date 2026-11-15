"""Pydantic schemas for user management."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.auth_schema import MIN_PASSWORD_LENGTH
from app.utils.validators import (
    is_valid_email,
    is_valid_phone,
    normalise_email,
    validate_password_strength,
)


class UserCreateRequest(BaseModel):
    """Payload for creating a user account."""

    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    password_confirm: str = Field(min_length=1, max_length=256)
    role_ids: list[int] = Field(default_factory=list)
    is_active: bool = True

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        if not is_valid_email(value):
            raise ValueError("Enter a valid email address.")
        return normalise_email(value)

    @field_validator("phone")
    @classmethod
    def _phone_shape(cls, value: str | None) -> str | None:
        if value and not is_valid_phone(value):
            raise ValueError("Enter a valid phone number.")
        return value or None

    @field_validator("password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        problems = validate_password_strength(value, MIN_PASSWORD_LENGTH)
        if problems:
            raise ValueError(" ".join(problems))
        return value

    @model_validator(mode="after")
    def _passwords_match(self) -> "UserCreateRequest":
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match.")
        if not self.role_ids:
            raise ValueError("Assign at least one role.")
        return self


class UserUpdateRequest(BaseModel):
    """Payload for editing an existing user."""

    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    role_ids: list[int] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        if not is_valid_email(value):
            raise ValueError("Enter a valid email address.")
        return normalise_email(value)

    @field_validator("phone")
    @classmethod
    def _phone_shape(cls, value: str | None) -> str | None:
        if value and not is_valid_phone(value):
            raise ValueError("Enter a valid phone number.")
        return value or None

    @model_validator(mode="after")
    def _roles_present(self) -> "UserUpdateRequest":
        if not self.role_ids:
            raise ValueError("Assign at least one role.")
        return self


class PasswordResetRequest(BaseModel):
    """Administrative password reset for another user."""

    model_config = ConfigDict(str_strip_whitespace=False)

    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    confirm_password: str = Field(min_length=1, max_length=256)

    @field_validator("new_password")
    @classmethod
    def _password_strength(cls, value: str) -> str:
        problems = validate_password_strength(value, MIN_PASSWORD_LENGTH)
        if problems:
            raise ValueError(" ".join(problems))
        return value

    @model_validator(mode="after")
    def _passwords_match(self) -> "PasswordResetRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class ProfileUpdateRequest(BaseModel):
    """A user editing their own basic profile."""

    model_config = ConfigDict(str_strip_whitespace=True)

    full_name: str = Field(min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=32)

    @field_validator("phone")
    @classmethod
    def _phone_shape(cls, value: str | None) -> str | None:
        if value and not is_valid_phone(value):
            raise ValueError("Enter a valid phone number.")
        return value or None


class UserSummary(BaseModel):
    """Read model returned to the UI."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    email: str
    phone: str | None = None
    is_active: bool
    is_superuser: bool
    roles: list[str] = Field(default_factory=list)
    role_ids: list[int] = Field(default_factory=list)
    created_at: datetime
    last_login_at: datetime | None = None
    locked_until: datetime | None = None

    @classmethod
    def from_user(cls, user) -> "UserSummary":
        return cls(
            id=user.id,
            full_name=user.full_name,
            email=user.email,
            phone=user.phone,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            roles=user.role_names,
            role_ids=user.role_ids,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
            locked_until=user.locked_until,
        )
