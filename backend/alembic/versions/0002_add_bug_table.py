"""新增缺陷表 bug。

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-12

与 0001 差异：0001 使用 Base.metadata.create_all() 建全部基线表；0002 改用
显式 op.create_table，保证 Alembic 迁移独立可复现，不依赖应用侧 ORM 定义。
0001 之后再新增表只能走显式 op 语法，无法再用 create_all。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


# 版本链：0002 接在 0001 之后，不启用分支。
revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """正向迁移：新增 bug 表及其索引、外键与默认值。

    幂等保护：scripts/seed_admin.py 会在每次运行时先 alembic stamp base 再
    upgrade head，以便在任意初始状态下重放迁移链。若表已存在（例如同一库
    反复执行 seed 脚本），跳过后建步骤；索引亦逐个以 IF NOT EXISTS 补齐。
    """
    from sqlalchemy import inspect

    bind = op.get_bind()
    inspector = inspect(bind)

    # 建表：仅在缺失时执行，避免与既有表冲突。
    if "bug" not in inspector.get_table_names():
        op.create_table(
            "bug",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=1000), nullable=True),
            sa.Column("severity", sa.Integer(), server_default=text("2"), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default=text("'待确认'"),
                nullable=False,
            ),
            sa.Column("steps_to_reproduce", sa.Text(), nullable=True),
            sa.Column("environment", sa.String(length=200), nullable=True),
            sa.Column("reporter_id", sa.Integer(), nullable=True),
            sa.Column("assignee_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["project_id"], ["project.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["reporter_id"], ["user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["assignee_id"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_bug"),
            comment="测试缺陷及其处理状态",
        )

    # 索引：全部用 IF NOT EXISTS 补齐，允许在已建好索引的表上安全重放。
    # 单列索引与 ORM 定义中的 index=True 一一对应；两条复合索引覆盖列表页
    # 按 (project, status, severity) 过滤以及按项目分页时按创建时间倒序两种
    # 主查询形状。
    existing_indexes = {idx["name"] for idx in inspector.get_indexes("bug")}
    index_defs = [
        ("ix_bug_id", ["id"]),
        ("ix_bug_project_id", ["project_id"]),
        ("ix_bug_title", ["title"]),
        ("ix_bug_status", ["status"]),
        ("ix_bug_reporter_id", ["reporter_id"]),
        ("ix_bug_assignee_id", ["assignee_id"]),
        ("ix_bug_project_status_severity", ["project_id", "status", "severity"]),
        ("ix_bug_project_created", ["project_id", "created_at"]),
    ]
    for name, columns in index_defs:
        if name in existing_indexes:
            continue
        columns_sql = ", ".join(f'"{c}"' for c in columns)
        bind.execute(
            text(f"CREATE INDEX IF NOT EXISTS {name} ON bug ({columns_sql})")
        )


def downgrade() -> None:
    """反向迁移：删除 bug 表及其所有索引。

    顺序与 upgrade 相反：先删索引再删表。全部语句走 IF EXISTS，允许
    在缺失索引或表不存在时安全重放（例如 downgrade 被重复执行）。
    """
    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS ix_bug_project_created"))
    bind.execute(text("DROP INDEX IF EXISTS ix_bug_project_status_severity"))
    bind.execute(text("DROP INDEX IF EXISTS ix_bug_assignee_id"))
    bind.execute(text("DROP INDEX IF EXISTS ix_bug_reporter_id"))
    bind.execute(text("DROP INDEX IF EXISTS ix_bug_status"))
    bind.execute(text("DROP INDEX IF EXISTS ix_bug_title"))
    bind.execute(text("DROP INDEX IF EXISTS ix_bug_project_id"))
    bind.execute(text("DROP INDEX IF EXISTS ix_bug_id"))
    bind.execute(text("DROP TABLE IF EXISTS bug"))
