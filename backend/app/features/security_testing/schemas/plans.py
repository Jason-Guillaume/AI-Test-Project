"""security_testing 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field, field_validator
from app.features.security_testing.schemas.common import MAX_STRATEGY_IDS
from app.features.security_testing.schemas.common import _ORM


class PlanPreviewRequest(BaseModel):
    """生成安全计划预览：三者必须且只能给一个目标。"""

    baseline_case_id: int | None = None
    api_id: int | None = None
    business_action_id: int | None = None
    strategy_ids: list[int] = Field(..., min_length=1, max_length=MAX_STRATEGY_IDS)
    environment_id: int | None = None
    name: str | None = Field(None, max_length=200)

    @field_validator("strategy_ids")
    @classmethod
    def _dedupe(cls, value: list[int]) -> list[int]:
        """去重对应数据。"""
        return list(dict.fromkeys(value))


class PlanPreviewItem(BaseModel):
    """预览里的一条计划项，形状即 §16.3。"""

    index: int
    name: str
    mutation_type: str
    target_type: str = "API"
    api_id: int | None = None
    business_action_id: int | None = None
    method: str | None = None
    location: str | None = None
    field: str | None = None
    expectation: str = "EXPECTED_DENY"
    expected_status_codes: list[int] | None = None
    severity: str = "MEDIUM"
    risk_level: str | None = None
    confirmation_required: bool = False
    blocked_reason: str | None = None
    mutation_config: dict[str, Any] = Field(default_factory=dict)
    source_rule_id: int | None = None
    source_strategy_id: int | None = None


class PlanPreviewResponse(BaseModel):
    plan_id: int
    status: str = "DRAFT"
    estimated_count: int
    truncated: bool = False
    items: list[PlanPreviewItem] = Field(default_factory=list)
    # 按 API / 业务动作目标生成时解析出的基线用例：计划 review 需要让用户看清
    # 变异会在哪条基线上做，而不只是看到策略与算子。
    baseline_case_id: int | None = None
    baseline_case_name: str | None = None


class PlanConfirmRequest(BaseModel):
    """确认哪些预览项要落成用例；空列表表示一条都不要。"""

    accepted_item_indexes: list[int] = Field(default_factory=list, max_length=200)
    plan_name: str | None = Field(None, max_length=200)


class PlanConfirmResponse(BaseModel):
    plan_id: int
    status: str
    created_case_ids: list[int] = Field(default_factory=list)
    created_count: int
    skipped_count: int


class SecurityPlanRead(_ORM):
    """计划响应，含未落 TestCase 的预览快照。"""

    id: int
    project_id: int
    name: str
    target_type: str
    api_id: int | None = None
    baseline_case_id: int | None = None
    business_action_id: int | None = None
    strategy_ids: list[int] | None = None
    status: str
    preview_json: Any = None
    estimated_count: int
    environment_id: int | None = None
    created_by: int | None = None
    confirmed_by: int | None = None
    confirmed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revision: int = 1
