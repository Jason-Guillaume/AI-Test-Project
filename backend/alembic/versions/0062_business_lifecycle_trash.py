"""Add recoverable lifecycle fields to business-domain configuration assets."""

import sqlalchemy as sa
from alembic import op


revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None


TABLES = (
    "business_domain",
    "business_flow",
    "business_action",
    "business_rule",
    "business_variable",
    "business_state",
    "business_binding",
    "business_precondition",
    "business_api_mapping",
    "business_variable_ref",
)


def upgrade():
    for table in TABLES:
        op.add_column(table, sa.Column("deleted_at", sa.DateTime(), nullable=True, comment="软删除时间"))
        op.add_column(table, sa.Column("deleted_by", sa.Integer(), nullable=True, comment="删除操作人"))
        op.add_column(table, sa.Column("deletion_reason", sa.String(length=500), nullable=True, comment="删除原因"))
        op.add_column(table, sa.Column("deletion_batch_id", sa.String(length=36), nullable=True, comment="删除批次 ID"))
        op.create_foreign_key(
            "fk_soft_delete_deleted_by_user", table, "user", ["deleted_by"], ["id"], ondelete="SET NULL",
        )

    for name, table, columns in (
        ("uq_business_domain_project_name", "business_domain", ["project_id", "name"]),
        ("uq_business_flow_domain_name", "business_flow", ["domain_id", "name"]),
        ("uq_business_action_flow_key", "business_action", ["flow_id", "action_key"]),
        ("uq_business_variable_action_dir_name", "business_variable", ["action_id", "direction", "name"]),
        ("uq_business_state_action_entity", "business_state", ["action_id", "entity"]),
        ("uq_business_api_mapping_binding_dir_var", "business_api_mapping", ["binding_id", "direction", "business_variable"]),
    ):
        op.drop_constraint(name, table, type_="unique")
        op.create_index(
            name,
            table,
            columns,
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
            sqlite_where=sa.text("deleted_at IS NULL"),
        )

    op.drop_index("ix_business_binding_action_default", table_name="business_binding")
    op.create_index(
        "ix_business_binding_action_default",
        "business_binding",
        ["action_id", "binding_type"],
        unique=True,
        postgresql_where=sa.text("is_default = true AND deleted_at IS NULL"),
        sqlite_where=sa.text("is_default = true AND deleted_at IS NULL"),
    )


def downgrade():
    op.drop_index("ix_business_binding_action_default", table_name="business_binding")
    op.create_index(
        "ix_business_binding_action_default",
        "business_binding",
        ["action_id", "binding_type"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

    for name, table, columns in reversed((
        ("uq_business_api_mapping_binding_dir_var", "business_api_mapping", ["binding_id", "direction", "business_variable"]),
        ("uq_business_state_action_entity", "business_state", ["action_id", "entity"]),
        ("uq_business_variable_action_dir_name", "business_variable", ["action_id", "direction", "name"]),
        ("uq_business_action_flow_key", "business_action", ["flow_id", "action_key"]),
        ("uq_business_flow_domain_name", "business_flow", ["domain_id", "name"]),
        ("uq_business_domain_project_name", "business_domain", ["project_id", "name"]),
    )):
        op.drop_index(name, table_name=table)
        op.create_unique_constraint(name, table, columns)

    for table in reversed(TABLES):
        op.drop_constraint("fk_soft_delete_deleted_by_user", table, type_="foreignkey")
        op.drop_column(table, "deletion_batch_id")
        op.drop_column(table, "deletion_reason")
        op.drop_column(table, "deleted_by")
        op.drop_column(table, "deleted_at")
