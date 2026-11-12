"""新增测试管理 13 张表（test_management feature-local）。

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-13

延续 0002/0003/0004 风格：显式 op.create_table（0001 之后的表不能再用 create_all），
幂等保护（inspect 检查表存在性，索引用 IF NOT EXISTS）。seed_admin.py 每次
stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。

模型**不**加入 app/models/__init__.py（feature-local），由本迁移显式建表。
建表顺序遵循外键依赖：strategy → point → case → case 子表 → suite → suite_case →
plan → plan_suite → run → case_execution。
跨域引用：api_interface.id（0003）、business_flow.id / business_action.id（0004）、
environment.id（0001）、project.id（0001）均用 ondelete=SET NULL，避免级联删除测试资产。
所有资产表预留 source_type 字段，为未来 source_type=AI 留位（本阶段不接入 LLM/Agent）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


# 表创建顺序（遵循外键依赖：父表先于子表）。
_TABLES_IN_ORDER = [
    "test_strategy",
    "test_point",
    "test_case",
    "test_case_precondition",
    "test_case_data",
    "test_step",
    "test_assertion",
    "test_suite",
    "test_suite_case",
    "test_plan",
    "test_plan_suite",
    "test_run",
    "case_execution",
]


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "test_strategy": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("category", sa.String(length=50), server_default=text("'FUNCTIONAL'"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("source_type", sa.String(length=20), server_default=text("'MANUAL'"), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_strategy"),
            sa.UniqueConstraint("project_id", "name", name="uq_test_strategy_project_name"),
        ],
        "test_point": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("strategy_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("priority", sa.String(length=10), server_default=text("'P1'"), nullable=False),
            sa.Column("target_type", sa.String(length=20), server_default=text("'API'"), nullable=False),
            sa.Column("api_id", sa.Integer(), nullable=True),
            sa.Column("business_flow_id", sa.Integer(), nullable=True),
            sa.Column("business_action_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'DRAFT'"), nullable=False),
            sa.Column("source_type", sa.String(length=20), server_default=text("'MANUAL'"), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["strategy_id"], ["test_strategy.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["api_id"], ["api_interface.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["business_flow_id"], ["business_flow.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["business_action_id"], ["business_action.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_point"),
            sa.UniqueConstraint("project_id", "name", name="uq_test_point_project_name"),
        ],
        "test_case": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("test_point_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("priority", sa.String(length=10), server_default=text("'P1'"), nullable=False),
            sa.Column("case_type", sa.String(length=30), server_default=text("'FUNCTIONAL'"), nullable=False),
            sa.Column("target_type", sa.String(length=20), server_default=text("'API'"), nullable=False),
            sa.Column("api_id", sa.Integer(), nullable=True),
            sa.Column("business_flow_id", sa.Integer(), nullable=True),
            sa.Column("business_action_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'DRAFT'"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("revision", sa.Integer(), server_default=text("1"), nullable=False),
            sa.Column("source_type", sa.String(length=20), server_default=text("'MANUAL'"), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_point_id"], ["test_point.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["api_id"], ["api_interface.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["business_flow_id"], ["business_flow.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["business_action_id"], ["business_action.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_case"),
            sa.UniqueConstraint("project_id", "name", name="uq_test_case_project_name"),
        ],
        "test_case_precondition": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("type", sa.String(length=30), server_default=text("'VARIABLE'"), nullable=False),
            sa.Column("target", sa.String(length=200), nullable=True),
            sa.Column("operator", sa.String(length=20), server_default=text("'EQ'"), nullable=False),
            sa.Column("expected_value", sa.Text(), nullable=True),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("config_json", sa.JSON(), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["test_case_id"], ["test_case.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_test_case_precondition"),
        ],
        "test_case_data": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("value_type", sa.String(length=20), server_default=text("'STRING'"), nullable=False),
            sa.Column("value", sa.Text(), nullable=True),
            sa.Column("source_type", sa.String(length=20), server_default=text("'STATIC'"), nullable=False),
            sa.Column("required", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("config_json", sa.JSON(), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["test_case_id"], ["test_case.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_test_case_data"),
            sa.UniqueConstraint("test_case_id", "name", name="uq_test_case_data_case_name"),
        ],
        "test_step": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("step_type", sa.String(length=20), server_default=text("'ACTION'"), nullable=False),
            sa.Column("target_type", sa.String(length=20), nullable=True),
            sa.Column("target_id", sa.Integer(), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["test_case_id"], ["test_case.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_test_step"),
        ],
        "test_assertion": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("step_id", sa.Integer(), nullable=True),
            sa.Column("assertion_type", sa.String(length=30), server_default=text("'STATUS_CODE'"), nullable=False),
            sa.Column("source", sa.String(length=100), nullable=True),
            sa.Column("path", sa.String(length=500), nullable=True),
            sa.Column("operator", sa.String(length=20), server_default=text("'EQ'"), nullable=False),
            sa.Column("expected_value", sa.Text(), nullable=True),
            sa.Column("required", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["test_case_id"], ["test_case.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["step_id"], ["test_step.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_assertion"),
        ],
        "test_suite": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("suite_type", sa.String(length=20), server_default=text("'REGRESSION'"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_suite"),
            sa.UniqueConstraint("project_id", "name", name="uq_test_suite_project_name"),
        ],
        "test_suite_case": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("suite_id", sa.Integer(), nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["suite_id"], ["test_suite.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_case_id"], ["test_case.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_test_suite_case"),
            sa.UniqueConstraint("suite_id", "test_case_id", name="uq_test_suite_case_suite_case"),
        ],
        "test_plan": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'DRAFT'"), nullable=False),
            sa.Column("execution_mode", sa.String(length=20), server_default=text("'MANUAL'"), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_plan"),
            sa.UniqueConstraint("project_id", "name", name="uq_test_plan_project_name"),
        ],
        "test_plan_suite": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("plan_id", sa.Integer(), nullable=False),
            sa.Column("suite_id", sa.Integer(), nullable=False),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["plan_id"], ["test_plan.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["suite_id"], ["test_suite.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_test_plan_suite"),
            sa.UniqueConstraint("plan_id", "suite_id", name="uq_test_plan_suite_plan_suite"),
        ],
        "test_run": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("plan_id", sa.Integer(), nullable=True),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'PENDING'"), nullable=False),
            sa.Column("total", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("passed", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("failed", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("skipped", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("error", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["plan_id"], ["test_plan.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_run"),
        ],
        "case_execution": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("test_run_id", sa.Integer(), nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'PENDING'"), nullable=False),
            sa.Column("executor_type", sa.String(length=20), nullable=True),
            sa.Column("request_snapshot", sa.JSON(), nullable=True),
            sa.Column("response_snapshot", sa.JSON(), nullable=True),
            sa.Column("assertion_results", sa.JSON(), nullable=True),
            sa.Column("context_json", sa.JSON(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("error_code", sa.String(length=50), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["test_run_id"], ["test_run.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_case_id"], ["test_case.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_case_execution"),
        ],
    }


# 每张表的非唯一索引（与 ORM index=True / __table_args__ Index 一一对应）。
_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "test_strategy": [
        ("ix_test_strategy_id", ["id"]),
        ("ix_test_strategy_project_id", ["project_id"]),
        ("ix_test_strategy_category", ["category"]),
        ("ix_test_strategy_project_category", ["project_id", "category"]),
    ],
    "test_point": [
        ("ix_test_point_id", ["id"]),
        ("ix_test_point_project_id", ["project_id"]),
        ("ix_test_point_strategy_id", ["strategy_id"]),
        ("ix_test_point_target_type", ["target_type"]),
        ("ix_test_point_status", ["status"]),
        ("ix_test_point_project_status", ["project_id", "status"]),
    ],
    "test_case": [
        ("ix_test_case_id", ["id"]),
        ("ix_test_case_project_id", ["project_id"]),
        ("ix_test_case_test_point_id", ["test_point_id"]),
        ("ix_test_case_target_type", ["target_type"]),
        ("ix_test_case_status", ["status"]),
        ("ix_test_case_project_status", ["project_id", "status"]),
        ("ix_test_case_project_target", ["project_id", "target_type"]),
    ],
    "test_case_precondition": [
        ("ix_test_case_precondition_id", ["id"]),
        ("ix_test_case_precondition_test_case_id", ["test_case_id"]),
    ],
    "test_case_data": [
        ("ix_test_case_data_id", ["id"]),
        ("ix_test_case_data_test_case_id", ["test_case_id"]),
    ],
    "test_step": [
        ("ix_test_step_id", ["id"]),
        ("ix_test_step_test_case_id", ["test_case_id"]),
        ("ix_test_step_sort", ["sort"]),
    ],
    "test_assertion": [
        ("ix_test_assertion_id", ["id"]),
        ("ix_test_assertion_test_case_id", ["test_case_id"]),
    ],
    "test_suite": [
        ("ix_test_suite_id", ["id"]),
        ("ix_test_suite_project_id", ["project_id"]),
        ("ix_test_suite_enabled", ["enabled"]),
        ("ix_test_suite_project_enabled", ["project_id", "enabled"]),
    ],
    "test_suite_case": [
        ("ix_test_suite_case_id", ["id"]),
        ("ix_test_suite_case_suite_id", ["suite_id"]),
        ("ix_test_suite_case_test_case_id", ["test_case_id"]),
        ("ix_test_suite_case_suite_sort", ["suite_id", "sort"]),
    ],
    "test_plan": [
        ("ix_test_plan_id", ["id"]),
        ("ix_test_plan_project_id", ["project_id"]),
        ("ix_test_plan_environment_id", ["environment_id"]),
        ("ix_test_plan_status", ["status"]),
        ("ix_test_plan_project_status", ["project_id", "status"]),
    ],
    "test_plan_suite": [
        ("ix_test_plan_suite_id", ["id"]),
        ("ix_test_plan_suite_plan_id", ["plan_id"]),
        ("ix_test_plan_suite_suite_id", ["suite_id"]),
        ("ix_test_plan_suite_plan_sort", ["plan_id", "sort"]),
    ],
    "test_run": [
        ("ix_test_run_id", ["id"]),
        ("ix_test_run_project_id", ["project_id"]),
        ("ix_test_run_plan_id", ["plan_id"]),
        ("ix_test_run_environment_id", ["environment_id"]),
        ("ix_test_run_status", ["status"]),
    ],
    "case_execution": [
        ("ix_case_execution_id", ["id"]),
        ("ix_case_execution_test_run_id", ["test_run_id"]),
        ("ix_case_execution_test_case_id", ["test_case_id"]),
        ("ix_case_execution_status", ["status"]),
    ],
}

# 表注释（与 ORM __table_args__ comment 对齐）。
_TABLE_COMMENTS: dict[str, str] = {
    "test_strategy": "测试策略：项目下某一测试维度的策略定义",
    "test_point": "测试点：从策略细化的具体验证场景",
    "test_case": "测试用例：可执行、可断言、可复用的测试资产核心实体",
    "test_case_precondition": "测试用例前置条件",
    "test_case_data": "测试用例数据项",
    "test_step": "测试步骤",
    "test_assertion": "测试断言",
    "test_suite": "测试套件：测试用例的集合容器",
    "test_suite_case": "套件-用例关联",
    "test_plan": "测试计划：组织套件与环境的执行单元",
    "test_plan_suite": "计划-套件关联",
    "test_run": "测试计划执行记录",
    "case_execution": "用例执行记录",
}


def upgrade() -> None:
    """正向迁移：建 13 张表 + 索引（幂等）。"""
    from sqlalchemy import inspect

    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    definitions = _table_definitions()

    for table in _TABLES_IN_ORDER:
        if table in existing_tables:
            continue
        op.create_table(
            table,
            *definitions[table],
            comment=_TABLE_COMMENTS.get(table),
        )

    # 索引：逐表 IF NOT EXISTS 补齐，允许在已建索引的库上安全重放。
    for table in _TABLES_IN_ORDER:
        if table not in inspect(bind).get_table_names():
            continue
        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table)}
        for name, columns in _INDEX_DEFINITIONS.get(table, []):
            if name in existing_indexes:
                continue
            columns_sql = ", ".join(f'"{c}"' for c in columns)
            bind.execute(
                text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns_sql})")
            )


def downgrade() -> None:
    """反向迁移：删 13 张表及其索引（全 IF EXISTS，可安全重放）。"""
    bind = op.get_bind()
    # 先删索引（含唯一约束产生的索引）再删表；按外键依赖逆序删表。
    for table in reversed(_TABLES_IN_ORDER):
        for name, _columns in _INDEX_DEFINITIONS.get(table, []):
            bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
