"""Shared service plumbing: auth context, unit of work, payload validation."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterator, TypeVar

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import (
    AuthenticationError,
    NotFoundError,
    SessionExpiredError,
    ValidationError,
)
from app.core.logging_config import get_logger
from app.database.models.user import User
from app.security.authorization import Principal, require_permission
from app.utils.date_utils import utcnow

logger = get_logger("services")

SchemaT = TypeVar("SchemaT", bound=BaseModel)


@dataclass
class AuthContext:
    """In-memory authentication state owned by the UI session."""

    principal: Principal | None = None
    token: str | None = None
    session_id: int | None = None
    expires_at: datetime | None = None

    @property
    def is_authenticated(self) -> bool:
        return self.principal is not None and bool(self.token)

    def set(self, principal: Principal, token: str, session_id: int, expires_at: datetime) -> None:
        self.principal = principal
        self.token = token
        self.session_id = session_id
        self.expires_at = expires_at

    def clear(self) -> None:
        self.principal = None
        self.token = None
        self.session_id = None
        self.expires_at = None


def validate_payload(schema: type[SchemaT], data: dict[str, Any] | BaseModel) -> SchemaT:
    """Validate a payload, converting pydantic errors into application errors."""
    if isinstance(data, BaseModel):
        return schema.model_validate(data.model_dump())
    try:
        return schema.model_validate(data)
    except PydanticValidationError as exc:
        fields: dict[str, str] = {}
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"]) or "form"
            message = str(error["msg"]).replace("Value error, ", "")
            fields.setdefault(location, message)
        summary = " ".join(dict.fromkeys(fields.values())) or "Invalid input."
        raise ValidationError(summary, fields=fields) from exc


class BaseService:
    """Common behaviour for every application service."""

    def __init__(self, session_factory: sessionmaker[Session], auth_context: AuthContext) -> None:
        self._session_factory = session_factory
        self._auth_context = auth_context

    # -- transactions ------------------------------------------------------
    @contextmanager
    def unit_of_work(self, *, write: bool = True) -> Iterator[Session]:
        """Transactional scope: commit on success, roll back on any error."""
        db = self._session_factory()
        try:
            yield db
            if write:
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # -- identity / authorisation -----------------------------------------
    @property
    def auth_context(self) -> AuthContext:
        return self._auth_context

    @property
    def principal(self) -> Principal | None:
        return self._auth_context.principal

    def _current_user(self, db: Session) -> User:
        """Load the signed-in user, validating that the session is still live."""
        principal = self._auth_context.principal
        if principal is None:
            raise AuthenticationError("No authenticated user")
        if self._auth_context.expires_at and self._auth_context.expires_at <= utcnow():
            self._auth_context.clear()
            raise SessionExpiredError("Session expired")
        user = db.get(User, principal.user_id)
        if user is None:
            raise AuthenticationError("The signed-in account no longer exists")
        if not user.is_active:
            raise AuthenticationError("The signed-in account has been deactivated")
        return user

    def _authorize(self, db: Session, permission_key: str) -> User:
        """Load the current user and enforce a permission (service-level RBAC)."""
        user = self._current_user(db)
        require_permission(db, user, permission_key)
        return user

    def _load_user(self, db: Session, user_id: int) -> User:
        user = db.get(User, user_id)
        if user is None:
            raise NotFoundError(f"User {user_id} was not found")
        return user
