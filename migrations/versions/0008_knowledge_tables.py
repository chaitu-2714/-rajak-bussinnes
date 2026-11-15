"""Phase 8: knowledge documents, chunks, extraction and RAG tables

Revision ID: 0008_knowledge
Revises: 0007_analytics
Create Date: 2026-11-04 08:21:02.558162

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '0008_knowledge'
down_revision = '0007_analytics'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('embedding_model_registry',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('model_id', sa.String(length=120), nullable=False),
    sa.Column('provider', sa.String(length=40), nullable=False),
    sa.Column('dimension', sa.Integer(), nullable=False),
    sa.Column('version', sa.String(length=20), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('indexed_chunks', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('registered_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_embedding_model_registry')),
    sa.UniqueConstraint('model_id', name='uq_embedding_model_registry_id')
    )
    with op.batch_alter_table('embedding_model_registry', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_embedding_model_registry_model_id'), ['model_id'], unique=False)

    op.create_table('hybrid_ai_usage',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('task', sa.String(length=40), nullable=False),
    sa.Column('policy', sa.String(length=30), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('success', sa.Boolean(), nullable=False),
    sa.Column('fallback_used', sa.Boolean(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('prompt_chars', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_hybrid_ai_usage'))
    )
    with op.batch_alter_table('hybrid_ai_usage', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_hybrid_ai_usage_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_hybrid_ai_usage_provider'), ['provider'], unique=False)
        batch_op.create_index(batch_op.f('ix_hybrid_ai_usage_task'), ['task'], unique=False)

    op.create_table('knowledge_collections',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('collection_key', sa.String(length=60), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_collections')),
    sa.UniqueConstraint('collection_key', name='uq_knowledge_collections_key')
    )
    with op.batch_alter_table('knowledge_collections', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_knowledge_collections_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_collections_collection_key'), ['collection_key'], unique=False)

    op.create_table('knowledge_access_policies',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('scope', sa.String(length=20), nullable=False),
    sa.Column('scope_value', sa.String(length=60), nullable=False),
    sa.Column('allowed_roles', sa.JSON(), nullable=True),
    sa.Column('restricted', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_knowledge_access_policies_created_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_access_policies'))
    )
    with op.batch_alter_table('knowledge_access_policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_knowledge_access_policies_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_access_policies_scope_value'), ['scope_value'], unique=False)

    op.create_table('knowledge_documents',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_ref', sa.String(length=40), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('file_type', sa.String(length=20), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('storage_path', sa.String(length=500), nullable=False),
    sa.Column('category', sa.String(length=40), nullable=False),
    sa.Column('category_source', sa.String(length=20), nullable=False),
    sa.Column('collection_key', sa.String(length=60), nullable=True),
    sa.Column('status', sa.String(length=20), server_default=sa.text("'PENDING'"), nullable=False),
    sa.Column('processing_stage', sa.String(length=40), nullable=True),
    sa.Column('ocr_status', sa.String(length=20), nullable=False),
    sa.Column('index_status', sa.String(length=20), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('word_count', sa.Integer(), nullable=False),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('current_version', sa.Integer(), nullable=False),
    sa.Column('version_count', sa.Integer(), nullable=False),
    sa.Column('is_restricted', sa.Boolean(), nullable=False),
    sa.Column('allowed_roles', sa.JSON(), nullable=True),
    sa.Column('allowed_user_ids', sa.JSON(), nullable=True),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('extracted_text', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('metadata_json', sa.JSON(), nullable=True),
    sa.Column('embedding_model', sa.String(length=80), nullable=True),
    sa.Column('is_archived', sa.Boolean(), nullable=False),
    sa.Column('is_deleted', sa.Boolean(), nullable=False),
    sa.Column('processed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_knowledge_documents_uploaded_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_documents')),
    sa.UniqueConstraint('document_ref', name='uq_knowledge_documents_ref')
    )
    with op.batch_alter_table('knowledge_documents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_knowledge_documents_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_category'), ['category'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_collection_key'), ['collection_key'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_content_hash'), ['content_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_document_ref'), ['document_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_file_type'), ['file_type'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_is_archived'), ['is_archived'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_is_deleted'), ['is_deleted'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_documents_status'), ['status'], unique=False)

    op.create_table('knowledge_search_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('query', sa.Text(), nullable=False),
    sa.Column('mode', sa.String(length=20), nullable=False),
    sa.Column('result_count', sa.Integer(), nullable=False),
    sa.Column('filters', sa.JSON(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_knowledge_search_history_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_search_history'))
    )
    with op.batch_alter_table('knowledge_search_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_knowledge_search_history_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_search_history_created_at'), ['created_at'], unique=False)

    op.create_table('rag_query_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('query_ref', sa.String(length=40), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('question', sa.Text(), nullable=False),
    sa.Column('mode', sa.String(length=30), nullable=False),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('grounded', sa.Boolean(), nullable=False),
    sa.Column('evidence_status', sa.String(length=20), nullable=False),
    sa.Column('provider', sa.String(length=30), nullable=False),
    sa.Column('model', sa.String(length=80), nullable=False),
    sa.Column('chunks_used', sa.Integer(), nullable=False),
    sa.Column('business_records', sa.Integer(), nullable=False),
    sa.Column('latency_ms', sa.Integer(), nullable=False),
    sa.Column('limitations', sa.JSON(), nullable=True),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_rag_query_history_user_id_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rag_query_history'))
    )
    with op.batch_alter_table('rag_query_history', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rag_query_history_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_rag_query_history_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_rag_query_history_query_ref'), ['query_ref'], unique=False)

    op.create_table('document_chunks',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('chunk_id', sa.String(length=60), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('business_id', sa.Integer(), nullable=True),
    sa.Column('document_version', sa.Integer(), nullable=False),
    sa.Column('chunk_index', sa.Integer(), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('section_heading', sa.String(length=200), nullable=True),
    sa.Column('source_file', sa.String(length=255), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('token_count', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], name=op.f('fk_document_chunks_document_id_knowledge_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_chunks')),
    sa.UniqueConstraint('chunk_id', name='uq_document_chunks_id')
    )
    with op.batch_alter_table('document_chunks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_chunks_business_id'), ['business_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_chunks_chunk_id'), ['chunk_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_chunks_content_hash'), ['content_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_chunks_document_id'), ['document_id'], unique=False)

    op.create_table('document_entities',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('entity_type', sa.String(length=30), nullable=False),
    sa.Column('entity_value', sa.String(length=200), nullable=False),
    sa.Column('resolved_entity_id', sa.Integer(), nullable=True),
    sa.Column('match_confidence', sa.Float(), nullable=True),
    sa.Column('needs_review', sa.Boolean(), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], name=op.f('fk_document_entities_document_id_knowledge_documents'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_entities'))
    )
    with op.batch_alter_table('document_entities', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_entities_document_id'), ['document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_entities_entity_type'), ['entity_type'], unique=False)

    op.create_table('document_extraction_results',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('document_type', sa.String(length=40), nullable=False),
    sa.Column('field_name', sa.String(length=80), nullable=False),
    sa.Column('field_value', sa.Text(), nullable=True),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('location', sa.String(length=120), nullable=True),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('validation_status', sa.String(length=20), nullable=False),
    sa.Column('verified_by', sa.Integer(), nullable=True),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.Column('evidence', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], name=op.f('fk_document_extraction_results_document_id_knowledge_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['verified_by'], ['users.id'], name=op.f('fk_document_extraction_results_verified_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_document_extraction_results'))
    )
    with op.batch_alter_table('document_extraction_results', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_document_extraction_results_document_id'), ['document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_document_extraction_results_field_name'), ['field_name'], unique=False)

    op.create_table('knowledge_document_versions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('file_name', sa.String(length=255), nullable=False),
    sa.Column('storage_path', sa.String(length=500), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('file_size', sa.Integer(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('chunk_count', sa.Integer(), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], name=op.f('fk_knowledge_document_versions_document_id_knowledge_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], name=op.f('fk_knowledge_document_versions_uploaded_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_document_versions')),
    sa.UniqueConstraint('document_id', 'version', name='uq_knowledge_document_versions')
    )
    with op.batch_alter_table('knowledge_document_versions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_knowledge_document_versions_document_id'), ['document_id'], unique=False)

    op.create_table('knowledge_processing_jobs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('job_ref', sa.String(length=40), nullable=False),
    sa.Column('document_id', sa.Integer(), nullable=True),
    sa.Column('job_type', sa.String(length=30), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('stage', sa.String(length=40), nullable=True),
    sa.Column('progress', sa.Integer(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('requested_by', sa.Integer(), nullable=True),
    sa.Column('started_at', sa.DateTime(), nullable=True),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['document_id'], ['knowledge_documents.id'], name=op.f('fk_knowledge_processing_jobs_document_id_knowledge_documents'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name=op.f('fk_knowledge_processing_jobs_requested_by_users'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_knowledge_processing_jobs'))
    )
    with op.batch_alter_table('knowledge_processing_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_knowledge_processing_jobs_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_processing_jobs_document_id'), ['document_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_processing_jobs_job_ref'), ['job_ref'], unique=False)
        batch_op.create_index(batch_op.f('ix_knowledge_processing_jobs_status'), ['status'], unique=False)

    op.create_table('rag_source_references',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('query_id', sa.Integer(), nullable=False),
    sa.Column('document_ref', sa.String(length=40), nullable=False),
    sa.Column('document_title', sa.String(length=200), nullable=False),
    sa.Column('chunk_id', sa.String(length=60), nullable=False),
    sa.Column('page_number', sa.Integer(), nullable=True),
    sa.Column('section_heading', sa.String(length=200), nullable=True),
    sa.Column('excerpt', sa.Text(), nullable=False),
    sa.Column('similarity', sa.Float(), nullable=True),
    sa.Column('source_type', sa.String(length=20), nullable=False),
    sa.ForeignKeyConstraint(['query_id'], ['rag_query_history.id'], name=op.f('fk_rag_source_references_query_id_rag_query_history'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_rag_source_references'))
    )
    with op.batch_alter_table('rag_source_references', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_rag_source_references_query_id'), ['query_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('rag_source_references', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rag_source_references_query_id'))

    op.drop_table('rag_source_references')
    with op.batch_alter_table('knowledge_processing_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_processing_jobs_status'))
        batch_op.drop_index(batch_op.f('ix_knowledge_processing_jobs_job_ref'))
        batch_op.drop_index(batch_op.f('ix_knowledge_processing_jobs_document_id'))
        batch_op.drop_index(batch_op.f('ix_knowledge_processing_jobs_created_at'))

    op.drop_table('knowledge_processing_jobs')
    with op.batch_alter_table('knowledge_document_versions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_document_versions_document_id'))

    op.drop_table('knowledge_document_versions')
    with op.batch_alter_table('document_extraction_results', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_extraction_results_field_name'))
        batch_op.drop_index(batch_op.f('ix_document_extraction_results_document_id'))

    op.drop_table('document_extraction_results')
    with op.batch_alter_table('document_entities', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_entities_entity_type'))
        batch_op.drop_index(batch_op.f('ix_document_entities_document_id'))

    op.drop_table('document_entities')
    with op.batch_alter_table('document_chunks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_document_chunks_document_id'))
        batch_op.drop_index(batch_op.f('ix_document_chunks_content_hash'))
        batch_op.drop_index(batch_op.f('ix_document_chunks_chunk_id'))
        batch_op.drop_index(batch_op.f('ix_document_chunks_business_id'))

    op.drop_table('document_chunks')
    with op.batch_alter_table('rag_query_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_rag_query_history_query_ref'))
        batch_op.drop_index(batch_op.f('ix_rag_query_history_created_at'))
        batch_op.drop_index(batch_op.f('ix_rag_query_history_business_id'))

    op.drop_table('rag_query_history')
    with op.batch_alter_table('knowledge_search_history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_search_history_created_at'))
        batch_op.drop_index(batch_op.f('ix_knowledge_search_history_business_id'))

    op.drop_table('knowledge_search_history')
    with op.batch_alter_table('knowledge_documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_status'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_is_deleted'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_is_archived'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_file_type'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_document_ref'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_created_at'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_content_hash'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_collection_key'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_category'))
        batch_op.drop_index(batch_op.f('ix_knowledge_documents_business_id'))

    op.drop_table('knowledge_documents')
    with op.batch_alter_table('knowledge_access_policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_access_policies_scope_value'))
        batch_op.drop_index(batch_op.f('ix_knowledge_access_policies_business_id'))

    op.drop_table('knowledge_access_policies')
    with op.batch_alter_table('knowledge_collections', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_knowledge_collections_collection_key'))
        batch_op.drop_index(batch_op.f('ix_knowledge_collections_business_id'))

    op.drop_table('knowledge_collections')
    with op.batch_alter_table('hybrid_ai_usage', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_hybrid_ai_usage_task'))
        batch_op.drop_index(batch_op.f('ix_hybrid_ai_usage_provider'))
        batch_op.drop_index(batch_op.f('ix_hybrid_ai_usage_created_at'))

    op.drop_table('hybrid_ai_usage')
    with op.batch_alter_table('embedding_model_registry', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_embedding_model_registry_model_id'))

    op.drop_table('embedding_model_registry')
