"""test_management 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class TestRunCreateRequest(BaseModel):
    """触发测试计划执行。"""

    environment_id: int | None = Field(None, gt=0, description="执行环境ID（覆盖计划环境；为空用计划环境）")


class TestRunResponse(BaseModel):
    id: int
    project_id: int
    plan_id: int | None = None
    environment_id: int | None = None
    status: str
    total: int
    passed: int
    failed: int
    skipped: int
    error: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TestRunListResponse(BaseModel):
    items: list[TestRunResponse]
    total: int
    page: int = 1
    page_size: int = 20


class CaseExecutionResponse(BaseModel):
    id: int
    test_run_id: int
    test_case_id: int | None = None
    status: str
    executor_type: str | None = None
    request_snapshot: dict[str, Any] | None = None
    response_snapshot: dict[str, Any] | None = None
    assertion_results: list[dict[str, Any]] | None = None
    context_json: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    cleanup_status: str | None = Field(
        None, description="清理状态：PENDING/SUCCESS/FAILED/SKIPPED（不覆盖 status 与 error_code）",
    )
    cleanup_error_code: str | None = Field(None, description="清理失败错误码（仅 cleanup_* 字段）")
    cleanup_error_message: str | None = Field(None, description="清理失败原因（截断 2000 字）")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CaseExecutionListResponse(BaseModel):
    items: list[CaseExecutionResponse]
    total: int
    page: int = 1
    page_size: int = 100
