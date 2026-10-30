"""test_data 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.features.test_data.schemas.common import FIXTURE_KEY_PATTERN
from app.features.test_data.schemas.common import FixtureCleanupPolicy
from app.features.test_data.schemas.common import FixtureOnFailure
from app.features.test_data.schemas.common import FixturePhase
from app.features.test_data.schemas.common import FixtureScope
from app.features.test_data.schemas.common import FixtureStatus
from app.features.test_data.schemas.common import FixtureStepType
from app.features.test_data.schemas.common import ValueType


class FixtureStepInput(BaseModel):
    """步骤写入入参（整体替换时批量提交）。"""

    phase: FixturePhase = Field(default="GENERATE")
    step_type: FixtureStepType
    name: str = Field(..., min_length=1, max_length=200)
    sort: int = Field(default=0, ge=0)
    provider_id: int | None = None
    config_json: dict[str, Any] | None = None
    on_failure: FixtureOnFailure = Field(default="ABORT")


class FixtureStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fixture_id: int
    phase: str
    step_type: str
    name: str
    sort: int
    provider_id: int | None = None
    config_json: dict[str, Any] | None = None
    on_failure: str


class FixtureOutputInput(BaseModel):
    """输出契约写入入参。"""

    name: str = Field(..., min_length=1, max_length=100)
    value_type: ValueType = Field(default="STRING")
    source_path: str = Field(..., min_length=1, max_length=200, description="从私有上下文取值：task_id 或 $.data.id")
    description: str | None = Field(None, max_length=500)
    sort: int = Field(default=0, ge=0)


class FixtureOutputResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fixture_id: int
    name: str
    value_type: str
    source_path: str
    description: str | None = None
    sort: int


class FixtureDependencyResponse(BaseModel):
    """依赖边响应，附带被依赖方的名称与 key，便于前端直接画树。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fixture_id: int
    depends_on_fixture_id: int
    sort: int
    depends_on_key: str | None = None
    depends_on_name: str | None = None
    depends_on_entity_type: str | None = None


class FixtureCreate(BaseModel):
    """整体创建：基本信息 + 步骤 + 输出契约 + 依赖。"""

    name: str = Field(..., min_length=1, max_length=200)
    fixture_key: str = Field(..., min_length=1, max_length=100)
    entity_type: str = Field(..., min_length=1, max_length=50)
    description: str | None = Field(None, max_length=1000)
    scope: FixtureScope = "CASE"
    status: FixtureStatus = "DRAFT"
    cache_enabled: bool = True
    cleanup_policy: FixtureCleanupPolicy = "AFTER_CASE"
    steps: list[FixtureStepInput] = Field(default_factory=list)
    outputs: list[FixtureOutputInput] = Field(default_factory=list)
    dependencies: list[int] = Field(default_factory=list, description="依赖的 Fixture ID 列表")

    @field_validator("fixture_key")
    @classmethod
    def _check_key(cls, v: str) -> str:
        """检查键。"""
        import re

        if not re.fullmatch(FIXTURE_KEY_PATTERN, v):
            raise ValueError("fixture_key 必须匹配 " + FIXTURE_KEY_PATTERN)
        return v

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str) -> str:
        """检查名称。"""
        return v.strip()


class FixtureUpdate(BaseModel):
    """PATCH：只改基本信息，不动步骤/输出/依赖。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    scope: FixtureScope | None = None
    status: FixtureStatus | None = None
    cache_enabled: bool | None = None
    cleanup_policy: FixtureCleanupPolicy | None = None

    @field_validator("name")
    @classmethod
    def _check_name(cls, v: str | None) -> str | None:
        """检查名称。"""
        return v.strip() if v is not None else v


class FixtureStepsReplace(BaseModel):
    """整体替换步骤：同时提交 GENERATE 与 CLEANUP，后端重建依赖边并跑环检测。"""

    steps: list[FixtureStepInput] = Field(default_factory=list)


class FixtureOutputsReplace(BaseModel):
    """整体替换输出契约。"""

    outputs: list[FixtureOutputInput] = Field(default_factory=list)


class FixtureBriefResponse(BaseModel):
    """列表响应：只带必要字段 + 输出名，避免把步骤配置整包推给前端。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    name: str
    fixture_key: str
    entity_type: str
    description: str | None = None
    scope: str
    status: str
    cache_enabled: bool
    cleanup_policy: str
    output_names: list[str] = Field(default_factory=list)
    step_count: int = 0
    generate_step_count: int = 0
    cleanup_step_count: int = 0
    dependency_count: int = 0
    referenced_case_count: int = 0
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime


class FixtureDetailResponse(FixtureBriefResponse):
    """详情：基本信息 + 步骤 + 输出契约 + 依赖 + 引用它的用例。"""

    steps: list[FixtureStepResponse] = Field(default_factory=list)
    outputs: list[FixtureOutputResponse] = Field(default_factory=list)
    dependencies: list[FixtureDependencyResponse] = Field(default_factory=list)
    referenced_cases: list[dict[str, Any]] = Field(default_factory=list)


class FixtureTreeNodeResponse(BaseModel):
    """依赖树节点（含子依赖），用于左树与依赖 Tab。"""

    id: int
    fixture_key: str
    name: str
    entity_type: str
    scope: str
    status: str
    depth: int = 0
    children: list["FixtureTreeNodeResponse"] = Field(default_factory=list)


class FixtureGenerateRequest(BaseModel):
    """手工试跑：只指定环境，不挂 TestRun。"""

    environment_id: int = Field(..., description="本次试跑使用的环境")
    scope: FixtureScope = "CASE"
    variables: dict[str, Any] = Field(default_factory=dict, description="试跑注入的初始变量")


class FixtureListResponse(BaseModel):
    items: list[FixtureBriefResponse]
    page: int
    page_size: int
    total: int
