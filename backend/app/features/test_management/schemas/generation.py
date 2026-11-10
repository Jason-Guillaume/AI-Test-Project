"""用例生成草稿的请求与响应。接受前不会出现在正式用例列表。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class GenerationStartRequest(BaseModel):
    """从用例中心发起一次生成。模块由测试方向决定，不由页面随意改工具契约。"""

    agent_id: int = Field(gt=0)
    direction: Literal["API", "UI", "AI"]
    scope_node_id: int | None = Field(default=None, gt=0)
    requirements: str = Field(min_length=1, max_length=20000)
    include_security: bool = False
    cases_per_module: int = Field(default=5, ge=1, le=20)
    model_config_id: int | None = Field(default=None, gt=0)


class DraftUpdateRequest(BaseModel):
    """人工修改仍处于待审核状态的草稿。"""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    priority: Literal["P0", "P1", "P2", "P3"] | None = None
    requirement: str | None = Field(default=None, min_length=1, max_length=2000)
    preconditions: list[str] | None = Field(default=None, max_length=20)
    test_data: list[str] | None = Field(default=None, max_length=20)
    steps: list[str] | None = Field(default=None, min_length=1, max_length=30)
    expected_results: list[str] | None = Field(default=None, min_length=1, max_length=30)


class GenerationAgentOption(BaseModel):
    id: int
    name: str
    version: int
    modules: list[str]


class CaseDraftResponse(BaseModel):
    id: int
    batch_id: int
    module: str
    child_agent_id: int | None = None
    child_version: int
    child_name: str
    model_config_id: int | None = None
    model_name: str | None = None
    skill_versions: list[dict[str, Any]] = Field(default_factory=list)
    title: str
    priority: str
    payload: dict[str, Any]
    original_payload: dict[str, Any] = Field(default_factory=dict)
    quality: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    review_comment: str | None = None
    reviewed_at: datetime | None = None
    test_case_id: int | None = None
    import_error: str | None = None
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DraftRejectRequest(BaseModel):
    """拒绝草稿可附原因，供生成侧改进。"""

    model_config = ConfigDict(extra="forbid")
    comment: str | None = Field(default=None, max_length=500)


class BatchReviewRequest(BaseModel):
    """批量审核。accept 即入库；confirm 缺失时服务端拒绝执行。"""

    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "reject"]
    scope: Literal["all", "module", "drafts"]
    module: str | None = Field(default=None, max_length=20)
    draft_ids: list[int] | None = Field(default=None, max_length=200)
    comment: str | None = Field(default=None, max_length=500)
    confirm: bool = False


class BatchReviewItem(BaseModel):
    draft_id: int
    ok: bool
    test_case_id: int | None = None
    error: str | None = None


class BatchReviewResponse(BaseModel):
    batch_id: int
    action: str
    affected: int
    items: list[BatchReviewItem] = Field(default_factory=list)


class RegenerateRequest(BaseModel):
    """只重新生成失败模块；已成功与已审核草稿不受影响。"""

    model_config = ConfigDict(extra="forbid")
    cases_per_module: int = Field(default=5, ge=1, le=20)
    model_config_id: int | None = Field(default=None, gt=0)


class GenerationBatchListItem(BaseModel):
    id: int
    project_id: int
    direction: str
    status: str
    supervisor_name: str
    modules: list[str] = Field(default_factory=list)
    draft_total: int = 0
    pending_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    module_error_count: int = 0
    created_by: int | None = None
    created_at: datetime


class GenerationBatchListResponse(BaseModel):
    items: list[GenerationBatchListItem] = Field(default_factory=list)
    total: int
    page: int
    page_size: int
    completed_count: int = 0
    partial_failed_count: int = 0
    failed_count: int = 0


class CaseGenerationAuditResponse(BaseModel):
    id: int
    batch_id: int
    draft_id: int | None = None
    action: str
    actor_id: int | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GenerationBatchResponse(BaseModel):
    id: int
    project_id: int
    direction: str
    scope_node_id: int | None = None
    supervisor_agent_id: int | None = None
    supervisor_version: int
    supervisor_name: str
    model_config_id: int | None = None
    model_name: str | None = None
    status: str
    review_summary: str | None = None
    review_gaps: list[str] = Field(default_factory=list)
    module_errors: list[dict[str, Any]] = Field(default_factory=list)
    module_metrics: list[dict[str, Any]] = Field(default_factory=list)
    drafts: list[CaseDraftResponse] = Field(default_factory=list)
    created_at: datetime


class DraftDecisionResponse(BaseModel):
    draft_id: int
    status: str
    test_case_id: int | None = None
    source_type: str | None = None


class GenerationTrace(BaseModel):
    """正式用例上追溯到的生成批次。没有草稿来源时详情不返回该对象。"""

    batch_id: int
    supervisor_agent_id: int | None = None
    supervisor_version: int
    supervisor_name: str
    model_config_id: int | None = None
    model_name: str | None = None
    module: str | None = None
    child_agent_id: int | None = None
    child_version: int | None = None
    child_name: str | None = None
    skill_versions: list[dict[str, Any]] = Field(default_factory=list)
    review_status: str
    review_summary: str | None = None
