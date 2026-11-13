"""云效自动化测试中心的数据模型。

一次云效运行对应一条 AutomationExecution，报告文件只存路径。
凭证列只保存 Fernet 密文，响应层不得读出明文。
"""

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func, text

from app.core.database.base import Base
from app.core.database.soft_delete import SoftDeleteBase


class AutomationIntegrationConfig(SoftDeleteBase):
    """一个业务项目下的云效接入配置。令牌和回调密钥只以密文保存。"""

    __tablename__ = "automation_integration_config"
    __table_args__ = (
        Index(
            "uq_automation_integration_project_name_live", "project_id", "name", unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_automation_integration_callback_key_live", "callback_key", unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        {"comment": "云效接入配置：地址、组织、密文凭证与回调标识"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(100), nullable=False, comment="配置名称")
    provider_type = Column(String(20), nullable=False, server_default=text("'YUNXIAO'"), comment="执行平台")
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    allow_private_network = Column(Boolean, nullable=False, server_default=text("false"), comment="管理员授权访问内网 Jenkins")
    api_base_url = Column(String(300), nullable=False, comment="云效 OpenAPI 域名")
    organization_id = Column(String(64), nullable=False, server_default=text("''"), comment="云效企业 ID，Region 版可空")
    deployment = Column(String(20), nullable=False, server_default=text("'central'"), comment="central 或 region")
    access_token_encrypted = Column(Text, nullable=False, comment="个人访问令牌密文")
    callback_key = Column(String(64), nullable=False, comment="回调地址中的公开标识，不是密钥")
    callback_secret_encrypted = Column(Text, nullable=False, comment="回调 HMAC 密钥密文")
    default_timeout_seconds = Column(Integer, nullable=False, server_default=text("3600"), comment="默认执行超时秒数")
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    jenkins_credential = relationship(
        "AutomationJenkinsCredential", uselist=False, cascade="all, delete-orphan", lazy="select",
    )


class AutomationJenkinsCredential(Base):
    """Jenkins 凭据独立保存；Username 可读，API Token 只保存 Fernet 密文。"""

    __tablename__ = "automation_jenkins_credential"

    integration_config_id = Column(
        Integer, ForeignKey("automation_integration_config.id", ondelete="CASCADE"), primary_key=True,
    )
    base_url = Column(String(500), nullable=False)
    username = Column(String(200), nullable=False)
    api_token_encrypted = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class AutomationProject(SoftDeleteBase):
    """外部自动化项目。脚本留在 Codeup，这里只保存绑定和默认执行参数。"""

    __tablename__ = "automation_project"
    __table_args__ = (
        Index(
            "uq_automation_project_name_live", "project_id", "name", unique=True,
            postgresql_where=text("deleted_at IS NULL"),
            sqlite_where=text("deleted_at IS NULL"),
        ),
        Index("ix_automation_project_project_created", "project_id", "created_at"),
        {"comment": "自动化项目：仓库、默认分支、通知策略"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    integration_config_id = Column(
        Integer, ForeignKey("automation_integration_config.id", ondelete="RESTRICT"), nullable=False, index=True,
    )
    name = Column(String(120), nullable=False)
    description = Column(String(500), nullable=False, server_default=text("''"))
    repository_url = Column(String(500), nullable=False, server_default=text("''"), comment="Codeup 仓库地址")
    repository_id = Column(String(64), nullable=False, server_default=text("''"), comment="Codeup 仓库标识")
    default_branch = Column(String(200), nullable=False, server_default=text("'master'"))
    default_environment = Column(String(100), nullable=False, server_default=text("''"))
    pytest_args = Column(String(500), nullable=False, server_default=text("''"))
    test_tags = Column(String(300), nullable=False, server_default=text("''"))
    test_scope = Column(String(500), nullable=False, server_default=text("''"))
    pipeline_params = Column(JSON, nullable=True, comment="附加流水线变量")
    timeout_seconds = Column(Integer, nullable=False, server_default=text("3600"))
    notification_channel_id = Column(
        Integer, ForeignKey("notification_channel.id", ondelete="SET NULL"), nullable=True,
    )
    notify_condition = Column(String(20), nullable=False, server_default=text("'ALWAYS'"))
    enabled = Column(Boolean, nullable=False, server_default=text("true"))
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class AutomationPipeline(Base):
    """自动化项目绑定的一条云效 Flow 流水线。"""

    __tablename__ = "automation_pipeline"
    __table_args__ = (
        UniqueConstraint("automation_project_id", "pipeline_id", name="uq_automation_pipeline_binding"),
        {"comment": "云效流水线绑定"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    automation_project_id = Column(
        Integer, ForeignKey("automation_project.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name = Column(String(120), nullable=False, server_default=text("''"))
    pipeline_id = Column(String(255), nullable=False, comment="云效流水线 ID 或 Jenkins Folder/Job 路径")
    is_default = Column(Boolean, nullable=False, server_default=text("true"))
    extra_params = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class AutomationExecution(Base):
    """一次流水线运行。重复运行新增记录，不覆盖历史。"""

    __tablename__ = "automation_execution"
    __table_args__ = (
        Index("ix_automation_execution_project_status", "project_id", "status", "created_at"),
        Index("ix_automation_execution_automation_project", "automation_project_id", "created_at"),
        Index(
            "uq_automation_execution_pipeline_run",
            "automation_project_id",
            "pipeline_run_id",
            unique=True,
            postgresql_where=text("pipeline_run_id IS NOT NULL"),
        ),
        Index(
            "uq_automation_execution_jenkins_queue",
            "integration_config_id", "external_queue_id", unique=True,
            postgresql_where=text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_queue_id IS NOT NULL"
            ),
            sqlite_where=text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_queue_id IS NOT NULL"
            ),
        ),
        Index(
            "uq_automation_execution_jenkins_build",
            "integration_config_id", "external_pipeline_id", "external_build_number", unique=True,
            postgresql_where=text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_build_number IS NOT NULL"
            ),
            sqlite_where=text(
                "provider_type = 'JENKINS' AND integration_config_id IS NOT NULL AND external_build_number IS NOT NULL"
            ),
        ),
        Index("ix_automation_execution_stop_requested", "status", "stop_requested_at"),
        {"comment": "云效自动化执行记录"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False)
    automation_project_id = Column(
        Integer, ForeignKey("automation_project.id", ondelete="CASCADE"), nullable=False,
    )
    pipeline_binding_id = Column(
        Integer, ForeignKey("automation_pipeline.id", ondelete="SET NULL"), nullable=True,
    )
    integration_config_id = Column(
        Integer, ForeignKey("automation_integration_config.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    provider_type = Column(String(20), nullable=False, server_default=text("'YUNXIAO'"))
    external_pipeline_id = Column(String(255), nullable=False, server_default=text("''"))
    pipeline_run_id = Column(String(64), nullable=True, comment="云效运行实例 ID")
    external_queue_id = Column(String(64), nullable=True)
    external_build_number = Column(Integer, nullable=True)
    external_run_url = Column(String(1000), nullable=False, server_default=text("''"))
    stop_reason = Column(String(20), nullable=True, comment="外部终止请求原因：CANCELLED 或 TIMEOUT")
    stop_requested_at = Column(DateTime, nullable=True)
    queue_missing_since = Column(DateTime, nullable=True)
    trigger_source = Column(String(20), nullable=False, server_default=text("'MANUAL'"))
    status = Column(String(20), nullable=False, server_default=text("'PENDING'"), index=True)
    branch = Column(String(200), nullable=False, server_default=text("''"))
    environment_name = Column(String(100), nullable=False, server_default=text("''"))
    pytest_args = Column(String(500), nullable=False, server_default=text("''"))
    test_tags = Column(String(300), nullable=False, server_default=text("''"))
    test_scope = Column(String(500), nullable=False, server_default=text("''"))
    run_params = Column(JSON, nullable=True, comment="传给云效的非敏感参数")
    git_commit = Column(String(64), nullable=False, server_default=text("''"))
    external_status = Column(String(40), nullable=False, server_default=text("''"))
    log_excerpt = Column(Text, nullable=False, server_default=text("''"))
    error_message = Column(String(500), nullable=False, server_default=text("''"))
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    timeout_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    notify_status = Column(String(20), nullable=False, server_default=text("'WAITING'"))
    notify_attempts = Column(Integer, nullable=False, server_default=text("0"))
    last_sync_at = Column(DateTime, nullable=True)
    created_by = Column(Integer, ForeignKey("user.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class AutomationReport(Base):
    """Allure 报告元数据。HTML 与压缩包位于服务器目录，不写入本表。"""

    __tablename__ = "automation_report"
    __table_args__ = (
        UniqueConstraint("execution_id", name="uq_automation_report_execution"),
        Index("ix_automation_report_project_created", "automation_project_id", "created_at"),
        {"comment": "Allure 报告元数据与存储路径"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(
        Integer, ForeignKey("automation_execution.id", ondelete="CASCADE"), nullable=False,
    )
    project_id = Column(Integer, ForeignKey("project.id", ondelete="CASCADE"), nullable=False, index=True)
    automation_project_id = Column(
        Integer, ForeignKey("automation_project.id", ondelete="CASCADE"), nullable=False,
    )
    storage_dir = Column(String(500), nullable=False, comment="相对报告根目录的 HTML 目录")
    archive_sha256 = Column(String(64), nullable=False, server_default=text("''"))
    archive_size = Column(Integer, nullable=False, server_default=text("0"))
    status = Column(String(20), nullable=False, server_default=text("'READY'"))
    total_cases = Column(Integer, nullable=False, server_default=text("0"))
    passed_cases = Column(Integer, nullable=False, server_default=text("0"))
    failed_cases = Column(Integer, nullable=False, server_default=text("0"))
    broken_cases = Column(Integer, nullable=False, server_default=text("0"))
    skipped_cases = Column(Integer, nullable=False, server_default=text("0"))
    unknown_cases = Column(Integer, nullable=False, server_default=text("0"))
    pass_rate = Column(Numeric(5, 2), nullable=False, server_default=text("0"))
    duration_ms = Column(Integer, nullable=True)
    suite_summary = Column(JSON, nullable=True, comment="测试套件分布")
    history_included = Column(Boolean, nullable=False, server_default=text("false"))
    generated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class AutomationArtifact(Base):
    """报告压缩包、原始结果和执行日志的文件索引。"""

    __tablename__ = "automation_artifact"
    __table_args__ = ({"comment": "自动化执行附件索引"},)

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_id = Column(
        Integer, ForeignKey("automation_execution.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    report_id = Column(Integer, ForeignKey("automation_report.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(40), nullable=False, comment="ALLURE_HTML_ZIP、ALLURE_RESULTS 或 LOG")
    relative_path = Column(String(500), nullable=False)
    sha256 = Column(String(64), nullable=False, server_default=text("''"))
    size_bytes = Column(Integer, nullable=False, server_default=text("0"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class AutomationCallbackReceipt(Base):
    """回调幂等收据。同一配置下的幂等键只能成功处理一次。"""

    __tablename__ = "automation_callback_receipt"
    __table_args__ = (
        UniqueConstraint("integration_config_id", "idempotency_key", name="uq_automation_callback_idempotency"),
        {"comment": "云效回调幂等收据"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    integration_config_id = Column(
        Integer, ForeignKey("automation_integration_config.id", ondelete="CASCADE"), nullable=False,
    )
    idempotency_key = Column(String(120), nullable=False)
    execution_id = Column(Integer, ForeignKey("automation_execution.id", ondelete="SET NULL"), nullable=True)
    payload_sha256 = Column(String(64), nullable=False, server_default=text("''"))
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class AutomationReportGrant(Base):
    """报告静态资源的短期访问凭据。只保存哈希，明文只返回给当前浏览者一次。"""

    __tablename__ = "automation_report_grant"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_automation_report_grant_token"),
        {"comment": "Allure 报告文件访问凭据"},
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_id = Column(Integer, ForeignKey("automation_report.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
