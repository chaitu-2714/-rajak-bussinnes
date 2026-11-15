"""Pydantic schemas for authentication and initial setup."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.constants import CURRENCIES, TIMEZONES
from app.utils.validators import (
    is_valid_email,
    is_valid_phone,
    normalise_email,
    validate_password_strength,
)

MIN_PASSWORD_LENGTH = 10


class LoginRequest(BaseModel):
    """Credentials submitted from the login screen."""

    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _email_shape(cls, value: str) -> str:
        if not is_valid_email(value):
            raise ValueError("Enter a valid email address.")
        return normalise_email(value)


class InitialSetupRequest(BaseModel):
    """Payload from the first-launch setup wizard."""

    model_config = ConfigDict(str_strip_whitespace=True)

    business_name: str = Field(min_length=2, max_length=150)
    owner_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    password_confirm: str = Field(min_length=1, max_length=256)
    currency: str = Field(default="INR", max_length=8)
    timezone: str = Field(default="Asia/Kolkata", max_length=64)
    financial_year_start: str = Field(default="04-01", max_length=5)

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

    @field_validator("currency")
    @classmethod
    def _currency_supported(cls, value: str) -> str:
        code = value.upper()
        if code not in CURRENCIES:
            raise ValueError(f"Currency must be one of {', '.join(CURRENCIES)}.")
        return code

    @field_validator("timezone")
    @classmethod
    def _timezone_supported(cls, value: str) -> str:
        if value not in TIMEZONES:
            raise ValueError("Select a supported timezone.")
        return value

    @field_validator("financial_year_start")
    @classmethod
    def _financial_year(cls, value: str) -> str:
        parts = value.split("-")
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("Financial year start must use MM-DD format.")
        month, day = int(parts[0]), int(parts[1])
        if not 1 <= month <= 12 or not 1 <= day <= 31:
            raise ValueError("Financial year start must be a valid month and day.")
        return f"{month:02d}-{day:02d}"

    @model_validator(mode="after")
    def _passwords_match(self) -> "InitialSetupRequest":
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match.")
        return self


class PasswordChangeRequest(BaseModel):
    """Self-service password change."""

    model_config = ConfigDict(str_strip_whitespace=False)

    current_password: str = Field(min_length=1, max_length=256)
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
    def _passwords_match(self) -> "PasswordChangeRequest":
        if self.new_password != self.confirm_password:
            raise ValueError("New passwords do not match.")
        if self.new_password == self.current_password:
            raise ValueError("The new password must differ from the current password.")
        return self


class SessionInfo(BaseModel):
    """Read-only view of the active session."""

    session_id: int
    created_at: str
    expires_at: str
    last_activity_at: str
