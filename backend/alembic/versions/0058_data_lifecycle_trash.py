"""Add domain soft-delete fields and the recycle-bin/audit catalogue."""

import sqlalchemy as sa
from alembic import op


revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None


SOFT_DELETE_TABLES = ("test_case", "test_point", "test_scope_node", "api_module", "api_interface", "api_relation")


def upgrade():
    """Keep primary keys and associations; free active-name keys with partial indexes."""
    for table in SOFT_DELETE_TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
        op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
        op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
        op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )

    op.drop_constraint("uq_test_case_project_name", "test_case", type_="unique")
    op.create_index(
        "uq_test_case_project_name", "test_case", ["project_id", "name"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_test_point_project_name", "test_point", type_="unique")
    op.create_index(
        "uq_test_point_project_name", "test_point", ["project_id", "name"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_api_module_project_name", "api_module", type_="unique")
    op.create_index(
        "uq_api_module_project_name", "api_module", ["project_id", "name"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_api_interface_project_method_path", "api_interface", type_="unique")
    op.create_index(
        "uq_api_interface_project_method_path", "api_interface", ["project_id", "method", "path"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )
    op.drop_constraint("uq_api_relation_src_tgt_type_var", "api_relation", type_="unique")
    op.create_index(
        "uq_api_relation_src_tgt_type_var", "api_relation",
        ["source_api_id", "target_api_id", "relation_type", "variable_name"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"), sqlite_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "recycle_bin_item",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=500), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.Column("deleted_by_name", sa.String(length=100), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("deletion_reason", sa.String(length=500), nullable=True),
        sa.Column("deletion_batch_id", sa.String(length=36), nullable=False),
        sa.Column("deletion_status", sa.String(length=20), server_default="ACTIVE", nullable=False),
        sa.Column("metadata_json", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("restored_by", sa.Integer(), nullable=True),
        sa.Column("restored_at", sa.DateTime(), nullable=True),
        sa.Column("last_restore_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="统一回收站目录；保留原业务表主键，不建立跨域资源外键",
    )
    for col in ("resource_type", "project_id", "organization_id", "deleted_by", "deleted_at", "deletion_batch_id", "deletion_status"):
        op.create_index(f"ix_recycle_bin_item_{col}", "recycle_bin_item", [col])
    op.create_index(
        "ix_recycle_bin_scope_deleted", "recycle_bin_item",
        ["project_id", "deletion_status", "deleted_at"],
    )
    op.create_index("ix_recycle_bin_resource", "recycle_bin_item", ["resource_type", "resource_id"])

    op.create_table(
        "data_lifecycle_audit_event",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=20), nullable=False),
        sa.Column("result", sa.String(length=20), server_default="SUCCEEDED", nullable=False),
        sa.Column("resource_type", sa.String(length=80), nullable=False),
        sa.Column("resource_id", sa.String(length=64), nullable=False),
        sa.Column("recycle_bin_item_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("deletion_batch_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column("detail", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        comment="数据删除、恢复与物理清理的不可变审计事件",
    )
    op.create_index(
        "ix_lifecycle_audit_resource", "data_lifecycle_audit_event",
        ["resource_type", "resource_id", "created_at"],
    )
    op.create_index(
        "ix_lifecycle_audit_batch", "data_lifecycle_audit_event", ["deletion_batch_id", "created_at"],
    )
    op.create_index(
        "ix_data_lifecycle_audit_event_created_at", "data_lifecycle_audit_event", ["created_at"],
    )


def downgrade():
    """Remove lifecycle structures. Reverting requires resolving duplicate historic names first."""
    op.drop_index("ix_data_lifecycle_audit_event_created_at", table_name="data_lifecycle_audit_event")
    op.drop_index("ix_lifecycle_audit_batch", table_name="data_lifecycle_audit_event")
    op.drop_index("ix_lifecycle_audit_resource", table_name="data_lifecycle_audit_event")
    op.drop_table("data_lifecycle_audit_event")

    op.drop_index("ix_recycle_bin_resource", table_name="recycle_bin_item")
    op.drop_index("ix_recycle_bin_scope_deleted", table_name="recycle_bin_item")
    for col in ("resource_type", "project_id", "organization_id", "deleted_by", "deleted_at", "deletion_batch_id", "deletion_status"):
        op.drop_index(f"ix_recycle_bin_item_{col}", table_name="recycle_bin_item")
    op.drop_table("recycle_bin_item")

    op.drop_index("uq_api_relation_src_tgt_type_var", table_name="api_relation")
    op.create_unique_constraint(
        "uq_api_relation_src_tgt_type_var", "api_relation",
        ["source_api_id", "target_api_id", "relation_type", "variable_name"],
    )
    op.drop_index("uq_api_interface_project_method_path", table_name="api_interface")
    op.create_unique_constraint("uq_api_interface_project_method_path", "api_interface", ["project_id", "method", "path"])
    op.drop_index("uq_api_module_project_name", table_name="api_module")
    op.create_unique_constraint("uq_api_module_project_name", "api_module", ["project_id", "name"])
    op.drop_index("uq_test_point_project_name", table_name="test_point")
    op.create_unique_constraint("uq_test_point_project_name", "test_point", ["project_id", "name"])
    op.drop_index("uq_test_case_project_name", table_name="test_case")
    op.create_unique_constraint("uq_test_case_project_name", "test_case", ["project_id", "name"])

    for table in reversed(SOFT_DELETE_TABLES):
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        op.drop_column(table, "deletion_batch_id")
        op.drop_column(table, "deletion_reason")
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
