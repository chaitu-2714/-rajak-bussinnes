"""Password and credential policy for the security layer."""

from __future__ import annotations

from app.utils.validators import validate_password_strength


class PasswordPolicy:
    """Enforces the account password policy in one place."""

    def __init__(self, min_length: int = 10) -> None:
        self._min_length = min_length

    @property
    def min_length(self) -> int:
        return self._min_length

    def violations(self, password: str) -> list[str]:
        return validate_password_strength(password, self._min_length)

    def is_valid(self, password: str) -> bool:
        return not self.violations(password)

    def describe(self) -> str:
        return (
            f"At least {self._min_length} characters, with an uppercase letter, "
            "a lowercase letter, a number and a special character."
        )
