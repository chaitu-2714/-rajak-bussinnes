"""Time-based one-time passwords (TOTP) with hashed recovery codes."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.exceptions import BizPilotError, ConflictError, NotFoundError, ValidationError
from app.core.logging_config import get_logger
from app.database.models.security import MfaRecoveryCode, UserMfaSetting
from app.database.models.user import User
from app.security.data_protection.secret_manager import SecretManager
from app.utils.date_utils import utcnow

logger = get_logger("security.mfa")

RECOVERY_CODE_COUNT = 8


class MfaError(BizPilotError):
    default_user_message = "Multi-factor authentication failed."


@dataclass
class EnrollmentResult:
    secret: str
    provisioning_uri: str
    qr_png: bytes | None
    recovery_codes: list[str]


class MfaService:
    """Enrol, verify and enforce TOTP second factors."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        secret_manager: SecretManager,
        *,
        issuer: str = "BizPilot AI",
        window: int = 1,
    ) -> None:
        self._session_factory = session_factory
        self._secrets = secret_manager
        self._issuer = issuer
        self._window = window

    # -- enrolment ---------------------------------------------------------
    def start_enrollment(self, user_id: int, *, account_label: str) -> EnrollmentResult:
        import pyotp

        with self._session_factory() as db:
            user = db.get(User, user_id)
            if user is None:
                raise NotFoundError("User not found")
            setting = db.scalars(
                select(UserMfaSetting).where(UserMfaSetting.user_id == user_id)
            ).first()
            if setting is not None and setting.is_enabled and setting.is_verified:
                raise ConflictError("MFA is already enabled for this account")

            secret = pyotp.random_base32()
            if setting is None:
                setting = UserMfaSetting(user_id=user_id)
                db.add(setting)
            setting.secret_encrypted = self._secrets.encrypt(secret)
            setting.secret_hint = secret[-4:]
            setting.is_enabled = False
            setting.is_verified = False
            setting.enrolled_at = utcnow()
            setting.failed_attempts = 0

            recovery_codes = self._issue_recovery_codes(db, user_id)
            db.commit()

        uri = pyotp.TOTP(secret).provisioning_uri(
            name=account_label or "user", issuer_name=self._issuer
        )
        return EnrollmentResult(
            secret=secret, provisioning_uri=uri, qr_png=self._qr_png(uri),
            recovery_codes=recovery_codes,
        )

    def _qr_png(self, uri: str) -> bytes | None:
        try:
            import io

            import qrcode

            image = qrcode.make(uri)
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception:  # noqa: BLE001 - the URI is still usable without a QR
            logger.warning("QR generation unavailable")
            return None

    def _issue_recovery_codes(self, db: Session, user_id: int) -> list[str]:
        for old in db.scalars(
            select(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id)
        ).all():
            db.delete(old)
        db.flush()
        codes: list[str] = []
        for _ in range(RECOVERY_CODE_COUNT):
            code = f"{secrets.token_hex(2)}-{secrets.token_hex(2)}-{secrets.token_hex(2)}"
            codes.append(code)
            db.add(MfaRecoveryCode(user_id=user_id, code_hash=self._hash_code(code)))
        db.flush()
        return codes

    def _hash_code(self, code: str) -> str:
        return hashlib.sha256(code.strip().lower().encode("utf-8")).hexdigest()

    # -- verification ------------------------------------------------------
    def verify_enrollment(self, user_id: int, code: str) -> bool:
        import pyotp

        with self._session_factory() as db:
            setting = db.scalars(
                select(UserMfaSetting).where(UserMfaSetting.user_id == user_id)
            ).first()
            if setting is None or not setting.secret_encrypted:
                raise MfaError("Start MFA enrolment first")
            secret = self._secrets.decrypt(setting.secret_encrypted)
            if not pyotp.TOTP(secret).verify((code or "").strip(), valid_window=self._window):
                setting.failed_attempts += 1
                db.commit()
                return False
            setting.is_enabled = True
            setting.is_verified = True
            setting.verified_at = utcnow()
            setting.last_used_at = utcnow()
            setting.failed_attempts = 0
            db.commit()
            return True

    def verify_code(self, user_id: int, code: str) -> bool:
        """Verify a TOTP code or a single-use recovery code."""
        import pyotp

        code = (code or "").strip()
        with self._session_factory() as db:
            setting = db.scalars(
                select(UserMfaSetting).where(UserMfaSetting.user_id == user_id)
            ).first()
            if setting is None or not setting.is_enabled:
                raise MfaError("MFA is not enabled for this account")
            secret = self._secrets.decrypt(setting.secret_encrypted)
            if pyotp.TOTP(secret).verify(code, valid_window=self._window):
                setting.last_used_at = utcnow()
                setting.failed_attempts = 0
                db.commit()
                return True

            hashed = self._hash_code(code)
            row = db.scalars(
                select(MfaRecoveryCode).where(
                    MfaRecoveryCode.user_id == user_id,
                    MfaRecoveryCode.code_hash == hashed,
                    MfaRecoveryCode.used_at.is_(None),
                )
            ).first()
            if row is not None:
                row.used_at = utcnow()
                setting.last_used_at = utcnow()
                setting.failed_attempts = 0
                db.commit()
                logger.info("MFA recovery code used for user %s", user_id)
                return True

            setting.failed_attempts += 1
            db.commit()
            return False

    # -- state -------------------------------------------------------------
    def is_enabled(self, user_id: int) -> bool:
        with self._session_factory() as db:
            setting = db.scalars(
                select(UserMfaSetting).where(UserMfaSetting.user_id == user_id)
            ).first()
            return bool(setting and setting.is_enabled and setting.is_verified)

    def is_enforced(self, user_id: int) -> bool:
        with self._session_factory() as db:
            setting = db.scalars(
                select(UserMfaSetting).where(UserMfaSetting.user_id == user_id)
            ).first()
            return bool(setting and setting.enforced)

    def enforce_for_user(self, user_id: int, *, enforced: bool = True) -> dict:
        with self._session_factory() as db:
            setting = db.scalars(
                select(UserMfaSetting).where(UserMfaSetting.user_id == user_id)
            ).first()
            if setting is None:
                setting = UserMfaSetting(user_id=user_id)
                db.add(setting)
            setting.enforced = enforced
            db.commit()
            return {"user_id": user_id, "enforced": enforced, "enabled": setting.is_enabled}

    def status(self, user_id: int) -> dict[str, Any]:
        with self._session_factory() as db:
            setting = db.scalars(
                select(UserMfaSetting).where(UserMfaSetting.user_id == user_id)
            ).first()
            if setting is None:
                return {
                    "user_id": user_id, "enabled": False, "verified": False,
                    "enforced": False, "recovery_codes_remaining": 0,
                }
            remaining = len(
                db.scalars(
                    select(MfaRecoveryCode).where(
                        MfaRecoveryCode.user_id == user_id,
                        MfaRecoveryCode.used_at.is_(None),
                    )
                ).all()
            )
            return {
                "user_id": user_id,
                "enabled": setting.is_enabled,
                "verified": setting.is_verified,
                "enforced": setting.enforced,
                "algorithm": setting.algorithm,
                "digits": setting.digits,
                "period": setting.period,
                "secret_hint": setting.secret_hint,
                "enrolled_at": setting.enrolled_at,
                "verified_at": setting.verified_at,
                "last_used_at": setting.last_used_at,
                "recovery_codes_remaining": remaining,
            }

    def disable(self, user_id: int, *, code: str) -> dict:
        if not self.verify_code(user_id, code):
            raise ValidationError("A valid MFA code is required to disable MFA")
        with self._session_factory() as db:
            setting = db.scalars(
                select(UserMfaSetting).where(UserMfaSetting.user_id == user_id)
            ).first()
            if setting is not None:
                setting.is_enabled = False
                setting.is_verified = False
                setting.secret_encrypted = None
                db.commit()
            return {"user_id": user_id, "enabled": False}

    def regenerate_recovery_codes(self, user_id: int, *, code: str) -> list[str]:
        if not self.verify_code(user_id, code):
            raise ValidationError("A valid MFA code is required to regenerate recovery codes")
        with self._session_factory() as db:
            codes = self._issue_recovery_codes(db, user_id)
            db.commit()
            return codes
