"""缺陷表新增前后端划分字段 category。

Revision ID: 0090
Revises: 0089
Create Date: 2026-11-17

为 ``bug`` 表补充可空列 ``category``（前端/后端）及对应查询索引，
历史存量缺陷保持 NULL，在展示层统一归为「未划分」。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0090"
down_revision = "0089"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    """读取当前数据库中的表名，供幂等迁移判断。"""
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    """读取指定表的列名；表不存在时返回空集。"""
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    """读取指定表的索引名；表不存在时返回空集。"""
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    """正向迁移：为 bug 表添加 category 列及筛选索引。"""
    if "bug" not in _tables():
        return
    columns = _columns("bug")
    if "category" not in columns:
        # 历史数据不回填猜测归属，允许 NULL 并在列表展示为「未划分」。
        op.add_column(
            "bug",
            sa.Column("category", sa.String(length=20), nullable=True, comment="前后端划分：前端/后端"),
        )
    indexes = _indexes("bug")
    if "ix_bug_category" not in indexes:
        op.create_index("ix_bug_category", "bug", ["category"])
    if "ix_bug_project_category" not in indexes:
        op.create_index("ix_bug_project_category", "bug", ["project_id", "category"])


def downgrade() -> None:
    """反向迁移：移除 bug 表的 category 索引与列。"""
    if "bug" not in _tables():
        return
    indexes = _indexes("bug")
    if "ix_bug_project_category" in indexes:
        op.drop_index("ix_bug_project_category", table_name="bug")
    if "ix_bug_category" in indexes:
        op.drop_index("ix_bug_category", table_name="bug")
    if "category" in _columns("bug"):
        op.drop_column("bug", "category")
