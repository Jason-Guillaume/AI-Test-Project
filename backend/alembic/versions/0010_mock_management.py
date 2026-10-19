"""新增 Mock Management Phase 1 全部表（feature-local）。

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-15

延续 0006-0009 风格：显式 op.create_table（0001 之后不能用 create_all），幂等保护
（inspect 检查表存在性，索引用 CREATE [UNIQUE] INDEX IF NOT EXISTS）。seed_admin.py
每次 stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。

新增 7 张表（按外键依赖排序）：
- mock_service：Mock 依赖服务（service_key 项目内唯一，runtime_token_hash 只存哈希）
- mock_endpoint：Mock 接口（method + path 匹配，api_id 可空关联 API Catalog）
- mock_scenario：接口场景（behavior_type + 响应配置；per-endpoint 唯一 is_default）
- mock_matcher：场景匹配规则（source/field/operator/expected_value）
- mock_context：CaseExecution 激活的执行作用域（scenario_overrides，并发隔离）
- mock_execution：Mock Runtime 调用记录（快照经 SensitiveDataMasker 脱敏）
- test_case_mock：用例声明的 required_mocks（service/endpoint/scenario + scope）

模型 feature-local，不进 app/models/__init__.py（红线 17），由本迁移显式建表。
mock_service.default_scenario_id 不建 FK（避免 service ↔ scenario 循环依赖），由服务层校验。
不修改已有表（不加列），case_execution 的 Mock 关联通过 mock_context/mock_execution 反查。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


# 新建表（严格按外键依赖排序，downgrade 逆序删除）。
_NEW_TABLES = [
    "mock_service",
    "mock_endpoint",
    "mock_scenario",
    "mock_matcher",
    "mock_context",
    "mock_execution",
    "test_case_mock",
]


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "mock_service": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("service_key", sa.String(length=100), nullable=False),
            sa.Column("base_path", sa.String(length=500), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("default_scenario_id", sa.Integer(), nullable=True),
            sa.Column("public_runtime", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("runtime_token_hash", sa.String(length=128), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("revision", sa.Integer(), server_default=text("1"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_mock_service"),
            sa.UniqueConstraint("project_id", "service_key", name="uq_mock_service_project_key"),
        ],
        "mock_endpoint": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("mock_service_id", sa.Integer(), nullable=False),
            sa.Column("api_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("method", sa.String(length=10), nullable=False),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("revision", sa.Integer(), server_default=text("1"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["mock_service_id"], ["mock_service.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["api_id"], ["api_interface.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_mock_endpoint"),
            sa.UniqueConstraint(
                "mock_service_id", "method", "path", name="uq_mock_endpoint_service_method_path"
            ),
        ],
        "mock_scenario": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("mock_endpoint_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("scenario_key", sa.String(length=100), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("is_default", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("priority", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column(
                "behavior_type", sa.String(length=30),
                server_default=text("'STATIC_RESPONSE'"), nullable=False,
            ),
            sa.Column("delay_ms", sa.Integer(), nullable=True),
            sa.Column("status_code", sa.Integer(), server_default=text("200"), nullable=False),
            sa.Column("response_headers", sa.JSON(), nullable=True),
            sa.Column("response_body", sa.JSON(), nullable=True),
            sa.Column("response_template", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("revision", sa.Integer(), server_default=text("1"), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["mock_endpoint_id"], ["mock_endpoint.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_mock_scenario"),
            sa.UniqueConstraint(
                "mock_endpoint_id", "scenario_key", name="uq_mock_scenario_endpoint_key"
            ),
        ],
        "mock_matcher": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("scenario_id", sa.Integer(), nullable=False),
            sa.Column("source", sa.String(length=20), nullable=False),
            sa.Column("field", sa.String(length=200), nullable=False),
            sa.Column("operator", sa.String(length=30), nullable=False),
            sa.Column("expected_value", sa.JSON(), nullable=True),
            sa.Column("priority", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["scenario_id"], ["mock_scenario.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_mock_matcher"),
        ],
        "mock_context": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("context_id", sa.String(length=64), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("test_run_id", sa.Integer(), nullable=True),
            sa.Column("case_execution_id", sa.Integer(), nullable=True),
            sa.Column("scenario_overrides", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'ACTIVE'"), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("closed_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_run_id"], ["test_run.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["case_execution_id"], ["case_execution.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_mock_context"),
            sa.UniqueConstraint("context_id", name="uq_mock_context_id"),
        ],
        "mock_execution": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("mock_service_id", sa.Integer(), nullable=True),
            sa.Column("mock_endpoint_id", sa.Integer(), nullable=True),
            sa.Column("mock_scenario_id", sa.Integer(), nullable=True),
            sa.Column("request_id", sa.String(length=64), nullable=True),
            sa.Column("method", sa.String(length=10), nullable=False),
            sa.Column("path", sa.String(length=500), nullable=False),
            sa.Column("query_snapshot", sa.JSON(), nullable=True),
            sa.Column("header_snapshot", sa.JSON(), nullable=True),
            sa.Column("body_snapshot", sa.JSON(), nullable=True),
            sa.Column("response_status", sa.Integer(), nullable=True),
            sa.Column("response_header_snapshot", sa.JSON(), nullable=True),
            sa.Column("response_body_snapshot", sa.JSON(), nullable=True),
            sa.Column("matched", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(length=50), nullable=True),
            sa.Column("error_message", sa.String(length=2000), nullable=True),
            sa.Column("test_run_id", sa.Integer(), nullable=True),
            sa.Column("case_execution_id", sa.Integer(), nullable=True),
            sa.Column("mock_context_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["mock_service_id"], ["mock_service.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["mock_endpoint_id"], ["mock_endpoint.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["mock_scenario_id"], ["mock_scenario.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_mock_execution"),
        ],
        "test_case_mock": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("mock_service_id", sa.Integer(), nullable=False),
            sa.Column("mock_endpoint_id", sa.Integer(), nullable=False),
            sa.Column("mock_scenario_id", sa.Integer(), nullable=False),
            sa.Column("scope", sa.String(length=20), server_default=text("'EXECUTION'"), nullable=False),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["test_case_id"], ["test_case.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["mock_service_id"], ["mock_service.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["mock_endpoint_id"], ["mock_endpoint.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["mock_scenario_id"], ["mock_scenario.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_test_case_mock"),
            sa.UniqueConstraint(
                "test_case_id", "mock_scenario_id", name="uq_test_case_mock_case_scenario"
            ),
        ],
    }


_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "mock_service": [
        ("ix_mock_service_id", ["id"]),
        ("ix_mock_service_project_id", ["project_id"]),
        ("ix_mock_service_project_enabled", ["project_id", "enabled"]),
    ],
    "mock_endpoint": [
        ("ix_mock_endpoint_id", ["id"]),
        ("ix_mock_endpoint_project_id", ["project_id"]),
        ("ix_mock_endpoint_service_id", ["mock_service_id"]),
        ("ix_mock_endpoint_api_id", ["api_id"]),
        ("ix_mock_endpoint_service_enabled", ["mock_service_id", "enabled"]),
    ],
    "mock_scenario": [
        ("ix_mock_scenario_id", ["id"]),
        ("ix_mock_scenario_project_id", ["project_id"]),
        ("ix_mock_scenario_endpoint_id", ["mock_endpoint_id"]),
        ("ix_mock_scenario_endpoint_enabled", ["mock_endpoint_id", "enabled"]),
    ],
    "mock_matcher": [
        ("ix_mock_matcher_id", ["id"]),
        ("ix_mock_matcher_project_id", ["project_id"]),
        ("ix_mock_matcher_scenario_id", ["scenario_id"]),
        ("ix_mock_matcher_scenario_enabled", ["scenario_id", "enabled"]),
    ],
    "mock_context": [
        ("ix_mock_context_id", ["id"]),
        ("ix_mock_context_project_id", ["project_id"]),
        ("ix_mock_context_project_status", ["project_id", "status"]),
        ("ix_mock_context_run", ["test_run_id"]),
        ("ix_mock_context_case_execution", ["case_execution_id"]),
        ("ix_mock_context_expires", ["expires_at"]),
    ],
    "mock_execution": [
        ("ix_mock_execution_id", ["id"]),
        ("ix_mock_execution_project_id", ["project_id"]),
        ("ix_mock_execution_project_created", ["project_id", "created_at"]),
        ("ix_mock_execution_service", ["mock_service_id"]),
        ("ix_mock_execution_endpoint", ["mock_endpoint_id"]),
        ("ix_mock_execution_scenario", ["mock_scenario_id"]),
        ("ix_mock_execution_run", ["test_run_id"]),
        ("ix_mock_execution_case_execution", ["case_execution_id"]),
        ("ix_mock_execution_context", ["mock_context_id"]),
    ],
    "test_case_mock": [
        ("ix_test_case_mock_id", ["id"]),
        ("ix_test_case_mock_test_case_id", ["test_case_id"]),
        ("ix_test_case_mock_service_id", ["mock_service_id"]),
        ("ix_test_case_mock_endpoint_id", ["mock_endpoint_id"]),
        ("ix_test_case_mock_scenario_id", ["mock_scenario_id"]),
    ],
}

# 部分唯一索引：同一 Endpoint 只允许一个 is_default=true（§三十六）。
_PARTIAL_INDEXES: list[tuple[str, str, str]] = [
    (
        "uq_mock_scenario_default",
        "mock_scenario",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_mock_scenario_default ON mock_scenario "
        "(\"mock_endpoint_id\") WHERE is_default = true",
    ),
]

_TABLE_COMMENTS: dict[str, str] = {
    "mock_service": "Mock 依赖服务：service_key 项目内唯一",
    "mock_endpoint": "Mock 接口：method + path 匹配，api_id 可空关联 API Catalog",
    "mock_scenario": "Mock 场景：行为类型 + 响应配置 + 延迟/超时",
    "mock_matcher": "Mock 匹配规则：source/field/operator/expected_value",
    "mock_context": "Mock 执行作用域：X-Mock-Context 对应的 scenario_overrides",
    "mock_execution": "Mock 调用记录：请求/响应快照（敏感脱敏）+ 命中/耗时",
    "test_case_mock": "用例声明的 Mock 依赖：service/endpoint/scenario + scope",
}


def _existing_index_names(bind, table: str) -> set[str]:
    """读取库中该表已有的索引名（含部分索引、唯一约束自动生成的索引）。"""
    return {
        row[0]
        for row in bind.execute(
            text("SELECT indexname FROM pg_indexes WHERE tablename = :t").bindparams(t=table)
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
    """正向迁移：建 7 张表 + 索引（全幂等）。"""
    bind = op.get_bind()
    inspector = bind.execute(
        text(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
        )
    ).fetchall()
    existing_tables = {row[0] for row in inspector}
    definitions = _table_definitions()

    # 1. 建表（幂等）。
    for table in _NEW_TABLES:
        if table in existing_tables:
            continue
        op.create_table(table, *definitions[table], comment=_TABLE_COMMENTS.get(table))

    # 2. 索引：逐表 IF NOT EXISTS 补齐，允许在已建索引的库上安全重放。
    _create_indexes(bind)


def downgrade() -> None:
    """反向迁移：删 7 张表及其索引（全 IF EXISTS，逆序可安全重放）。"""
    bind = op.get_bind()

    # 1. 部分唯一索引。
    for name, _table, _statement in _PARTIAL_INDEXES:
        bind.execute(text(f"DROP INDEX IF EXISTS {name}"))

    # 2. 逆序删表。
    for table in reversed(_NEW_TABLES):
        for name, _columns in _INDEX_DEFINITIONS.get(table, []):
            bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
