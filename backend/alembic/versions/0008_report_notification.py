"""新增测试报告 + 飞书通知渠道 + 通知发送记录三表（Phase 2，feature-local）。

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14

延续 0006/0007 风格：显式 op.create_table（0001 之后的表不能再用 create_all），
幂等保护（inspect 检查表存在性，索引用 CREATE INDEX IF NOT EXISTS）。seed_admin.py
每次 stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。

新增 3 张表（按外键依赖排序：report/channel 互不依赖，record 依赖前两者）：
- test_report：正式测试报告（汇总 + AI 总结 + 风险，不复制执行明细）；
- notification_channel：外发通知渠道（飞书 Webhook，webhook/secret 加密存储）；
- notification_record：外发发送审计（状态独立于 TestRun/Report）。

模型**不**加入 app/models/__init__.py（feature-local），由本迁移显式建表（红线 17）。
报告统计字段一律由 ReportBuilder 代码计算，LLM 不参与（§五）。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


# 新建表（按外键依赖：report / channel 在前，record 依赖两者）。
_NEW_TABLES = ["test_report", "notification_channel", "notification_record"]


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "test_report": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("test_run_id", sa.Integer(), nullable=True),
            sa.Column("report_no", sa.String(length=32), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'GENERATING'"), nullable=False),
            sa.Column("total_cases", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("passed_cases", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("failed_cases", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("error_cases", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("skipped_cases", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("pass_rate", sa.Numeric(5, 2), server_default=text("0"), nullable=False),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("summary", sa.JSON(), nullable=True),
            sa.Column("ai_summary", sa.JSON(), nullable=True),
            sa.Column("ai_summary_version", sa.String(length=20), nullable=True),
            sa.Column("risk_level", sa.String(length=20), server_default=text("'LOW'"), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["test_run_id"], ["test_run.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_test_report"),
            sa.UniqueConstraint("report_no", name="uq_test_report_no"),
        ],
        "notification_channel": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("channel_type", sa.String(length=30), server_default=text("'FEISHU_WEBHOOK'"), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("config_json", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_notification_channel"),
        ],
        "notification_record": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("channel_id", sa.Integer(), nullable=False),
            sa.Column("report_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(length=20), server_default=text("'PENDING'"), nullable=False),
            sa.Column("request_snapshot", sa.JSON(), nullable=True),
            sa.Column("response_snapshot", sa.JSON(), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("sent_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            # 渠道删除连带删发送记录（审计随渠道生命周期）。
            sa.ForeignKeyConstraint(["channel_id"], ["notification_channel.id"], ondelete="CASCADE"),
            # 报告删除不连带删发送记录，置空即可（保留投递审计）。
            sa.ForeignKeyConstraint(["report_id"], ["test_report.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id", name="pk_notification_record"),
        ],
    }


# 每张表的非唯一索引（与 ORM __table_args__ Index 一一对应）。
_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "test_report": [
        ("ix_test_report_id", ["id"]),
        ("ix_test_report_project_id", ["project_id"]),
        ("ix_test_report_test_run_id", ["test_run_id"]),
        ("ix_test_report_environment_id", ["environment_id"]),
        ("ix_test_report_status", ["status"]),
        ("ix_test_report_risk_level", ["risk_level"]),
        ("ix_test_report_project_created", ["project_id", "created_at"]),
    ],
    "notification_channel": [
        ("ix_notification_channel_id", ["id"]),
        ("ix_notification_channel_project_id", ["project_id"]),
    ],
    "notification_record": [
        ("ix_notification_record_id", ["id"]),
        ("ix_notification_record_project_id", ["project_id"]),
        ("ix_notification_record_channel_id", ["channel_id"]),
        ("ix_notification_record_report_id", ["report_id"]),
        ("ix_notification_record_status", ["status"]),
    ],
}

# 表注释（与 ORM __table_args__ comment 对齐）。
_TABLE_COMMENTS: dict[str, str] = {
    "test_report": "正式测试报告：汇总 + AI 总结 + 风险（不复制执行明细）",
    "notification_channel": "外发通知渠道（飞书 Webhook 等）：webhook/secret 加密存储",
    "notification_record": "外发通知发送记录：状态独立于 TestRun/Report",
}


def upgrade() -> None:
    """正向迁移：建 3 张表 + 索引（全幂等，可安全重放）。"""
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


def downgrade() -> None:
    """反向迁移：删 3 张表及其索引（全 IF EXISTS，逆序可安全重放）。"""
    bind = op.get_bind()

    # 逆序：record 先于 channel/report（record 依赖后两者）。
    for table in reversed(_NEW_TABLES):
        for name, _columns in _INDEX_DEFINITIONS.get(table, []):
            bind.execute(text(f"DROP INDEX IF EXISTS {name}"))
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
