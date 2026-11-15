"""Shared input validation helpers used by schemas and UI forms."""

from __future__ import annotations

import re

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
PHONE_PATTERN = re.compile(r"^[0-9+\-\s()]{7,20}$")

SPECIAL_CHARACTERS = "!@#$%^&*()-_=+[]{};:'\",.<>/?\\|`~"


def normalise_email(value: str) -> str:
    """Emails are stored and compared in lower case."""
    return value.strip().lower()


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_PATTERN.match((value or "").strip()))


def is_valid_phone(value: str | None) -> bool:
    if not value:
        return True
    return bool(PHONE_PATTERN.match(value.strip()))


def validate_password_strength(password: str, min_length: int = 10) -> list[str]:
    """Return a list of human readable password policy violations."""
    problems: list[str] = []
    if len(password or "") < min_length:
        problems.append(f"Password must be at least {min_length} characters long.")
    if not any(char.islower() for char in password or ""):
        problems.append("Password must include a lowercase letter.")
    if not any(char.isupper() for char in password or ""):
        problems.append("Password must include an uppercase letter.")
    if not any(char.isdigit() for char in password or ""):
        problems.append("Password must include a number.")
    if not any(char in SPECIAL_CHARACTERS for char in password or ""):
        problems.append("Password must include a special character.")
    return problems


def is_strong_password(password: str, min_length: int = 10) -> bool:
    return not validate_password_strength(password, min_length)


def validate_required(value: str | None, label: str, min_length: int = 1) -> list[str]:
    if value is None or not str(value).strip():
        return [f"{label} is required."]
    if len(str(value).strip()) < min_length:
        return [f"{label} must be at least {min_length} characters."]
    return []
