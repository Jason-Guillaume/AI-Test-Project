"""创建 ASR 评测产物索引；正文保存在 API 与 Worker 共享的受控持久卷。"""

from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """新增产物登记，不改变旧 ASR 结果。"""
    op.create_table(
        "asr_evaluation_artifact",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("asr_job.id", ondelete="CASCADE"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("asr_model_run.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(60), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("redaction_version", sa.String(40)),
        sa.Column("redacted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_asr_evaluation_artifact_project_id", "asr_evaluation_artifact", ["project_id"])
    op.create_index("ix_asr_evaluation_artifact_run_id", "asr_evaluation_artifact", ["run_id"])
    op.create_index("ix_asr_evaluation_artifact_status", "asr_evaluation_artifact", ["status"])


def downgrade() -> None:
    """删除登记表；卷内文件保留，清理前需先备份并确认数据损失。"""
    op.drop_index("ix_asr_evaluation_artifact_status", table_name="asr_evaluation_artifact")
    op.drop_index("ix_asr_evaluation_artifact_run_id", table_name="asr_evaluation_artifact")
    op.drop_index("ix_asr_evaluation_artifact_project_id", table_name="asr_evaluation_artifact")
    op.drop_table("asr_evaluation_artifact")
