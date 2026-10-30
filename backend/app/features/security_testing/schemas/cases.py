"""security_testing 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from app.features.security_testing.schemas.executions import SecurityExecutionRead
from app.features.security_testing.schemas.common import _ORM


class SecurityCaseRead(_ORM):
    """安全用例扩展数据响应。"""

    id: int
    project_id: int
    test_case_id: int
    plan_id: int | None = None
    baseline_case_id: int | None = None
    strategy_id: int | None = None
    rule_id: int | None = None
    api_id: int | None = None
    business_action_id: int | None = None
    mutation_type: str
    mutation_config: dict[str, Any] = Field(default_factory=dict)
    security_expectation: str
    risk_level: str | None = None
    confirmation_required: bool
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SecurityCaseUpdate(BaseModel):
    """只允许改启用状态，同步 test_case.enabled。"""

    enabled: bool


class SecurityCaseDetail(SecurityCaseRead):
    """用例详情：带基线引用、最近一次执行与目标接口名。"""

    enabled: bool = True
    case_name: str | None = None
    baseline_case_name: str | None = None
    api_name: str | None = None
    rule_name: str | None = None
    latest_execution: SecurityExecutionRead | None = None


class SecurityCaseListResponse(BaseModel):
    items: list[SecurityCaseDetail]
    total: int
    page: int
    page_size: int
