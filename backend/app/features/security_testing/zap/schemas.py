"""Security Testing Phase 2 的请求 / 响应 Schema。

约定：
- 全部使用 Pydantic v2，写法与 security_testing.schemas 保持一致
  （_ORM 基类 + ConfigDict(from_attributes=True)）。
- 认证配置 **永不回显凭据明文**，只回显 has_credential / token_fingerprint /
  credential_updated_at（§十一）。写入用 credential 明文，读出永远是掩码字段。
- 列表响应统一 ``{items, total, page, page_size}``（红线 11）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.features.security_testing.zap.contracts import (
    AUTH_MODES,
    AUTH_STATUSES,
    JOB_STATUSES,
    SCAN_MODES,
    TARGET_TYPES,
)

TargetType = Literal["API", "WEB", "HYBRID"]
ScanMode = Literal[
    "API_PASSIVE", "WEB_PASSIVE", "HYBRID_PASSIVE",
    "API_ACTIVE", "WEB_ACTIVE", "FULL_AUTHORIZED",
]
AuthMode = Literal["NONE", "BEARER_TOKEN", "HEADER_BASED", "BROWSER_AUTH", "MANUAL"]
AuthorizationStatus = Literal["PENDING", "AUTHORIZED", "REVOKED"]
AuthStatus = Literal["LOGGED_IN", "LOGGED_OUT", "UNVERIFIABLE"]
JobStatus = Literal[
    "PENDING", "PREPARING", "AUTHENTICATING", "CRAWLING", "PASSIVE_SCANNING",
    "ACTIVE_SCANNING", "IMPORTING_RESULTS", "COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT",
]
CoverageStage = Literal[
    "DISCOVERED", "REQUESTED", "RESPONDED", "PASSIVE_ANALYZED", "ACTIVE_SCANNED", "NOT_COVERED",
]
Severity = Literal["INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


class _ORM(BaseModel):
    """从 ORM 实体构造响应的基类。"""

    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------- ZAP 服务健康

class ZapHealthRead(_ORM):
    """ZAP 服务健康检查结果。"""

    enabled: bool = False
    available: bool = False
    version: str | None = None
    reachable: bool = False
    api_key_configured: bool = False
    message: str = ""


class ZapCapabilityRead(_ORM):
    """单个 ZAP 能力探测结果。supported=False 时前端必须显示「受限」而不是假装可用。"""

    name: str
    supported: bool
    detail: str = ""


class ZapCapabilitiesRead(_ORM):
    """ZAP 版本与能力清单（§三 第 7 条）。"""

    version: str | None = None
    addon_names: list[str] = Field(default_factory=list)
    addon_versions: dict[str, str] = Field(default_factory=dict)
    capabilities: list[ZapCapabilityRead] = Field(default_factory=list)


# --------------------------------------------------------------------------- 扫描目标

class ScanTargetCreate(BaseModel):
    """创建扫描目标。base_url 必须过 scope_guard（协议 / 白名单 / 解析 IP）。"""

    name: str = Field(..., min_length=1, max_length=100)
    target_type: TargetType
    base_url: str = Field(..., min_length=1, max_length=500)
    entry_url: str | None = Field(None, max_length=500)
    environment_id: int | None = None
    enabled: bool = True
    authorization_status: AuthorizationStatus = "AUTHORIZED"
    authorization_note: str | None = Field(None, max_length=500)
    active_scan_allowed: bool = False
    allowed_hosts: list[str] = Field(default_factory=list, max_length=50)
    include_paths: list[str] = Field(default_factory=list, max_length=200)
    exclude_paths: list[str] = Field(default_factory=list, max_length=200)

    @field_validator("base_url")
    @classmethod
    def _strip_base_url(cls, value: str) -> str:
        """清理`base`URL。"""
        return value.strip()


class ScanTargetUpdate(BaseModel):
    """修改扫描目标。只允许改传入的字段。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    target_type: TargetType | None = None
    base_url: str | None = Field(None, min_length=1, max_length=500)
    entry_url: str | None = Field(None, max_length=500)
    environment_id: int | None = None
    enabled: bool | None = None
    authorization_status: AuthorizationStatus | None = None
    authorization_note: str | None = Field(None, max_length=500)
    active_scan_allowed: bool | None = None
    allowed_hosts: list[str] | None = Field(None, max_length=50)
    include_paths: list[str] | None = Field(None, max_length=200)
    exclude_paths: list[str] | None = Field(None, max_length=200)


class ScanTargetRead(_ORM):
    """扫描目标响应。"""

    id: int
    project_id: int
    environment_id: int | None = None
    name: str
    target_type: TargetType
    base_url: str
    entry_url: str | None = None
    enabled: bool
    authorization_status: AuthorizationStatus
    authorization_note: str | None = None
    active_scan_allowed: bool
    allowed_hosts: list[str] = Field(default_factory=list)
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    # 生产环境保护：目标落在生产环境时该字段为 True，主动扫描请求会直接拒绝。
    is_production: bool = False
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScanTargetListResponse(BaseModel):
    items: list[ScanTargetRead]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 认证配置

class ScanAuthProfileCreate(BaseModel):
    """创建认证配置。credential 是明文，只用于落库加密，响应中永不回显。"""

    name: str = Field(..., min_length=1, max_length=100)
    auth_mode: AuthMode = "NONE"
    session_method: str | None = Field(None, max_length=30)
    session_header: str | None = Field(None, max_length=100)
    session_name: str | None = Field(None, max_length=100)
    credential: str | None = None
    authentication_check_url: str | None = Field(None, max_length=500)
    logged_in_indicator: str | None = Field(None, max_length=200)
    logged_out_indicator: str | None = Field(None, max_length=200)
    expected_user_id: str | None = Field(None, max_length=100)
    auth_expiry_policy: str = Field("UNKNOWN", max_length=20)
    credential_expires_at: datetime | None = None
    description: str | None = Field(None, max_length=500)

    @field_validator("auth_mode")
    @classmethod
    def _check_auth_mode(cls, value: str) -> str:
        """检查认证`mode`。"""
        if value not in AUTH_MODES:
            raise ValueError(f"不支持的认证模式：{value}")
        return value


class ScanAuthProfileUpdate(BaseModel):
    """修改认证配置。credential 传空字符串表示删除凭据。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    auth_mode: AuthMode | None = None
    enabled: bool | None = None
    session_method: str | None = Field(None, max_length=30)
    session_header: str | None = Field(None, max_length=100)
    session_name: str | None = Field(None, max_length=100)
    credential: str | None = None
    remove_credential: bool = False
    authentication_check_url: str | None = Field(None, max_length=500)
    logged_in_indicator: str | None = Field(None, max_length=200)
    logged_out_indicator: str | None = Field(None, max_length=200)
    expected_user_id: str | None = Field(None, max_length=100)
    auth_expiry_policy: str | None = Field(None, max_length=20)
    credential_expires_at: datetime | None = None
    description: str | None = Field(None, max_length=500)


class ScanAuthProfileRead(_ORM):
    """认证配置响应：**只回显掩码字段，绝不含凭据明文**。"""

    id: int
    project_id: int
    name: str
    auth_mode: AuthMode
    enabled: bool
    session_method: str | None = None
    session_header: str | None = None
    session_name: str | None = None
    has_credential: bool = False
    token_fingerprint: str | None = None
    credential_updated_at: datetime | None = None
    credential_expires_at: datetime | None = None
    authentication_check_url: str | None = None
    logged_in_indicator: str | None = None
    logged_out_indicator: str | None = None
    expected_user_id: str | None = None
    auth_expiry_policy: str = "UNKNOWN"
    description: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScanAuthProfileListResponse(BaseModel):
    items: list[ScanAuthProfileRead]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 扫描策略

class ScanProfileCreate(BaseModel):
    """创建扫描策略。scan_mode 决定该策略是否属于受控主动扫描。"""

    name: str = Field(..., min_length=1, max_length=100)
    scan_mode: ScanMode
    spider_enabled: bool = True
    client_spider_enabled: bool = False
    passive_enabled: bool = True
    active_enabled: bool = False
    authentication_profile_id: int | None = None
    max_duration: int = Field(30, ge=1, le=240)
    max_depth: int = Field(5, ge=1, le=10)
    max_concurrency: int = Field(4, ge=1, le=50)
    request_delay: int = Field(300, ge=0, le=5000)
    max_alerts_per_rule: int | None = Field(None, ge=1, le=200)
    max_request_budget: int | None = Field(None, ge=1, le=50000)
    include_paths: list[str] = Field(default_factory=list, max_length=200)
    exclude_paths: list[str] = Field(default_factory=list, max_length=200)
    selected_rule_ids: list[str] = Field(default_factory=list, max_length=500)
    enabled: bool = True
    description: str | None = Field(None, max_length=500)

    @field_validator("scan_mode")
    @classmethod
    def _check_scan_mode(cls, value: str) -> str:
        """检查扫描`mode`。"""
        if value not in SCAN_MODES:
            raise ValueError(f"不支持的扫描模式：{value}")
        return value


class ScanProfileUpdate(BaseModel):
    """修改扫描策略。"""

    name: str | None = Field(None, min_length=1, max_length=100)
    scan_mode: ScanMode | None = None
    spider_enabled: bool | None = None
    client_spider_enabled: bool | None = None
    passive_enabled: bool | None = None
    active_enabled: bool | None = None
    authentication_profile_id: int | None = None
    max_duration: int | None = Field(None, ge=1, le=240)
    max_depth: int | None = Field(None, ge=1, le=10)
    max_concurrency: int | None = Field(None, ge=1, le=50)
    request_delay: int | None = Field(None, ge=0, le=5000)
    max_alerts_per_rule: int | None = Field(None, ge=1, le=200)
    max_request_budget: int | None = Field(None, ge=1, le=50000)
    include_paths: list[str] | None = Field(None, max_length=200)
    exclude_paths: list[str] | None = Field(None, max_length=200)
    selected_rule_ids: list[str] | None = Field(None, max_length=500)
    enabled: bool | None = None
    description: str | None = Field(None, max_length=500)


class ScanProfileRead(_ORM):
    """扫描策略响应。"""

    id: int
    project_id: int | None = None
    code: str | None = None
    is_builtin: bool = False
    name: str
    scan_mode: ScanMode
    is_active_scan: bool = False
    spider_enabled: bool
    client_spider_enabled: bool
    passive_enabled: bool
    active_enabled: bool
    authentication_profile_id: int | None = None
    max_duration: int
    max_depth: int
    max_concurrency: int
    request_delay: int
    max_alerts_per_rule: int | None = None
    max_request_budget: int | None = None
    include_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    selected_rule_ids: list[str] = Field(default_factory=list)
    enabled: bool
    description: str | None = None
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScanProfileListResponse(BaseModel):
    items: list[ScanProfileRead]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 扫描任务

class ScanJobCreate(BaseModel):
    """发起一次扫描。

    主动扫描需要显式 ``confirmed`` 且由后端校验到真实的人类批准行为（§二十三）：
    Agent 路径的批准必须来自后端记录的确认动作，而不是 LLM 输出 confirmed=true。
    """

    target_id: int
    scan_profile_id: int
    test_run_id: int | None = None
    confirmed: bool = False
    approval_note: str | None = Field(None, max_length=500)
    idempotency_key: str | None = Field(None, min_length=1, max_length=160)

    @field_validator("target_id", "scan_profile_id")
    @classmethod
    def _positive(cls, value: int) -> int:
        """校验正数对应数据。"""
        if value <= 0:
            raise ValueError("必须为正整数")
        return value


class ScanJobRead(_ORM):
    """扫描任务响应。"""

    id: int
    project_id: int
    target_id: int
    target_name: str | None = None
    environment_id: int | None = None
    environment_name: str | None = None
    scan_profile_id: int
    scan_profile_name: str | None = None
    scan_mode: ScanMode
    status: JobStatus
    progress: int = 0
    stage: str | None = None
    authentication_mode: AuthMode | None = None
    authentication_status: AuthStatus | None = None
    browser_session_established: bool = False
    initiated_by: int | None = None
    approved_by: int | None = None
    zap_scan_reference: str | None = None
    test_run_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    total_alerts: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    urls_discovered: int = 0
    requests_made: int = 0
    new_findings_count: int = 0
    duplicate_findings_count: int = 0
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    worker_owner: str | None = None
    heartbeat_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScanJobListResponse(BaseModel):
    items: list[ScanJobRead]
    total: int
    page: int
    page_size: int


class ScanJobProgressRead(_ORM):
    """进度查询响应。progress 为 -1 表示无法给出精确百分比，只展示阶段与计数。"""

    id: int
    status: JobStatus
    stage: str | None = None
    progress: int = 0
    urls_discovered: int = 0
    requests_made: int = 0
    total_alerts: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    cancel_requested: bool = False
    duration_ms: int | None = None


class ScanEventRead(_ORM):
    """过程事件响应。"""

    id: int
    job_id: int
    seq: int
    event_type: str
    stage: str | None = None
    message: str | None = None
    payload_json: dict[str, Any] | None = None
    created_at: datetime | None = None


class ScanEventListResponse(BaseModel):
    items: list[ScanEventRead]
    total: int
    page: int
    page_size: int


class ScanAlertRead(_ORM):
    """一条归一化后的 ZAP 告警（已脱敏）。

    confidence 与 severity 是**两个独立维度**，不能混用（§十八）。
    """

    rule_id: str
    name: str
    risk: str
    confidence: int
    severity: Severity
    url: str
    method: str = ""
    parameter: str = ""
    description: str = ""
    remediation: str = ""
    evidence: str = ""
    cwe_id: int | None = None
    wasc_id: int | None = None
    reference: str = ""


class ScanAlertCountsRead(BaseModel):
    total: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class ScanAlertListResponse(BaseModel):
    items: list[ScanAlertRead]
    total: int
    page: int
    page_size: int
    counts: ScanAlertCountsRead = Field(default_factory=ScanAlertCountsRead)


class CoverageRowRead(_ORM):
    """一个扫描对象的覆盖阶段（§三十一）。"""

    identifier: str
    stage: CoverageStage
    method: str = ""
    status_code: int | None = None
    passive_analyzed: bool = False
    active_scanned: bool = False


class CoverageRead(BaseModel):
    items: list[CoverageRowRead]
    total: int
    page: int
    page_size: int
    summary: dict[str, int] = Field(default_factory=dict)


class ScanFindingLinkRead(_ORM):
    """扫描任务与 Finding 的关联响应。"""

    id: int
    job_id: int
    finding_id: int
    source: str = "ZAP"
    source_rule_id: str | None = None
    source_alert_name: str | None = None
    risk: str | None = None
    confidence: int | None = None
    url: str | None = None
    method: str | None = None
    parameter: str | None = None
    fingerprint: str | None = None
    evidence_json: dict[str, Any] | None = None
    first_seen_in_job: bool = False
    repeat_count: int = 1
    created_at: datetime | None = None


class ScanFindingListResponse(BaseModel):
    items: list[ScanFindingLinkRead]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- 扫描计划（人工确认前置）

class ScanPlanRead(BaseModel):
    """扫描前的计划预览（§二十三「生成扫描计划 → 人工确认」）。

    计划里必须包含将被提交给 ZAP 的**实际范围**：目标、模式、认证状态、
    请求预算、超时、并发、风险与是否为主动扫描。
    """

    target: dict[str, Any]
    profile: dict[str, Any]
    environment: dict[str, Any]
    is_active_scan: bool = False
    production_blocked: bool = False
    authentication_mode: AuthMode | None = None
    browser_session_established: bool = False
    zap_available: bool = False
    limitations: list[str] = Field(default_factory=list)
    estimated_requests: int | None = None
    max_duration_minutes: int = 30
    max_depth: int = 5
    max_concurrency: int = 4
    request_delay_ms: int = 300
    exclude_paths: list[str] = Field(default_factory=list)
    warning: str | None = None


# --------------------------------------------------------------------------- 扫描报告

class ScanReportRead(BaseModel):
    """独立安全扫描报告（§二十五）。

    所有数字都来自真实的 SecurityScanJob 记录，不接受前端传入。
    """

    job: ScanJobRead
    target: ScanTargetRead | None = None
    profile: ScanProfileRead | None = None
    alert_counts: ScanAlertCountsRead = Field(default_factory=ScanAlertCountsRead)
    high_risk_alerts: list[ScanAlertRead] = Field(default_factory=list)
    coverage_summary: dict[str, int] = Field(default_factory=dict)
    findings: list[ScanFindingLinkRead] = Field(default_factory=list)
    generated_at: datetime | None = None
