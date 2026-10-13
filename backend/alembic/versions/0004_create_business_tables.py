"""新增业务管理 10 张表（business feature-local）。

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12

延续 0002/0003 风格：显式 op.create_table（0001 之后的表不能再用 create_all），
幂等保护（inspect 检查表存在性，索引用 IF NOT EXISTS）。
seed_admin.py 每次 stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。

模型**不**加入 app/models/__init__.py（feature-local），与 Bug / api_catalog 同款。
建表顺序遵循外键依赖：domain → flow → action → 各 action 子配置 → binding → api_mapping。
business_binding.api_id 引用 api_interface.id（0003 已建），用 ondelete=SET NULL。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


# 表创建顺序（遵循外键依赖：父表先于子表；binding 先于 api_mapping）。
_TABLES_IN_ORDER = [
    "business_domain",
    "business_flow",
    "business_action",
    "business_precondition",
    "business_variable",
    "business_state",
    "business_variable_ref",
    "business_rule",
    "business_binding",
    "business_api_mapping",
]


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "business_domain": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("status", sa.String(length=20), server_default=text("'ACTIVE'"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_domain"),
            sa.UniqueConstraint("project_id", "name", name="uq_business_domain_project_name"),
        ],
        "business_flow": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("domain_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'DRAFT'"), nullable=False),
            sa.Column("version", sa.Integer(), server_default=text("1"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["domain_id"], ["business_domain.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_flow"),
            sa.UniqueConstraint("domain_id", "name", name="uq_business_flow_domain_name"),
        ],
        "business_action": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("flow_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("action_key", sa.String(length=100), nullable=False),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("action_type", sa.String(length=30), server_default=text("'API'"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["flow_id"], ["business_flow.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_action"),
            sa.UniqueConstraint("flow_id", "action_key", name="uq_business_action_flow_key"),
        ],
        "business_precondition": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("action_id", sa.Integer(), nullable=False),
            sa.Column("type", sa.String(length=20), nullable=False),
            sa.Column("target", sa.String(length=200), nullable=False),
            sa.Column("operator", sa.String(length=20), server_default=text("'EQ'"), nullable=False),
            sa.Column("expected_value", sa.String(length=500), nullable=True),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["action_id"], ["business_action.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_precondition"),
        ],
        "business_variable": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("action_id", sa.Integer(), nullable=False),
            sa.Column("direction", sa.String(length=10), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("data_type", sa.String(length=20), server_default=text("'STRING'"), nullable=False),
            sa.Column("required", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("sort", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["action_id"], ["business_action.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_variable"),
            sa.UniqueConstraint(
                "action_id", "direction", "name", name="uq_business_variable_action_dir_name"
            ),
        ],
        "business_state": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("action_id", sa.Integer(), nullable=False),
            sa.Column("entity", sa.String(length=100), nullable=False),
            sa.Column("pre_state", sa.String(length=50), nullable=True),
            sa.Column("post_state", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["action_id"], ["business_action.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_state"),
            sa.UniqueConstraint("action_id", "entity", name="uq_business_state_action_entity"),
        ],
        "business_variable_ref": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("flow_id", sa.Integer(), nullable=False),
            sa.Column("source_action_id", sa.Integer(), nullable=False),
            sa.Column("source_variable", sa.String(length=100), nullable=False),
            sa.Column("target_action_id", sa.Integer(), nullable=False),
            sa.Column("target_variable", sa.String(length=100), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["flow_id"], ["business_flow.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_action_id"], ["business_action.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["target_action_id"], ["business_action.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_variable_ref"),
        ],
        "business_rule": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("flow_id", sa.Integer(), nullable=True),
            sa.Column("action_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("rule_type", sa.String(length=30), server_default=text("'GENERAL'"), nullable=False),
            sa.Column("expression", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["flow_id"], ["business_flow.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["action_id"], ["business_action.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_rule"),
        ],
        "business_binding": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("action_id", sa.Integer(), nullable=False),
            sa.Column("binding_type", sa.String(length=20), server_default=text("'API'"), nullable=False),
            # api_id 用 SET NULL：接口被删除时绑定保留、api_id 置空，由服务层标记失效（非 CASCADE）。
            sa.Column("api_id", sa.Integer(), nullable=True),
            sa.Column("config_json", sa.JSON(), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["action_id"], ["business_action.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["api_id"], ["api_interface.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_business_binding"),
            sa.UniqueConstraint("action_id", "binding_type", name="uq_business_binding_action_type"),
        ],
        "business_api_mapping": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("binding_id", sa.Integer(), nullable=False),
            sa.Column("direction", sa.String(length=10), nullable=False),
            sa.Column("business_variable", sa.String(length=100), nullable=False),
            sa.Column("api_location", sa.String(length=20), nullable=False),
            sa.Column("api_field", sa.String(length=300), nullable=True),
            sa.Column("expression", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["binding_id"], ["business_binding.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_business_api_mapping"),
            sa.UniqueConstraint(
                "binding_id", "direction", "business_variable",
                name="uq_business_api_mapping_binding_dir_var",
            ),
        ],
    }


# 每张表的非唯一索引（与 ORM index=True / __table_args__ Index 一一对应）。
_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "business_domain": [
        ("ix_business_domain_id", ["id"]),
        ("ix_business_domain_project_id", ["project_id"]),
        ("ix_business_domain_status", ["status"]),
        ("ix_business_domain_project_sort", ["project_id", "sort"]),
    ],
    "business_flow": [
        ("ix_business_flow_id", ["id"]),
        ("ix_business_flow_project_id", ["project_id"]),
        ("ix_business_flow_domain_id", ["domain_id"]),
        ("ix_business_flow_status", ["status"]),
        ("ix_business_flow_project_status", ["project_id", "status"]),
    ],
    "business_action": [
        ("ix_business_action_id", ["id"]),
        ("ix_business_action_flow_id", ["flow_id"]),
        ("ix_business_action_action_key", ["action_key"]),
        ("ix_business_action_flow_sort", ["flow_id", "sort"]),
    ],
    "business_precondition": [
        ("ix_business_precondition_id", ["id"]),
        ("ix_business_precondition_action_id", ["action_id"]),
        ("ix_business_precondition_action_sort", ["action_id", "sort"]),
    ],
    "business_variable": [
        ("ix_business_variable_id", ["id"]),
        ("ix_business_variable_action_id", ["action_id"]),
        ("ix_business_variable_action_direction", ["action_id", "direction"]),
    ],
    "business_state": [
        ("ix_business_state_id", ["id"]),
        ("ix_business_state_action_id", ["action_id"]),
    ],
    "business_variable_ref": [
        ("ix_business_variable_ref_id", ["id"]),
        ("ix_business_variable_ref_flow_id", ["flow_id"]),
        ("ix_business_variable_ref_source_action_id", ["source_action_id"]),
        ("ix_business_variable_ref_target_action_id", ["target_action_id"]),
    ],
    "business_rule": [
        ("ix_business_rule_id", ["id"]),
        ("ix_business_rule_project_id", ["project_id"]),
        ("ix_business_rule_flow_id", ["flow_id"]),
        ("ix_business_rule_action_id", ["action_id"]),
    ],
    "business_binding": [
        ("ix_business_binding_id", ["id"]),
        ("ix_business_binding_action_id", ["action_id"]),
        ("ix_business_binding_api_id", ["api_id"]),
    ],
    "business_api_mapping": [
        ("ix_business_api_mapping_id", ["id"]),
        ("ix_business_api_mapping_binding_id", ["binding_id"]),
        ("ix_business_api_mapping_binding_direction", ["binding_id", "direction"]),
    ],
}

# 表注释（与 ORM __table_args__ comment 对齐）。
_TABLE_COMMENTS: dict[str, str] = {
    "business_domain": "业务域：项目下的业务流程分组容器",
    "business_flow": "业务流程：一组有序业务动作的完整业务过程",
    "business_action": "业务动作：业务流程中一个不可分割的业务步骤",
    "business_precondition": "业务动作前置条件",
    "business_variable": "业务动作输入/输出变量",
    "business_state": "业务动作对某实体的前置/后置状态定义",
    "business_variable_ref": "业务动作之间的变量引用关系",
    "business_rule": "业务规则：项目/流程/动作级业务知识配置",
    "business_binding": "业务绑定：业务动作与具体执行接口的关系",
    "business_api_mapping": "业务变量与绑定 API 接口参数之间的映射",
}


def upgrade() -> None:
    """正向迁移：建 10 张表 + 索引（幂等）。"""
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
    """反向迁移：删 10 张表及其索引（全 IF EXISTS，可安全重放）。"""
    bind = op.get_bind()
    # 先删索引（含唯一约束产生的索引）再删表；按外键依赖逆序删表。
    for table in reversed(_TABLES_IN_ORDER):
        for name, _columns in _INDEX_DEFINITIONS.get(table, []):
            bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
