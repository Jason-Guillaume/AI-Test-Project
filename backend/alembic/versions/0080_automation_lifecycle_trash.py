"""为云效接入配置和自动化项目补上可恢复删除。

执行记录、报告和回调事件不进入回收站。
"""

import sqlalchemy as sa
from alembic import op


revision = "0080"
down_revision = "0079"
branch_labels = None
depends_on = None

_TABLES = (
    "automation_integration_config",
    "automation_project",
)


def upgrade():
    """增加软删除列，并把名称、回调标识改成只约束未删除行。"""
    for table in _TABLES:
        for column in (
            sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"),
            sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"),
            sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"),
            sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"),
        ):
            op.add_column(table, column)
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user",
            ["deleted_by"], ["id"], ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_deleted_at", table, ["deleted_at"])

    op.drop_constraint(
        "uq_automation_integration_project_name", "automation_integration_config", type_="unique",
    )
    op.drop_constraint(
        "uq_automation_integration_callback_key", "automation_integration_config", type_="unique",
    )
    op.drop_constraint("uq_automation_project_name", "automation_project", type_="unique")
    op.create_index(
        "uq_automation_integration_project_name_live", "automation_integration_config",
        ["project_id", "name"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_automation_integration_callback_key_live", "automation_integration_config",
        ["callback_key"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "uq_automation_project_name_live", "automation_project",
        ["project_id", "name"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade():
    """恢复全表唯一约束。回收站里仍有记录或活跃键冲突时拒绝降级。"""
    bind = op.get_bind()
    for table in _TABLES:
        if bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE deleted_at IS NOT NULL")).scalar_one():
            raise RuntimeError(f"Cannot downgrade {table} lifecycle while deleted records remain; restore them first")
    op.drop_index("uq_automation_project_name_live", table_name="automation_project")
    op.drop_index(
        "uq_automation_integration_callback_key_live", table_name="automation_integration_config",
    )
    op.drop_index(
        "uq_automation_integration_project_name_live", table_name="automation_integration_config",
    )
    op.create_unique_constraint(
        "uq_automation_project_name", "automation_project", ["project_id", "name"],
    )
    op.create_unique_constraint(
        "uq_automation_integration_callback_key", "automation_integration_config", ["callback_key"],
    )
    op.create_unique_constraint(
        "uq_automation_integration_project_name", "automation_integration_config", ["project_id", "name"],
    )
    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_deleted_at", table_name=table)
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        for column in ("deletion_batch_id", "deletion_reason", "deleted_by", "deleted_at"):
            op.drop_column(table, column)
