"""缺陷队列工作流迁移：优先级、影响/修复版本、记录版本、草稿、归档、判重、幂等键，
以及活动时间线 bug_activity、项目开关 defect_project_setting、项目模板 defect_template 三张新表。

Revision ID: 0107
Revises: 0106
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0107"
down_revision = "0106"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    if table not in _tables():
        return set()
    return {item["name"] for item in sa.inspect(op.get_bind()).get_indexes(table)}


_BUG_COLUMNS = (
    ("priority", sa.Integer(), False, sa.text("2"), "处理优先级 1-4，1 低 2 中 3 高 4 紧急"),
    ("affected_version", sa.String(100), True, None, "影响版本"),
    ("fix_version", sa.String(200), True, None, "登记可回归时的版本/构建/环境"),
    ("record_version", sa.Integer(), False, sa.text("0"), "记录版本，乐观并发控制"),
    ("is_draft", sa.Boolean(), False, sa.text("false"), "草稿标记，提交后进入待确认队列"),
    ("archived_at", sa.DateTime(), True, None, "归档时间"),
    ("archived_by", sa.Integer(), True, None, "归档操作人"),
    ("archive_reason", sa.String(500), True, None, "归档原因"),
    ("duplicate_of_bug_id", sa.Integer(), True, None, "判重指向的主单"),
    ("request_key", sa.String(100), True, None, "创建幂等请求键"),
    ("request_digest", sa.String(64), True, None, "创建请求内容摘要"),
)


def upgrade() -> None:
    columns = _columns("bug")
    for name, type_, nullable, default, comment in _BUG_COLUMNS:
        if name not in columns:
            op.add_column(
                "bug",
                sa.Column(name, type_, nullable=nullable, server_default=default, comment=comment),
            )
    if "archived_by" in _columns("bug") and not any(
        fk.get("referred_table") == "user"
        for fk in sa.inspect(op.get_bind()).get_foreign_keys("bug")
        if fk.get("constrained_columns") == ["archived_by"]
    ):
        op.create_foreign_key("fk_bug_archived_by_user", "bug", "user", ["archived_by"], ["id"], ondelete="SET NULL")
    if "duplicate_of_bug_id" in _columns("bug") and not any(
        fk.get("referred_table") == "bug"
        for fk in sa.inspect(op.get_bind()).get_foreign_keys("bug")
        if fk.get("constrained_columns") == ["duplicate_of_bug_id"]
    ):
        op.create_foreign_key("fk_bug_duplicate_of_bug", "bug", "bug", ["duplicate_of_bug_id"], ["id"], ondelete="SET NULL")
    if "uq_bug_project_request_key" not in _indexes("bug"):
        op.create_index("uq_bug_project_request_key", "bug", ["project_id", "request_key"], unique=True)
    if "ix_bug_project_updated" not in _indexes("bug"):
        op.create_index("ix_bug_project_updated", "bug", ["project_id", "updated_at"])

    if "bug_activity" not in _tables():
        op.create_table(
            "bug_activity",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("bug_id", sa.Integer(), sa.ForeignKey("bug.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_name", sa.String(100), nullable=True),
            sa.Column("actor_type", sa.String(20), nullable=False, server_default=sa.text("'INTERNAL'")),
            sa.Column("action", sa.String(30), nullable=False),
            sa.Column("old_status", sa.String(20), nullable=True),
            sa.Column("new_status", sa.String(20), nullable=True),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            comment="缺陷动作与活动事件",
        )
    if "ix_bug_activity_bug_id" not in _indexes("bug_activity"):
        op.create_index("ix_bug_activity_bug_id", "bug_activity", ["bug_id"])
    if "ix_bug_activity_project_id" not in _indexes("bug_activity"):
        op.create_index("ix_bug_activity_project_id", "bug_activity", ["project_id"])
    if "ix_bug_activity_project_action" not in _indexes("bug_activity"):
        op.create_index("ix_bug_activity_project_action", "bug_activity", ["project_id", "action", "created_at"])

    if "defect_project_setting" not in _tables():
        op.create_table(
            "defect_project_setting",
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("queue_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("reminder_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("stale_reminder_days", sa.Integer(), nullable=False, server_default=sa.text("7")),
            sa.Column("updated_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            comment="缺陷项目级开关：队列灰度与积压提醒订阅",
        )

    if "defect_template" not in _tables():
        op.create_table(
            "defect_template",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("config", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'draft'")),
            sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("published_at", sa.DateTime(), nullable=True),
            comment="缺陷项目模板：字段显隐、默认值与分阶段必填规则",
        )
    if "ix_defect_template_project_id" not in _indexes("defect_template"):
        op.create_index("ix_defect_template_project_id", "defect_template", ["project_id"])
    if "uq_defect_template_project_version" not in _indexes("defect_template"):
        op.create_index("uq_defect_template_project_version", "defect_template", ["project_id", "version"], unique=True)


def downgrade() -> None:
    if "defect_template" in _tables():
        op.drop_table("defect_template")
    if "defect_project_setting" in _tables():
        op.drop_table("defect_project_setting")
    if "bug_activity" in _tables():
        op.drop_table("bug_activity")
    if "uq_bug_project_request_key" in _indexes("bug"):
        op.drop_index("uq_bug_project_request_key", table_name="bug")
    if "ix_bug_project_updated" in _indexes("bug"):
        op.drop_index("ix_bug_project_updated", table_name="bug")
    columns = _columns("bug")
    for name, *_ in reversed(_BUG_COLUMNS):
        if name in columns:
            op.drop_column("bug", name)