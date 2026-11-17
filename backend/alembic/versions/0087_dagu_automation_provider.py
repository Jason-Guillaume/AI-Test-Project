"""Replace Jenkins execution support with Dagu while retaining old run history.

降级只恢复空库上的 Jenkins 表结构。已经归档的 Jenkins 凭据和 Dagu 密钥无法重建，
因此只要存在 LEGACY 或 DAGU 数据就拒绝降级，避免测试为了往返迁移而丢掉历史。
"""

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
    """把 Jenkins 标识写入 JSON，并把仍在排队或运行的历史任务标成已归档。"""
    columns = _columns("automation_execution")
    if "provider_type" not in columns:
        return
    required = {"id", "run_params", "provider_type"}
    if not required.issubset(columns):
        return
    queue_expr = "external_queue_id" if "external_queue_id" in columns else "NULL"
    build_expr = "external_build_number" if "external_build_number" in columns else "NULL"
    status_expr = "status" if "status" in columns else "NULL"
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, run_params, provider_type, " + queue_expr + ", " + build_expr + ", " + status_expr
        + " FROM automation_execution WHERE provider_type = 'JENKINS' OR "
        + queue_expr + " IS NOT NULL OR " + build_expr + " IS NOT NULL"
    )).all()
    table = sa.Table("automation_execution", sa.MetaData(), autoload_with=conn)
    for row_id, raw_params, provider_type, queue_id, build_number, status in rows:
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
        # 未结束的 Jenkins 任务如果继续保持 PENDING/RUNNING，会占住新 Poller 的同步名额。
        values = {"provider_type": "LEGACY", "run_params": params}
        if status in {"PENDING", "RUNNING"}:
            legacy["previous_status"] = str(status)
            legacy["archived_incomplete"] = True
            params["legacy_provider_identifiers"] = legacy
            values["run_params"] = params
            if "status" in columns:
                values["status"] = "CANCELLED"
            if "error_message" in columns:
                values["error_message"] = "历史 Jenkins 任务已归档，不再同步"
            if "finished_at" in columns:
                values["finished_at"] = sa.func.now()
            if "stop_requested_at" in columns:
                values["stop_requested_at"] = None
        conn.execute(table.update().where(table.c.id == row_id).values(**values))


def _unsafe_downgrade_reason() -> str | None:
    """Jenkins 凭据表和 Dagu 密钥在降级时无法重建，有这类数据就必须停下来。"""
    tables = set(_inspector().get_table_names())
    bind = op.get_bind()
    if "automation_integration_config" in tables and "provider_type" in _columns("automation_integration_config"):
        unsafe_configs = bind.execute(sa.text(
            "SELECT count(*) FROM automation_integration_config WHERE provider_type IN ('DAGU', 'LEGACY')"
        )).scalar_one()
        if unsafe_configs:
            return "0087 无法安全降级：Dagu 配置或已归档的 Jenkins 接入凭据无法恢复"
    if "automation_execution" in tables and "provider_type" in _columns("automation_execution"):
        unsafe_runs = bind.execute(sa.text(
            "SELECT count(*) FROM automation_execution WHERE provider_type IN ('DAGU', 'LEGACY')"
        )).scalar_one()
        if unsafe_runs:
            return "0087 无法安全降级：Dagu 执行或已归档的 Jenkins 历史不能在降级中重建"
    config_columns = _columns("automation_integration_config")
    if "dagu_api_key_encrypted" in config_columns:
        secrets_present = bind.execute(sa.text(
            "SELECT count(*) FROM automation_integration_config "
            "WHERE dagu_api_key_encrypted IS NOT NULL AND dagu_api_key_encrypted <> ''"
        )).scalar_one()
        if secrets_present:
            return "0087 无法安全降级：Dagu API Key 密文会在删除列时丢失"
    return None


def _restore_jenkins_schema() -> None:
    """在没有不可恢复数据时，把 0087 删除的 Jenkins 列和空凭据表加回来。"""
    _add_column(
        "automation_integration_config",
        sa.Column("allow_private_network", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column("automation_execution", sa.Column("external_queue_id", sa.String(64), nullable=True))
    _add_column("automation_execution", sa.Column("external_build_number", sa.Integer(), nullable=True))
    _add_column("automation_execution", sa.Column("queue_missing_since", sa.DateTime(), nullable=True))
    if "automation_jenkins_credential" not in set(_inspector().get_table_names()):
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
        )
    indexes = _indexes("automation_execution")
    if "uq_automation_execution_jenkins_queue" not in indexes and "external_queue_id" in _columns("automation_execution"):
        op.create_index(
            "uq_automation_execution_jenkins_queue", "automation_execution",
            ["integration_config_id", "external_queue_id"], unique=True,
            postgresql_where=sa.text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_queue_id IS NOT NULL"
            ),
        )
    if "uq_automation_execution_jenkins_build" not in indexes and "external_build_number" in _columns("automation_execution"):
        op.create_index(
            "uq_automation_execution_jenkins_build", "automation_execution",
            ["integration_config_id", "external_pipeline_id", "external_build_number"], unique=True,
            postgresql_where=sa.text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_build_number IS NOT NULL"
            ),
        )
    for name in ("dagu_base_url", "dagu_api_key_encrypted", "dagu_api_key_configured"):
        if name in _columns("automation_integration_config"):
            op.drop_column("automation_integration_config", name)


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
    """没有 Dagu/LEGACY 数据时恢复 Jenkins 表结构；有历史数据时保持单向保护。"""
    reason = _unsafe_downgrade_reason()
    if reason:
        raise RuntimeError(reason + "；请恢复数据库备份")
    if "automation_integration_config" not in set(_inspector().get_table_names()):
        return
    _restore_jenkins_schema()
