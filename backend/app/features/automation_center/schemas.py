"""自动化测试中心接口契约。凭证字段只出现在写入请求中。"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

from app.features.automation_center.validation import validate_pipeline_parameters

Deployment = Literal["central", "region"]
ProviderType = Literal["YUNXIAO", "JENKINS"]
NotifyCondition = Literal["ALWAYS", "ONLY_FAILED", "NEVER"]
ExecutionStatus = Literal["PENDING", "RUNNING", "SUCCESS", "FAILED", "CANCELLED", "TIMEOUT"]
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def _validate_jenkins_url(value: str | None) -> str:
    if not value:
        raise ValueError("Jenkins 必须填写 Base URL")
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        raise ValueError("Jenkins 地址必须是 HTTPS URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Jenkins 地址不能包含账号、密码、查询参数或片段")
    try:
        port = parsed.port or 443
    except ValueError as exc:
        raise ValueError("Jenkins 地址端口无效") from exc
    if port not in {443, 8443, 9443}:
        raise ValueError("Jenkins 仅允许使用 HTTPS 端口 443、8443 或 9443")
    return value.strip().rstrip("/")


def _validate_resource_path(value: str | None) -> str:
    if value is None:
        raise ValueError("流水线或 Jenkins Job 路径不能为空")
    path = value.strip().strip("/")
    segments = path.split("/")
    if (
        not path or len(path) > 255
        or any(not part or part in {".", ".."} or part.strip() != part
               or re.search(r"[\\?#%\x00-\x1f]", part) for part in segments)
    ):
        raise ValueError("流水线或 Jenkins Job 路径不合法")
    return path


class IntegrationCreate(BaseModel):
    """创建 CI 接入配置。凭证只写入一次，响应不会回传明文。"""

    provider_type: ProviderType = "YUNXIAO"
    name: str = Field(min_length=1, max_length=100)
    api_base_url: str | None = "https://openapi-rdc.aliyuncs.com"
    organization_id: str = ""
    deployment: Deployment = "central"
    access_token: str | None = Field(None, min_length=8, max_length=500)
    jenkins_base_url: str | None = Field(None, max_length=500)
    jenkins_username: str | None = Field(None, max_length=200)
    jenkins_api_token: str | None = Field(None, min_length=8, max_length=500)
    allow_private_network: bool = False
    enabled: bool = True
    callback_secret: str = Field(min_length=8, max_length=200)
    default_timeout_seconds: int = Field(3600, ge=60, le=10800)

    @field_validator("api_base_url")
    @classmethod
    def https_base(cls, value: str | None) -> str | None:
        """云效接口只接受 HTTPS，避免令牌在明文链路传输。"""
        if value is None:
            return None
        normalized = value.strip().rstrip("/")
        if not normalized.startswith("https://"):
            raise ValueError("云效 API 地址必须使用 HTTPS")
        return normalized

    @model_validator(mode="after")
    def provider_fields_valid(self):
        """按 Provider 校验字段，避免把 Jenkins 配置混入云效凭据列。"""
        if self.provider_type == "JENKINS":
            _validate_jenkins_url(self.jenkins_base_url)
            if not self.jenkins_username or not self.jenkins_api_token:
                raise ValueError("Jenkins 必须填写 Username 和 API Token")
            return self
        if not self.api_base_url or not self.access_token:
            raise ValueError("云效必须填写 API 地址和访问令牌")
        if self.deployment == "central" and not _ID.fullmatch(self.organization_id):
            raise ValueError("中心版必须填写云效企业 ID")
        if self.organization_id and not _ID.fullmatch(self.organization_id):
            raise ValueError("企业 ID 不合法")
        return self


class IntegrationUpdate(BaseModel):
    """更新接入配置。令牌和密钥留空表示保持原值。"""

    provider_type: ProviderType | None = None
    name: str | None = Field(None, min_length=1, max_length=100)
    api_base_url: str | None = None
    organization_id: str | None = None
    deployment: Deployment | None = None
    access_token: str | None = Field(None, max_length=500)
    jenkins_base_url: str | None = Field(None, max_length=500)
    jenkins_username: str | None = Field(None, max_length=200)
    jenkins_api_token: str | None = Field(None, max_length=500)
    allow_private_network: bool | None = None
    enabled: bool | None = None
    callback_secret: str | None = Field(None, max_length=200)
    default_timeout_seconds: int | None = Field(None, ge=60, le=10800)

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

    @field_validator("jenkins_base_url")
    @classmethod
    def jenkins_url_valid(cls, value: str | None) -> str | None:
        if value is not None:
            _validate_jenkins_url(value)
        return value.rstrip("/") if value else value


class IntegrationResponse(BaseModel):
    """接入配置响应。不包含令牌和回调密钥。"""

    id: int
    project_id: int
    name: str
    provider_type: ProviderType = "YUNXIAO"
    enabled: bool = True
    allow_private_network: bool = False
    jenkins_base_url: str | None = None
    jenkins_username: str | None = None
    api_token_configured: bool = False
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


class JenkinsJobItem(BaseModel):
    """One Jenkins folder or buildable Job."""

    name: str
    job_path: str
    url: str
    is_folder: bool
    buildable: bool
    color: str = ""


class JenkinsJobListResponse(BaseModel):
    """One-level Jenkins folder contents."""

    folder_path: str
    items: list[JenkinsJobItem]


class JenkinsJobParameter(BaseModel):
    name: str
    type: str = ""
    default_value: str = ""


class JenkinsJobInspectResponse(BaseModel):
    """Jenkins Job execution capabilities and declared parameters."""

    name: str
    job_path: str
    url: str
    is_folder: bool
    buildable: bool
    concurrent_build: bool
    parameters: list[JenkinsJobParameter]


class AutomationProjectCreate(BaseModel):
    """创建自动化项目并绑定一条流水线。"""

    integration_config_id: int
    provider_type: ProviderType | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    repository_url: str = Field("", max_length=500)
    repository_id: str = Field("", max_length=64)
    pipeline_id: str = Field(min_length=1, max_length=255)
    pipeline_name: str = Field("", max_length=120)
    default_branch: str = Field("master", max_length=200)
    default_environment: str = Field("", max_length=100)
    pytest_args: str = Field("", max_length=500)
    test_tags: str = Field("", max_length=300)
    test_scope: str = Field("", max_length=500)
    pipeline_params: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: int = Field(3600, ge=60, le=10800)
    notification_channel_id: int | None = None
    notify_condition: NotifyCondition = "ALWAYS"

    @field_validator("pipeline_id")
    @classmethod
    def pipeline_id_safe(cls, value: str) -> str:
        """流水线 ID 会进入云效 URL。"""
        return _validate_resource_path(value)

    @model_validator(mode="after")
    def jenkins_parameters_safe(self):
        if self.provider_type == "JENKINS":
            validate_pipeline_parameters(self.pipeline_params, reject_reserved=True)
        return self


class AutomationProjectUpdate(BaseModel):
    """更新自动化项目。未传字段保持不变。"""

    name: str | None = Field(None, min_length=1, max_length=120)
    provider_type: ProviderType | None = None
    description: str | None = Field(None, max_length=500)
    repository_url: str | None = Field(None, max_length=500)
    repository_id: str | None = Field(None, max_length=64)
    pipeline_id: str | None = Field(None, max_length=255)
    pipeline_name: str | None = Field(None, max_length=120)
    default_branch: str | None = Field(None, max_length=200)
    default_environment: str | None = Field(None, max_length=100)
    pytest_args: str | None = Field(None, max_length=500)
    test_tags: str | None = Field(None, max_length=300)
    test_scope: str | None = Field(None, max_length=500)
    pipeline_params: dict[str, str] | None = None
    timeout_seconds: int | None = Field(None, ge=60, le=10800)
    notification_channel_id: int | None = None
    clear_notification_channel: bool = False
    notify_condition: NotifyCondition | None = None
    enabled: bool | None = None
    integration_config_id: int | None = None

    @model_validator(mode="after")
    def jenkins_parameters_safe(self):
        if self.provider_type == "JENKINS" and self.pipeline_params is not None:
            validate_pipeline_parameters(self.pipeline_params, reject_reserved=True)
        return self


class AutomationProjectResponse(BaseModel):
    """自动化项目及最近一次执行摘要。"""

    id: int
    project_id: int
    integration_config_id: int
    provider_type: ProviderType = "YUNXIAO"
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
    pipeline_id: str | None = Field(None, max_length=255)

    @field_validator("pipeline_id")
    @classmethod
    def resource_path_safe(cls, value: str | None) -> str | None:
        return _validate_resource_path(value) if value else value


class ExecutionResponse(BaseModel):
    """执行记录。云效运行 ID 与平台执行 ID 同时保留。"""

    id: int
    project_id: int
    automation_project_id: int
    automation_project_name: str
    pipeline_id: str
    pipeline_run_id: str | None
    provider_type: ProviderType = "YUNXIAO"
    queue_id: str | None = None
    build_number: int | None = None
    external_run_url: str = ""
    trigger_source: str
    status: ExecutionStatus
    branch: str
    environment_name: str
    pytest_args: str
    test_tags: str
    test_scope: str
    git_commit: str
    external_status: str
    stop_requested: bool = False
    stop_reason: Literal["CANCELLED", "TIMEOUT"] | None = None
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


class ConsoleLogResponse(BaseModel):
    execution_id: int
    content: str
    truncated: bool


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
    provider_type: ProviderType = "YUNXIAO"
    build_number: int | None = None
    external_run_url: str = ""
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
