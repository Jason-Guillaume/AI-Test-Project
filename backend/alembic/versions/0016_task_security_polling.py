"""任务内 ZAP 关联与外部扫描轮询。

Revision ID: 0016
Revises: 0015
"""

from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    """增量增加可空列，兼容已经存在的任务和独立 ZAP 记录。"""
    inspector = sa.inspect(op.get_bind())
    task_columns = {column["name"] for column in inspector.get_columns("task")}
    if "security_scan_json" not in task_columns:
        op.add_column("task", sa.Column("security_scan_json", sa.JSON(), nullable=True))

    work_columns = {column["name"] for column in inspector.get_columns("task_work_item")}
    if "available_at" not in work_columns:
        op.add_column("task_work_item", sa.Column("available_at", sa.DateTime(), nullable=True, comment="外部任务轮询或延迟重试的最早领取时间"))
    existing_task_indexes = {idx["name"] for idx in inspector.get_indexes("task_work_item")}
    if "ix_task_work_item_available_at" not in existing_task_indexes:
        op.create_index("ix_task_work_item_available_at", "task_work_item", ["available_at"], unique=False)

    scan_columns = {column["name"] for column in inspector.get_columns("security_scan_job")}
    if "idempotency_key" not in scan_columns:
        op.add_column("security_scan_job", sa.Column("idempotency_key", sa.String(160), nullable=True, comment="调用方提供的幂等键；统一任务用其工具回执键恢复"))
    existing_scan_indexes = {idx["name"] for idx in inspector.get_indexes("security_scan_job")}
    if "uq_security_scan_job_idempotency" not in existing_scan_indexes:
        op.create_index("uq_security_scan_job_idempotency", "security_scan_job", ["project_id", "idempotency_key"], unique=True)


def downgrade():
    """仅在结构回滚时删除本迁移新增的可空字段与索引。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("security_scan_job"):
        indexes = {idx["name"] for idx in inspector.get_indexes("security_scan_job")}
        if "uq_security_scan_job_idempotency" in indexes:
            op.drop_index("uq_security_scan_job_idempotency", table_name="security_scan_job")
        columns = {column["name"] for column in inspector.get_columns("security_scan_job")}
        if "idempotency_key" in columns:
            op.drop_column("security_scan_job", "idempotency_key")
    if inspector.has_table("task_work_item"):
        indexes = {idx["name"] for idx in inspector.get_indexes("task_work_item")}
        if "ix_task_work_item_available_at" in indexes:
            op.drop_index("ix_task_work_item_available_at", table_name="task_work_item")
        columns = {column["name"] for column in inspector.get_columns("task_work_item")}
        if "available_at" in columns:
            op.drop_column("task_work_item", "available_at")
    if inspector.has_table("task"):
        columns = {column["name"] for column in inspector.get_columns("task")}
        if "security_scan_json" in columns:
            op.drop_column("task", "security_scan_json")
