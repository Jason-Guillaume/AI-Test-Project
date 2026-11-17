"""Add defect attachments."""
from alembic import op
import sqlalchemy as sa

revision = '0090'
down_revision = '0089'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('bug_attachment',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('bug_id', sa.Integer(), sa.ForeignKey('bug.id', ondelete='CASCADE'), nullable=False),
        sa.Column('filename', sa.String(255), nullable=False),
        sa.Column('content_type', sa.String(255), nullable=False),
        sa.Column('content', sa.LargeBinary(), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    op.create_index('ix_bug_attachment_bug_id', 'bug_attachment', ['bug_id'])


def downgrade():
    op.drop_index('ix_bug_attachment_bug_id', table_name='bug_attachment')
    op.drop_table('bug_attachment')
