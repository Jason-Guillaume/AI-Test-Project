"""Add Jenkins execution support and repair databases stamped by the old 0082."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0085"
down_revision = "0084"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table: str) -> dict[str, dict]:
    return {column["name"]: column for column in _inspector().get_columns(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _ensure_api_response_keys() -> None:
    columns = _columns("api_response")
    if "response_key" not in columns:
        op.add_column("api_response", sa.Column("response_key", sa.String(16), nullable=True))
    columns = _columns("api_response")
    op.execute(
        "UPDATE api_response SET response_key = COALESCE(response_key, CAST(status_code AS VARCHAR(16)), 'default') "
        "WHERE response_key IS NULL"
    )
    if columns["response_key"].get("nullable", True):
        op.alter_column("api_response", "response_key", existing_type=columns["response_key"]["type"], nullable=False)
        columns = _columns("api_response")
    if not columns["status_code"].get("nullable", True):
        op.alter_column(
            "api_response", "status_code", existing_type=columns["status_code"]["type"], nullable=True,
        )


def _ensure_jenkins_schema() -> None:
    _add_column(
        "automation_integration_config",
        sa.Column("provider_type", sa.String(20), nullable=False, server_default="YUNXIAO"),
    )
    _add_column(
        "automation_integration_config",
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _add_column(
        "automation_integration_config",
        sa.Column("allow_private_network", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    if "automation_jenkins_credential" not in _inspector().get_table_names():
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

    _widen_string("automation_pipeline", "pipeline_id", 255)
    _add_column(
        "automation_execution",
        sa.Column("integration_config_id", sa.Integer(), nullable=True),
    )
    execution_columns = _columns("automation_execution")
    foreign_keys = _inspector().get_foreign_keys("automation_execution")
    if not any(
        fk.get("constrained_columns") == ["integration_config_id"]
        and fk.get("referred_table") == "automation_integration_config"
        for fk in foreign_keys
    ):
        op.create_foreign_key(
            "fk_automation_execution_integration_config", "automation_execution",
            "automation_integration_config", ["integration_config_id"], ["id"], ondelete="SET NULL",
        )
    if "ix_automation_execution_integration_config_id" not in {
        index["name"] for index in _inspector().get_indexes("automation_execution")
    }:
        op.create_index(
            "ix_automation_execution_integration_config_id", "automation_execution", ["integration_config_id"],
        )
    _add_column(
        "automation_execution",
        sa.Column("provider_type", sa.String(20), nullable=False, server_default="YUNXIAO"),
    )
    _add_column("automation_execution", sa.Column("external_queue_id", sa.String(64), nullable=True))
    _add_column("automation_execution", sa.Column("external_build_number", sa.Integer(), nullable=True))
    _add_column(
        "automation_execution",
        sa.Column("external_run_url", sa.String(1000), nullable=False, server_default=""),
    )
    _add_column("automation_execution", sa.Column("stop_reason", sa.String(20), nullable=True))
    _add_column("automation_execution", sa.Column("stop_requested_at", sa.DateTime(), nullable=True))
    _add_column("automation_execution", sa.Column("queue_missing_since", sa.DateTime(), nullable=True))
    _widen_string("automation_execution", "external_pipeline_id", 255)

    op.execute(
        "UPDATE automation_execution e SET integration_config_id = p.integration_config_id "
        "FROM automation_project p WHERE e.automation_project_id = p.id "
        "AND e.integration_config_id IS NULL"
    )
    columns = _columns("automation_execution")
    if "provider_type" in columns and "external_queue_id" in columns:
        op.execute(
            "UPDATE automation_execution SET provider_type = 'JENKINS' "
            "WHERE provider_type = 'YUNXIAO' "
            "AND (external_queue_id IS NOT NULL OR external_build_number IS NOT NULL)"
        )

    duplicate_queue = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM automation_execution "
        "WHERE provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_queue_id IS NOT NULL "
        "GROUP BY integration_config_id, external_queue_id HAVING count(*) > 1)"
    )).scalar_one()
    duplicate_build = op.get_bind().execute(sa.text(
        "SELECT EXISTS (SELECT 1 FROM automation_execution "
        "WHERE provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_build_number IS NOT NULL "
        "GROUP BY integration_config_id, external_pipeline_id, external_build_number HAVING count(*) > 1)"
    )).scalar_one()
    if duplicate_queue or duplicate_build:
        raise RuntimeError(
            "Jenkins 执行记录存在重复 Queue/Build 标识；请先合并或隔离重复记录，再升级 0085"
        )

    indexes = {index["name"] for index in _inspector().get_indexes("automation_execution")}
    if "uq_automation_execution_jenkins_queue" not in indexes:
        op.create_index(
            "uq_automation_execution_jenkins_queue", "automation_execution",
            ["integration_config_id", "external_queue_id"], unique=True,
            postgresql_where=sa.text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_queue_id IS NOT NULL"
            ),
            sqlite_where=sa.text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_queue_id IS NOT NULL"
            ),
        )
    if "uq_automation_execution_jenkins_build" not in indexes:
        op.create_index(
            "uq_automation_execution_jenkins_build", "automation_execution",
            ["integration_config_id", "external_pipeline_id", "external_build_number"], unique=True,
            postgresql_where=sa.text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_build_number IS NOT NULL"
            ),
            sqlite_where=sa.text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_build_number IS NOT NULL"
            ),
        )
    if "ix_automation_execution_stop_requested" not in indexes:
        op.create_index(
            "ix_automation_execution_stop_requested", "automation_execution",
            ["status", "stop_requested_at"],
        )


def _widen_string(table: str, name: str, length: int) -> None:
    column = _columns(table).get(name)
    existing_type = column.get("type") if column else None
    if column is None or getattr(existing_type, "length", None) is None:
        return
    if existing_type.length < length:
        op.alter_column(
            table, name, existing_type=existing_type, type_=sa.String(length),
            existing_nullable=column.get("nullable", True),
        )


def upgrade() -> None:
    """Repair either historical 0082 shape, then ensure Jenkins schema exactly once.

    The former Jenkins migration used revision ID ``0082`` and may have been applied
    before the API response-key migration claimed that ID. Alembic cannot distinguish
    those databases by version number alone, so this migration inspects both schemas.
    """
    _ensure_api_response_keys()
    _ensure_jenkins_schema()
    op.execute(
        "UPDATE automation_integration_config SET default_timeout_seconds = 10800 "
        "WHERE default_timeout_seconds > 10800"
    )
    op.execute(
        "UPDATE automation_project SET timeout_seconds = 10800 WHERE timeout_seconds > 10800"
    )


def downgrade() -> None:
    """Refuse to remove Jenkins schema while any Jenkins data or paths remain."""
    bind = op.get_bind()
    has_jenkins = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM automation_integration_config WHERE provider_type = 'JENKINS') "
            "OR EXISTS (SELECT 1 FROM automation_execution WHERE provider_type = 'JENKINS' "
            "OR external_queue_id IS NOT NULL OR external_build_number IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM automation_jenkins_credential)"
        )
    ).scalar_one()
    if has_jenkins:
        raise RuntimeError("Cannot downgrade while Jenkins integration configurations or executions exist")
    has_paths = bind.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM automation_pipeline WHERE length(pipeline_id) > 64) "
            "OR EXISTS (SELECT 1 FROM automation_execution WHERE length(external_pipeline_id) > 64)"
        )
    ).scalar_one()
    if has_paths:
        raise RuntimeError("Cannot downgrade while CI resource paths exceed 64 characters")

    op.drop_index("ix_automation_execution_stop_requested", table_name="automation_execution")
    op.drop_index("uq_automation_execution_jenkins_build", table_name="automation_execution")
    op.drop_index("uq_automation_execution_jenkins_queue", table_name="automation_execution")
    op.drop_column("automation_execution", "queue_missing_since")
    op.drop_column("automation_execution", "stop_requested_at")
    op.drop_column("automation_execution", "stop_reason")
    op.alter_column(
        "automation_execution", "external_pipeline_id", type_=sa.String(64), existing_nullable=False,
    )
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
