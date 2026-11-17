"""缺陷表新增接口专属字段（请求方法/地址/请求头/请求体/响应结果）。

Revision ID: 0093
Revises: 0092
Create Date: 2026-11-17

「接口」类缺陷需要记录接口层面的定位信息：请求方法、请求地址、请求头、
请求体与响应结果。全部为可空列，仅当 category='接口' 时由表单填写；
历史存量缺陷与前端/前后端缺陷保持 NULL，不做回填。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0093"
down_revision = "0092"
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


_API_COLUMNS = (
    sa.Column("api_method", sa.String(length=10), nullable=True, comment="请求方法：GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS"),
    sa.Column("api_url", sa.String(length=500), nullable=True, comment="请求地址（完整 URL 或路径）"),
    sa.Column("api_request_headers", sa.Text(), nullable=True, comment="请求头（JSON 或原始文本）"),
    sa.Column("api_request_body", sa.Text(), nullable=True, comment="请求体"),
    sa.Column("api_response", sa.Text(), nullable=True, comment="实际响应结果（脱敏后填写）"),
)


def upgrade() -> None:
    """正向迁移：为 bug 表追加接口专属可空列。"""
    if "bug" not in _tables():
        return
    columns = _columns("bug")
    for column in _API_COLUMNS:
        if column.name not in columns:
            op.add_column("bug", column.copy())


def downgrade() -> None:
    """反向迁移：移除接口专属列。"""
    if "bug" not in _tables():
        return
    columns = _columns("bug")
    for column in reversed(_API_COLUMNS):
        if column.name in columns:
            op.drop_column("bug", column.name)
