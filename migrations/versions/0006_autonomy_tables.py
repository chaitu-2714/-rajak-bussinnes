"""Phase 6: autonomous workflow, policy and approval tables

Revision ID: 0006_autonomy
Revises: 0005_collaboration
Create Date: 2026-11-04 05:55:41.730547

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0006_autonomy'
down_revision = '0005_collaboration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('scheduled_workflows',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('schedule_key', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('workflow_type', sa.String(length=60), nullable=False),
    sa.Column('frequency', sa.String(length=20), nullable=False),
    sa.Column('time_of_day', sa.String(length=5), nullable=False),
    sa.Column('weekday', sa.Integer(), nullable=True),
    sa.Column('interval_hours', sa.Integer(), nullable=True),
    sa.Column('timezone', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('last_run_at', sa.DateTime(), nullable=True),
    sa.Column('next_run_at', sa.DateTime(), nullable=True),
    sa.Column('last_status', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_scheduled_workflows')),
    sa.UniqueConstraint('schedule_key', name='uq_scheduled_workflows_schedule_key')
    )
    with op.batch_alter_table('scheduled_workflows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_scheduled_workflows_next_run_at'), ['next_run_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_scheduled_workflows_schedule_key'), ['schedule_key'], unique=False)

    op.create_table('workflow_dead_letters',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source', sa.String(length=40), nullable=False),
    sa.Column('reference', sa.String(length=160), nullable=True),
    sa.Column('event_type', sa.String(length=60), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_dead_letters'))
    )
    with op.batch_alter_table('workflow_dead_letters', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workflow_dead_letters_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_dead_letters_reference'), ['reference'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_dead_letters_status'), ['status'], unique=False)

    op.create_table('autonomous_workflows',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('workflow_ref', sa.String(length=40), nullable=False),
    sa.Column('workflow_type', sa.String(length=60), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('objective', sa.Text(), nullable=False),
    sa.Column('trigger_type', sa.String(length=20), nullable=False),
    sa.Column('trigger_ref', sa.String(length=120), nullable=True),
    sa.Column('trigger_payload', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('phase', sa.String(length=60), nullable=True),
    sa.Column('requested_by', sa.Integer(), nullable=True),
    sa.Column('current_task_key', sa.String(length=60), nullable=True),
    sa.Column('planned_at', sa.DateTime(), nullable=True),
    sa.Column('scheduled_for', sa.DateTime(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('retry_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('verification', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_autonomous_workflows_requested_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_autonomous_workflows')),
    sa.UniqueConstraint('workflow_ref', name='uq_autonomous_workflows_workflow_ref')
    )
    with op.batch_alter_table('autonomous_workflows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_autonomous_workflows_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_autonomous_workflows_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_autonomous_workflows_scheduled_for'), ['scheduled_for'], unique=False)
        batch_op.create_index(batch_op.f('ix_autonomous_workflows_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_autonomous_workflows_trigger_ref'), ['trigger_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_autonomous_workflows_workflow_ref'), ['workflow_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_autonomous_workflows_workflow_type'), ['workflow_type'], unique=False)

    op.create_table('autonomy_policies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('policy_id', sa.String(length=40), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('action_name', sa.String(length=60), nullable=False),
    sa.Column('display_name', sa.String(length=120), nullable=False),
    sa.Column('execution_mode', sa.String(length=20), nullable=False),
    sa.Column('maximum_amount', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('allowed_roles', sa.JSON(), nullable=True),
    sa.Column('approval_required', sa.Boolean(), nullable=False),
    sa.Column('approval_count', sa.Integer(), nullable=False),
    sa.Column('allow_self_approval', sa.Boolean(), nullable=False),
    sa.Column('daily_execution_limit', sa.Integer(), nullable=True),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_autonomy_policies_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_autonomy_policies')),
    sa.UniqueConstraint('action_name', name='uq_autonomy_policies_action_name')
    )
    with op.batch_alter_table('autonomy_policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_autonomy_policies_action_name'), ['action_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_autonomy_policies_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_autonomy_policies_policy_id'), ['policy_id'], unique=False)

    op.create_table('approval_requests',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('approval_ref', sa.String(length=40), nullable=False),
    sa.Column('workflow_id', sa.Integer(), nullable=True),
    sa.Column('task_key', sa.String(length=60), nullable=True),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('requested_by', sa.Integer(), nullable=True),
    sa.Column('requested_action', sa.String(length=60), nullable=False),
    sa.Column('action_details', sa.JSON(), nullable=True),
    sa.Column('financial_impact', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.Column('decided_at', sa.DateTime(), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('executed_at', sa.DateTime(), nullable=True),
    sa.Column('execution_result', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_approval_requests_decided_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_approval_requests_requested_by_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workflow_id'], ['autonomous_workflows.id'], name=op.f('fk_approval_requests_workflow_id_autonomous_workflows'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_requests')),
    sa.UniqueConstraint('approval_ref', name='uq_approval_requests_approval_ref')
    )
    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_requests_approval_ref'), ['approval_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_expires_at'), ['expires_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_requested_action'), ['requested_action'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_requests_workflow_id'), ['workflow_id'], unique=False)

    op.create_table('workflow_execution_logs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('workflow_id', sa.Integer(), nullable=False),
    sa.Column('task_key', sa.String(length=60), nullable=True),
    sa.Column('level', sa.String(length=10), nullable=False),
    sa.Column('event', sa.String(length=60), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('data', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['autonomous_workflows.id'], name=op.f('fk_workflow_execution_logs_workflow_id_autonomous_workflows'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_execution_logs'))
    )
    with op.batch_alter_table('workflow_execution_logs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workflow_execution_logs_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_execution_logs_event'), ['event'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_execution_logs_workflow_id'), ['workflow_id'], unique=False)

    op.create_table('workflow_idempotency_records',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('idempotency_key', sa.String(length=160), nullable=False),
    sa.Column('workflow_id', sa.Integer(), nullable=True),
    sa.Column('task_key', sa.String(length=60), nullable=True),
    sa.Column('action_name', sa.String(length=60), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['autonomous_workflows.id'], name=op.f('fk_workflow_idempotency_records_workflow_id_autonomous_workflows'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_idempotency_records')),
    sa.UniqueConstraint('idempotency_key', name='uq_workflow_idempotency_records_key')
    )
    with op.batch_alter_table('workflow_idempotency_records', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workflow_idempotency_records_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_idempotency_records_idempotency_key'), ['idempotency_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_idempotency_records_workflow_id'), ['workflow_id'], unique=False)

    op.create_table('workflow_tasks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('workflow_id', sa.Integer(), nullable=False),
    sa.Column('task_key', sa.String(length=60), nullable=False),
    sa.Column('task_type', sa.String(length=40), nullable=False),
    sa.Column('assigned_agent', sa.String(length=60), nullable=True),
    sa.Column('action_name', sa.String(length=60), nullable=True),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('input_data', sa.JSON(), nullable=True),
    sa.Column('dependencies', sa.JSON(), nullable=True),
    sa.Column('execution_status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('retry_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('max_retries', sa.Integer(), server_default=sa.text('2'), nullable=False),
    sa.Column('idempotency_key', sa.String(length=160), nullable=False),
    sa.Column('permission_required', sa.String(length=60), nullable=True),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error_details', sa.Text(), nullable=True),
    sa.Column('execution_ms', sa.Float(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['workflow_id'], ['autonomous_workflows.id'], name=op.f('fk_workflow_tasks_workflow_id_autonomous_workflows'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_tasks')),
    sa.UniqueConstraint('idempotency_key', name='uq_workflow_tasks_idempotency_key')
    )
    with op.batch_alter_table('workflow_tasks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workflow_tasks_action_name'), ['action_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_tasks_assigned_agent'), ['assigned_agent'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_tasks_execution_status'), ['execution_status'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_tasks_task_key'), ['task_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_tasks_task_type'), ['task_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_tasks_workflow_id'), ['workflow_id'], unique=False)

    op.create_table('workflow_triggers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('trigger_key', sa.String(length=160), nullable=False),
    sa.Column('trigger_type', sa.String(length=20), nullable=False),
    sa.Column('event_type', sa.String(length=60), nullable=True),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('workflow_type', sa.String(length=60), nullable=False),
    sa.Column('workflow_id', sa.Integer(), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['event_id'], ['business_events.id'], name=op.f('fk_workflow_triggers_event_id_business_events'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['workflow_id'], ['autonomous_workflows.id'], name=op.f('fk_workflow_triggers_workflow_id_autonomous_workflows'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workflow_triggers')),
    sa.UniqueConstraint('trigger_key', name='uq_workflow_triggers_trigger_key')
    )
    with op.batch_alter_table('workflow_triggers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workflow_triggers_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_triggers_event_type'), ['event_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_triggers_trigger_key'), ['trigger_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_workflow_triggers_trigger_type'), ['trigger_type'], unique=False)

    op.create_table('approval_decisions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('approval_id', sa.Integer(), nullable=False),
    sa.Column('decision', sa.String(length=20), nullable=False),
    sa.Column('decided_by', sa.Integer(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['approval_id'], ['approval_requests.id'], name=op.f('fk_approval_decisions_approval_id_approval_requests'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['decided_by'], ['users.id'], name=op.f('fk_approval_decisions_decided_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_decisions'))
    )
    with op.batch_alter_table('approval_decisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approval_decisions_approval_id'), ['approval_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_decisions_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_approval_decisions_decision'), ['decision'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('approval_decisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approval_decisions_decision'))
        batch_op.drop_index(batch_op.f('ix_approval_decisions_created_at'))
        batch_op.drop_index(batch_op.f('ix_approval_decisions_approval_id'))

    op.drop_table('approval_decisions')
    with op.batch_alter_table('workflow_triggers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workflow_triggers_trigger_type'))
        batch_op.drop_index(batch_op.f('ix_workflow_triggers_trigger_key'))
        batch_op.drop_index(batch_op.f('ix_workflow_triggers_event_type'))
        batch_op.drop_index(batch_op.f('ix_workflow_triggers_created_at'))

    op.drop_table('workflow_triggers')
    with op.batch_alter_table('workflow_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workflow_tasks_workflow_id'))
        batch_op.drop_index(batch_op.f('ix_workflow_tasks_task_type'))
        batch_op.drop_index(batch_op.f('ix_workflow_tasks_task_key'))
        batch_op.drop_index(batch_op.f('ix_workflow_tasks_execution_status'))
        batch_op.drop_index(batch_op.f('ix_workflow_tasks_assigned_agent'))
        batch_op.drop_index(batch_op.f('ix_workflow_tasks_action_name'))

    op.drop_table('workflow_tasks')
    with op.batch_alter_table('workflow_idempotency_records', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workflow_idempotency_records_workflow_id'))
        batch_op.drop_index(batch_op.f('ix_workflow_idempotency_records_idempotency_key'))
        batch_op.drop_index(batch_op.f('ix_workflow_idempotency_records_created_at'))

    op.drop_table('workflow_idempotency_records')
    with op.batch_alter_table('workflow_execution_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workflow_execution_logs_workflow_id'))
        batch_op.drop_index(batch_op.f('ix_workflow_execution_logs_event'))
        batch_op.drop_index(batch_op.f('ix_workflow_execution_logs_created_at'))

    op.drop_table('workflow_execution_logs')
    with op.batch_alter_table('approval_requests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approval_requests_workflow_id'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_status'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_requested_action'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_expires_at'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_created_at'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_business_id'))
        batch_op.drop_index(batch_op.f('ix_approval_requests_approval_ref'))

    op.drop_table('approval_requests')
    with op.batch_alter_table('autonomy_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_autonomy_policies_policy_id'))
        batch_op.drop_index(batch_op.f('ix_autonomy_policies_business_id'))
        batch_op.drop_index(batch_op.f('ix_autonomy_policies_action_name'))

    op.drop_table('autonomy_policies')
    with op.batch_alter_table('autonomous_workflows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_autonomous_workflows_workflow_type'))
        batch_op.drop_index(batch_op.f('ix_autonomous_workflows_workflow_ref'))
        batch_op.drop_index(batch_op.f('ix_autonomous_workflows_trigger_ref'))
        batch_op.drop_index(batch_op.f('ix_autonomous_workflows_status'))
        batch_op.drop_index(batch_op.f('ix_autonomous_workflows_scheduled_for'))
        batch_op.drop_index(batch_op.f('ix_autonomous_workflows_created_at'))
        batch_op.drop_index(batch_op.f('ix_autonomous_workflows_business_id'))

    op.drop_table('autonomous_workflows')
    with op.batch_alter_table('workflow_dead_letters', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workflow_dead_letters_status'))
        batch_op.drop_index(batch_op.f('ix_workflow_dead_letters_reference'))
        batch_op.drop_index(batch_op.f('ix_workflow_dead_letters_created_at'))

    op.drop_table('workflow_dead_letters')
    with op.batch_alter_table('scheduled_workflows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_scheduled_workflows_schedule_key'))
        batch_op.drop_index(batch_op.f('ix_scheduled_workflows_next_run_at'))

    op.drop_table('scheduled_workflows')
