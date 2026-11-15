"""Phase 5: multi-agent collaboration tables

Revision ID: 0005_collaboration
Revises: 0004_agent_tables
Create Date: 2026-11-04 05:02:08.469315

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0005_collaboration'
down_revision = '0004_agent_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('agent_collaborations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collaboration_id', sa.String(length=40), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('objective', sa.Text(), nullable=False),
    sa.Column('scenario', sa.String(length=60), nullable=False),
    sa.Column('strategy', sa.String(length=40), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('reporting_period', sa.String(length=40), nullable=True),
    sa.Column('shared_context', sa.JSON(), nullable=True),
    sa.Column('phase', sa.String(length=40), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_agent_collaborations_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_collaborations')),
    sa.UniqueConstraint('collaboration_id', name='uq_agent_collaborations_collaboration_id')
    )
    with op.batch_alter_table('agent_collaborations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_collaborations_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_collaborations_collaboration_id'), ['collaboration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_collaborations_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_collaborations_scenario'), ['scenario'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_collaborations_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_collaborations_user_id'), ['user_id'], unique=False)

    op.create_table('collaboration_checkpoints',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collaboration_id', sa.Integer(), nullable=False),
    sa.Column('phase', sa.String(length=40), nullable=False),
    sa.Column('state', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['collaboration_id'], ['agent_collaborations.id'], name=op.f('fk_collaboration_checkpoints_collaboration_id_agent_collaborations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collaboration_checkpoints'))
    )
    with op.batch_alter_table('collaboration_checkpoints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_collaboration_checkpoints_collaboration_id'), ['collaboration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_checkpoints_created_at'), ['created_at'], unique=False)

    op.create_table('collaboration_conflicts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collaboration_id', sa.Integer(), nullable=False),
    sa.Column('conflict_id', sa.String(length=40), nullable=False),
    sa.Column('conflict_type', sa.String(length=40), nullable=False),
    sa.Column('agents', sa.JSON(), nullable=True),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('resolution', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['collaboration_id'], ['agent_collaborations.id'], name=op.f('fk_collaboration_conflicts_collaboration_id_agent_collaborations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collaboration_conflicts'))
    )
    with op.batch_alter_table('collaboration_conflicts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_collaboration_conflicts_collaboration_id'), ['collaboration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_conflicts_conflict_id'), ['conflict_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_conflicts_conflict_type'), ['conflict_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_conflicts_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_conflicts_status'), ['status'], unique=False)

    op.create_table('collaboration_decisions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collaboration_id', sa.Integer(), nullable=False),
    sa.Column('executive_summary', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('generated_at', sa.DateTime(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['collaboration_id'], ['agent_collaborations.id'], name=op.f('fk_collaboration_decisions_collaboration_id_agent_collaborations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collaboration_decisions')),
    sa.UniqueConstraint('collaboration_id', name='uq_collaboration_decisions_collaboration_id')
    )
    with op.batch_alter_table('collaboration_decisions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_collaboration_decisions_collaboration_id'), ['collaboration_id'], unique=False)

    op.create_table('collaboration_dependencies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collaboration_id', sa.Integer(), nullable=False),
    sa.Column('task_key', sa.String(length=60), nullable=False),
    sa.Column('depends_on_key', sa.String(length=60), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['collaboration_id'], ['agent_collaborations.id'], name=op.f('fk_collaboration_dependencies_collaboration_id_agent_collaborations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collaboration_dependencies')),
    sa.UniqueConstraint('collaboration_id', 'task_key', 'depends_on_key', name='uq_collaboration_dependencies_edge')
    )
    with op.batch_alter_table('collaboration_dependencies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_collaboration_dependencies_collaboration_id'), ['collaboration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_dependencies_task_key'), ['task_key'], unique=False)

    op.create_table('collaboration_findings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collaboration_id', sa.Integer(), nullable=False),
    sa.Column('task_key', sa.String(length=60), nullable=False),
    sa.Column('agent_id', sa.String(length=60), nullable=False),
    sa.Column('finding_type', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('evidence', sa.JSON(), nullable=True),
    sa.Column('reporting_period', sa.String(length=80), nullable=True),
    sa.Column('validation_status', sa.String(length=20), nullable=False),
    sa.Column('validation_issues', sa.JSON(), nullable=True),
    sa.Column('source_execution_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['collaboration_id'], ['agent_collaborations.id'], name=op.f('fk_collaboration_findings_collaboration_id_agent_collaborations'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_execution_id'], ['agent_executions.id'], name=op.f('fk_collaboration_findings_source_execution_id_agent_executions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collaboration_findings'))
    )
    with op.batch_alter_table('collaboration_findings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_collaboration_findings_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_findings_collaboration_id'), ['collaboration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_findings_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_findings_finding_type'), ['finding_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_findings_severity'), ['severity'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_findings_task_key'), ['task_key'], unique=False)

    op.create_table('collaboration_messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collaboration_id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.String(length=40), nullable=False),
    sa.Column('sender_agent', sa.String(length=60), nullable=False),
    sa.Column('receiver_agent', sa.String(length=60), nullable=False),
    sa.Column('message_type', sa.String(length=40), nullable=False),
    sa.Column('task_key', sa.String(length=60), nullable=True),
    sa.Column('payload', sa.JSON(), nullable=True),
    sa.Column('evidence_refs', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['collaboration_id'], ['agent_collaborations.id'], name=op.f('fk_collaboration_messages_collaboration_id_agent_collaborations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collaboration_messages')),
    sa.UniqueConstraint('message_id', name='uq_collaboration_messages_message_id')
    )
    with op.batch_alter_table('collaboration_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_collaboration_messages_collaboration_id'), ['collaboration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_messages_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_messages_message_id'), ['message_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_messages_message_type'), ['message_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_messages_receiver_agent'), ['receiver_agent'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_messages_sender_agent'), ['sender_agent'], unique=False)

    op.create_table('collaboration_tasks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collaboration_id', sa.Integer(), nullable=False),
    sa.Column('task_key', sa.String(length=60), nullable=False),
    sa.Column('parent_task_key', sa.String(length=60), nullable=True),
    sa.Column('assigned_agent', sa.String(length=60), nullable=False),
    sa.Column('task_type', sa.String(length=60), nullable=False),
    sa.Column('objective', sa.Text(), nullable=False),
    sa.Column('input_context', sa.JSON(), nullable=True),
    sa.Column('priority', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('idempotency_key', sa.String(length=120), nullable=False),
    sa.Column('agent_execution_id', sa.Integer(), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('execution_ms', sa.Float(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['agent_execution_id'], ['agent_executions.id'], name=op.f('fk_collaboration_tasks_agent_execution_id_agent_executions'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['collaboration_id'], ['agent_collaborations.id'], name=op.f('fk_collaboration_tasks_collaboration_id_agent_collaborations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_collaboration_tasks')),
    sa.UniqueConstraint('idempotency_key', name='uq_collaboration_tasks_idempotency_key')
    )
    with op.batch_alter_table('collaboration_tasks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_collaboration_tasks_assigned_agent'), ['assigned_agent'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_tasks_collaboration_id'), ['collaboration_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_tasks_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_collaboration_tasks_task_key'), ['task_key'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('collaboration_tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collaboration_tasks_task_key'))
        batch_op.drop_index(batch_op.f('ix_collaboration_tasks_status'))
        batch_op.drop_index(batch_op.f('ix_collaboration_tasks_collaboration_id'))
        batch_op.drop_index(batch_op.f('ix_collaboration_tasks_assigned_agent'))

    op.drop_table('collaboration_tasks')
    with op.batch_alter_table('collaboration_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collaboration_messages_sender_agent'))
        batch_op.drop_index(batch_op.f('ix_collaboration_messages_receiver_agent'))
        batch_op.drop_index(batch_op.f('ix_collaboration_messages_message_type'))
        batch_op.drop_index(batch_op.f('ix_collaboration_messages_message_id'))
        batch_op.drop_index(batch_op.f('ix_collaboration_messages_created_at'))
        batch_op.drop_index(batch_op.f('ix_collaboration_messages_collaboration_id'))

    op.drop_table('collaboration_messages')
    with op.batch_alter_table('collaboration_findings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collaboration_findings_task_key'))
        batch_op.drop_index(batch_op.f('ix_collaboration_findings_severity'))
        batch_op.drop_index(batch_op.f('ix_collaboration_findings_finding_type'))
        batch_op.drop_index(batch_op.f('ix_collaboration_findings_created_at'))
        batch_op.drop_index(batch_op.f('ix_collaboration_findings_collaboration_id'))
        batch_op.drop_index(batch_op.f('ix_collaboration_findings_agent_id'))

    op.drop_table('collaboration_findings')
    with op.batch_alter_table('collaboration_dependencies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collaboration_dependencies_task_key'))
        batch_op.drop_index(batch_op.f('ix_collaboration_dependencies_collaboration_id'))

    op.drop_table('collaboration_dependencies')
    with op.batch_alter_table('collaboration_decisions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collaboration_decisions_collaboration_id'))

    op.drop_table('collaboration_decisions')
    with op.batch_alter_table('collaboration_conflicts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collaboration_conflicts_status'))
        batch_op.drop_index(batch_op.f('ix_collaboration_conflicts_created_at'))
        batch_op.drop_index(batch_op.f('ix_collaboration_conflicts_conflict_type'))
        batch_op.drop_index(batch_op.f('ix_collaboration_conflicts_collaboration_id'))

    op.drop_table('collaboration_conflicts')
    with op.batch_alter_table('collaboration_checkpoints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_collaboration_checkpoints_created_at'))
        batch_op.drop_index(batch_op.f('ix_collaboration_checkpoints_collaboration_id'))

    op.drop_table('collaboration_checkpoints')
    with op.batch_alter_table('agent_collaborations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_collaborations_user_id'))
        batch_op.drop_index(batch_op.f('ix_agent_collaborations_status'))
        batch_op.drop_index(batch_op.f('ix_agent_collaborations_scenario'))
        batch_op.drop_index(batch_op.f('ix_agent_collaborations_created_at'))
        batch_op.drop_index(batch_op.f('ix_agent_collaborations_collaboration_id'))
        batch_op.drop_index(batch_op.f('ix_agent_collaborations_business_id'))

    op.drop_table('agent_collaborations')
