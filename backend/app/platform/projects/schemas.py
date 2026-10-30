"""项目模块：契约定义。

只放请求/响应模型与角色字面量类型，不含任何业务逻辑；
service 层与 router 层共享这里的类型，作为两层的接口契约。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 项目内三种成员角色，权限递增；负责人（owner）与平台管理员（admin）不在此枚举内，
# 而是由 project_role_for 在判定时就地提升，所以成员表里不会存 owner 角色。
ProjectRole = Literal["viewer", "member", "editor"]


class ProjectBase(BaseModel):
    """项目共有字段。"""

    name: str = Field(..., min_length=2, max_length=100, description="项目名称")
    description: str | None = Field(None, max_length=500, description="项目描述")


class ProjectCreate(ProjectBase):
    """新增项目入参。"""

    # 允许创建“未归属任何组织”的项目；传入后由 service 校验操作者是否管理该组织。
    organization_id: int | None = Field(default=None, gt=0, description="所属组织ID")


class ProjectUpdate(BaseModel):
    """修改项目入参（局部）。"""

    name: str | None = Field(None, min_length=2, max_length=100, description="项目名称")
    description: str | None = Field(None, max_length=500, description="项目描述")
    owner_id: int | None = Field(None, gt=0, description="负责人ID（仅负责人或管理员可改）")
    organization_id: int | None = Field(default=None, gt=0, description="所属组织ID")


class ProjectResponse(BaseModel):
    """项目响应。"""

    id: int
    name: str
    description: str | None = None
    owner_id: int
    owner_username: str | None = None
    organization_id: int | None = None
    organization_name: str | None = None
    # 当前请求用户在该项目的有效角色，供前端直接决定按钮可见性；越权访问时接口直接 404。
    my_role: str | None = None
    # 成员表行数，不含负责人（负责人由 owner_id 单独表达，不占成员行）。
    member_count: int = 0
    created_at: datetime
    updated_at: datetime

    # 允许从 ORM 模型实例直接实例化响应模型。
    model_config = ConfigDict(from_attributes=True)


class ProjectMemberCreate(BaseModel):
    """新增项目成员。"""

    user_id: int = Field(..., gt=0)
    role: ProjectRole = "member"


class ProjectMemberUpdate(BaseModel):
    """修改项目成员角色。"""

    role: ProjectRole


class ProjectMemberResponse(BaseModel):
    """项目成员响应。"""

    user_id: int
    username: str | None = None
    role: str
    # 负责人标记由查询方按 owner_id 推导，成员表本身不存这个字段。
    is_owner: bool = False
    created_by: int | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class OutboundTargetCreate(BaseModel):
    """新增项目出站目标（需项目 editor 及以上）。"""

    scheme: Literal["http", "https"] = "https"
    host: str = Field(..., min_length=1, max_length=253)
    port: int = Field(..., ge=1, le=65535)
    # 生产标记要求强制 https，service 侧会二次校验。
    is_production: bool = False


class OutboundTargetUpdate(BaseModel):
    """更新出站目标开关。"""

    enabled: bool


class OutboundTargetResponse(BaseModel):
    """出站目标响应。"""

    id: int
    project_id: int
    scheme: str
    host: str
    port: int
    is_production: bool
    enabled: bool
    approved_by: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedProjectResponse(BaseModel):
    """项目列表响应。"""

    items: list[ProjectResponse]
    total: int
    page: int = 1
    page_size: int = 1


class ProjectMemberListResponse(BaseModel):
    """项目成员列表响应。"""

    items: list[ProjectMemberResponse]
    total: int
    page: int = 1
    page_size: int = 1


class ProjectDetailResponse(ProjectResponse):
    """项目详情：附带成员列表。"""

    members: list[ProjectMemberResponse] = Field(default_factory=list)


__all__ = [
    "OutboundTargetCreate",
    "OutboundTargetResponse",
    "OutboundTargetUpdate",
    "PaginatedProjectResponse",
    "ProjectBase",
    "ProjectCreate",
    "ProjectDetailResponse",
    "ProjectMemberCreate",
    "ProjectMemberListResponse",
    "ProjectMemberResponse",
    "ProjectMemberUpdate",
    "ProjectResponse",
    "ProjectRole",
    "ProjectUpdate",
]
