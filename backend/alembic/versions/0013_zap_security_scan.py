"""新增 Security Testing Phase 2（OWASP ZAP 集成）全部表 + 平台内置扫描策略。

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-19

接在 0012（Web UI 自动化一期）之后；本仓库的迁移链必须保持单 head。
延续 0006-0012 风格：显式 op.create_table（0001 之后不能用 create_all），幂等保护
（inspect 检查表存在性，索引用 CREATE [UNIQUE] INDEX IF NOT EXISTS）。seed_admin.py
每次 stamp base + upgrade head 会重放整条迁移链，因此本迁移必须可重复执行。

新增 6 张表（按外键依赖排序）：
- security_scan_auth_profile：认证配置。凭据只存 Fernet 密文，任何接口不回显明文
- security_scan_target：扫描目标。base_url 创建时必须过 scope_guard，授权状态登记
- security_scan_profile：扫描策略。内置 6 个（code 非空、is_builtin=True、project_id 为空）
- security_scan_job：扫描任务。DB 支撑的异步执行记录，不是伪造的 CaseExecution
- security_scan_event：过程事件。payload_json 写入前必须已脱敏
- security_scan_finding：扫描任务与 security_finding 的多对多关系（重复命中不重置人工状态）

模型 feature-local，不进 app/models/__init__.py（红线 17），由本迁移显式建表。
不修改 security_finding / test_run / test_report / environment / project 的列。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.sql import func, text


revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


# 新建表（严格按外键依赖排序，downgrade 逆序删除）。
_NEW_TABLES = [
    "security_scan_auth_profile",
    "security_scan_target",
    "security_scan_profile",
    "security_scan_job",
    "security_scan_finding",
    "security_scan_event",
]


def _table_definitions() -> dict[str, list]:
    """每张表的列与约束定义（与 ORM 模型逐列对齐）。"""
    return {
        "security_scan_auth_profile": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("auth_mode", sa.String(length=20), nullable=False),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("session_method", sa.String(length=30), nullable=True),
            sa.Column("session_header", sa.String(length=100), nullable=True),
            sa.Column("session_name", sa.String(length=100), nullable=True),
            # 明文凭据只以密文存在；任何接口都不返回这一列的原文。
            sa.Column("credential_encrypted", sa.Text(), nullable=True),
            sa.Column("token_fingerprint", sa.String(length=64), nullable=True),
            sa.Column("has_credential", sa.Boolean(), server_default=text("false"), nullable=False),
            sa.Column("credential_updated_at", sa.DateTime(), nullable=True),
            sa.Column("authentication_check_url", sa.String(length=500), nullable=True),
            sa.Column("logged_in_indicator", sa.String(length=200), nullable=True),
            sa.Column("logged_out_indicator", sa.String(length=200), nullable=True),
            sa.Column("expected_user_id", sa.String(length=100), nullable=True),
            sa.Column(
                "auth_expiry_policy", sa.String(length=20), server_default=text("'UNKNOWN'"),
                nullable=False,
            ),
            sa.Column("credential_expires_at", sa.DateTime(), nullable=True),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        ],
        "security_scan_target": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column(
                "target_type", sa.String(length=20), server_default=text("'API'"), nullable=False,
            ),
            sa.Column("base_url", sa.String(length=500), nullable=False),
            sa.Column("entry_url", sa.String(length=500), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column(
                "authorization_status", sa.String(length=20),
                server_default=text("'PENDING'"), nullable=False,
            ),
            sa.Column("authorization_note", sa.String(length=500), nullable=True),
            sa.Column(
                "active_scan_allowed", sa.Boolean(), server_default=text("false"), nullable=False,
            ),
            sa.Column("allowed_hosts", sa.JSON(), nullable=True),
            sa.Column("include_paths", sa.JSON(), nullable=True),
            sa.Column("exclude_paths", sa.JSON(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        ],
        "security_scan_profile": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=True),
            sa.Column("code", sa.String(length=60), nullable=True),
            sa.Column(
                "is_builtin", sa.Boolean(), server_default=text("false"), nullable=False,
            ),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("scan_mode", sa.String(length=30), nullable=False),
            sa.Column(
                "spider_enabled", sa.Boolean(), server_default=text("true"), nullable=False,
            ),
            sa.Column(
                "client_spider_enabled", sa.Boolean(), server_default=text("false"), nullable=False,
            ),
            sa.Column(
                "passive_enabled", sa.Boolean(), server_default=text("true"), nullable=False,
            ),
            sa.Column(
                "active_enabled", sa.Boolean(), server_default=text("false"), nullable=False,
            ),
            sa.Column("authentication_profile_id", sa.Integer(), nullable=True),
            sa.Column("max_duration", sa.Integer(), server_default=text("30"), nullable=False),
            sa.Column("max_depth", sa.Integer(), server_default=text("5"), nullable=False),
            sa.Column(
                "max_concurrency", sa.Integer(), server_default=text("4"), nullable=False,
            ),
            sa.Column("request_delay", sa.Integer(), server_default=text("300"), nullable=False),
            sa.Column("max_alerts_per_rule", sa.Integer(), nullable=True),
            sa.Column("max_request_budget", sa.Integer(), nullable=True),
            sa.Column("include_paths", sa.JSON(), nullable=True),
            sa.Column("exclude_paths", sa.JSON(), nullable=True),
            sa.Column("selected_rule_ids", sa.JSON(), nullable=True),
            sa.Column("enabled", sa.Boolean(), server_default=text("true"), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["authentication_profile_id"], ["security_scan_auth_profile.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(["created_by"], ["user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["updated_by"], ["user.id"], ondelete="SET NULL"),
        ],
        "security_scan_job": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("target_id", sa.Integer(), nullable=False),
            sa.Column("environment_id", sa.Integer(), nullable=True),
            sa.Column("scan_profile_id", sa.Integer(), nullable=False),
            sa.Column("scan_mode", sa.String(length=30), nullable=False),
            sa.Column(
                "status", sa.String(length=24), server_default=text("'PENDING'"), nullable=False,
            ),
            sa.Column("progress", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("stage", sa.String(length=40), nullable=True),
            sa.Column("authentication_mode", sa.String(length=20), nullable=True),
            sa.Column("authentication_status", sa.String(length=20), nullable=True),
            sa.Column(
                "browser_session_established", sa.Boolean(),
                server_default=text("false"), nullable=False,
            ),
            sa.Column("initiated_by", sa.Integer(), nullable=True),
            sa.Column("approved_by", sa.Integer(), nullable=True),
            sa.Column("approval_note", sa.String(length=500), nullable=True),
            sa.Column("zap_scan_reference", sa.String(length=100), nullable=True),
            sa.Column("test_run_id", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("duration_ms", sa.BigInteger(), nullable=True),
            sa.Column("total_alerts", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("high_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("medium_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("low_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("info_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column(
                "urls_discovered", sa.Integer(), server_default=text("0"), nullable=False,
            ),
            sa.Column("requests_made", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column(
                "new_findings_count", sa.Integer(), server_default=text("0"), nullable=False,
            ),
            sa.Column(
                "duplicate_findings_count", sa.Integer(), server_default=text("0"), nullable=False,
            ),
            sa.Column("coverage_summary", sa.JSON(), nullable=True),
            sa.Column("error_code", sa.String(length=60), nullable=True),
            sa.Column("error_message", sa.String(length=500), nullable=True),
            sa.Column(
                "cancel_requested", sa.Boolean(), server_default=text("false"), nullable=False,
            ),
            sa.Column("worker_owner", sa.String(length=64), nullable=True),
            sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
            sa.Column("started_by_worker_at", sa.DateTime(), nullable=True),
            sa.Column("poll_count", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["target_id"], ["security_scan_target.id"], ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["scan_profile_id"], ["security_scan_profile.id"], ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(["environment_id"], ["environment.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["test_run_id"], ["test_run.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["initiated_by"], ["user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["approved_by"], ["user.id"], ondelete="SET NULL"),
        ],
        "security_scan_finding": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("finding_id", sa.Integer(), nullable=False),
            sa.Column(
                "source", sa.String(length=20), server_default=text("'ZAP'"), nullable=False,
            ),
            sa.Column("source_rule_id", sa.String(length=20), nullable=True),
            sa.Column("source_alert_name", sa.String(length=200), nullable=True),
            sa.Column("risk", sa.String(length=20), nullable=True),
            sa.Column("confidence", sa.Integer(), nullable=True),
            sa.Column("url", sa.String(length=800), nullable=True),
            sa.Column("method", sa.String(length=10), nullable=True),
            sa.Column("parameter", sa.String(length=200), nullable=True),
            sa.Column("fingerprint", sa.String(length=200), nullable=True),
            sa.Column("evidence_json", sa.JSON(), nullable=True),
            sa.Column(
                "first_seen_in_job", sa.Boolean(), server_default=text("false"), nullable=False,
            ),
            sa.Column("repeat_count", sa.Integer(), server_default=text("1"), nullable=False),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["job_id"], ["security_scan_job.id"], ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["finding_id"], ["security_finding.id"], ondelete="CASCADE",
            ),
        ],
        "security_scan_event": [
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("job_id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("seq", sa.Integer(), server_default=text("0"), nullable=False),
            sa.Column("event_type", sa.String(length=20), nullable=False),
            sa.Column("stage", sa.String(length=40), nullable=True),
            sa.Column("message", sa.String(length=500), nullable=True),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["job_id"], ["security_scan_job.id"], ondelete="CASCADE",
            ),
        ],
    }


# 普通索引定义（名称与 ORM 的 index=True / Index(...) 声明保持一致）。
_INDEX_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "security_scan_auth_profile": [
        ("ix_security_scan_auth_profile_id", ["id"]),
        ("ix_security_scan_auth_profile_project_id", ["project_id"]),
        ("ix_security_scan_auth_profile_project_enabled", ["project_id", "enabled"]),
        ("ix_security_scan_auth_profile_created_by", ["created_by"]),
    ],
    "security_scan_target": [
        ("ix_security_scan_target_id", ["id"]),
        ("ix_security_scan_target_project_id", ["project_id"]),
        ("ix_security_scan_target_environment_id", ["environment_id"]),
        ("ix_security_scan_target_project_enabled", ["project_id", "enabled"]),
        ("ix_security_scan_target_created_by", ["created_by"]),
    ],
    "security_scan_profile": [
        ("ix_security_scan_profile_id", ["id"]),
        ("ix_security_scan_profile_project_id", ["project_id"]),
        ("ix_security_scan_profile_authentication_profile_id", ["authentication_profile_id"]),
        ("ix_security_scan_profile_project_enabled", ["project_id", "enabled"]),
        ("ix_security_scan_profile_created_by", ["created_by"]),
    ],
    "security_scan_job": [
        ("ix_security_scan_job_id", ["id"]),
        ("ix_security_scan_job_project_id", ["project_id"]),
        ("ix_security_scan_job_target_id", ["target_id"]),
        ("ix_security_scan_job_environment_id", ["environment_id"]),
        ("ix_security_scan_job_scan_profile_id", ["scan_profile_id"]),
        ("ix_security_scan_job_initiated_by", ["initiated_by"]),
        ("ix_security_scan_job_test_run_id", ["test_run_id"]),
        ("ix_security_scan_job_project_status", ["project_id", "status"]),
        ("ix_security_scan_job_inflight_heartbeat", ["status", "heartbeat_at"]),
    ],
    "security_scan_finding": [
        ("ix_security_scan_finding_id", ["id"]),
        ("ix_security_scan_finding_project_id", ["project_id"]),
        ("ix_security_scan_finding_job_id", ["job_id"]),
        ("ix_security_scan_finding_finding_id", ["finding_id"]),
        ("ix_security_scan_finding_project_finding", ["project_id", "finding_id"]),
    ],
    "security_scan_event": [
        ("ix_security_scan_event_id", ["id"]),
        ("ix_security_scan_event_job_id", ["job_id"]),
        ("ix_security_scan_event_project_id", ["project_id"]),
    ],
}

# 唯一索引：CREATE TABLE 无法表达（列上 unique=True / Index(unique=True) 都不带名字）。
# - code：平台内置策略代号唯一（自定义策略 code 为空，不参与唯一性）。
# - (job_id, finding_id)：同一任务对同一 Finding 只记录一行，重复扫描新增另一行。
# - (job_id, seq)：过程事件序号在任务内唯一。写入方是 read-then-write，
#   worker 线程与 HTTP 请求并发时会算出同一个 seq，靠这个索引挡住重号。
_UNIQUE_INDEXES: list[tuple[str, str, list[str]]] = [
    ("ix_security_scan_profile_code", "security_scan_profile", ["code"]),
    ("uq_security_scan_finding_job_finding", "security_scan_finding", ["job_id", "finding_id"]),
    ("uq_security_scan_event_job_seq", "security_scan_event", ["job_id", "seq"]),
]

_TABLE_COMMENTS: dict[str, str] = {
    "security_scan_auth_profile": "OWASP ZAP 认证配置：凭据只存密文，接口不回显明文",
    "security_scan_target": "OWASP ZAP 扫描目标：范围与授权登记的唯一入口",
    "security_scan_profile": "OWASP ZAP 扫描策略：内置 6 个 + 项目自定义",
    "security_scan_job": "OWASP ZAP 扫描任务：DB 支撑的异步执行，不由 FastAPI 后台任务承担",
    "security_scan_finding": "扫描任务与 security_finding 的多对多关系：保留每次出现记录",
    "security_scan_event": "OWASP ZAP 扫描过程事件（脱敏），用于审计与详情页时间线",
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
    """按表补齐索引（普通 + 唯一），允许在已建索引的库上安全重放。"""
    for table in _NEW_TABLES:
        existing = _existing_index_names(bind, table)
        for name, columns in _INDEX_DEFINITIONS.get(table, []):
            if name in existing:
                continue
            columns_sql = ", ".join(f'"{c}"' for c in columns)
            bind.execute(text(f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns_sql})"))

    for name, table, columns in _UNIQUE_INDEXES:
        if name in _existing_index_names(bind, table):
            continue
        columns_sql = ", ".join(f'"{c}"' for c in columns)
        bind.execute(
            text(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({columns_sql})")
        )


def upgrade() -> None:
    """正向迁移：建 6 张表 + 索引 + 平台内置扫描策略（全幂等）。"""
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

    # 事件序号索引已从普通索引改为唯一索引（兜住并发重号），清掉早期版本留下的普通索引。
    bind.execute(text("DROP INDEX IF EXISTS ix_security_scan_event_job_seq"))

    # 3. 平台内置扫描策略（按 code 幂等跳过）。
    #    延迟 import：避免 alembic 收集迁移版本时把整个 feature 包拉进来。
    from app.features.security_testing.zap.builtins import ensure_builtin_profiles

    ensure_builtin_profiles(bind)


def downgrade() -> None:
    """反向迁移：删 6 张表（IF EXISTS，逆序可安全重放）。

    唯一索引在 CREATE TABLE 之外单独创建，需要先 DROP INDEX；表上的普通索引由
    DROP TABLE 连带删除。
    """
    bind = op.get_bind()

    for name, _table, _columns in _UNIQUE_INDEXES:
        bind.execute(text(f"DROP INDEX IF EXISTS {name}"))

    for table in reversed(_NEW_TABLES):
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
