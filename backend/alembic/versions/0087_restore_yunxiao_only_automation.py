"""Remove the retired Jenkins schema while preserving Yunxiao execution history."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table: str) -> dict[str, dict]:
    if table not in _inspector().get_table_names():
        return {}
    return {column["name"]: column for column in _inspector().get_columns(table)}


def _rows_exist(table: str, condition: str = "TRUE") -> bool:
    if table not in _inspector().get_table_names():
        return False
    return bool(op.get_bind().execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} WHERE {condition})")).scalar_one())


def _assert_safe_to_remove() -> None:
    credential_table = "automation_jenkins_credential"
    if _rows_exist(credential_table):
        raise RuntimeError("0087 refuses to drop non-empty Jenkins credentials; export or review them first")

    config_columns = _columns("automation_integration_config")
    if "provider_type" in config_columns and _rows_exist(
        "automation_integration_config", "upper(provider_type) = 'JENKINS'",
    ):
        raise RuntimeError("0087 refuses to remove Jenkins integration configurations")

    execution_columns = _columns("automation_execution")
    retired_data = [
        f"upper(provider_type) = 'JENKINS'" if "provider_type" in execution_columns else None,
        "external_queue_id IS NOT NULL" if "external_queue_id" in execution_columns else None,
        "external_build_number IS NOT NULL" if "external_build_number" in execution_columns else None,
        "external_run_url <> ''" if "external_run_url" in execution_columns else None,
    ]
    retired_data = [condition for condition in retired_data if condition]
    if retired_data and _rows_exist("automation_execution", " OR ".join(retired_data)):
        raise RuntimeError("0087 refuses to remove Jenkins execution identifiers or URLs")

    for table, column in (("automation_pipeline", "pipeline_id"), ("automation_execution", "external_pipeline_id")):
        if column in _columns(table) and _rows_exist(table, f"length({column}) > 64"):
            raise RuntimeError(f"0087 refuses to narrow {table}.{column}; a value exceeds 64 characters")


def _drop_index_if_present(table: str, name: str) -> None:
    if name in {index["name"] for index in _inspector().get_indexes(table)}:
        op.drop_index(name, table_name=table)


def _drop_column_if_present(table: str, name: str) -> None:
    if name in _columns(table):
        op.drop_column(table, name)


def _resize_string(table: str, name: str, size: int) -> None:
    column = _columns(table).get(name)
    if column is None:
        return
    current_size = getattr(column.get("type"), "length", None)
    if current_size and current_size != size:
        op.alter_column(
            table,
            name,
            existing_type=column["type"],
            type_=sa.String(size),
            existing_nullable=column.get("nullable", True),
        )


def upgrade() -> None:
    """Drop only retired CI fields; fail before DDL if Jenkins data would be lost."""
    _assert_safe_to_remove()

    for index_name in (
        "ix_automation_execution_stop_requested",
        "uq_automation_execution_jenkins_build",
        "uq_automation_execution_jenkins_queue",
    ):
        _drop_index_if_present("automation_execution", index_name)

    if "automation_jenkins_credential" in _inspector().get_table_names():
        op.drop_table("automation_jenkins_credential")

    for column in ("allow_private_network", "enabled", "provider_type"):
        _drop_column_if_present("automation_integration_config", column)

    for column in (
        "queue_missing_since",
        "stop_requested_at",
        "stop_reason",
        "external_run_url",
        "external_build_number",
        "external_queue_id",
        "provider_type",
    ):
        _drop_column_if_present("automation_execution", column)

    # This generic relation was backfilled for Yunxiao runs in 0085; retain it so
    # historical executions remain associated with the integration that ran them.
    _resize_string("automation_pipeline", "pipeline_id", 64)
    _resize_string("automation_execution", "external_pipeline_id", 64)


def downgrade() -> None:
    """Restore the empty legacy columns so an older release can be redeployed."""
    for table, column in (
        ("automation_integration_config", sa.Column("provider_type", sa.String(20), nullable=False, server_default="YUNXIAO")),
        ("automation_integration_config", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true())),
        ("automation_integration_config", sa.Column("allow_private_network", sa.Boolean(), nullable=False, server_default=sa.false())),
        ("automation_execution", sa.Column("provider_type", sa.String(20), nullable=False, server_default="YUNXIAO")),
        ("automation_execution", sa.Column("external_queue_id", sa.String(64), nullable=True)),
        ("automation_execution", sa.Column("external_build_number", sa.Integer(), nullable=True)),
        ("automation_execution", sa.Column("external_run_url", sa.String(1000), nullable=False, server_default="")),
        ("automation_execution", sa.Column("stop_reason", sa.String(20), nullable=True)),
        ("automation_execution", sa.Column("stop_requested_at", sa.DateTime(), nullable=True)),
        ("automation_execution", sa.Column("queue_missing_since", sa.DateTime(), nullable=True)),
    ):
        if column.name not in _columns(table):
            op.add_column(table, column)

    _resize_string("automation_pipeline", "pipeline_id", 255)
    _resize_string("automation_execution", "external_pipeline_id", 255)

    if "automation_jenkins_credential" not in _inspector().get_table_names():
        op.create_table(
            "automation_jenkins_credential",
            sa.Column(
                "integration_config_id",
                sa.Integer(),
                sa.ForeignKey("automation_integration_config.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column("base_url", sa.String(500), nullable=False),
            sa.Column("username", sa.String(200), nullable=False),
            sa.Column("api_token_encrypted", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )

    indexes = {index["name"] for index in _inspector().get_indexes("automation_execution")}
    if "uq_automation_execution_jenkins_queue" not in indexes:
        op.create_index(
            "uq_automation_execution_jenkins_queue",
            "automation_execution",
            ["integration_config_id", "external_queue_id"],
            unique=True,
            postgresql_where=sa.text("provider_type = 'JENKINS' AND external_queue_id IS NOT NULL"),
            sqlite_where=sa.text("provider_type = 'JENKINS' AND external_queue_id IS NOT NULL"),
        )
    if "uq_automation_execution_jenkins_build" not in indexes:
        op.create_index(
            "uq_automation_execution_jenkins_build",
            "automation_execution",
            ["integration_config_id", "external_pipeline_id", "external_build_number"],
            unique=True,
            postgresql_where=sa.text("provider_type = 'JENKINS' AND external_build_number IS NOT NULL"),
            sqlite_where=sa.text("provider_type = 'JENKINS' AND external_build_number IS NOT NULL"),
        )
    if "ix_automation_execution_stop_requested" not in indexes:
        op.create_index(
            "ix_automation_execution_stop_requested",
            "automation_execution",
            ["status", "stop_requested_at"],
        )
