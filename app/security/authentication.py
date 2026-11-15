"""Local credential authentication with lockout and generic errors."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.core.config import SecuritySettings
from app.core.exceptions import (
    AccountInactiveError,
    AccountLockedError,
    InvalidCredentialsError,
)
from app.core.logging_config import get_logger
from app.database.models.user import User
from app.database.repositories.user_repository import UserRepository
from app.security.password_manager import PasswordManager
from app.utils.date_utils import utcnow
from app.utils.validators import normalise_email

logger = get_logger("security.auth")


class Authenticator:
    """Verifies credentials and maintains failed-attempt counters."""

    def __init__(
        self,
        user_repository: UserRepository,
        password_manager: PasswordManager,
        settings: SecuritySettings,
    ) -> None:
        self._users = user_repository
        self._passwords = password_manager
        self._settings = settings

    def authenticate(self, db: Session, email: str, password: str) -> User:
        """Return the authenticated user or raise an authentication error."""
        user = self._users.get_by_email(db, normalise_email(email or ""))

        if user is None:
            # Equalise timing so unknown emails cannot be detected by latency.
            self._passwords.dummy_verify()
            raise InvalidCredentialsError("Unknown email supplied")

        if user.locked_until is not None and user.locked_until > utcnow():
            raise AccountLockedError(
                f"Account locked until {user.locked_until.isoformat()}",
                locked_until=user.locked_until,
            )

        if not self._passwords.verify_password(user.password_hash, password or ""):
            self.register_failure(db, user)
            raise InvalidCredentialsError("Password mismatch")

        if not user.is_active:
            raise AccountInactiveError("Account is deactivated")

        self.register_success(db, user)

        if self._passwords.needs_rehash(user.password_hash):
            user.password_hash = self._passwords.hash_password(password)
            db.flush()

        return user

    def register_failure(self, db: Session, user: User) -> None:
        """Increment the failure counter and lock the account when exceeded."""
        user.failed_login_attempts = int(user.failed_login_attempts or 0) + 1
        if user.failed_login_attempts >= self._settings.max_failed_attempts:
            user.locked_until = utcnow() + timedelta(minutes=self._settings.lockout_minutes)
            user.failed_login_attempts = 0
            logger.warning("Account %s locked until %s", user.email, user.locked_until)
        db.flush()

    def register_success(self, db: Session, user: User) -> None:
        user.failed_login_attempts = 0
        user.locked_until = None
        user.last_login_at = utcnow()
        db.flush()

    def unlock(self, db: Session, user: User) -> None:
        """Administrative unlock (used when resetting a password)."""
        user.failed_login_attempts = 0
        user.locked_until = None
        db.flush()
