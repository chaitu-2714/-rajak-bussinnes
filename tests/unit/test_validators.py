"""Unit tests: validation rules and schema conversion."""

from __future__ import annotations

import pytest

from app.core.exceptions import ValidationError
from app.schemas.auth_schema import InitialSetupRequest
from app.schemas.user_schema import UserCreateRequest
from app.services.base_service import validate_payload
from app.utils.validators import (
    is_valid_email,
    is_valid_phone,
    validate_password_strength,
)


@pytest.mark.parametrize(
    "email",
    ["tej@example.com", "owner.name+tag@business.co.in", "a@b.io"],
)
def test_valid_emails(email: str) -> None:
    assert is_valid_email(email) is True


@pytest.mark.parametrize("email", ["", "no-at-sign", "a@b", "spaces in@mail.com", "@example.com"])
def test_invalid_emails(email: str) -> None:
    assert is_valid_email(email) is False


def test_phone_validation() -> None:
    assert is_valid_phone("+91 98765 43210") is True
    assert is_valid_phone("98765") is False
    assert is_valid_phone(None) is True


def test_password_policy_requires_mixed_characters() -> None:
    problems = validate_password_strength("short", 10)
    assert any("10 characters" in problem for problem in problems)
    assert any("uppercase" in problem for problem in problems)

    problems = validate_password_strength("alllowercase123!", 10)
    assert any("uppercase" in problem for problem in problems)

    assert validate_password_strength("Str0ng!Passw0rd", 10) == []


def test_validate_payload_reports_field_errors() -> None:
    with pytest.raises(ValidationError) as excinfo:
        validate_payload(
            UserCreateRequest,
            {
                "full_name": "A",
                "email": "bad-email",
                "password": "weak",
                "password_confirm": "weak",
                "role_ids": [],
            },
        )
    error = excinfo.value
    assert error.fields
    assert "email" in error.fields


def test_setup_schema_rejects_mismatched_passwords() -> None:
    with pytest.raises(ValidationError):
        validate_payload(
            InitialSetupRequest,
            {
                "business_name": "Test Traders",
                "owner_name": "Owner",
                "email": "owner@example.com",
                "password": "Str0ng!Passw0rd",
                "password_confirm": "Different!Passw0rd",
            },
        )


def test_setup_schema_rejects_unsupported_currency() -> None:
    with pytest.raises(ValidationError):
        validate_payload(
            InitialSetupRequest,
            {
                "business_name": "Test Traders",
                "owner_name": "Owner",
                "email": "owner@example.com",
                "password": "Str0ng!Passw0rd",
                "password_confirm": "Str0ng!Passw0rd",
                "currency": "XYZ",
            },
        )
