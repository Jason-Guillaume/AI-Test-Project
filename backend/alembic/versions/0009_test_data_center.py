"""新增测试数据中心 + Data Factory 全部表（Phase A，feature-local）。

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-14

延续 0006/0007/0008 风格：显式 op.create_table（0001 之后的表不能再用 create_all），
幂等保护（inspect 检查表存在性，索引用 CREATE [UNIQUE] INDEX IF NOT EXISTS）。
seed_admin.py 每次 stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。

新增 17 张表（按外键依赖排序）：
- fixture / fixture_dependency / fixture_step / fixture_output：Fixture 定义（配方 + 依赖 + 步骤 + 输出契约）
- data_provider：数据工厂 Provider 配置
- test_data_asset：测试数据目录项
- data_pool / data_pool_item / data_pool_lease：数据池与租约
- target_database_connection：被测库连接（password 只存加密串）
- database_access_policy：数据库访问策略（表白名单 + 操作白名单）
- data_execution / fixture_execution / provider_execution：造数执行记录
- fixture_cache：按 scope 的 Fixture 输出缓存
- test_case_fixture：用例声明所需 Fixture
- td_sandbox_task：仅供测试用的 sandbox 表（DATABASE Provider 白名单验证，不属业务域）

`case_execution` 增加 3 个可空 cleanup 列（cleanup_status / cleanup_error_code /
cleanup_error_message）。Cleanup 失败不覆盖既有 error_code / error_message / status。

模型**不**加入 app/models/__init__.py（feature-local，由本迁移显式建表，红线 17）。
api_interface / business_flow / business_action **不建**跨 feature FK（§20 风险结论：
执行时报 API_NOT_FOUND → 用例 ERROR，保持删除接口的既有 204 行为）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


# 新建表（严格按外键依赖排序，downgrade 逆序删除）。
_NEW_TABLES = [
    "fixture",
    "fixture_dependency",
    "data_provider",
    "fixture_step",
    "fixture_output",
    "test_data_asset",
    "data_pool",
    "data_pool_item",
    "data_pool_lease",
    "target_database_connection",
    "database_access_policy",
    "data_execution",
    "fixture_execution",
    "provider_execution",
    "fixture_cache",
    "test_case_fixture",
    "td_sandbox_task",
]

# case_execution 增量列（可空，无默认值，老数据不受影响）。
_CASE_EXECUTION_COLUMNS: dict[str, sa.Column] = {
    "cleanup_status": sa.Column("cleanup_status", sa.String(length=20), nullable=True),
    "cleanup_error_code": sa.Column("cleanup_error_code", sa.String(length=50), nullable=True),
    "cleanup_error_message": sa.Column("cleanup_error_message", sa.Text(), nullable=True),
}


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "fixture": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("fixture_key", sa.String(length=100), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("scope", sa.String(length=20), server_default=text("'CASE'"), nullable=False),
            sa.Column("status", sa.String(length=20), server_default=text("'DRAFT'"), nullable=False),
            sa.Column("cache_enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column(
                "cleanup_policy", sa.String(length=20),
                server_default=text("'AFTER_CASE'"), nullable=False,
            ),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_fixture"),
            # 部分唯一索引在 _PARTIAL_INDEXES 里单独创建（op.create_table 不支持 WHERE）。
            sa.UniqueConstraint("project_id", "fixture_key", name="uq_fixture_project_key"),
        ],
        "fixture_dependency": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("fixture_id", sa.Integer(), nullable=False),
            sa.Column("depends_on_fixture_id", sa.Integer(), nullable=False),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.ForeignKeyConstraint(["fixture_id"], ["fixture.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["depends_on_fixture_id"], ["fixture.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id", name="pk_fixture_dependency"),
            sa.UniqueConstraint(
                "fixture_id", "depends_on_fixture_id", name="uq_fixture_dependency"
            ),
        ],
        "data_provider": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("provider_type", sa.String(length=30), nullable=False),
            sa.Column("config_json", sa.JSON(), server_default=text("'{}'"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("risk_level", sa.String(length=20), server_default=text("'MEDIUM'"), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_data_provider"),
            sa.UniqueConstraint("project_id", "name", name="uq_data_provider_project_name"),
        ],
        "fixture_step": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("fixture_id", sa.Integer(), nullable=False),
            sa.Column("phase", sa.String(length=20), server_default=text("'GENERATE'"), nullable=False),
            sa.Column("step_type", sa.String(length=30), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=True),
            sa.Column("config_json", sa.JSON(), nullable=True),
            sa.Column("on_failure", sa.String(length=20), server_default=text("'ABORT'"), nullable=False),
            sa.ForeignKeyConstraint(["fixture_id"], ["fixture.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["provider_id"], ["data_provider.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_fixture_step"),
        ],
        "fixture_output": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("fixture_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("value_type", sa.String(length=20), server_default=text("'STRING'"), nullable=False),
            sa.Column("source_path", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.ForeignKeyConstraint(["fixture_id"], ["fixture.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_fixture_output"),
            sa.UniqueConstraint("fixture_id", "name", name="uq_fixture_output_name"),
        ],
        "test_data_asset": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("entity_type", sa.String(length=50), nullable=False),
            sa.Column("source", sa.String(length=30), server_default=text("'STATIC'"), nullable=False),
            sa.Column("scope", sa.String(length=20), server_default=text("'PROJECT'"), nullable=False),
            sa.Column("status", sa.String(length=20), server_default=text("'ACTIVE'"), nullable=False),
            sa.Column("fixture_id", sa.Integer(), nullable=True),
            sa.Column("value_json", sa.JSON(), nullable=True),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["fixture_id"], ["fixture.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_data_asset"),
            sa.UniqueConstraint("project_id", "name", name="uq_test_data_asset_project_name"),
        ],
        "data_pool": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=True),
            sa.Column("pool_key", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("scope", sa.String(length=20), server_default=text("'PROJECT'"), nullable=False),
            sa.Column("max_concurrency", sa.Integer(), server_default=text("1"), nullable=False),
            sa.Column("lease_ttl_seconds", sa.Integer(), server_default=text("1800"), nullable=False),
            sa.Column("status", sa.String(length=20), server_default=text("'ACTIVE'"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["asset_id"], ["test_data_asset.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_data_pool"),
            sa.UniqueConstraint("project_id", "pool_key", name="uq_data_pool_project_key"),
        ],
        "data_pool_item": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("pool_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=20), server_default=text("'AVAILABLE'"), nullable=False),
            sa.Column("payload_json", sa.JSON(), server_default=text("'{}'"), nullable=False),
            sa.Column("occupied_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["pool_id"], ["data_pool.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_data_pool_item"),
        ],
        "data_pool_lease": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("item_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("test_run_id", sa.Integer(), nullable=True),
            sa.Column("case_execution_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'ACTIVE'"), nullable=False),
            sa.Column("leased_at", sa.DateTime(), nullable=True),
            sa.Column("released_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["item_id"], ["data_pool_item.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_run_id"], ["test_run.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["case_execution_id"], ["case_execution.id"], ondelete="SET NULL"
            ),
            sa.PrimaryKeyConstraint("id", name="pk_data_pool_lease"),
        ],
        "target_database_connection": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("host", sa.String(length=255), nullable=False),
            sa.Column("port", sa.Integer(), server_default=text("5432"), nullable=False),
            sa.Column("database_name", sa.String(length=128), nullable=False),
            sa.Column("username", sa.String(length=128), nullable=False),
            sa.Column("password_encrypted", sa.Text(), nullable=False),
            sa.Column("schema_name", sa.String(length=128), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            # environment 是被测环境锚点：删环境不应连带删连接配置（RESTRICT 由服务层挡住）。
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_target_database_connection"),
            sa.UniqueConstraint(
                "project_id", "environment_id", "name", name="uq_target_db_conn"
            ),
        ],
        "database_access_policy": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("allowed_tables", sa.JSON(), server_default=text("'[]'"), nullable=False),
            sa.Column(
                "allowed_operations", sa.JSON(),
                server_default=text("'[\"INSERT\", \"UPDATE\", \"SELECT\"]'"), nullable=False,
            ),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_database_access_policy"),
            sa.UniqueConstraint("project_id", "environment_id", name="uq_db_policy_project_env"),
        ],
        "data_execution": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("test_run_id", sa.Integer(), nullable=True),
            sa.Column("case_execution_id", sa.Integer(), nullable=True),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'PENDING'"), nullable=False),
            sa.Column("scope", sa.String(length=20), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(length=50), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("cleanup_status", sa.String(length=20), nullable=True),
            sa.Column("cleanup_error_code", sa.String(length=50), nullable=True),
            sa.Column("cleanup_error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_run_id"], ["test_run.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["case_execution_id"], ["case_execution.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_data_execution"),
        ],
        "fixture_execution": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("data_execution_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("fixture_id", sa.Integer(), nullable=True),
            sa.Column("fixture_key", sa.String(length=100), nullable=False),
            sa.Column("status", sa.String(length=20), server_default=text("'PENDING'"), nullable=False),
            sa.Column("scope", sa.String(length=20), server_default=text("'CASE'"), nullable=False),
            sa.Column("cache_hit", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("input_snapshot", sa.JSON(), nullable=True),
            sa.Column("output_snapshot", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(length=50), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("cleanup_status", sa.String(length=20), nullable=True),
            sa.Column("cleanup_error_code", sa.String(length=50), nullable=True),
            sa.Column("cleanup_error_message", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["data_execution_id"], ["data_execution.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            # Fixture 删除后记录仍可读（保留 fixture_key 快照）。
            sa.ForeignKeyConstraint(["fixture_id"], ["fixture.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_fixture_execution"),
        ],
        "provider_execution": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("fixture_execution_id", sa.Integer(), nullable=True),
            sa.Column("data_execution_id", sa.Integer(), nullable=True),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("provider_id", sa.Integer(), nullable=True),
            sa.Column("provider_type", sa.String(length=30), nullable=False),
            sa.Column("step_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'PENDING'"), nullable=False),
            sa.Column("input_snapshot", sa.JSON(), nullable=True),
            sa.Column("output_snapshot", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(length=50), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("cleanup_status", sa.String(length=20), nullable=True),
            sa.ForeignKeyConstraint(
                ["fixture_execution_id"], ["fixture_execution.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["data_execution_id"], ["data_execution.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            # Provider 删除后记录保留（便于排查历史执行）。
            sa.ForeignKeyConstraint(["provider_id"], ["data_provider.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_provider_execution"),
        ],
        "fixture_cache": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("fixture_id", sa.Integer(), nullable=False),
            sa.Column("scope", sa.String(length=20), server_default=text("'CASE'"), nullable=False),
            sa.Column("scope_key", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=20), server_default=text("'READY'"), nullable=False),
            sa.Column("output_json", sa.JSON(), server_default=text("'{}'"), nullable=False),
            sa.Column("ref_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("data_execution_id", sa.Integer(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["fixture_id"], ["fixture.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["data_execution_id"], ["data_execution.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_fixture_cache"),
            sa.UniqueConstraint(
                "project_id", "fixture_id", "scope", "scope_key", name="uq_fixture_cache_scope"
            ),
        ],
        "test_case_fixture": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("fixture_id", sa.Integer(), nullable=False),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["test_case_id"], ["test_case.id"], ondelete="CASCADE"),
            # RESTRICT：被引用的 Fixture 不允许直接删除（服务层先 409）。
            sa.ForeignKeyConstraint(["fixture_id"], ["fixture.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id", name="pk_test_case_fixture"),
            sa.UniqueConstraint("test_case_id", "fixture_id", name="uq_test_case_fixture"),
        ],
        "td_sandbox_task": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column(
                "status", sa.String(length=30), server_default=text("'PENDING'"), nullable=False
            ),
            sa.Column("name", sa.String(length=200), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_td_sandbox_task"),
        ],
    }


# 每张表的非唯一索引（与 ORM __table_args__ Index 一一对应）。
_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "fixture": [
        ("ix_fixture_id", ["id"]),
        ("ix_fixture_project_id", ["project_id"]),
        ("ix_fixture_project_status", ["project_id", "status"]),
        ("ix_fixture_project_entity", ["project_id", "entity_type"]),
    ],
    "fixture_dependency": [
        ("ix_fixture_dependency_id", ["id"]),
        ("ix_fixture_dependency_fixture_id", ["fixture_id"]),
        ("ix_fixture_dependency_depends_on_fixture_id", ["depends_on_fixture_id"]),
    ],
    "data_provider": [
        ("ix_data_provider_id", ["id"]),
        ("ix_data_provider_project_id", ["project_id"]),
        ("ix_data_provider_project_type", ["project_id", "provider_type", "enabled"]),
    ],
    "fixture_step": [
        ("ix_fixture_step_id", ["id"]),
        ("ix_fixture_step_fixture_id", ["fixture_id"]),
        ("ix_fixture_step_provider_id", ["provider_id"]),
        ("ix_fixture_step_fixture_phase_sort", ["fixture_id", "phase", "sort"]),
    ],
    "fixture_output": [
        ("ix_fixture_output_id", ["id"]),
        ("ix_fixture_output_fixture_id", ["fixture_id"]),
    ],
    "test_data_asset": [
        ("ix_test_data_asset_id", ["id"]),
        ("ix_test_data_asset_project_id", ["project_id"]),
        ("ix_test_data_asset_fixture_id", ["fixture_id"]),
        ("ix_test_data_asset_project_entity", ["project_id", "entity_type", "status"]),
    ],
    "data_pool": [
        ("ix_data_pool_id", ["id"]),
        ("ix_data_pool_project_id", ["project_id"]),
        ("ix_data_pool_asset_id", ["asset_id"]),
    ],
    "data_pool_item": [
        ("ix_data_pool_item_id", ["id"]),
        ("ix_data_pool_item_pool_id", ["pool_id"]),
        ("ix_data_pool_item_available", ["pool_id", "status"]),
    ],
    "data_pool_lease": [
        ("ix_data_pool_lease_id", ["id"]),
        ("ix_data_pool_lease_item_id", ["item_id"]),
        ("ix_data_pool_lease_project_id", ["project_id"]),
        ("ix_data_pool_lease_test_run_id", ["test_run_id"]),
        ("ix_data_pool_lease_case_execution_id", ["case_execution_id"]),
        ("ix_data_pool_lease_status", ["status"]),
    ],
    "target_database_connection": [
        ("ix_target_database_connection_id", ["id"]),
        ("ix_target_database_connection_project_id", ["project_id"]),
        ("ix_target_database_connection_environment_id", ["environment_id"]),
    ],
    "database_access_policy": [
        ("ix_database_access_policy_id", ["id"]),
        ("ix_database_access_policy_project_id", ["project_id"]),
        ("ix_database_access_policy_environment_id", ["environment_id"]),
    ],
    "data_execution": [
        ("ix_data_execution_id", ["id"]),
        ("ix_data_execution_project_id", ["project_id"]),
        ("ix_data_execution_test_run_id", ["test_run_id"]),
        ("ix_data_execution_case_execution_id", ["case_execution_id"]),
        ("ix_data_execution_environment_id", ["environment_id"]),
        ("ix_data_execution_status", ["status"]),
        ("ix_data_execution_project_created", ["project_id", "created_at"]),
    ],
    "fixture_execution": [
        ("ix_fixture_execution_id", ["id"]),
        ("ix_fixture_execution_data_execution_id", ["data_execution_id"]),
        ("ix_fixture_execution_project_id", ["project_id"]),
        ("ix_fixture_execution_fixture_id", ["fixture_id"]),
        ("ix_fixture_execution_fixture_key", ["fixture_key"]),
        ("ix_fixture_execution_status", ["status"]),
    ],
    "provider_execution": [
        ("ix_provider_execution_id", ["id"]),
        ("ix_provider_execution_fixture_execution_id", ["fixture_execution_id"]),
        ("ix_provider_execution_data_execution_id", ["data_execution_id"]),
        ("ix_provider_execution_project_id", ["project_id"]),
        ("ix_provider_execution_provider_id", ["provider_id"]),
        ("ix_provider_execution_provider_type", ["provider_type"]),
        ("ix_provider_execution_status", ["status"]),
    ],
    "fixture_cache": [
        ("ix_fixture_cache_id", ["id"]),
        ("ix_fixture_cache_project_id", ["project_id"]),
        ("ix_fixture_cache_fixture_id", ["fixture_id"]),
        ("ix_fixture_cache_status", ["status"]),
        ("ix_fixture_cache_expires_at", ["expires_at"]),
    ],
    "test_case_fixture": [
        ("ix_test_case_fixture_id", ["id"]),
        ("ix_test_case_fixture_test_case_id", ["test_case_id"]),
        ("ix_test_case_fixture_fixture_id", ["fixture_id"]),
    ],
    "td_sandbox_task": [
        ("ix_td_sandbox_task_id", ["id"]),
        ("ix_td_sandbox_task_status", ["status"]),
    ],
}

# 部分唯一索引：两个项目不能发布同一个 GLOBAL fixture_key（§4.1）。
_PARTIAL_INDEXES: list[tuple[str, str, str]] = [
    (
        "uq_fixture_global_key",
        "fixture",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_fixture_global_key ON fixture (\"fixture_key\") "
        "WHERE scope = 'GLOBAL'",
    ),
]

# 表注释（与 ORM __table_args__ comment 对齐）。
_TABLE_COMMENTS: dict[str, str] = {
    "fixture": "Fixture：测试需要的业务状态配方（非静态 JSON 结果）",
    "fixture_dependency": "Fixture 显式依赖边（环检测与执行顺序）",
    "data_provider": "数据工厂 Provider 配置（config_json 禁止密码，连接只存 connection_id）",
    "fixture_step": "Fixture 步骤（GENERATE/CLEANUP，config_json 按 step_type 约定）",
    "fixture_output": "Fixture 输出契约：用例只能引用这里声明的名字",
    "test_data_asset": "测试数据目录项：静态样本 / 池分组 / Fixture 登记的可检索数据",
    "data_pool": "数据池：可并发占用的共享测试数据集合",
    "data_pool_item": "池条目：payload 脱敏后落库，占用计数由执行引擎维护",
    "data_pool_lease": "池租约：绑定 TestRun / CaseExecution，Run 结束必须释放",
    "target_database_connection": "被测库连接（非平台库），password 只存 encrypt_secret 结果",
    "database_access_policy": "数据库访问策略：表白名单 + 操作白名单，PRODUCTION 强制关闭",
    "data_execution": "造数总记录：一次用例/Run 级准备/手工试跑",
    "fixture_execution": "Fixture 单次执行：输入输出快照已脱敏",
    "provider_execution": "Provider 单步执行：input/output 快照已脱敏，_cleanup 存句柄",
    "fixture_cache": "Fixture 输出缓存：按 scope 共享，DIRTY 不可复用",
    "test_case_fixture": "用例声明所需 Fixture（不存运行时 ID）",
    "td_sandbox_task": "仅供测试的 sandbox 表（DATABASE Provider 白名单验证）",
}


def _existing_index_names(bind, table: str) -> set[str]:
    """读取库中该表已有的索引名（含部分索引、唯一约束自动生成的索引）。"""
    return {
        row[0]
        for row in bind.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = :t").bindparams(
                t=table
            )
        ).fetchall()
    }


def _create_indexes(bind) -> None:
    """按表补齐索引（含部分唯一索引），允许在已建索引的库上安全重放。"""
    for table in _NEW_TABLES:
        existing = _existing_index_names(bind, table)
        for name, columns in _INDEX_DEFINITIONS.get(table, []):
            if name in existing:
                continue
            columns_sql = ", ".join(f'"{c}"' for c in columns)
            bind.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns_sql})"))

    # 部分唯一索引单独创建：CREATE TABLE 无法表达 WHERE 条件。
    for name, table, statement in _PARTIAL_INDEXES:
        if name in _existing_index_names(bind, table):
            continue
        bind.execute(text(statement))


def upgrade() -> None:
    """正向迁移：建 17 张表 + 索引 + case_execution 三个 cleanup 列（全幂等）。"""
    bind = op.get_bind()
    inspector = bind.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")).fetchall()
    existing_tables = {row[0] for row in inspector}
    definitions = _table_definitions()

    # 1. 建表（幂等）。
    for table in _NEW_TABLES:
        if table in existing_tables:
            continue
        op.create_table(table, *definitions[table], comment=_TABLE_COMMENTS.get(table))

    # 2. 索引：逐表 IF NOT EXISTS 补齐，允许在已建索引的库上安全重放。
    _create_indexes(bind)

    # 3. case_execution 增量列（Cleanup 失败不得覆盖既有 error_code/error_message）。
    # 用位置下标取值：bind.execute(...).fetchall() 返回 tuple 行，不是 Mapping。
    columns = {row[0] for row in bind.execute(text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'case_execution' "
        "AND table_schema = current_schema()"
    )).fetchall()}
    for name, column in _CASE_EXECUTION_COLUMNS.items():
        if name in columns:
            continue
        op.add_column("case_execution", column)
        bind.execute(text(
            f"COMMENT ON COLUMN case_execution.{name} IS '{_case_column_comment(name)}'"
        ))


def _case_column_comment(name: str) -> str:
    """case_execution 三个 cleanup 列的中文注释。"""
    return {
        "cleanup_status": "清理状态：PENDING/SUCCESS/FAILED/SKIPPED（不覆盖 status 与 error_code）",
        "cleanup_error_code": "清理失败错误码（仅 cleanup_* 字段，不改原错误码）",
        "cleanup_error_message": "清理失败原因（多步骤拼接，截断 2000 字）",
    }.get(name, "")


def downgrade() -> None:
    """反向迁移：删 case_execution 列 + 17 张表及其索引（全 IF EXISTS，逆序可安全重放）。"""
    bind = op.get_bind()

    # 1. 先删 case_execution 的增量列。
    for name in reversed(list(_CASE_EXECUTION_COLUMNS)):
        bind.execute(text(f"ALTER TABLE case_execution DROP COLUMN IF EXISTS {name}"))

    # 2. 部分唯一索引。
    for name, _table, _statement in _PARTIAL_INDEXES:
        bind.execute(text(f"DROP INDEX IF EXISTS {name}"))

    # 3. 逆序删表。
    for table in reversed(_NEW_TABLES):
        for name, _columns in _INDEX_DEFINITIONS.get(table, []):
            bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
