"""Argon2id password hashing.

Argon2id is the only algorithm used for password storage. Plain SHA-256 or
any other fast digest is deliberately not available.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from argon2.low_level import Type

# OWASP-aligned baseline: 64 MiB, 3 iterations, 4 lanes, Argon2id.
_TIME_COST = 3
_MEMORY_COST = 64 * 1024
_PARALLELISM = 4
_HASH_LEN = 32
_SALT_LEN = 16


class PasswordManager:
    """Hash and verify passwords with Argon2id."""

    def __init__(
        self,
        *,
        time_cost: int = _TIME_COST,
        memory_cost: int = _MEMORY_COST,
        parallelism: int = _PARALLELISM,
    ) -> None:
        self._hasher = PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=_HASH_LEN,
            salt_len=_SALT_LEN,
            type=Type.ID,
        )

    def hash_password(self, password: str) -> str:
        """Return an Argon2id hash (never the plaintext)."""
        if not password:
            raise ValueError("Password must not be empty")
        return self._hasher.hash(password)

    def verify_password(self, password_hash: str, password: str) -> bool:
        """Constant-time verification; False for any mismatch or malformed hash."""
        if not password_hash or password is None:
            return False
        try:
            return self._hasher.verify(password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            return self._hasher.check_needs_rehash(password_hash)
        except InvalidHashError:
            return True

    def dummy_verify(self) -> None:
        """Burn comparable CPU time when the email does not exist."""
        self.verify_password(
            "$argon2id$v=19$m=65536,t=3,p=4$c29tZXNhbHR2YWx1ZQ$"
            "0YQ0dZ0m0Yy0h0d0n0V0d0c0h0a0r0s0e0t0v0a0l0u0e0",
            "timing-equaliser",
        )
