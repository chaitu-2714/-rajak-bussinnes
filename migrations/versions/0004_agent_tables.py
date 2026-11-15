"""Phase 4: specialised agent tables

Revision ID: 0004_agent_tables
Revises: 0003_ai_orchestration
Create Date: 2026-11-04 03:54:13.809919

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0004_agent_tables'
down_revision = '0003_ai_orchestration'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('agents',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('agent_code', sa.String(length=60), nullable=False),
    sa.Column('agent_name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agents')),
    sa.UniqueConstraint('agent_code', name='uq_agents_agent_code')
    )
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agents_agent_code'), ['agent_code'], unique=False)

    op.create_table('agent_executions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('workflow_id', sa.String(length=40), nullable=True),
    sa.Column('task_type', sa.String(length=60), nullable=False),
    sa.Column('task_id', sa.String(length=40), nullable=True),
    sa.Column('input_data', sa.JSON(), nullable=True),
    sa.Column('output_data', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('execution_time', sa.Float(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('triggered_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_agent_executions_agent_id_agents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['triggered_by'], ['users.id'], name=op.f('fk_agent_executions_triggered_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_executions'))
    )
    with op.batch_alter_table('agent_executions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_executions_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_executions_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_executions_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_executions_task_type'), ['task_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_executions_triggered_by'), ['triggered_by'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_executions_workflow_id'), ['workflow_id'], unique=False)

    op.create_table('agent_findings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('execution_id', sa.Integer(), nullable=False),
    sa.Column('finding_type', sa.String(length=60), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('severity', sa.String(length=20), nullable=False),
    sa.Column('evidence_data', sa.JSON(), nullable=True),
    sa.Column('reporting_period', sa.String(length=80), nullable=True),
    sa.Column('metric_value', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['execution_id'], ['agent_executions.id'], name=op.f('fk_agent_findings_execution_id_agent_executions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_findings'))
    )
    with op.batch_alter_table('agent_findings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_findings_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_findings_execution_id'), ['execution_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_findings_finding_type'), ['finding_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_findings_severity'), ['severity'], unique=False)

    op.create_table('agent_memory',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('agent_id', sa.Integer(), nullable=False),
    sa.Column('memory_type', sa.String(length=30), nullable=False),
    sa.Column('memory_content', sa.JSON(), nullable=True),
    sa.Column('source_execution_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_agent_memory_agent_id_agents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_execution_id'], ['agent_executions.id'], name=op.f('fk_agent_memory_source_execution_id_agent_executions'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_memory'))
    )
    with op.batch_alter_table('agent_memory', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_memory_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_memory_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_memory_memory_type'), ['memory_type'], unique=False)

    op.create_table('agent_recommendations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('execution_id', sa.Integer(), nullable=False),
    sa.Column('recommendation', sa.Text(), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('priority', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'OPEN'"), nullable=False),
    sa.Column('supporting_data', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['execution_id'], ['agent_executions.id'], name=op.f('fk_agent_recommendations_execution_id_agent_executions'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agent_recommendations'))
    )
    with op.batch_alter_table('agent_recommendations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_recommendations_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_recommendations_execution_id'), ['execution_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_recommendations_priority'), ['priority'], unique=False)
        batch_op.create_index(batch_op.f('ix_agent_recommendations_status'), ['status'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('agent_recommendations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_recommendations_status'))
        batch_op.drop_index(batch_op.f('ix_agent_recommendations_priority'))
        batch_op.drop_index(batch_op.f('ix_agent_recommendations_execution_id'))
        batch_op.drop_index(batch_op.f('ix_agent_recommendations_created_at'))

    op.drop_table('agent_recommendations')
    with op.batch_alter_table('agent_memory', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_memory_memory_type'))
        batch_op.drop_index(batch_op.f('ix_agent_memory_created_at'))
        batch_op.drop_index(batch_op.f('ix_agent_memory_agent_id'))

    op.drop_table('agent_memory')
    with op.batch_alter_table('agent_findings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_findings_severity'))
        batch_op.drop_index(batch_op.f('ix_agent_findings_finding_type'))
        batch_op.drop_index(batch_op.f('ix_agent_findings_execution_id'))
        batch_op.drop_index(batch_op.f('ix_agent_findings_created_at'))

    op.drop_table('agent_findings')
    with op.batch_alter_table('agent_executions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_executions_workflow_id'))
        batch_op.drop_index(batch_op.f('ix_agent_executions_triggered_by'))
        batch_op.drop_index(batch_op.f('ix_agent_executions_task_type'))
        batch_op.drop_index(batch_op.f('ix_agent_executions_status'))
        batch_op.drop_index(batch_op.f('ix_agent_executions_created_at'))
        batch_op.drop_index(batch_op.f('ix_agent_executions_agent_id'))

    op.drop_table('agent_executions')
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agents_agent_code'))

    op.drop_table('agents')
