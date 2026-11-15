"""Centralised application exception hierarchy.

Every exception carries a ``user_message`` that is safe to show in the UI.
Internal details are only written to the application log by the callers, so
stack traces and database internals never reach an end user.
"""

from __future__ import annotations


class BizPilotError(Exception):
    """Base class for every expected application error."""

    default_user_message = "An unexpected error occurred. Please try again."

    def __init__(self, message: str | None = None, *, user_message: str | None = None) -> None:
        self.message = message or self.default_user_message
        self.user_message = user_message or self.default_user_message
        super().__init__(self.message)

    @property
    def safe_message(self) -> str:
        """The most specific message that is safe to show to a user."""
        if self.user_message and self.user_message != type(self).default_user_message:
            return self.user_message
        return self.message or self.user_message


class ConfigurationError(BizPilotError):
    default_user_message = "The application configuration is incomplete or invalid."


class DatabaseError(BizPilotError):
    default_user_message = "The application database could not be accessed."


class MigrationError(DatabaseError):
    default_user_message = "The database schema could not be prepared. Please contact your administrator."


class ValidationError(BizPilotError):
    default_user_message = "Please correct the highlighted fields and try again."

    def __init__(
        self,
        message: str,
        *,
        fields: dict[str, str] | None = None,
        user_message: str | None = None,
    ) -> None:
        # The specific message is normally safe to show (e.g. "only 8 outstanding"),
        # so it is used as the user-facing text unless one is supplied.
        super().__init__(message, user_message=user_message or message)
        self.fields = fields or {}


class AuthenticationError(BizPilotError):
    default_user_message = "You need to sign in to continue."


class InvalidCredentialsError(AuthenticationError):
    default_user_message = "Invalid email or password."


class AccountLockedError(AuthenticationError):
    default_user_message = "This account is temporarily locked. Please try again later."

    def __init__(self, message: str, *, locked_until=None) -> None:
        super().__init__(message)
        self.locked_until = locked_until


class AccountInactiveError(AuthenticationError):
    default_user_message = "This account is not active. Contact your administrator."


class SessionExpiredError(AuthenticationError):
    default_user_message = "Your session has expired. Please sign in again."


class AuthorizationError(BizPilotError):
    default_user_message = "You do not have permission to perform this action."


class NotFoundError(BizPilotError):
    default_user_message = "The requested record could not be found."


class DuplicateEmailError(BizPilotError):
    default_user_message = "A user with this email address already exists."


class ConflictError(BizPilotError):
    default_user_message = "The operation conflicts with the current state of the data."


class ProtectedRecordError(BizPilotError):
    default_user_message = "This record is protected and cannot be modified or removed."


class BackupError(BizPilotError):
    default_user_message = "The backup or restore operation failed."
