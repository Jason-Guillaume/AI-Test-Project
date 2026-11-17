"""Add defect attachments."""
from alembic import op
import sqlalchemy as sa

revision = '0090'
down_revision = '0089'
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    """读取当前数据库中的表名，供幂等迁移判断。"""
    return set(sa.inspect(op.get_bind()).get_table_names())


def _indexes(table: str) -> set[str]:
    """读取指定表的索引名；表不存在时返回空集。"""
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    """幂等创建缺陷附件表及索引。"""
    if 'bug_attachment' not in _tables():
        op.create_table('bug_attachment',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('bug_id', sa.Integer(), sa.ForeignKey('bug.id', ondelete='CASCADE'), nullable=False),
            sa.Column('filename', sa.String(255), nullable=False),
            sa.Column('content_type', sa.String(255), nullable=False),
            sa.Column('content', sa.LargeBinary(), nullable=False),
            sa.Column('size', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()))
    if 'ix_bug_attachment_bug_id' not in _indexes('bug_attachment'):
        op.create_index('ix_bug_attachment_bug_id', 'bug_attachment', ['bug_id'])


def downgrade():
    """安全移除缺陷附件表及索引。"""
    if 'bug_attachment' not in _tables():
        return
    if 'ix_bug_attachment_bug_id' in _indexes('bug_attachment'):
        op.drop_index('ix_bug_attachment_bug_id', table_name='bug_attachment')
    op.drop_table('bug_attachment')
