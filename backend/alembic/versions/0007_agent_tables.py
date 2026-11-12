"""新增接口测试 Agent 会话表 + 测试资产追溯列（agent feature-local）。

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-14

延续 0006 风格：显式 op.create_table（0001 之后的表不能再用 create_all），
幂等保护（inspect 检查表/列存在性，索引用 IF NOT EXISTS）。seed_admin.py 每次
stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。

新增 2 张表：
- agent_session：Agent 会话（project_id + user_id 隔离，current_stage 记录工作流阶段）
- agent_message：会话消息历史（role/message_type/content/metadata_json，metadata 脱敏后存储）

扩列（幂等 add_column）：
- test_point / test_case 各加 agent_session_id（FK agent_session.id, SET NULL, nullable）
  与 generation_version（Integer, nullable），用于追溯 Agent 生成的资产来源。

模型**不**加入 app/models/__init__.py（feature-local），由本迁移显式建表/扩列。
持久化完全在自建表（§26），不依赖 langgraph checkpointer：每次 HTTP 请求从
agent_session/agent_message 重建 AgentState 后全新 invoke（见 agent/state.py）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


# 新建表（按外键依赖：session 先于 message）。
_NEW_TABLES = ["agent_session", "agent_message"]


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "agent_session": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=200), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'ACTIVE'"), nullable=False),
            sa.Column("current_stage", sa.String(length=30), server_default=text("'UNDERSTANDING'"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_agent_session"),
        ],
        "agent_message": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=20), server_default=text("'USER'"), nullable=False),
            sa.Column("message_type", sa.String(length=20), server_default=text("'TEXT'"), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["agent_session.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name="pk_agent_message"),
        ],
    }


# 每张表的非唯一索引（与 ORM __table_args__ Index 一一对应）。
_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "agent_session": [
        ("ix_agent_session_id", ["id"]),
        ("ix_agent_session_project_id", ["project_id"]),
        ("ix_agent_session_user_id", ["user_id"]),
        ("ix_agent_session_project_status", ["project_id", "status"]),
    ],
    "agent_message": [
        ("ix_agent_message_id", ["id"]),
        ("ix_agent_message_session_id", ["session_id"]),
    ],
}

# 表注释（与 ORM __table_args__ comment 对齐）。
_TABLE_COMMENTS: dict[str, str] = {
    "agent_session": "接口测试 Agent 会话：按 project+user 隔离，记录工作流阶段",
    "agent_message": "Agent 会话消息历史（metadata_json 存脱敏后的结构化数据）",
}

# 扩列目标：(表, 列, Column 定义) —— 幂等：列已存在则跳过。
_COLUMN_ADDITIONS: list[tuple[str, str, sa.Column]] = [
    ("test_point", "agent_session_id",
     sa.Column("agent_session_id", sa.Integer(),
               sa.ForeignKey("agent_session.id", ondelete="SET NULL"),
               nullable=True, comment="生成该测试点的 Agent 会话ID（追溯用）")),
    ("test_point", "generation_version",
     sa.Column("generation_version", sa.Integer(), nullable=True,
               comment="Agent 生成版本号（追溯用）")),
    ("test_case", "agent_session_id",
     sa.Column("agent_session_id", sa.Integer(),
               sa.ForeignKey("agent_session.id", ondelete="SET NULL"),
               nullable=True, comment="生成该用例的 Agent 会话ID（追溯用）")),
    ("test_case", "generation_version",
     sa.Column("generation_version", sa.Integer(), nullable=True,
               comment="Agent 生成版本号（追溯用）")),
]


def upgrade() -> None:
    """正向迁移：建 2 张表 + 索引 + test_point/test_case 扩列（全幂等）。"""
    from sqlalchemy import inspect

    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    definitions = _table_definitions()

    # 1. 建表（幂等）。
    for table in _NEW_TABLES:
        if table in existing_tables:
            continue
        op.create_table(table, *definitions[table], comment=_TABLE_COMMENTS.get(table))

    # 2. 索引：逐表 IF NOT EXISTS 补齐，允许在已建索引的库上安全重放。
    for table in _NEW_TABLES:
        if table not in inspect(bind).get_table_names():
            continue
        existing_indexes = {idx["name"] for idx in inspector.get_indexes(table)}
        for name, columns in _INDEX_DEFINITIONS.get(table, []):
            if name in existing_indexes:
                continue
            columns_sql = ", ".join(f'"{c}"' for c in columns)
            bind.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns_sql})"))

    # 3. test_point / test_case 扩列（幂等：列已存在则跳过）。
    for table, _col_name, column in _COLUMN_ADDITIONS:
        existing_cols = {c["name"] for c in inspector.get_columns(table)}
        if column.name in existing_cols:
            continue
        op.add_column(table, column)


def downgrade() -> None:
    """反向迁移：删扩列 + 删 2 张表及其索引（全 IF EXISTS，可安全重放）。"""
    bind = op.get_bind()

    # 1. 先删 test_point/test_case 的扩列（逆序）。
    for table, col_name, _column in reversed(_COLUMN_ADDITIONS):
        bind.execute(text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col_name}"))

    # 2. 删索引 + 删表（逆序：message 先于 session）。
    for table in reversed(_NEW_TABLES):
        for name, _columns in _INDEX_DEFINITIONS.get(table, []):
            bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
