"""新增 Security Testing Phase 1 全部表（feature-local）+ 系统内置策略。

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-15

延续 0006-0010 风格：显式 op.create_table（0001 之后不能用 create_all），幂等保护
（inspect 检查表存在性，索引用 CREATE [UNIQUE] INDEX IF NOT EXISTS）。seed_admin.py
每次 stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。

新增 7 张表（按外键依赖排序）：
- security_project_setting：项目级环境开关（allow_production 落库但不被执行器读取）
- security_strategy：安全策略（SYSTEM 模板 project_id 为空 / PROJECT 自定义）
- security_mutation_rule：结构化变异规则（算子白名单，禁止脚本）
- security_plan：人工确认前的计划（preview_json 快照，不是第二套 TestRun）
- security_case：安全用例扩展数据（与 test_case 一对一，不给 test_case 加列）
- security_execution：一次 CaseExecution 的安全细结果（不改 case_execution 列）
- security_finding：疑似问题（独立于 bug 表，Phase 1 不自动建缺陷）

模型 feature-local，不进 app/models/__init__.py（红线 17），由本迁移显式建表。
不修改 test_case / case_execution / test_run / test_report / environment 的列。

⚠️ 降级顺序（重要）：downgrade 只 DROP 上面 7 张表。已经生成的 test_case
（case_type='SECURITY'）行不在本迁移的管理范围内，DROP 后仍然留在库里，而且
executor 的安全分支读不到 security_case 了，会继续按普通 API 用例执行。
因此降级前必须先手工禁用这些用例，例如：

    UPDATE test_case SET enabled = false WHERE case_type = 'SECURITY';

本 downgrade 不写这条 UPDATE：迁移只负责自己建的表，业务状态由服务层或运维脚本
决定。0011 文件头在这里写明顺序，是因为降级是一个不可逆动作，漏了会留下
「能跑但会误判」的安全用例。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


# 新建表（严格按外键依赖排序，downgrade 逆序删除）。
_NEW_TABLES = [
    "security_project_setting",
    "security_strategy",
    "security_mutation_rule",
    "security_plan",
    "security_case",
    "security_execution",
    "security_finding",
]


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "security_project_setting": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column(
                "allow_dev", sa.Boolean(), server_default=text("true"), nullable=False
            ),
            sa.Column(
                "allow_test", sa.Boolean(), server_default=text("true"), nullable=False
            ),
            sa.Column(
                "allow_staging", sa.Boolean(), server_default=text("false"), nullable=False
            ),
            # 生产永远拒绝：服务层与执行器都不读这一列，留它只为记录用户意图。
            sa.Column(
                "allow_production", sa.Boolean(), server_default=text("false"), nullable=False
            ),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=func.now(), nullable=False
            ),
            sa.Column(
                "revision", sa.Integer(), server_default=text("1"), nullable=False
            ),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_security_project_setting"),
            sa.UniqueConstraint("project_id", name="uq_security_setting_project"),
        ],
        "security_strategy": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            # 可空：空 = 系统模板（scope=SYSTEM），删除平台项目时不会波及模板。
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("scope", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("strategy_key", sa.String(length=100), nullable=False),
            sa.Column("category", sa.String(length=40), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column(
                "enabled", sa.Boolean(), server_default=text("true"), nullable=False
            ),
            sa.Column(
                "risk_level", sa.String(length=20), server_default=text("'MEDIUM'"),
                nullable=False,
            ),
            sa.Column(
                "builtin", sa.Boolean(), server_default=text("false"), nullable=False
            ),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=func.now(), nullable=False
            ),
            sa.Column(
                "revision", sa.Integer(), server_default=text("1"), nullable=False
            ),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_security_strategy"),
            sa.UniqueConstraint(
                "project_id", "strategy_key", name="uq_security_strategy_project_key"
            ),
        ],
        "security_mutation_rule": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("strategy_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("mutation_type", sa.String(length=40), nullable=False),
            sa.Column("target_location", sa.String(length=20), nullable=False),
            sa.Column("target_field", sa.String(length=200), nullable=True),
            sa.Column("operator", sa.String(length=40), nullable=False),
            sa.Column(
                "mutation_config", sa.JSON(), nullable=False,
                server_default=text("'{}'::json"),
            ),
            sa.Column("expected_security_behavior", sa.String(length=40), nullable=False),
            sa.Column("expected_status_codes", sa.JSON(), nullable=True),
            sa.Column(
                "severity", sa.String(length=20), server_default=text("'MEDIUM'"),
                nullable=False,
            ),
            sa.Column(
                "enabled", sa.Boolean(), server_default=text("true"), nullable=False
            ),
            sa.Column(
                "confirmation_required", sa.Boolean(), server_default=text("false"),
                nullable=False,
            ),
            sa.Column(
                "sort", sa.Integer(), server_default=text("0"), nullable=False
            ),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["strategy_id"], ["security_strategy.id"], ondelete="CASCADE"
            ),
            sa.PrimaryKeyConstraint("id", name="pk_security_mutation_rule"),
        ],
        "security_plan": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("target_type", sa.String(length=20), nullable=False),
            sa.Column("api_id", sa.Integer(), nullable=True),
            sa.Column("baseline_case_id", sa.Integer(), nullable=True),
            sa.Column("business_action_id", sa.Integer(), nullable=True),
            sa.Column("strategy_ids", sa.JSON(), nullable=True),
            sa.Column(
                "status", sa.String(length=20), server_default=text("'DRAFT'"), nullable=False
            ),
            sa.Column("preview_json", sa.JSON(), nullable=True),
            sa.Column(
                "estimated_count", sa.Integer(), server_default=text("0"), nullable=False
            ),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("confirmed_by", sa.Integer(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=func.now(), nullable=False
            ),
            sa.Column(
                "revision", sa.Integer(), server_default=text("1"), nullable=False
            ),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["api_id"], ["api_interface.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["baseline_case_id"], ["test_case.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["business_action_id"], ["business_action.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["confirmed_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_security_plan"),
        ],
        "security_case": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("test_case_id", sa.Integer(), nullable=False),
            sa.Column("plan_id", sa.Integer(), nullable=True),
            sa.Column("baseline_case_id", sa.Integer(), nullable=True),
            sa.Column("strategy_id", sa.Integer(), nullable=True),
            sa.Column("rule_id", sa.Integer(), nullable=True),
            sa.Column("api_id", sa.Integer(), nullable=True),
            sa.Column("business_action_id", sa.Integer(), nullable=True),
            sa.Column("mutation_type", sa.String(length=40), nullable=False),
            sa.Column(
                "mutation_config", sa.JSON(), nullable=False,
                server_default=text("'{}'::json"),
            ),
            sa.Column(
                "security_expectation", sa.JSON(), nullable=False,
                server_default=text("'{}'::json"),
            ),
            sa.Column(
                "risk_level", sa.String(length=20), server_default=text("'MEDIUM'"),
                nullable=False,
            ),
            sa.Column(
                "confirmation_required", sa.Boolean(), server_default=text("false"),
                nullable=False,
            ),
            sa.Column("confirmed_by", sa.Integer(), nullable=True),
            sa.Column("confirmed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["test_case_id"], ["test_case.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["plan_id"], ["security_plan.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["baseline_case_id"], ["test_case.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["strategy_id"], ["security_strategy.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["rule_id"], ["security_mutation_rule.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["api_id"], ["api_interface.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["business_action_id"], ["business_action.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["confirmed_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_security_case"),
            sa.UniqueConstraint(
                "test_case_id", name="uq_security_case_test_case"
            ),
        ],
        "security_execution": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("test_run_id", sa.Integer(), nullable=False),
            sa.Column("case_execution_id", sa.Integer(), nullable=False),
            sa.Column("security_case_id", sa.Integer(), nullable=True),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("baseline_status", sa.String(length=20), nullable=True),
            sa.Column("baseline_http_status", sa.Integer(), nullable=True),
            sa.Column("security_result", sa.String(length=30), nullable=False),
            sa.Column("classification", sa.String(length=40), nullable=True),
            sa.Column("mutation_trace", sa.JSON(), nullable=True),
            sa.Column("replay_count", sa.Integer(), nullable=True),
            sa.Column("actual_status_codes", sa.JSON(), nullable=True),
            sa.Column("evidence", sa.JSON(), nullable=True),
            sa.Column("error_code", sa.String(length=50), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_run_id"], ["test_run.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["case_execution_id"], ["case_execution.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["security_case_id"], ["security_case.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["actor_id"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_security_execution"),
            sa.UniqueConstraint("case_execution_id", name="uq_security_execution_case"),
        ],
        "security_finding": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("test_run_id", sa.Integer(), nullable=True),
            sa.Column("case_execution_id", sa.Integer(), nullable=True),
            sa.Column("security_execution_id", sa.Integer(), nullable=True),
            sa.Column("api_id", sa.Integer(), nullable=True),
            sa.Column("business_action_id", sa.Integer(), nullable=True),
            sa.Column("strategy_id", sa.Integer(), nullable=True),
            sa.Column("security_case_id", sa.Integer(), nullable=True),
            sa.Column("mutation_type", sa.String(length=40), nullable=False),
            sa.Column(
                "severity", sa.String(length=20), server_default=text("'MEDIUM'"),
                nullable=False,
            ),
            sa.Column(
                "status", sa.String(length=20), server_default=text("'OPEN'"), nullable=False
            ),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("evidence", sa.JSON(), nullable=True),
            sa.Column("recommendation", sa.Text(), nullable=True),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            # 故意不加 FK：Phase 1 不自动建缺陷，以后人工确认再关联，避免现在绑死缺陷模块。
            sa.Column("bug_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("resolved_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column(
                "updated_at", sa.DateTime(), server_default=func.now(), nullable=False
            ),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_run_id"], ["test_run.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["case_execution_id"], ["case_execution.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["security_execution_id"], ["security_execution.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["api_id"], ["api_interface.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(
                ["business_action_id"], ["business_action.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["strategy_id"], ["security_strategy.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(
                ["security_case_id"], ["security_case.id"], ondelete="SET NULL"
            ),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["resolved_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_security_finding"),
        ],
    }


_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "security_project_setting": [
        ("ix_security_project_setting_id", ["id"]),
        ("uq_security_setting_project", ["project_id"]),
    ],
    "security_strategy": [
        ("ix_security_strategy_id", ["id"]),
        ("ix_security_strategy_project_id", ["project_id"]),
        ("ix_security_strategy_strategy_key", ["strategy_key"]),
        ("uq_security_strategy_project_key", ["project_id", "strategy_key"]),
        ("ix_security_strategy_project_category", ["project_id", "category"]),
        ("ix_security_strategy_scope_enabled", ["scope", "enabled"]),
    ],
    "security_mutation_rule": [
        ("ix_security_mutation_rule_id", ["id"]),
        ("ix_security_mutation_rule_project_id", ["project_id"]),
        ("ix_security_mutation_rule_strategy_id", ["strategy_id"]),
        ("ix_security_rule_strategy_sort", ["strategy_id", "enabled", "sort"]),
    ],
    "security_plan": [
        ("ix_security_plan_id", ["id"]),
        ("ix_security_plan_project_id", ["project_id"]),
        ("ix_security_plan_api_id", ["api_id"]),
        ("ix_security_plan_baseline_case_id", ["baseline_case_id"]),
        ("ix_security_plan_business_action_id", ["business_action_id"]),
        ("ix_security_plan_status", ["status"]),
        ("ix_security_plan_environment_id", ["environment_id"]),
        ("ix_security_plan_project_status", ["project_id", "status", "created_at"]),
    ],
    "security_case": [
        ("ix_security_case_id", ["id"]),
        ("ix_security_case_project_id", ["project_id"]),
        ("uq_security_case_test_case", ["test_case_id"]),
        ("ix_security_case_plan_id", ["plan_id"]),
        ("ix_security_case_strategy_id", ["strategy_id"]),
        ("ix_security_case_rule_id", ["rule_id"]),
        ("ix_security_case_api_id", ["api_id"]),
        ("ix_security_case_business_action_id", ["business_action_id"]),
        ("ix_security_case_project_mutation", ["project_id", "mutation_type"]),
        ("ix_security_case_project_strategy", ["project_id", "strategy_id"]),
        ("ix_security_case_baseline", ["baseline_case_id"]),
    ],
    "security_execution": [
        ("ix_security_execution_id", ["id"]),
        ("ix_security_execution_project_id", ["project_id"]),
        ("ix_security_execution_test_run_id", ["test_run_id"]),
        ("uq_security_execution_case", ["case_execution_id"]),
        ("ix_security_execution_security_case_id", ["security_case_id"]),
        ("ix_security_execution_environment_id", ["environment_id"]),
        ("ix_security_execution_actor_id", ["actor_id"]),
        ("ix_security_execution_project_result", ["project_id", "security_result"]),
        ("ix_security_execution_run", ["test_run_id"]),
    ],
    "security_finding": [
        ("ix_security_finding_id", ["id"]),
        ("ix_security_finding_project_id", ["project_id"]),
        ("ix_security_finding_test_run_id", ["test_run_id"]),
        ("ix_security_finding_case_execution_id", ["case_execution_id"]),
        ("ix_security_finding_security_execution_id", ["security_execution_id"]),
        ("ix_security_finding_api_id", ["api_id"]),
        ("ix_security_finding_business_action_id", ["business_action_id"]),
        ("ix_security_finding_strategy_id", ["strategy_id"]),
        ("ix_security_finding_security_case_id", ["security_case_id"]),
        ("ix_security_finding_project_status", ["project_id", "status"]),
        ("ix_security_finding_project_severity", ["project_id", "severity"]),
    ],
}

# 部分唯一索引：CREATE TABLE 无法表达 WHERE 条件。
# - 系统模板 project_id 为空，普通 UNIQUE(project_id, strategy_key) 拦不住重复模板
#   （NULL 不相等），必须单独加一条 WHERE project_id IS NULL 的部分唯一索引。
# - 同一接口、同一变异、同一字段上未关闭的 Finding 不重复插入：只锁 OPEN / CONFIRMED。
#   FALSE_POSITIVE / IGNORED / RESOLVED 不占该索引，误报之后允许再开一条新的 OPEN。
_PARTIAL_INDEXES: list[tuple[str, str, str]] = [
    (
        "uq_security_strategy_system_key",
        "security_strategy",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_security_strategy_system_key "
        "ON security_strategy (\"strategy_key\") WHERE project_id IS NULL",
    ),
    (
        "uq_security_finding_open_fingerprint",
        "security_finding",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_security_finding_open_fingerprint "
        "ON security_finding (\"project_id\", \"fingerprint\") "
        "WHERE status IN ('OPEN', 'CONFIRMED')",
    ),
]

_TABLE_COMMENTS: dict[str, str] = {
    "security_project_setting": "项目级安全执行环境开关：生产永远拒绝，allow_production 仅记录意图",
    "security_strategy": "安全策略：SYSTEM 模板 / PROJECT 自定义；category 区分可执行与预留攻击类",
    "security_mutation_rule": "结构化变异规则：字段/位置/算子/期望/级别，禁止脚本",
    "security_plan": "人工确认前的安全计划：preview_json 快照 + estimated_count",
    "security_case": "安全用例扩展数据：与 test_case 一对一，引用基线不复制基线",
    "security_execution": "安全细结果：基线结论 + 变异 trace（脱敏）+ 五态结论",
    "security_finding": "疑似问题：fingerprint 去重，独立于 bug 表",
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

    # 部分唯一索引单独创建。
    for name, table, statement in _PARTIAL_INDEXES:
        if name in _existing_index_names(bind, table):
            continue
        bind.execute(text(statement))


def upgrade() -> None:
    """正向迁移：建 7 张表 + 索引 + 系统内置策略（全幂等）。"""
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

    # 3. 系统内置策略与规则（按 strategy_key 幂等跳过）。
    #    延迟 import：避免 alembic 收集迁移版本时把整个 feature 包拉进来。
    from app.features.security_testing.builtins import ensure_builtin_strategies

    ensure_builtin_strategies(bind)


def downgrade() -> None:
    """反向迁移：删 7 张表（IF EXISTS，逆序可安全重放）。

    这里只显式删部分唯一索引——它是在 CREATE TABLE 之外单独建的。表上的普通索引
    与 UNIQUE 约束索引由 DROP TABLE 连带删除，不需要（也不能）单独 DROP INDEX：
    uq_security_setting_project / uq_security_strategy_project_key /
    uq_security_case_test_case / uq_security_execution_case 是 UniqueConstraint 的
    支撑索引，对它们执行 DROP INDEX 会被 PostgreSQL 拒绝
    （DependentObjectsStillExist）。

    ⚠️ 降级前请先禁用 case_type='SECURITY' 的 test_case（见文件头注释）。
    """
    bind = op.get_bind()

    for name, _table, _statement in _PARTIAL_INDEXES:
        bind.execute(text(f"DROP INDEX IF EXISTS {name}"))

    for table in reversed(_NEW_TABLES):
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
