"""Add versioned knowledge embedding spaces and durable indexing jobs.

Revision ID: 0097
Revises: 0096
"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

revision = '0097'
down_revision = '0096'
branch_labels = None
depends_on = None


def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('knowledge_index_generation',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id', ondelete='CASCADE'), nullable=False),
        sa.Column('embedding_revision_id', sa.Integer(), sa.ForeignKey('model_revision.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('dimension', sa.Integer(), nullable=False),
        sa.Column('distance', sa.String(16), nullable=False),
        sa.Column('encoding_version', sa.String(200), nullable=False),
        sa.Column('document_input_type', sa.String(100)), sa.Column('query_input_type', sa.String(100)),
        sa.Column('state', sa.String(20), nullable=False, server_default='BUILDING'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('dimension > 0', name='ck_knowledge_generation_dimension'),
        sa.CheckConstraint("distance IN ('cosine', 'l2', 'inner_product')", name='ck_knowledge_generation_distance'))
    op.create_index('ix_knowledge_index_generation_project_id', 'knowledge_index_generation', ['project_id'])
    op.create_table('knowledge_retrieval_config',
        sa.Column('project_id', sa.Integer(), sa.ForeignKey('project.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('active_generation_id', sa.Integer(), sa.ForeignKey('knowledge_index_generation.id', ondelete='SET NULL')),
        sa.Column('rerank_revision_id', sa.Integer(), sa.ForeignKey('model_revision.id', ondelete='RESTRICT')),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('bm25_candidates', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('vector_candidates', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('rerank_window', sa.Integer(), nullable=False, server_default='30'),
        sa.Column('default_top_k', sa.Integer(), nullable=False, server_default='8'),
        sa.Column('timeout_seconds', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('fusion_min_score', sa.Float()), sa.Column('rerank_min_score', sa.Float()))
    op.create_table('knowledge_vector',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('generation_id', sa.Integer(), sa.ForeignKey('knowledge_index_generation.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_id', sa.Integer(), sa.ForeignKey('knowledge_chunk.id', ondelete='CASCADE'), nullable=False),
        sa.Column('embedding', Vector(), nullable=False),
        sa.UniqueConstraint('generation_id', 'chunk_id', name='uq_knowledge_vector_generation_chunk'))
    op.create_index('ix_knowledge_vector_generation_id', 'knowledge_vector', ['generation_id'])
    op.create_index('ix_knowledge_vector_chunk_id', 'knowledge_vector', ['chunk_id'])
    op.create_table('knowledge_index_job',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('generation_id', sa.Integer(), sa.ForeignKey('knowledge_index_generation.id', ondelete='CASCADE'), nullable=False),
        sa.Column('chunk_id', sa.Integer(), sa.ForeignKey('knowledge_chunk.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(20), nullable=False, server_default='QUEUED'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True)),
        sa.Column('lease_token', sa.String(64)), sa.Column('lease_until', sa.DateTime(timezone=True)),
        sa.Column('error', sa.String(200)),
        sa.UniqueConstraint('generation_id', 'chunk_id', name='uq_knowledge_index_job_generation_chunk'))
    for col in ('generation_id', 'chunk_id', 'status'):
        op.create_index(f'ix_knowledge_index_job_{col}', 'knowledge_index_job', [col])


def downgrade():
    op.drop_table('knowledge_index_job')
    op.drop_table('knowledge_vector')
    op.drop_table('knowledge_retrieval_config')
    op.drop_table('knowledge_index_generation')
