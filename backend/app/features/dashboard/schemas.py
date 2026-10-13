"""看板模块：契约定义。

所有统计都以「当前用户可见范围」为口径，响应体里带 scope 字段说明统计口径，
避免把全局数字误当成个人指标展示。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DashboardScopeResponse(BaseModel):
    """统计口径说明。"""

    subject: str = Field(..., description="统计主体，如 user 或 platform")
    user_id: int
    role: str
    is_platform_admin: bool
    organization_ids: list[int] = Field(default_factory=list)
    project_ids: list[int] = Field(default_factory=list)


class StatCard(BaseModel):
    """单个统计卡片。"""

    key: str
    label: str
    value: int = 0
    hint: str | None = None


class DashboardOverviewResponse(BaseModel):
    """个人工作台总览，所有数字都是当前用户可见范围。"""

    scope: DashboardScopeResponse
    stats: list[StatCard]


class ProjectSummaryItem(BaseModel):
    """项目概况列表项。"""

    id: int
    name: str
    description: str | None = None
    owner_id: int
    owner_username: str | None = None
    organization_id: int | None = None
    organization_name: str | None = None
    my_role: str | None = None
    member_count: int = 0
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ProjectSummaryResponse(BaseModel):
    """项目概况列表响应。"""

    total: int
    items: list[ProjectSummaryItem]


class ReadyCheckItem(BaseModel):
    """单项就绪检查结果。"""

    name: str
    status: str = Field(..., description="up / degraded / unavailable / unknown")
    detail: str | None = None


class ReadyResponse(BaseModel):
    """依赖就绪状态。

    单个非核心依赖失败不会让整个服务报 not_ready，只在 total 上标 degraded。
    """

    status: str = Field(..., description="ready / degraded / not_ready")
    checks: list[ReadyCheckItem]


__all__ = [
    "DashboardOverviewResponse",
    "DashboardScopeResponse",
    "ProjectSummaryItem",
    "ProjectSummaryResponse",
    "ReadyCheckItem",
    "ReadyResponse",
    "StatCard",
]
