"""关联用例生成批次与统一任务，增加模块草稿幂等约束。"""
import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade():
    """仅为异步生成添加可空关联，旧批次和人工审核数据保持原样。"""
    op.add_column("case_generation_batch", sa.Column("task_run_id", sa.Integer(), sa.ForeignKey("task_run.id", deferrable=True, initially="DEFERRED"), nullable=True))
    op.create_unique_constraint("uq_generation_batch_run", "case_generation_batch", ["task_run_id"])
    op.add_column("case_draft", sa.Column("work_item_id", sa.Integer(), sa.ForeignKey("task_work_item.id", deferrable=True, initially="DEFERRED"), nullable=True))
    op.add_column("case_draft", sa.Column("result_ordinal", sa.Integer(), nullable=True))
    op.create_unique_constraint("uq_generation_draft_work_ordinal", "case_draft", ["work_item_id", "result_ordinal"])


def downgrade():
    """移除任务关联，不删除批次、草稿或正式用例。"""
    op.drop_constraint("uq_generation_draft_work_ordinal", "case_draft", type_="unique")
    op.drop_column("case_draft", "result_ordinal")
    op.drop_column("case_draft", "work_item_id")
    op.drop_constraint("uq_generation_batch_run", "case_generation_batch", type_="unique")
    op.drop_column("case_generation_batch", "task_run_id")
