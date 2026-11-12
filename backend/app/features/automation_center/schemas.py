"""自动化测试中心接口契约。凭证字段只出现在写入请求中。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Deployment = Literal["central", "region"]
NotifyCondition = Literal["ALWAYS", "ONLY_FAILED", "NEVER"]
ExecutionStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED", "TIMEOUT"]
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class IntegrationCreate(BaseModel):
    """创建云效接入配置。令牌和回调密钥只写入一次。"""

    name: str = Field(min_length=1, max_length=100)
    api_base_url: str = "https://openapi-rdc.aliyuncs.com"
    organization_id: str = ""
    deployment: Deployment = "central"
    access_token: str = Field(min_length=8, max_length=500)
    callback_secret: str = Field(min_length=8, max_length=200)
    default_timeout_seconds: int = Field(3600, ge=60, le=86400)

    @field_validator("api_base_url")
    @classmethod
    def https_base(cls, value: str) -> str:
        """云效接口只接受 HTTPS，避免令牌在明文链路传输。"""
        normalized = value.strip().rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("云效 API 地址必须使用 HTTPS")
        return normalized

    @model_validator(mode="after")
    def organization_required(self):
        """中心版路径包含企业 ID，缺失时无法调用官方接口。"""
        if self.deployment == "central" and not _ID.fullmatch(self.organization_id):
            raise ValueError("中心版必须填写云效企业 ID")
        if self.organization_id and not _ID.fullmatch(self.organization_id):
            raise ValueError("企业 ID 不合法")
        return self


class IntegrationUpdate(BaseModel):
    """更新接入配置。令牌和密钥留空表示保持原值。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    api_base_url: str | None = None
    organization_id: str | None = None
    deployment: Deployment | None = None
    access_token: str | None = Field(None, max_length=500)
    callback_secret: str | None = Field(None, max_length=200)
    default_timeout_seconds: int | None = Field(None, ge=60, le=86400)

    @field_validator("api_base_url")
    @classmethod
    def https_base(cls, value: str | None) -> str | None:
        """更新地址时同样限制 HTTPS。"""
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("云效 API 地址必须使用 HTTPS")
        return normalized


class IntegrationResponse(BaseModel):
    """接入配置响应。不包含令牌和回调密钥。"""

    id: int
    project_id: int
    name: str
    api_base_url: str
    organization_id: str
    deployment: str
    token_configured: bool
    callback_key: str
    callback_secret_configured: bool
    callback_path: str
    default_timeout_seconds: int
    created_at: datetime


class IntegrationListResponse(BaseModel):
    """接入配置分页。"""

    items: list[IntegrationResponse]
    total: int
    page: int
    page_size: int


class ConnectionTestResponse(BaseModel):
    """连通性结果。不回传云效运行详情。"""

    ok: bool
    message: str
    sample_run_count: int = 0


class AutomationProjectCreate(BaseModel):
    """创建自动化项目并绑定一条流水线。"""

    integration_config_id: int
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    repository_url: str = Field("", max_length=500)
    repository_id: str = Field("", max_length=64)
    pipeline_id: str = Field(min_length=1, max_length=64)
    pipeline_name: str = Field("", max_length=120)
    default_branch: str = Field("master", max_length=200)
    default_environment: str = Field("", max_length=100)
    pytest_args: str = Field("", max_length=500)
    test_tags: str = Field("", max_length=300)
    test_scope: str = Field("", max_length=500)
    pipeline_params: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(3600, ge=60, le=86400)
    notification_channel_id: int | None = None
    notify_condition: NotifyCondition = "ALWAYS"

    @field_validator("pipeline_id")
    @classmethod
    def pipeline_id_safe(cls, value: str) -> str:
        """流水线 ID 会进入云效 URL。"""
        if not _ID.fullmatch(value):
            raise ValueError("流水线 ID 不合法")
        return value


class AutomationProjectUpdate(BaseModel):
    """更新自动化项目。未传字段保持不变。"""

    name: str | None = Field(None, min_length=1, max_length=120)
    description: str | None = Field(None, max_length=500)
    repository_url: str | None = Field(None, max_length=500)
    repository_id: str | None = Field(None, max_length=64)
    pipeline_id: str | None = Field(None, max_length=64)
    pipeline_name: str | None = Field(None, max_length=120)
    default_branch: str | None = Field(None, max_length=200)
    default_environment: str | None = Field(None, max_length=100)
    pytest_args: str | None = Field(None, max_length=500)
    test_tags: str | None = Field(None, max_length=300)
    test_scope: str | None = Field(None, max_length=500)
    pipeline_params: dict[str, str] | None = None
    timeout_seconds: int | None = Field(None, ge=60, le=86400)
    notification_channel_id: int | None = None
    clear_notification_channel: bool = False
    notify_condition: NotifyCondition | None = None
    enabled: bool | None = None
    integration_config_id: int | None = None


class AutomationProjectResponse(BaseModel):
    """自动化项目及最近一次执行摘要。"""

    id: int
    project_id: int
    integration_config_id: int
    name: str
    description: str
    repository_url: str
    repository_id: str
    pipeline_id: str
    pipeline_name: str
    default_branch: str
    default_environment: str
    pytest_args: str
    test_tags: str
    test_scope: str
    pipeline_params: dict[str, str]
    timeout_seconds: int
    notification_channel_id: int | None
    notify_condition: str
    enabled: bool
    last_status: str | None = None
    last_execution_at: datetime | None = None
    created_at: datetime


class AutomationProjectListResponse(BaseModel):
    """自动化项目分页。"""

    items: list[AutomationProjectResponse]
    total: int
    page: int
    page_size: int


class ExecutionTrigger(BaseModel):
    """手动触发。留空的字段使用自动化项目默认值。"""

    branch: str | None = Field(None, max_length=200)
    environment_name: str | None = Field(None, max_length=100)
    pytest_args: str | None = Field(None, max_length=500)
    test_tags: str | None = Field(None, max_length=300)
    test_scope: str | None = Field(None, max_length=500)
    pipeline_id: str | None = Field(None, max_length=64)


class ExecutionResponse(BaseModel):
    """执行记录。云效运行 ID 与平台执行 ID 同时保留。"""

    id: int
    project_id: int
    automation_project_id: int
    automation_project_name: str
    pipeline_id: str
    pipeline_run_id: str | None
    trigger_source: str
    status: ExecutionStatus
    branch: str
    environment_name: str
    pytest_args: str
    test_tags: str
    test_scope: str
    git_commit: str
    external_status: str
    log_excerpt: str
    error_message: str
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    notify_status: str
    report_id: int | None
    created_at: datetime


class ExecutionListResponse(BaseModel):
    """执行历史分页。"""

    items: list[ExecutionResponse]
    total: int
    page: int
    page_size: int


class ReportResponse(BaseModel):
    """Allure 报告元数据。"""

    id: int
    execution_id: int
    project_id: int
    automation_project_id: int
    automation_project_name: str
    status: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    broken_cases: int
    skipped_cases: int
    unknown_cases: int
    pass_rate: float
    duration_ms: int | None
    suite_summary: list[dict]
    history_included: bool
    branch: str
    environment_name: str
    git_commit: str
    generated_at: datetime | None
    created_at: datetime


class ReportListResponse(BaseModel):
    """报告分页。"""

    items: list[ReportResponse]
    total: int
    page: int
    page_size: int


class ReportGrantResponse(BaseModel):
    """短期报告访问地址。token 只在这一次响应中出现。"""

    token: str
    expires_at: datetime
    index_url: str


class ReportCompareResponse(BaseModel):
    """两次报告的统计差。"""

    left: ReportResponse
    right: ReportResponse
    delta: dict[str, float]


class CallbackResponse(BaseModel):
    """回调处理结果。重复回调返回已有记录。"""

    execution_id: int
    report_id: int | None
    status: str
    duplicate: bool
