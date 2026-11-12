"""把仍会物理删除的配置、成员关系和用例子资源改为可恢复删除。"""

import sqlalchemy as sa
from alembic import op


revision = "0081"
down_revision = "0080"
branch_labels = None
depends_on = None

_TABLES = (
    "model_configuration",
    "notification",
    "project_member",
    "organization_member",
    "project_outbound_target",
    "notification_channel",
    "web_auth_profile",
    "security_scan_target",
    "security_scan_profile",
    "security_scan_auth_profile",
    "test_step",
    "test_assertion",
    "test_case_precondition",
    "test_case_data",
    "test_suite_case",
    "test_plan_suite",
)


def _add_soft_columns(table: str) -> None:
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


def upgrade():
    """增加软删除列，并只对未删除行保留会阻止同名重建的唯一约束。"""
    for table in _TABLES:
        _add_soft_columns(table)

    op.drop_constraint("model_configuration_domain_id_key", "model_configuration", type_="unique")
    op.create_index(
        "uq_model_configuration_domain_id_live", "model_configuration", ["domain_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_project_member_project_user", "project_member", type_="unique")
    op.create_index(
        "uq_project_member_project_user_live", "project_member", ["project_id", "user_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_organization_member_user", "organization_member", type_="unique")
    op.create_index(
        "uq_organization_member_user_live", "organization_member", ["organization_id", "user_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_project_outbound_target", "project_outbound_target", type_="unique")
    op.create_index(
        "uq_project_outbound_target_live", "project_outbound_target",
        ["project_id", "scheme", "host", "port"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_index("ix_security_scan_profile_code", table_name="security_scan_profile")
    op.create_index(
        "ix_security_scan_profile_code", "security_scan_profile", ["code"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_test_case_data_case_name", "test_case_data", type_="unique")
    op.create_index(
        "uq_test_case_data_case_name_live", "test_case_data", ["test_case_id", "name"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_test_suite_case_suite_case", "test_suite_case", type_="unique")
    op.create_index(
        "uq_test_suite_case_suite_case_live", "test_suite_case", ["suite_id", "test_case_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_test_plan_suite_plan_suite", "test_plan_suite", type_="unique")
    op.create_index(
        "uq_test_plan_suite_plan_suite_live", "test_plan_suite", ["plan_id", "suite_id"],
        unique=True, postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade():
    """恢复原唯一约束。回收站中仍有记录时拒绝降级。"""
    bind = op.get_bind()
    for table in _TABLES:
        if bind.execute(sa.text(f"SELECT count(*) FROM {table} WHERE deleted_at IS NOT NULL")).scalar_one():
            raise RuntimeError(f"Cannot downgrade {table} lifecycle while deleted records remain; restore them first")

    op.drop_index("uq_test_plan_suite_plan_suite_live", table_name="test_plan_suite")
    op.create_unique_constraint("uq_test_plan_suite_plan_suite", "test_plan_suite", ["plan_id", "suite_id"])
    op.drop_index("uq_test_suite_case_suite_case_live", table_name="test_suite_case")
    op.create_unique_constraint(
        "uq_test_suite_case_suite_case", "test_suite_case", ["suite_id", "test_case_id"],
    )
    op.drop_index("uq_test_case_data_case_name_live", table_name="test_case_data")
    op.create_unique_constraint("uq_test_case_data_case_name", "test_case_data", ["test_case_id", "name"])
    op.drop_index("ix_security_scan_profile_code", table_name="security_scan_profile")
    op.create_index("ix_security_scan_profile_code", "security_scan_profile", ["code"], unique=True)
    op.drop_index("uq_project_outbound_target_live", table_name="project_outbound_target")
    op.create_unique_constraint(
        "uq_project_outbound_target", "project_outbound_target", ["project_id", "scheme", "host", "port"],
    )
    op.drop_index("uq_organization_member_user_live", table_name="organization_member")
    op.create_unique_constraint(
        "uq_organization_member_user", "organization_member", ["organization_id", "user_id"],
    )
    op.drop_index("uq_project_member_project_user_live", table_name="project_member")
    op.create_unique_constraint(
        "uq_project_member_project_user", "project_member", ["project_id", "user_id"],
    )
    op.drop_index("uq_model_configuration_domain_id_live", table_name="model_configuration")
    op.create_unique_constraint("model_configuration_domain_id_key", "model_configuration", ["domain_id"])

    for table in reversed(_TABLES):
        op.drop_index(f"ix_{table}_deleted_at", table_name=table)
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        for column in ("deletion_batch_id", "deletion_reason", "deleted_by", "deleted_at"):
            op.drop_column(table, column)
