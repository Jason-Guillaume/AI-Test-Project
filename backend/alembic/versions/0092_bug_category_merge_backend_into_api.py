"""缺陷类别归并：存量「后端」缺陷统一改为「接口」。

Revision ID: 0092
Revises: 0091
Create Date: 2026-11-17

「接口」与「后端」视为同一归属：应用层已把旧入参「后端」自动映射为「接口」，
本迁移把数据库中的历史「后端」行一并归并为「接口」，保证筛选与统计口径唯一。
「前后端」保留自身类型不动；「前端」与「接口」行不做任何改写。
反向迁移不做数据回写（无法区分「接口」行原本是「后端」还是「接口」），仅保持结构不变。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0092"
down_revision = "0091"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    """读取当前数据库中的表名，供幂等迁移判断。"""
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    """正向迁移：bug.category = '后端' 的行统一更新为 '接口'。"""
    if "bug" not in _tables():
        return
    op.execute("UPDATE bug SET category = '接口' WHERE category = '后端'")


def downgrade() -> None:
    """反向迁移：数据不回写（无法区分原归属），仅保持结构与 0091 一致。"""
    return None
