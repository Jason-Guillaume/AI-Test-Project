"""为失败项重试与完整重跑增加批次级幂等键。"""

from alembic import op
import sqlalchemy as sa


revision = "0039"
down_revision = "0038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("asr_job", sa.Column("request_key", sa.String(128), nullable=True))
    op.create_index("uq_asr_job_request_key", "asr_job", ["request_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_asr_job_request_key", table_name="asr_job")
    op.drop_column("asr_job", "request_key")
