"""Replace Jenkins execution support with Dagu while retaining old run history."""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op


revision = "0087"
down_revision = "0086"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _columns(table: str) -> set[str]:
    if table not in _inspector().get_table_names():
        return set()
    return {item["name"] for item in _inspector().get_columns(table)}


def _indexes(table: str) -> set[str]:
    if table not in _inspector().get_table_names():
        return set()
    return {item["name"] for item in _inspector().get_indexes(table)}


def _add_column(table: str, column: sa.Column) -> None:
    if column.name not in _columns(table):
        op.add_column(table, column)


def _archive_jenkins_execution_ids() -> None:
    columns = _columns("automation_execution")
    if "provider_type" not in columns:
        return
    required = {"id", "run_params", "provider_type"}
    if not required.issubset(columns):
        return
    queue_expr = "external_queue_id" if "external_queue_id" in columns else "NULL"
    build_expr = "external_build_number" if "external_build_number" in columns else "NULL"
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, run_params, provider_type, " + queue_expr + ", " + build_expr
        + " FROM automation_execution WHERE provider_type = 'JENKINS' OR "
        + queue_expr + " IS NOT NULL OR " + build_expr + " IS NOT NULL"
    )).all()
    table = sa.Table("automation_execution", sa.MetaData(), autoload_with=conn)
    for row_id, raw_params, provider_type, queue_id, build_number in rows:
        params = raw_params
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except ValueError:
                params = {"legacy_run_params": params[:5000]}
        params = dict(params) if isinstance(params, dict) else {}
        legacy = dict(params.get("legacy_provider_identifiers") or {})
        legacy.update({"provider_type": provider_type or "JENKINS"})
        if queue_id is not None:
            legacy["queue_id"] = str(queue_id)
        if build_number is not None:
            legacy["build_number"] = int(build_number)
        params["legacy_provider_identifiers"] = legacy
        conn.execute(
            table.update().where(table.c.id == row_id).values(provider_type="LEGACY", run_params=params)
        )


def upgrade() -> None:
    tables = set(_inspector().get_table_names())
    if "automation_integration_config" not in tables:
        return

    _add_column("automation_integration_config", sa.Column("dagu_base_url", sa.String(500), nullable=True))
    _add_column("automation_integration_config", sa.Column("dagu_api_key_encrypted", sa.Text(), nullable=True))
    _add_column(
        "automation_integration_config",
        sa.Column("dagu_api_key_configured", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    _archive_jenkins_execution_ids()

    for name in ("uq_automation_execution_jenkins_queue", "uq_automation_execution_jenkins_build"):
        if name in _indexes("automation_execution"):
            op.drop_index(name, table_name="automation_execution")

    tables = set(_inspector().get_table_names())
    if "automation_integration_config" in tables:
        config_columns = _columns("automation_integration_config")
        if "provider_type" in config_columns and "enabled" in config_columns:
            op.execute(sa.text(
                "UPDATE automation_integration_config SET provider_type = 'LEGACY', enabled = false "
                "WHERE provider_type = 'JENKINS'"
            ))

    if "automation_jenkins_credential" in set(_inspector().get_table_names()):
        op.drop_table("automation_jenkins_credential")

    for name in ("external_build_number", "external_queue_id", "queue_missing_since", "allow_private_network"):
        for table in ("automation_execution", "automation_integration_config"):
            if name in _columns(table):
                op.drop_column(table, name)


def downgrade() -> None:
    configs = _columns("automation_integration_config")
    if {"provider_type", "dagu_base_url"}.issubset(configs):
        result = op.get_bind().execute(sa.text(
            "SELECT count(*) FROM automation_integration_config WHERE provider_type IN ('DAGU', 'LEGACY')"
        )).scalar_one()
        if result:
            raise RuntimeError("0087 无法安全降级：Dagu 配置和已归档历史执行记录必须保留")

    raise RuntimeError("0087 为保留历史数据的单向迁移，不支持降级；请恢复数据库备份")
