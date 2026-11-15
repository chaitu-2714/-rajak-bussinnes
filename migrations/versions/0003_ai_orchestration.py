"""Phase 3: AI orchestration tables

Revision ID: 0003_ai_orchestration
Revises: 0002_core_business
Create Date: 2026-11-04 02:52:11.992766

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0003_ai_orchestration'
down_revision = '0002_core_business'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('ai_model_settings',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model_name', sa.String(length=80), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('priority', sa.Integer(), nullable=False),
    sa.Column('configuration', sa.JSON(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_model_settings')),
    sa.UniqueConstraint('provider', name='uq_ai_model_settings_provider')
    )
    with op.batch_alter_table('ai_model_settings', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_model_settings_provider'), ['provider'], unique=False)

    op.create_table('ai_tool_registry',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('tool_name', sa.String(length=80), nullable=False),
    sa.Column('description', sa.String(length=255), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=True),
    sa.Column('required_permission', sa.String(length=64), nullable=False),
    sa.Column('risk_level', sa.String(length=20), nullable=False),
    sa.Column('is_enabled', sa.Boolean(), server_default=sa.text('1'), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_tool_registry')),
    sa.UniqueConstraint('tool_name', name='uq_ai_tool_registry_tool_name')
    )
    with op.batch_alter_table('ai_tool_registry', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_tool_registry_tool_name'), ['tool_name'], unique=False)

    op.create_table('ai_conversations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=160), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_conversations_user_id_users'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_conversations'))
    )
    with op.batch_alter_table('ai_conversations', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_conversations_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_conversations_user_id'), ['user_id'], unique=False)

    op.create_table('ai_messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('sender_type', sa.String(length=16), nullable=False),
    sa.Column('message_content', sa.Text(), nullable=False),
    sa.Column('metadata', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['ai_conversations.id'], name=op.f('fk_ai_messages_conversation_id_ai_conversations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_messages'))
    )
    with op.batch_alter_table('ai_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_messages_conversation_id'), ['conversation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_messages_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_messages_sender_type'), ['sender_type'], unique=False)

    op.create_table('ai_workflows',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('workflow_id', sa.String(length=40), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('intent', sa.String(length=60), nullable=False),
    sa.Column('command', sa.Text(), nullable=True),
    sa.Column('execution_plan', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=30), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('current_step', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('trigger_type', sa.String(length=20), server_default=sa.text("'COMMAND'"), nullable=False),
    sa.Column('source_event_id', sa.Integer(), nullable=True),
    sa.Column('provider', sa.String(length=30), nullable=True),
    sa.Column('result', sa.JSON(), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['ai_conversations.id'], name=op.f('fk_ai_workflows_conversation_id_ai_conversations'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['source_event_id'], ['business_events.id'], name=op.f('fk_ai_workflows_source_event_id_business_events'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_ai_workflows_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_workflows')),
    sa.UniqueConstraint('source_event_id', name='uq_ai_workflows_source_event_id'),
    sa.UniqueConstraint('workflow_id', name='uq_ai_workflows_workflow_id')
    )
    with op.batch_alter_table('ai_workflows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_workflows_conversation_id'), ['conversation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_workflows_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_workflows_intent'), ['intent'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_workflows_source_event_id'), ['source_event_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_workflows_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_workflows_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_workflows_workflow_id'), ['workflow_id'], unique=False)

    op.create_table('ai_workflow_steps',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('workflow_id', sa.Integer(), nullable=False),
    sa.Column('step_number', sa.Integer(), nullable=False),
    sa.Column('tool_name', sa.String(length=80), nullable=False),
    sa.Column('required_permission', sa.String(length=64), nullable=True),
    sa.Column('risk_level', sa.String(length=20), nullable=True),
    sa.Column('input_data', sa.JSON(), nullable=True),
    sa.Column('output_data', sa.JSON(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['workflow_id'], ['ai_workflows.id'], name=op.f('fk_ai_workflow_steps_workflow_id_ai_workflows'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_ai_workflow_steps')),
    sa.UniqueConstraint('workflow_id', 'step_number', name='uq_ai_workflow_steps_workflow_step')
    )
    with op.batch_alter_table('ai_workflow_steps', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_ai_workflow_steps_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_workflow_steps_tool_name'), ['tool_name'], unique=False)
        batch_op.create_index(batch_op.f('ix_ai_workflow_steps_workflow_id'), ['workflow_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('ai_workflow_steps', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_workflow_steps_workflow_id'))
        batch_op.drop_index(batch_op.f('ix_ai_workflow_steps_tool_name'))
        batch_op.drop_index(batch_op.f('ix_ai_workflow_steps_status'))

    op.drop_table('ai_workflow_steps')
    with op.batch_alter_table('ai_workflows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_workflows_workflow_id'))
        batch_op.drop_index(batch_op.f('ix_ai_workflows_user_id'))
        batch_op.drop_index(batch_op.f('ix_ai_workflows_status'))
        batch_op.drop_index(batch_op.f('ix_ai_workflows_source_event_id'))
        batch_op.drop_index(batch_op.f('ix_ai_workflows_intent'))
        batch_op.drop_index(batch_op.f('ix_ai_workflows_created_at'))
        batch_op.drop_index(batch_op.f('ix_ai_workflows_conversation_id'))

    op.drop_table('ai_workflows')
    with op.batch_alter_table('ai_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_messages_sender_type'))
        batch_op.drop_index(batch_op.f('ix_ai_messages_created_at'))
        batch_op.drop_index(batch_op.f('ix_ai_messages_conversation_id'))

    op.drop_table('ai_messages')
    with op.batch_alter_table('ai_conversations', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_conversations_user_id'))
        batch_op.drop_index(batch_op.f('ix_ai_conversations_created_at'))

    op.drop_table('ai_conversations')
    with op.batch_alter_table('ai_tool_registry', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_tool_registry_tool_name'))

    op.drop_table('ai_tool_registry')
    with op.batch_alter_table('ai_model_settings', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_ai_model_settings_provider'))

    op.drop_table('ai_model_settings')
