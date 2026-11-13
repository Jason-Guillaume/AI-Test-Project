"""Add Jenkins provider configuration and execution snapshots."""

import sqlalchemy as sa
from alembic import op


revision = "0082"
down_revision = "0081"
branch_labels = None
depends_on = None


def upgrade():
    """Extend automation center without rewriting existing Yunxiao rows."""
    op.add_column(
        "automation_integration_config",
        sa.Column("provider_type", sa.String(20), nullable=False, server_default="YUNXIAO"),
    )
    op.add_column(
        "automation_integration_config",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "automation_integration_config",
        sa.Column("allow_private_network", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "automation_jenkins_credential",
        sa.Column(
            "integration_config_id", sa.Integer(),
            sa.ForeignKey("automation_integration_config.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("base_url", sa.String(500), nullable=False),
        sa.Column("username", sa.String(200), nullable=False),
        sa.Column("api_token_encrypted", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        comment="Jenkins API 凭据密文",
    )

    op.alter_column("automation_pipeline", "pipeline_id", type_=sa.String(255), existing_nullable=False)
    op.add_column(
        "automation_execution",
        sa.Column("integration_config_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_automation_execution_integration_config", "automation_execution",
        "automation_integration_config", ["integration_config_id"], ["id"], ondelete="SET NULL",
    )
    op.create_index(
        "ix_automation_execution_integration_config_id", "automation_execution", ["integration_config_id"],
    )
    op.add_column(
        "automation_execution",
        sa.Column("provider_type", sa.String(20), nullable=False, server_default="YUNXIAO"),
    )
    op.add_column("automation_execution", sa.Column("external_queue_id", sa.String(64), nullable=True))
    op.add_column("automation_execution", sa.Column("external_build_number", sa.Integer(), nullable=True))
    op.add_column(
        "automation_execution",
        sa.Column("external_run_url", sa.String(1000), nullable=False, server_default=""),
    )
    op.alter_column("automation_execution", "external_pipeline_id", type_=sa.String(255), existing_nullable=False)

    op.execute(
        "UPDATE automation_execution e SET integration_config_id = p.integration_config_id "
        "FROM automation_project p WHERE p.id = e.automation_project_id"
    )
    op.create_index(
        "uq_automation_execution_jenkins_queue",
        "automation_execution", ["integration_config_id", "external_queue_id"], unique=True,
        postgresql_where=sa.text("provider_type = 'JENKINS' AND external_queue_id IS NOT NULL"),
    )
    op.create_index(
        "uq_automation_execution_jenkins_build",
        "automation_execution", ["integration_config_id", "external_pipeline_id", "external_build_number"], unique=True,
        postgresql_where=sa.text("provider_type = 'JENKINS' AND external_build_number IS NOT NULL"),
    )


def downgrade():
    """Refuse lossy downgrade while Jenkins-specific data exists."""
    bind = op.get_bind()
    has_jenkins = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM automation_integration_config WHERE provider_type = 'JENKINS') "
            "OR EXISTS (SELECT 1 FROM automation_execution WHERE provider_type = 'JENKINS')"
        )
    ).scalar_one()
    if has_jenkins:
        raise RuntimeError("Cannot downgrade while Jenkins integration configurations exist")
    has_paths = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM automation_pipeline WHERE length(pipeline_id) > 64) "
            "OR EXISTS (SELECT 1 FROM automation_execution WHERE length(external_pipeline_id) > 64)"
        )
    ).scalar_one()
    if has_paths:
        raise RuntimeError("Cannot downgrade while CI resource paths exceed 64 characters")

    op.drop_index("uq_automation_execution_jenkins_build", table_name="automation_execution")
    op.drop_index("uq_automation_execution_jenkins_queue", table_name="automation_execution")
    op.alter_column("automation_execution", "external_pipeline_id", type_=sa.String(64), existing_nullable=False)
    op.drop_column("automation_execution", "external_run_url")
    op.drop_column("automation_execution", "external_build_number")
    op.drop_column("automation_execution", "external_queue_id")
    op.drop_column("automation_execution", "provider_type")
    op.drop_index("ix_automation_execution_integration_config_id", table_name="automation_execution")
    op.drop_constraint("fk_automation_execution_integration_config", "automation_execution", type_="foreignkey")
    op.drop_column("automation_execution", "integration_config_id")
    op.alter_column("automation_pipeline", "pipeline_id", type_=sa.String(64), existing_nullable=False)
    op.drop_table("automation_jenkins_credential")
    op.drop_column("automation_integration_config", "allow_private_network")
    op.drop_column("automation_integration_config", "enabled")
    op.drop_column("automation_integration_config", "provider_type")
