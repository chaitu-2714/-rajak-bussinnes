"""Pydantic schemas for the business profile."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import CURRENCIES, TIMEZONES
from app.utils.validators import is_valid_email, is_valid_phone, normalise_email


class BusinessUpdateRequest(BaseModel):
    """Editable business profile fields."""

    model_config = ConfigDict(str_strip_whitespace=True)

    business_name: str = Field(min_length=2, max_length=150)
    owner_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
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


class BusinessSummary(BaseModel):
    """Read model for the business profile."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    business_name: str
    owner_name: str
    email: str
    phone: str | None = None
    address: str | None = None
    currency: str
    timezone: str
    financial_year_start: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_business(cls, business) -> "BusinessSummary":
        return cls.model_validate(business)
