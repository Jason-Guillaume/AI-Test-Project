"""测试范围的请求与响应契约。

节点是导航，不是测试点，也不是策略。用例列表按节点聚合时仍返回正式 TestCase 字段。
AI 方向的 executor_ready 由详情接口给出，本文件只声明字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.test_management.scope_placement import ASSET_TYPES, DIRECTIONS, NODE_TYPES

Direction = Literal["API", "UI", "AI"]
NodeType = Literal["FOLDER", "ASSET_LINK", "INBOX"]
AssetType = Literal[
    "API_MODULE",
    "API_INTERFACE",
    "BUSINESS_DOMAIN",
    "BUSINESS_FLOW",
    "BUSINESS_ACTION",
    "WEB_PAGE",
    "AGENT",
]


class ScopeNodeCreate(BaseModel):
    """新建目录或资产链接。待整理节点只由系统创建。"""

    direction: Direction
    parent_id: int | None = Field(default=None, gt=0)
    node_type: Literal["FOLDER", "ASSET_LINK"]
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    sort_order: int | None = Field(default=None, ge=0)
    asset_type: AssetType | None = None
    asset_id: int | None = Field(default=None, gt=0)


class ScopeNodeUpdate(BaseModel):
    """修改节点文案、排序或资产指针。不能改方向和节点类型。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    sort_order: int | None = Field(default=None, ge=0)
    status: Literal["ACTIVE", "ARCHIVED"] | None = None
    asset_type: AssetType | None = None
    asset_id: int | None = Field(default=None, gt=0)


class ScopeNodeMove(BaseModel):
    """调整父节点和同级顺序。parent_id 为空表示移到该方向的根。"""

    parent_id: int | None = Field(default=None, gt=0)
    sort_order: int = Field(default=0, ge=0)


class ScopeNodeResponse(BaseModel):
    """树节点。case_count / point_count 含全部子孙，不是只算直接挂载。"""

    id: int
    project_id: int
    direction: str
    parent_id: int | None = None
    node_type: str
    name: str
    description: str | None = None
    sort_order: int
    status: str
    asset_type: str | None = None
    asset_id: int | None = None
    is_system: bool
    case_count: int = 0
    point_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ScopePathItem(BaseModel):
    """从根到当前节点的一层。"""

    id: int
    name: str
    node_type: str


class ScopeNodeDetailResponse(ScopeNodeResponse):
    """节点详情：完整路径和下一层子节点。"""

    path: list[ScopePathItem] = Field(default_factory=list)
    children: list[ScopeNodeResponse] = Field(default_factory=list)


class ScopeTreeResponse(BaseModel):
    """某一方向的扁平节点列表，前端按 parent_id 组树。"""

    direction: str
    items: list[ScopeNodeResponse]


class ScopeStatsResponse(BaseModel):
    """方向级汇总，供页面顶部使用。"""

    direction: str
    scope_count: int
    case_count: int
    point_count: int
    priority_counts: dict[str, int]


class ScopeCaseQueryItem(BaseModel):
    """范围内的用例行。目录路径和测试点名称供表格直接展示。"""

    id: int
    project_id: int
    name: str
    priority: str
    case_type: str
    target_type: str
    status: str
    source_type: str
    test_point_id: int | None = None
    test_point_name: str | None = None
    direction: str
    updated_at: datetime


class ScopeCaseListResponse(BaseModel):
    items: list[ScopeCaseQueryItem]
    total: int
    page: int
    page_size: int


class ScopeCaseMoveRequest(BaseModel):
    """把用例的目录归属改到目标节点。不改 api_id 等执行外键。"""

    case_ids: list[int] = Field(min_length=1, max_length=200)
    scope_node_id: int = Field(gt=0)


class ScopeCaseArchiveRequest(BaseModel):
    """批量归档：状态改为 DEPRECATED，用例仍留在原目录。"""

    case_ids: list[int] = Field(min_length=1, max_length=200)


class ScopeLinkReplace(BaseModel):
    """整体替换用例的目录归属。"""

    scope_node_ids: list[int] = Field(min_length=1, max_length=20)


class CaseAssetItem(BaseModel):
    asset_type: AssetType
    asset_id: int = Field(gt=0)


class CaseAssetReplace(BaseModel):
    """整体替换用例的被测资产关联。不改写 TestCase 上已有的执行外键。"""

    items: list[CaseAssetItem] = Field(default_factory=list, max_length=30)


class CaseAssetResponse(BaseModel):
    id: int
    asset_type: str
    asset_id: int

    model_config = ConfigDict(from_attributes=True)


class CaseExecutionBrief(BaseModel):
    """详情里的最近执行，不含请求响应快照。"""

    id: int
    status: str
    executor_type: str | None = None
    error_code: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class ScopePathResponse(BaseModel):
    """一条目录归属及其从根开始的路径。"""

    scope_node_id: int
    direction: str
    path: list[ScopePathItem]


class ScopeMutationResult(BaseModel):
    """批量移动或归档后的影响行数。"""

    affected: int


def assert_contract_sets() -> None:
    """防止字面量和纯规则常量漂移。仅测试或导入自检时调用。"""
    if set(DIRECTIONS) != {"API", "UI", "AI"}:
        raise RuntimeError("测试方向常量漂移")
    if set(NODE_TYPES) != {"FOLDER", "ASSET_LINK", "INBOX"}:
        raise RuntimeError("节点类型常量漂移")
    if set(ASSET_TYPES) != {
        "API_MODULE", "API_INTERFACE", "BUSINESS_DOMAIN", "BUSINESS_FLOW",
        "BUSINESS_ACTION", "WEB_PAGE", "AGENT",
    }:
        raise RuntimeError("资产类型常量漂移")
