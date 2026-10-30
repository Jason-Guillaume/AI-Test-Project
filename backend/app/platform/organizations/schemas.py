"""组织模块：契约定义。

集中定义组织、成员与模型授权相关的 Pydantic 契约（请求体与响应信封）。
列表接口统一返回 {items, total, page, page_size} 信封，
与前端 TanStack Query 的分页约定保持一致。

与旧项目的差异：
- my_role 使用「组织内有效角色 + platform_admin 虚拟角色」的合并语义
- 成员行的 role 允许不再是 owner（负责人身份由 organization.owner_id 单独记录）
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 组织内角色三选一：owner 组织负责人 / admin 组织管理员 / member 普通成员
OrganizationRole = Literal["owner", "admin", "member"]


class OrganizationCreate(BaseModel):
    """创建组织入参。"""

    name: str = Field(..., min_length=2, max_length=100, description="组织名称")  # 组织名称，全平台唯一


class OrganizationUpdate(BaseModel):
    """更新组织入参（局部）。仅允许改名称，不允许多字段同时更新。"""

    name: str | None = Field(None, min_length=2, max_length=100, description="组织名称")  # 新组织名称


class OrganizationResponse(BaseModel):
    """组织响应。my_role 为当前用户在组织中的有效角色（含 platform_admin 虚拟角色）。"""

    id: int  # 组织 ID
    name: str  # 组织名称
    owner_id: int  # 当前负责人用户 ID
    my_role: str | None = None  # 当前用户在该组织内的有效角色，非成员为 None
    created_at: datetime | None = None  # 组织创建时间
    updated_at: datetime | None = None  # 最近更新时间
    member_count: int = 0  # 成员总数，供前端列表直接展示

    model_config = ConfigDict(from_attributes=True)  # 允许直接从 ORM 实例取值


class MemberGrant(BaseModel):
    """新增或更新组织成员。角色、Agent 开关与模型授权一起提交。"""

    user_id: int = Field(..., gt=0)  # 目标成员用户 ID
    role: OrganizationRole = "member"  # 组织内角色，默认普通成员
    agent_enabled: bool = False  # 是否开启 Agent 能力（决定是否需要模型授权）
    allowed_model_ids: list[str] = Field(default_factory=list, max_length=30)  # 允许的模型 domain_id 列表，最多 30 个


class OrganizationMemberResponse(BaseModel):
    """组织成员响应。is_org_owner 由 organization.owner_id 单独标记，与 role 解耦。"""

    user_id: int  # 成员用户 ID
    role: OrganizationRole  # 组织内角色（可能不再是 owner）
    agent_enabled: bool  # Agent 能力开关
    allowed_model_ids: list[str]  # 允许的模型 domain_id 列表
    is_org_owner: bool = False  # 是否为当前组织负责人
    created_at: datetime | None = None  # 成员行创建时间


class UserCandidate(BaseModel):
    """可加入组织的用户候选。仅返回启用账号。"""

    id: int  # 用户 ID
    username: str  # 用户名
    role: str  # 平台角色（admin/test/dev）
    is_active: bool = True  # 账号启用状态，候选接口固定返回 True


class CandidateResponse(BaseModel):
    """成员搜索候选。item 为 None 表示未找到匹配用户。"""

    item: UserCandidate | None = None  # 命中的候选；未命中为 None


class ModelOption(BaseModel):
    """可供组织管理员分配的模型选项。"""

    domain_id: str  # 模型域 ID，用作分配键
    label: str  # 展示用名称


class PaginatedOrganizationResponse(BaseModel):
    """组织列表响应。成员与组织均不超过百量级，列表不做服务端分页但仍返回统一信封。"""

    items: list[OrganizationResponse]  # 当前返回的组织列表
    total: int  # 总数（等于 items 长度）
    page: int = 1  # 页码，固定为 1
    page_size: int = 1  # 每页条数，兜底 1 避免前端分页组件报错


class MemberListResponse(BaseModel):
    """组织成员列表响应。"""

    items: list[OrganizationMemberResponse]  # 当前返回的成员列表
    total: int  # 成员总数
    page: int = 1  # 页码，固定为 1
    page_size: int = 1  # 每页条数，兜底 1


class ModelOptionsResponse(BaseModel):
    """可分配模型列表响应。"""

    items: list[ModelOption]  # 可分配模型选项
    total: int  # 总数


__all__ = [
    "CandidateResponse",
    "MemberGrant",
    "MemberListResponse",
    "ModelOption",
    "ModelOptionsResponse",
    "OrganizationCreate",
    "OrganizationMemberResponse",
    "OrganizationResponse",
    "OrganizationRole",
    "OrganizationUpdate",
    "PaginatedOrganizationResponse",
    "UserCandidate",
]
