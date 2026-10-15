"""测试报告模块：契约定义（Pydantic v2）。

只放请求 / 响应模型与字面量类型，不含业务逻辑；service 与 router 共用本文件
作为两层接口契约（与 test_management / business / defects 的 schemas 风格一致）。

覆盖：
- 报告状态 / 风险等级 / 失败分类字面量；
- 报告生成请求、列表查询、响应、详情聚合；
- AI 总结结构化输出（§九，Pydantic 强校验）。

报告**不**复制 CaseExecution / Request / Response / Assertion 明细，详情页实时
读取 TestRun + CaseExecution（见 report_service.get_report）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- 枚举字面量

# 数据库层均为 String（不设 sa.Enum / CHECK），合法取值由服务层校验。
REPORT_STATUSES = ("GENERATING", "COMPLETED", "FAILED")
ReportStatus = Literal["GENERATING", "COMPLETED", "FAILED"]

RISK_LEVELS = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
RiskLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# 失败分类（§七）。POTENTIAL_BUG 仅表示「疑似产品问题，需人工确认」，不得写成「已发现 Bug」。
FAILURE_TYPES = (
    "ASSERTION_FAILURE", "EXECUTION_ERROR", "TEST_DATA_ISSUE",
    "ENVIRONMENT_ERROR", "POTENTIAL_BUG", "UNKNOWN",
)
FailureType = Literal[
    "ASSERTION_FAILURE", "EXECUTION_ERROR", "TEST_DATA_ISSUE",
    "ENVIRONMENT_ERROR", "POTENTIAL_BUG", "UNKNOWN",
]

NOTIFY_CONDITIONS = ("ALWAYS", "ONLY_FAILED", "ONLY_HIGH_RISK")
NotifyCondition = Literal["ALWAYS", "ONLY_FAILED", "ONLY_HIGH_RISK"]

NOTIFY_STATUSES = ("PENDING", "SUCCESS", "FAILED")
NotifyStatus = Literal["PENDING", "SUCCESS", "FAILED"]


# --------------------------------------------------------------------------- AI 总结结构化输出（§九）


class AISummary(BaseModel):
    """LLM 报告总结的结构化输出，强制 Pydantic 校验（§九）。

    AI 只负责总结 / 风险解释 / 失败聚类 / 建议；不参与统计计算（§五）。
    """

    overview: str = Field("", description="总体结论")
    key_findings: list[str] = Field(default_factory=list, description="主要发现")
    potential_issues: list[str] = Field(default_factory=list, description="疑似产品问题（需人工确认，不得写成「已发现 Bug」）")
    test_data_issues: list[str] = Field(default_factory=list, description="测试数据问题")
    environment_issues: list[str] = Field(default_factory=list, description="环境问题")
    recommendations: list[str] = Field(default_factory=list, description="改进建议")
    risk_summary: str = Field("", description="风险解释（风险等级仍由代码规则决定）")


# --------------------------------------------------------------------------- 请求模型


class ReportGenerateRequest(BaseModel):
    """生成报告请求体（POST /test-runs/{run_id}/report）。"""

    generate_ai_summary: bool = True
    regenerate: bool = False


class ReportListQuery(BaseModel):
    """报告列表查询参数。"""

    page: int = 1
    page_size: int = 20
    environment_id: int | None = None
    risk_level: RiskLevel | None = None
    status: ReportStatus | None = None
    test_run_id: int | None = None


# --------------------------------------------------------------------------- 响应模型


class ReportGenerateResponse(BaseModel):
    """报告生成结果（仅返回 ID 与状态，详情另调 GET）。"""

    report_id: int
    status: ReportStatus


class CaseExecutionSummary(BaseModel):
    """报告详情内的单用例执行摘要（快照已脱敏，仍经 sanitize_context 兜底）。"""

    id: int
    test_case_id: int | None = None
    case_name: str = "(已删除用例)"
    priority: str = "P1"
    case_type: str | None = None
    status: str
    failure_type: FailureType | None = None
    executor_type: str | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    request_snapshot: dict[str, Any] | None = None
    response_snapshot: dict[str, Any] | None = None
    assertion_results: list[dict[str, Any]] | None = None
    context_json: dict[str, Any] | None = None


class TestRunBrief(BaseModel):
    """报告详情里附带的一次性 TestRun 摘要。"""

    id: int
    status: str
    environment_id: int | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class TestReportResponse(BaseModel):
    """报告完整字段（用于详情 / 单条返回）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    test_run_id: int | None = None
    report_no: str
    title: str
    environment_id: int | None = None
    status: ReportStatus
    total_cases: int
    passed_cases: int
    failed_cases: int
    error_cases: int
    skipped_cases: int
    pass_rate: float
    duration_ms: int | None = None
    summary: dict[str, Any] | None = None
    ai_summary: dict[str, Any] | None = None
    ai_summary_version: str | None = None
    risk_level: RiskLevel
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class TestReportListItem(BaseModel):
    """报告列表项（不含 AI 总结等大字段，列表更轻）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    report_no: str
    title: str
    test_run_id: int | None = None
    environment_id: int | None = None
    status: ReportStatus
    total_cases: int
    passed_cases: int
    failed_cases: int
    error_cases: int
    skipped_cases: int
    pass_rate: float
    duration_ms: int | None = None
    risk_level: RiskLevel
    created_at: datetime


class TestReportListResponse(BaseModel):
    """报告列表分页响应（与分页约定 {items,total,page,page_size} 一致）。"""

    items: list[TestReportListItem]
    total: int
    page: int
    page_size: int


class TestReportDetailResponse(BaseModel):
    """报告详情：报告本体 + TestRun 摘要 + 逐用例执行明细 + 失败分类。"""

    report: TestReportResponse
    test_run: TestRunBrief | None = None
    case_executions: list[CaseExecutionSummary] = Field(default_factory=list)
    failure_clusters: list[dict[str, Any]] = Field(default_factory=list)
