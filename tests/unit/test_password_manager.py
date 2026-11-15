"""Unit tests: Argon2id password hashing."""

from __future__ import annotations

import hashlib

import pytest

from app.security.password_manager import PasswordManager


@pytest.fixture()
def manager() -> PasswordManager:
    # Cheaper parameters keep the suite fast; production uses 64 MiB / 3 passes.
    return PasswordManager(time_cost=1, memory_cost=8192, parallelism=1)


def test_hash_uses_argon2id(manager: PasswordManager) -> None:
    digest = manager.hash_password("Str0ng!Passw0rd")
    assert digest.startswith("$argon2id$")
    assert "Str0ng!Passw0rd" not in digest


def test_verify_accepts_correct_password(manager: PasswordManager) -> None:
    digest = manager.hash_password("Str0ng!Passw0rd")
    assert manager.verify_password(digest, "Str0ng!Passw0rd") is True


def test_verify_rejects_wrong_password(manager: PasswordManager) -> None:
    digest = manager.hash_password("Str0ng!Passw0rd")
    assert manager.verify_password(digest, "str0ng!passw0rd") is False


def test_hashes_are_salted(manager: PasswordManager) -> None:
    assert manager.hash_password("same-password") != manager.hash_password("same-password")


def test_plain_sha256_digest_is_not_accepted(manager: PasswordManager) -> None:
    sha256 = hashlib.sha256(b"Str0ng!Passw0rd").hexdigest()
    assert manager.verify_password(sha256, "Str0ng!Passw0rd") is False


def test_malformed_hash_returns_false(manager: PasswordManager) -> None:
    assert manager.verify_password("not-a-hash", "anything") is False


def test_needs_rehash_false_for_current_parameters(manager: PasswordManager) -> None:
    digest = manager.hash_password("Str0ng!Passw0rd")
    assert manager.needs_rehash(digest) is False
