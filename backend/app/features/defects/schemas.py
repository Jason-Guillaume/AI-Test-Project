"""缺陷模块：契约定义。

只放请求/响应模型与状态/严重度字面量类型，不含任何业务逻辑；
service 与 router 共用这里的类型，作为两层的接口契约。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# 缺陷状态集合，与旧项目保持一致；数据库层不做枚举约束，服务层校验。
BUG_STATUSES = ("待确认", "处理中", "已修复", "已关闭", "已拒绝")
BugStatus = Literal["待确认", "处理中", "已修复", "已关闭", "已拒绝"]

# 严重度 1-4，1 最低、4 最高。
BugSeverity = Literal[1, 2, 3, 4]

# 严重度中文标签，供前端下拉选项复用（与旧项目保持一致）。
SEVERITY_LABELS: dict[int, str] = {
    1: "低",
    2: "中",
    3: "高",
    4: "严重",
}


class BugBase(BaseModel):
    """缺陷共有字段。"""

    title: str = Field(..., min_length=1, max_length=200, description="缺陷标题")
    description: str | None = Field(None, max_length=1000, description="缺陷描述")
    severity: BugSeverity = Field(default=2, description="严重度 1-4")
    status: BugStatus = Field(default="待确认", description="状态")
    steps_to_reproduce: str | None = Field(
        None, description="复现步骤"
    )
    environment: str | None = Field(
        None, max_length=200, description="发现环境"
    )


class BugCreate(BugBase):
    """新增缺陷入参。"""

    project_id: int = Field(..., gt=0, description="所属项目ID")
    # assignee_id 可选：新建时可以不分配处理人，稍后由他人修改。
    assignee_id: int | None = Field(None, gt=0, description="处理人ID")


class BugUpdate(BaseModel):
    """修改缺陷入参（局部）。"""

    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    severity: BugSeverity | None = None
    status: BugStatus | None = None
    steps_to_reproduce: str | None = None
    environment: str | None = Field(None, max_length=200)
    # None 表示清空处理人；仅当调用方未提交该字段时保持原值不变（exclude_unset 语义）。
    assignee_id: int | None = Field(None, gt=0)


class BugResponse(BaseModel):
    """缺陷响应。"""

    id: int
    project_id: int
    project_name: str | None = None
    title: str
    description: str | None = None
    severity: int
    status: str
    steps_to_reproduce: str | None = None
    environment: str | None = None
    reporter_id: int | None = None
    reporter_username: str | None = None
    assignee_id: int | None = None
    assignee_username: str | None = None
    created_at: datetime
    updated_at: datetime

    # 允许从 ORM 模型实例直接实例化响应模型（虽然 service 层主要手动构造）。
    model_config = ConfigDict(from_attributes=True)


class BugListResponse(BaseModel):
    """缺陷列表响应。"""

    items: list[BugResponse]
    total: int
    page: int = 1
    page_size: int = 1


class DefectSourceRequest(BaseModel):
    """关联现有缺陷，或提交人工填写的缺陷并原子创建关联。"""
    source_type: Literal["CASE_EXECUTION", "SECURITY_FINDING"]
    source_id: int = Field(gt=0)
    bug_id: int | None = Field(default=None, gt=0)
    bug: BugCreate | None = None
    request_key: str = Field(min_length=1, max_length=100)


class DefectSourceResponse(BaseModel):
    """只返回授权后的标识，不复制请求、凭据或证据。"""
    id: int
    project_id: int
    bug_id: int
    case_execution_id: int | None
    security_finding_id: int | None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


__all__ = [
    "BUG_STATUSES",
    "BugBase",
    "BugCreate",
    "BugListResponse",
    "BugResponse",
    "BugSeverity",
    "BugStatus",
    "BugUpdate",
    "SEVERITY_LABELS",
]
