"""Phase 9 models: MFA, security events, governance policies and audit integrity."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.utils.date_utils import utcnow


class UserMfaSetting(Base):
    """TOTP enrolment and MFA state for one user."""

    __tablename__ = "user_mfa_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_mfa_settings_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    secret_encrypted: Mapped[str | None] = mapped_column(Text)
    secret_hint: Mapped[str | None] = mapped_column(String(12))
    algorithm: Mapped[str] = mapped_column(String(20), nullable=False, default="SHA1")
    digits: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    period: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    enforced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class MfaRecoveryCode(Base):
    """A single-use recovery code, stored only as a hash."""

    __tablename__ = "mfa_recovery_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class SessionSecurityRecord(Base):
    """Security-relevant facts about one session."""

    __tablename__ = "session_security_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    event: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    device_info: Mapped[str | None] = mapped_column(String(255))
    reason: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class SecurityEvent(Base):
    """A security-relevant observation (indicator, not an accusation)."""

    __tablename__ = "security_events"
    __table_args__ = (UniqueConstraint("event_ref", name="uq_security_events_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="LOW", index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="ACCESS")
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    resource_type: Mapped[str | None] = mapped_column(String(60))
    resource_id: Mapped[str | None] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    recommended_response: Mapped[str | None] = mapped_column(Text)
    is_confirmed_incident: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="OPEN", index=True, server_default=text("'OPEN'")
    )
    correlation_id: Mapped[str | None] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class SecurityIncidentReview(Base):
    """A human review of a security event."""

    __tablename__ = "security_incident_reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class SecurityPolicy(Base):
    """A configurable security setting (with its audit trail)."""

    __tablename__ = "security_policies"
    __table_args__ = (UniqueConstraint("policy_key", name="uq_security_policies_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    policy_key: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="ACCESS")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    is_enforced: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class AgentSecurityPolicy(Base):
    """What one AI agent may do."""

    __tablename__ = "agent_security_policies"
    __table_args__ = (UniqueConstraint("agent_code", name="uq_agent_security_policies_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    allowed_tools: Mapped[list[Any] | None] = mapped_column(JSON)
    allowed_data_categories: Mapped[list[Any] | None] = mapped_column(JSON)
    business_scope: Mapped[str] = mapped_column(String(20), nullable=False, default="CURRENT")
    max_execution_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    max_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    cloud_ai_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    risk_classification: Mapped[str] = mapped_column(String(10), nullable=False, default="LOW")
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class AIDataGovernancePolicy(Base):
    """How one data classification may be handled, per provider."""

    __tablename__ = "ai_data_governance_policies"
    __table_args__ = (
        UniqueConstraint("classification", "provider", name="uq_ai_data_governance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classification: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_redaction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    requires_opt_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )


class ResourceAccessPolicy(Base):
    """Fine-grained rule for a resource type or a specific record."""

    __tablename__ = "resource_access_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(80), index=True)
    classification: Mapped[str] = mapped_column(String(20), nullable=False, default="INTERNAL")
    allowed_roles: Mapped[list[Any] | None] = mapped_column(JSON)
    allowed_permissions: Mapped[list[Any] | None] = mapped_column(JSON)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    business_id: Mapped[int | None] = mapped_column(Integer, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)


class AuditIntegrityRecord(Base):
    """The hash-chain head for one appended audit record."""

    __tablename__ = "audit_integrity_records"
    __table_args__ = (UniqueConstraint("audit_id", name="uq_audit_integrity_audit"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)


class BackupHistory(Base):
    """One backup or restore attempt, with validation state."""

    __tablename__ = "backup_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    backup_ref: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    backup_type: Mapped[str] = mapped_column(String(20), nullable=False, default="MANUAL")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    includes_knowledge: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    integrity_status: Mapped[str] = mapped_column(String(20), nullable=False, default="UNVERIFIED")
    validation_detail: Mapped[str | None] = mapped_column(Text)
    operation: Mapped[str] = mapped_column(String(20), nullable=False, default="BACKUP")
    performed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow, index=True)
