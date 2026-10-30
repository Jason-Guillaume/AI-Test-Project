"""security_testing 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, field_validator
from app.features.security_testing.schemas.common import FINDING_STATUSES
from app.features.security_testing.schemas.common import _ORM


class SecurityFindingRead(_ORM):
    """疑似问题响应。Phase 1 不写 bug_id。"""

    id: int
    project_id: int
    test_run_id: int | None = None
    case_execution_id: int | None = None
    security_execution_id: int | None = None
    api_id: int | None = None
    business_action_id: int | None = None
    strategy_id: int | None = None
    security_case_id: int | None = None
    mutation_type: str
    severity: str
    status: str
    title: str
    description: str | None = None
    evidence: dict[str, Any] | None = None
    recommendation: str | None = None
    fingerprint: str
    bug_id: int | None = None
    created_by: int | None = None
    resolved_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SecurityFindingUpdate(BaseModel):
    """只允许改状态；非法迁移由服务层 400。"""

    status: str

    @field_validator("status")
    @classmethod
    def _check_status(cls, value: str) -> str:
        """检查状态。"""
        if value not in FINDING_STATUSES:
            raise ValueError(f"不支持的 Finding 状态：{value}")
        return value


class SecurityFindingListResponse(BaseModel):
    items: list[SecurityFindingRead]
    total: int
    page: int
    page_size: int
