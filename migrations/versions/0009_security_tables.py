"""Phase 9: security events, MFA, governance policies and audit integrity

Revision ID: 0009_security
Revises: 0008_knowledge
Create Date: 2026-11-04 14:13:00.061623

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0009_security'
down_revision = '0008_knowledge'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ai_data_governance_policies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('classification', sa.String(length=20), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('allowed', sa.Boolean(), nullable=False),
    sa.Column('requires_redaction', sa.Boolean(), nullable=False),
    sa.Column('requires_opt_in', sa.Boolean(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_data_governance_policies')),
    sa.UniqueConstraint('classification', 'provider', name='uq_ai_data_governance')
    )
    with op.batch_alter_table('ai_data_governance_policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_data_governance_policies_classification'), ['classification'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_data_governance_policies_provider'), ['provider'], unique=False)

    op.create_table('audit_integrity_records',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('previous_hash', sa.String(length=64), nullable=False),
    sa.Column('record_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_integrity_records')),
    sa.UniqueConstraint('audit_id', name='uq_audit_integrity_audit')
    )
    with op.batch_alter_table('audit_integrity_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_integrity_records_audit_id'), ['audit_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_integrity_records_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_integrity_records_record_hash'), ['record_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_integrity_records_sequence'), ['sequence'], unique=False)

    op.create_table('agent_security_policies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('agent_code', sa.String(length=60), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('allowed_tools', sa.JSON(), nullable=True),
    sa.Column('allowed_data_categories', sa.JSON(), nullable=True),
    sa.Column('business_scope', sa.String(length=20), nullable=False),
    sa.Column('max_execution_depth', sa.Integer(), nullable=False),
    sa.Column('max_task_count', sa.Integer(), nullable=False),
    sa.Column('max_duration_seconds', sa.Integer(), nullable=False),
    sa.Column('cloud_ai_eligible', sa.Boolean(), nullable=False),
    sa.Column('requires_approval', sa.Boolean(), nullable=False),
    sa.Column('risk_classification', sa.String(length=10), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_agent_security_policies_updated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_security_policies')),
    sa.UniqueConstraint('agent_code', name='uq_agent_security_policies_code')
    )
    with op.batch_alter_table('agent_security_policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_security_policies_agent_code'), ['agent_code'], unique=False)

    op.create_table('backup_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('backup_ref', sa.String(length=40), nullable=False),
    sa.Column('backup_type', sa.String(length=20), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('includes_knowledge', sa.Boolean(), nullable=False),
    sa.Column('integrity_status', sa.String(length=20), nullable=False),
    sa.Column('validation_detail', sa.Text(), nullable=True),
    sa.Column('operation', sa.String(length=20), nullable=False),
    sa.Column('performed_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['performed_by'], ['users.id'], name=op.f('fk_backup_history_performed_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_backup_history'))
    )
    with op.batch_alter_table('backup_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_backup_history_backup_ref'), ['backup_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_backup_history_created_at'), ['created_at'], unique=False)

    op.create_table('mfa_recovery_codes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('code_hash', sa.String(length=128), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_mfa_recovery_codes_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mfa_recovery_codes'))
    )
    with op.batch_alter_table('mfa_recovery_codes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_mfa_recovery_codes_code_hash'), ['code_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_mfa_recovery_codes_user_id'), ['user_id'], unique=False)

    op.create_table('resource_access_policies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('resource_type', sa.String(length=60), nullable=False),
    sa.Column('resource_id', sa.String(length=80), nullable=True),
    sa.Column('classification', sa.String(length=20), nullable=False),
    sa.Column('allowed_roles', sa.JSON(), nullable=True),
    sa.Column('allowed_permissions', sa.JSON(), nullable=True),
    sa.Column('requires_approval', sa.Boolean(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_resource_access_policies_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_resource_access_policies'))
    )
    with op.batch_alter_table('resource_access_policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_resource_access_policies_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_resource_access_policies_resource_id'), ['resource_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_resource_access_policies_resource_type'), ['resource_type'], unique=False)

    op.create_table('security_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('event_ref', sa.String(length=40), nullable=False),
    sa.Column('event_type', sa.String(length=50), nullable=False),
    sa.Column('severity', sa.String(length=10), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('resource_type', sa.String(length=60), nullable=True),
    sa.Column('resource_id', sa.String(length=80), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('recommended_response', sa.Text(), nullable=True),
    sa.Column('is_confirmed_incident', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'OPEN'"), nullable=False),
    sa.Column('correlation_id', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_security_events_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_security_events')),
    sa.UniqueConstraint('event_ref', name='uq_security_events_ref')
    )
    with op.batch_alter_table('security_events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_security_events_correlation_id'), ['correlation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_event_ref'), ['event_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_severity'), ['severity'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_security_events_user_id'), ['user_id'], unique=False)

    op.create_table('security_incident_reviews',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('event_ref', sa.String(length=40), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('reviewed_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name=op.f('fk_security_incident_reviews_reviewed_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_security_incident_reviews'))
    )
    with op.batch_alter_table('security_incident_reviews', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_security_incident_reviews_event_ref'), ['event_ref'], unique=False)

    op.create_table('security_policies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('policy_key', sa.String(length=60), nullable=False),
    sa.Column('category', sa.String(length=30), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('value', sa.JSON(), nullable=True),
    sa.Column('is_enforced', sa.Boolean(), nullable=False),
    sa.Column('updated_by', sa.Integer(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['updated_by'], ['users.id'], name=op.f('fk_security_policies_updated_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_security_policies')),
    sa.UniqueConstraint('policy_key', name='uq_security_policies_key')
    )
    with op.batch_alter_table('security_policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_security_policies_policy_key'), ['policy_key'], unique=False)

    op.create_table('user_mfa_settings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), nullable=False),
    sa.Column('is_verified', sa.Boolean(), nullable=False),
    sa.Column('secret_encrypted', sa.Text(), nullable=True),
    sa.Column('secret_hint', sa.String(length=12), nullable=True),
    sa.Column('algorithm', sa.String(length=20), nullable=False),
    sa.Column('digits', sa.Integer(), nullable=False),
    sa.Column('period', sa.Integer(), nullable=False),
    sa.Column('enrolled_at', sa.DateTime(), nullable=True),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('failed_attempts', sa.Integer(), nullable=False),
    sa.Column('enforced', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_user_mfa_settings_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_user_mfa_settings')),
    sa.UniqueConstraint('user_id', name='uq_user_mfa_settings_user')
    )
    with op.batch_alter_table('user_mfa_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_user_mfa_settings_user_id'), ['user_id'], unique=False)

    op.create_table('session_security_records',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('event', sa.String(length=30), nullable=False),
    sa.Column('mfa_verified', sa.Boolean(), nullable=False),
    sa.Column('device_info', sa.String(length=255), nullable=True),
    sa.Column('reason', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], name=op.f('fk_session_security_records_session_id_sessions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_session_security_records_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_session_security_records'))
    )
    with op.batch_alter_table('session_security_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_session_security_records_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_security_records_event'), ['event'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_security_records_session_id'), ['session_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_session_security_records_user_id'), ['user_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('session_security_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_session_security_records_user_id'))
        batch_op.drop_index(batch_op.f('ix_session_security_records_session_id'))
        batch_op.drop_index(batch_op.f('ix_session_security_records_event'))
        batch_op.drop_index(batch_op.f('ix_session_security_records_created_at'))

    op.drop_table('session_security_records')
    with op.batch_alter_table('user_mfa_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_user_mfa_settings_user_id'))

    op.drop_table('user_mfa_settings')
    with op.batch_alter_table('security_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_security_policies_policy_key'))

    op.drop_table('security_policies')
    with op.batch_alter_table('security_incident_reviews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_security_incident_reviews_event_ref'))

    op.drop_table('security_incident_reviews')
    with op.batch_alter_table('security_events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_security_events_user_id'))
        batch_op.drop_index(batch_op.f('ix_security_events_status'))
        batch_op.drop_index(batch_op.f('ix_security_events_severity'))
        batch_op.drop_index(batch_op.f('ix_security_events_event_type'))
        batch_op.drop_index(batch_op.f('ix_security_events_event_ref'))
        batch_op.drop_index(batch_op.f('ix_security_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_security_events_correlation_id'))

    op.drop_table('security_events')
    with op.batch_alter_table('resource_access_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_resource_access_policies_resource_type'))
        batch_op.drop_index(batch_op.f('ix_resource_access_policies_resource_id'))
        batch_op.drop_index(batch_op.f('ix_resource_access_policies_business_id'))

    op.drop_table('resource_access_policies')
    with op.batch_alter_table('mfa_recovery_codes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_mfa_recovery_codes_user_id'))
        batch_op.drop_index(batch_op.f('ix_mfa_recovery_codes_code_hash'))

    op.drop_table('mfa_recovery_codes')
    with op.batch_alter_table('backup_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_backup_history_created_at'))
        batch_op.drop_index(batch_op.f('ix_backup_history_backup_ref'))

    op.drop_table('backup_history')
    with op.batch_alter_table('agent_security_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_security_policies_agent_code'))

    op.drop_table('agent_security_policies')
    with op.batch_alter_table('audit_integrity_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_integrity_records_sequence'))
        batch_op.drop_index(batch_op.f('ix_audit_integrity_records_record_hash'))
        batch_op.drop_index(batch_op.f('ix_audit_integrity_records_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_integrity_records_audit_id'))

    op.drop_table('audit_integrity_records')
    with op.batch_alter_table('ai_data_governance_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_data_governance_policies_provider'))
        batch_op.drop_index(batch_op.f('ix_ai_data_governance_policies_classification'))

    op.drop_table('ai_data_governance_policies')
