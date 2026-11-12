"""新增云效自动化测试中心表。

报告正文不入库。凭证列只保存密文。
"""

import sqlalchemy as sa
from alembic import op


revision = "0079"
down_revision = "0078"
branch_labels = None
depends_on = None


def upgrade():
    """创建自动化接入、执行、报告和回调表。"""
    op.create_table(
        "automation_integration_config",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False, comment="配置名称"),
        sa.Column("api_base_url", sa.String(300), nullable=False, comment="云效 OpenAPI 域名"),
        sa.Column("organization_id", sa.String(64), nullable=False, server_default="", comment="云效企业 ID"),
        sa.Column("deployment", sa.String(20), nullable=False, server_default="central", comment="central 或 region"),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False, comment="个人访问令牌密文"),
        sa.Column("callback_key", sa.String(64), nullable=False, comment="回调公开标识"),
        sa.Column("callback_secret_encrypted", sa.Text(), nullable=False, comment="回调密钥密文"),
        sa.Column("default_timeout_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "name", name="uq_automation_integration_project_name"),
        sa.UniqueConstraint("callback_key", name="uq_automation_integration_callback_key"),
        comment="云效接入配置",
    )
    op.create_index("ix_automation_integration_config_project_id", "automation_integration_config", ["project_id"])

    op.create_table(
        "automation_project",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("integration_config_id", sa.Integer(), sa.ForeignKey("automation_integration_config.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.String(500), nullable=False, server_default=""),
        sa.Column("repository_url", sa.String(500), nullable=False, server_default=""),
        sa.Column("repository_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("default_branch", sa.String(200), nullable=False, server_default="master"),
        sa.Column("default_environment", sa.String(100), nullable=False, server_default=""),
        sa.Column("pytest_args", sa.String(500), nullable=False, server_default=""),
        sa.Column("test_tags", sa.String(300), nullable=False, server_default=""),
        sa.Column("test_scope", sa.String(500), nullable=False, server_default=""),
        sa.Column("pipeline_params", sa.JSON(), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("notification_channel_id", sa.Integer(), sa.ForeignKey("notification_channel.id", ondelete="SET NULL"), nullable=True),
        sa.Column("notify_condition", sa.String(20), nullable=False, server_default="ALWAYS"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "name", name="uq_automation_project_name"),
        comment="自动化项目",
    )
    op.create_index("ix_automation_project_project_id", "automation_project", ["project_id"])
    op.create_index("ix_automation_project_integration_config_id", "automation_project", ["integration_config_id"])
    op.create_index("ix_automation_project_project_created", "automation_project", ["project_id", "created_at"])

    op.create_table(
        "automation_pipeline",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("automation_project_id", sa.Integer(), sa.ForeignKey("automation_project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("pipeline_id", sa.String(64), nullable=False, comment="云效流水线 ID"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("extra_params", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("automation_project_id", "pipeline_id", name="uq_automation_pipeline_binding"),
        comment="云效流水线绑定",
    )
    op.create_index("ix_automation_pipeline_automation_project_id", "automation_pipeline", ["automation_project_id"])

    op.create_table(
        "automation_execution",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("automation_project_id", sa.Integer(), sa.ForeignKey("automation_project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("pipeline_binding_id", sa.Integer(), sa.ForeignKey("automation_pipeline.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_pipeline_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("pipeline_run_id", sa.String(64), nullable=True, comment="云效运行实例 ID"),
        sa.Column("trigger_source", sa.String(20), nullable=False, server_default="MANUAL"),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("branch", sa.String(200), nullable=False, server_default=""),
        sa.Column("environment_name", sa.String(100), nullable=False, server_default=""),
        sa.Column("pytest_args", sa.String(500), nullable=False, server_default=""),
        sa.Column("test_tags", sa.String(300), nullable=False, server_default=""),
        sa.Column("test_scope", sa.String(500), nullable=False, server_default=""),
        sa.Column("run_params", sa.JSON(), nullable=True),
        sa.Column("git_commit", sa.String(64), nullable=False, server_default=""),
        sa.Column("external_status", sa.String(40), nullable=False, server_default=""),
        sa.Column("log_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.String(500), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("timeout_at", sa.DateTime(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("notify_status", sa.String(20), nullable=False, server_default="WAITING"),
        sa.Column("notify_attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        comment="云效自动化执行记录",
    )
    op.create_index("ix_automation_execution_project_id", "automation_execution", ["project_id"])
    op.create_index("ix_automation_execution_status", "automation_execution", ["status"])
    op.create_index("ix_automation_execution_project_status", "automation_execution", ["project_id", "status", "created_at"])
    op.create_index("ix_automation_execution_automation_project", "automation_execution", ["automation_project_id", "created_at"])
    op.create_index(
        "uq_automation_execution_pipeline_run",
        "automation_execution",
        ["automation_project_id", "pipeline_run_id"],
        unique=True,
        postgresql_where=sa.text("pipeline_run_id IS NOT NULL"),
    )

    op.create_table(
        "automation_report",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.Integer(), sa.ForeignKey("automation_execution.id", ondelete="CASCADE"), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("automation_project_id", sa.Integer(), sa.ForeignKey("automation_project.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_dir", sa.String(500), nullable=False, comment="HTML 报告相对目录"),
        sa.Column("archive_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("archive_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="READY"),
        sa.Column("total_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("broken_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unknown_cases", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_rate", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("suite_summary", sa.JSON(), nullable=True),
        sa.Column("history_included", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("execution_id", name="uq_automation_report_execution"),
        comment="Allure 报告元数据",
    )
    op.create_index("ix_automation_report_project_id", "automation_report", ["project_id"])
    op.create_index("ix_automation_report_project_created", "automation_report", ["automation_project_id", "created_at"])

    op.create_table(
        "automation_artifact",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("execution_id", sa.Integer(), sa.ForeignKey("automation_execution.id", ondelete="CASCADE"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("automation_report.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("relative_path", sa.String(500), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        comment="自动化执行附件索引",
    )
    op.create_index("ix_automation_artifact_execution_id", "automation_artifact", ["execution_id"])

    op.create_table(
        "automation_callback_receipt",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("integration_config_id", sa.Integer(), sa.ForeignKey("automation_integration_config.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("execution_id", sa.Integer(), sa.ForeignKey("automation_execution.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("integration_config_id", "idempotency_key", name="uq_automation_callback_idempotency"),
        comment="云效回调幂等收据",
    )

    op.create_table(
        "automation_report_grant",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("automation_report.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("token_hash", name="uq_automation_report_grant_token"),
        comment="Allure 报告文件访问凭据",
    )
    op.create_index("ix_automation_report_grant_report_id", "automation_report_grant", ["report_id"])


def downgrade():
    """删除自动化测试中心表。已有执行记录时拒绝回滚，避免静默丢历史。"""
    bind = op.get_bind()
    remaining = bind.execute(sa.text("SELECT count(*) FROM automation_execution")).scalar_one()
    if remaining:
        raise RuntimeError("存在自动化执行记录，回滚前需要先清理这些记录")
    for name in (
        "automation_report_grant",
        "automation_callback_receipt",
        "automation_artifact",
        "automation_report",
        "automation_execution",
        "automation_pipeline",
        "automation_project",
        "automation_integration_config",
    ):
        op.drop_table(name)
