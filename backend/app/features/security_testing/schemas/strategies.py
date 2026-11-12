"""security_testing 资源契约；字段、默认值、校验和 wire 名称保持不变。"""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from app.features.security_testing.schemas.mutations import MutationRuleCreate
from app.features.security_testing.schemas.mutations import MutationRuleResponse
from app.features.security_testing.schemas.common import SEVERITY_LEVELS
from app.features.security_testing.schemas.common import STRATEGY_CATEGORIES
from app.features.security_testing.schemas.common import STRATEGY_KEY_PATTERN
from app.features.security_testing.schemas.common import _ORM


class SecurityStrategyCreate(BaseModel):
    """创建项目自定义策略（只创建 scope=PROJECT）。

    预留攻击类允许保存，但 ``enabled`` 在服务层被强制 false。
    """

    name: str = Field(..., min_length=1, max_length=200)
    strategy_key: str = Field(..., min_length=1, max_length=100, pattern=STRATEGY_KEY_PATTERN)
    category: str = Field(..., min_length=1, max_length=40)
    description: str | None = Field(None, max_length=1000)
    enabled: bool = True
    risk_level: str = Field("MEDIUM", max_length=20)
    rules: list[MutationRuleCreate] = Field(default_factory=list, max_length=200)

    @field_validator("category")
    @classmethod
    def _check_category(cls, value: str) -> str:
        """检查`category`。"""
        if value not in STRATEGY_CATEGORIES:
            raise ValueError(f"不支持的策略类别：{value}")
        return value

    @field_validator("risk_level")
    @classmethod
    def _check_risk(cls, value: str) -> str:
        """检查风险。"""
        if value not in SEVERITY_LEVELS:
            raise ValueError(f"不支持的风险级别：{value}")
        return value


class SecurityStrategyUpdate(BaseModel):
    """修改策略（系统模板 403；预留类别不能重新启用）。"""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    enabled: bool | None = None
    risk_level: str | None = Field(None, max_length=20)
    revision: int | None = None

    @field_validator("risk_level")
    @classmethod
    def _check_risk(cls, value: str | None) -> str | None:
        """检查风险。"""
        if value is not None and value not in SEVERITY_LEVELS:
            raise ValueError(f"不支持的风险级别：{value}")
        return value


class SecurityStrategyResponse(_ORM):
    """策略响应（可携带规则列表）。"""

    id: int
    project_id: int | None = None
    scope: str
    name: str
    strategy_key: str
    category: str
    description: str | None = None
    enabled: bool
    risk_level: str
    builtin: bool
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    revision: int = 1
    rules: list[MutationRuleResponse] = Field(default_factory=list)


class SecurityStrategyListResponse(BaseModel):
    items: list[SecurityStrategyResponse]
    total: int
    page: int
    page_size: int
