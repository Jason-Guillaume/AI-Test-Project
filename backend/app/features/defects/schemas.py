"""缺陷模块：契约定义。

只放请求/响应模型与状态/严重度字面量类型，不含任何业务逻辑；
service 与 router 共用这里的类型，作为两层的接口契约。

无指派人模型：缺陷以项目为归属，通过状态队列跟进。
assignee_id 仅保留入参兼容（显式非空值返回停用提示），不再出现在响应中。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 缺陷状态集合，与旧项目保持一致；数据库层不做枚举约束，服务层校验。
BUG_STATUSES = ("待确认", "处理中", "已修复", "已关闭", "已拒绝")
BugStatus = Literal["待确认", "处理中", "已修复", "已关闭", "已拒绝"]

# 界面展示名：底层「已修复」对测试人员显示为「待验证」，提示仍需回归。
STATUS_DISPLAY: dict[str, str] = {"已修复": "待验证"}

# 队列动作与状态迁移映射；服务端统一校验当前状态。
BUG_ACTIONS = (
    "confirm",
    "ready_for_regression",
    "regression_pass",
    "regression_fail",
    "reject",
    "mark_duplicate",
    "reopen",
)
BugAction = Literal[
    "confirm", "ready_for_regression", "regression_pass",
    "regression_fail", "reject", "mark_duplicate", "reopen",
]
ACTION_TRANSITIONS: dict[str, tuple[tuple[str, ...], str]] = {
    "confirm": (("待确认",), "处理中"),
    "ready_for_regression": (("处理中",), "已修复"),
    "regression_pass": (("已修复",), "已关闭"),
    "regression_fail": (("已修复",), "处理中"),
    "reject": (("待确认",), "已拒绝"),
    "mark_duplicate": (("待确认",), "已拒绝"),
    "reopen": (("已关闭", "已拒绝"), "待确认"),
}
ACTION_LABELS: dict[str, str] = {
    "created": "创建缺陷",
    "updated": "编辑事实字段",
    "confirm": "确认问题",
    "ready_for_regression": "登记可回归",
    "regression_pass": "回归通过",
    "regression_fail": "回归失败",
    "reject": "拒绝",
    "mark_duplicate": "判重",
    "reopen": "重开",
    "archive": "归档",
    "restore": "撤销归档",
    "external_resolved": "外部标记已解决",
}

ASSIGNEE_RETIRED_MESSAGE = (
    "处理人字段已停用：缺陷改由项目状态队列跟进，请移除 assignee_id（允许传空值）"
)
STATUS_EDIT_RETIRED_MESSAGE = (
    "状态不再通过普通编辑修改，请使用队列动作：确认问题/登记可回归/回归通过/回归失败/拒绝/判重/重开"
)

# 前后端划分集合；历史存量允许为空，在列表筛选时以「未划分」指代 NULL。
# 「接口」吸收原「后端」类别：接口与后端视为同一归属，旧入参「后端」自动映射为「接口」。
# 「前后端」保留自身类型，与「前端」共用同一提交表单。
BUG_CATEGORIES = ("前端", "前后端", "接口")
UNCATEGORIZED_BUG_CATEGORY = "未划分"
BugCategory = Literal["前端", "前后端", "接口"]
BugCategoryFilter = Literal["前端", "前后端", "接口", "未划分"]

# 旧类别别名：提交「后端」时自动归并为「接口」，兼容历史调用方。
BUG_CATEGORY_ALIASES: dict[str, BugCategory] = {"后端": "接口"}


def normalize_bug_category(value):
    """把旧类别「后端」归并为「接口」，其余值原样返回。"""
    if isinstance(value, str):
        return BUG_CATEGORY_ALIASES.get(value, value)
    return value

# 严重度 1-4，1 最低、4 最高。
BugSeverity = Literal[1, 2, 3, 4]

# 严重度中文标签，供前端下拉选项复用（与旧项目保持一致）。
SEVERITY_LABELS: dict[int, str] = {
    1: "低",
    2: "中",
    3: "高",
    4: "严重",
}

# 处理优先级 1-4，用于安排项目处理顺序，与严重度独立。
BugPriority = Literal[1, 2, 3, 4]
PRIORITY_LABELS: dict[int, str] = {
    1: "低",
    2: "中",
    3: "高",
    4: "紧急",
}

# 接口缺陷的请求方法集合；仅 category='接口' 时表单展示。
API_METHODS = ("GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS")
ApiMethod = Literal["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]


def _reject_assignee(value):
    """旧客户端允许传空值；显式设置处理人时返回明确的字段停用提示。"""
    if value is not None:
        raise ValueError(ASSIGNEE_RETIRED_MESSAGE)
    return None


class BugApiFields(BaseModel):
    """接口缺陷专属字段：请求方法/地址/请求头/请求体/响应结果。

    全部可选；仅 category='接口' 时表单展示，其他类别提交这些字段会被忽略落空。
    """

    api_method: ApiMethod | None = Field(None, description="请求方法")
    api_url: str | None = Field(None, max_length=500, description="请求地址")
    api_request_headers: str | None = Field(None, max_length=2000, description="请求头")
    api_request_body: str | None = Field(None, max_length=5000, description="请求体")
    api_response: str | None = Field(None, max_length=5000, description="实际响应结果")


class BugBase(BugApiFields):
    """缺陷共有字段。"""

    title: str = Field(..., min_length=1, max_length=200, description="缺陷标题")
    category: BugCategory | None = Field(default=None, description="前后端划分：前端/前后端/接口")
    description: str | None = Field(None, max_length=1000, description="缺陷描述")
    expected_result: str | None = Field(None, max_length=4000, description="预期结果")
    actual_result: str | None = Field(None, max_length=4000, description="实际结果")
    severity: BugSeverity | None = Field(default=None, description="严重度 1-4；缺省按模板默认值或 2")
    priority: BugPriority | None = Field(default=None, description="处理优先级 1-4；缺省按模板默认值或 2")
    # 兼容旧客户端：创建时提交的状态被忽略，新单统一进入待确认队列。
    status: BugStatus = Field(default="待确认", description="已停用：新单统一进入待确认队列")
    steps_to_reproduce: str | None = Field(None, description="复现步骤")
    environment: str | None = Field(None, max_length=200, description="发现环境，支持「待确认」")
    affected_version: str | None = Field(None, max_length=100, description="影响版本，支持「待确认」")

    @field_validator("category", mode="before")
    @classmethod
    def merge_legacy_category(cls, value):
        """旧入参「后端」自动归并为「接口」，选择后端即关联接口缺陷。"""
        return normalize_bug_category(value)


class BugCreate(BugBase):
    """新增缺陷入参；报告人、创建时间与初始状态由系统填写。"""

    project_id: int = Field(..., gt=0, description="所属项目ID")
    assignee_id: int | None = Field(None, description="已停用：仅允许空值")
    is_draft: bool = Field(default=False, description="保存草稿；草稿不进入队列")
    request_key: str | None = Field(
        default=None, min_length=8, max_length=100,
        description="创建幂等键：同项目同键同内容返回已创建缺陷，避免超时重试重复建单",
    )

    @field_validator("assignee_id")
    @classmethod
    def assignee_retired(cls, value):
        return _reject_assignee(value)

    @field_validator("title")
    @classmethod
    def valid_title(cls, value: str) -> str:
        """单条创建时剔除纯空白标题，直接返回 422 校验错误。"""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("标题不能为空")
        return cleaned


class BugBatchItem(BugBase):
    """批量创建中的单条缺陷入参；信息较少的记录进入待确认队列后再补齐。"""

    category: BugCategory | None = Field(default=None, description="前后端划分，可待确认时补齐")
    assignee_id: int | None = Field(None, description="已停用：仅允许空值")

    @field_validator("assignee_id")
    @classmethod
    def assignee_retired(cls, value):
        return _reject_assignee(value)


class BugBatchCreate(BaseModel):
    """批量创建缺陷入参：同项目下整批原子创建。"""

    project_id: int = Field(..., gt=0, description="所属项目ID")
    items: list[BugBatchItem] = Field(
        ..., min_length=1, max_length=100, description="待批量创建的缺陷明细"
    )


class BugUpdate(BugApiFields):
    """修改缺陷入参（局部）：只修改事实字段，状态通过队列动作变更。"""

    title: str | None = Field(None, min_length=1, max_length=200)
    category: BugCategory | None = None
    description: str | None = Field(None, max_length=1000)
    expected_result: str | None = Field(None, max_length=4000)
    actual_result: str | None = Field(None, max_length=4000)
    severity: BugSeverity | None = None
    priority: BugPriority | None = None
    status: BugStatus | None = Field(None, description="已停用：请使用队列动作")
    steps_to_reproduce: str | None = None
    environment: str | None = Field(None, max_length=200)
    affected_version: str | None = Field(None, max_length=100)
    assignee_id: int | None = Field(None, description="已停用：仅允许空值")
    expected_version: int | None = Field(
        default=None, ge=0, description="乐观并发：与当前记录版本不一致时返回 409 与最新数据"
    )

    @field_validator("category", mode="before")
    @classmethod
    def merge_legacy_category(cls, value):
        """旧入参「后端」自动归并为「接口」。"""
        return normalize_bug_category(value)

    @field_validator("assignee_id")
    @classmethod
    def assignee_retired(cls, value):
        return _reject_assignee(value)

    @field_validator("status")
    @classmethod
    def status_retired(cls, value):
        if value is not None:
            raise ValueError(STATUS_EDIT_RETIRED_MESSAGE)
        return None


class BugResponse(BugApiFields):
    """缺陷响应；不包含处理人字段。"""

    id: int
    project_id: int
    project_name: str | None = None
    title: str
    category: BugCategory | None = None
    description: str | None = None
    expected_result: str | None = None
    actual_result: str | None = None
    severity: int
    priority: int = 2
    status: str
    status_display: str = ""
    steps_to_reproduce: str | None = None
    environment: str | None = None
    affected_version: str | None = None
    fix_version: str | None = None
    reporter_id: int | None = None
    reporter_username: str | None = None
    record_version: int = 0
    is_draft: bool = False
    archived_at: datetime | None = None
    archive_reason: str | None = None
    duplicate_of_bug_id: int | None = None
    created_at: datetime
    updated_at: datetime
    active_share_count: int = 0

    # 允许从 ORM 模型实例直接实例化响应模型（虽然 service 层主要手动构造）。
    model_config = ConfigDict(from_attributes=True)


class BugListResponse(BaseModel):
    """缺陷列表响应。"""

    items: list[BugResponse]
    total: int
    page: int = 1
    page_size: int = 1


class BugBatchCreateResponse(BaseModel):
    """批量创建缺陷响应。"""

    items: list[BugResponse]
    created_count: int


class BugActionRequest(BaseModel):
    """队列动作入参：确认问题/登记可回归/回归通过/回归失败/拒绝/判重/重开。"""

    action: BugAction
    note: str | None = Field(None, max_length=4000, description="操作说明；拒绝/回归失败/重开必填")
    expected_version: int | None = Field(default=None, ge=0)
    fix_version: str | None = Field(None, max_length=200, description="登记可回归的版本/构建/环境")
    feedback_source: str | None = Field(None, max_length=200, description="外部处理反馈来源")
    verification_execution_id: int | None = Field(None, gt=0, description="回归通过关联的新执行")
    verification_environment: str | None = Field(None, max_length=200, description="手工回归环境")
    duplicate_of_bug_id: int | None = Field(None, gt=0, description="判重指向的同项目主单")
    # 确认问题时可补齐的事实字段。
    severity: BugSeverity | None = None
    priority: BugPriority | None = None
    steps_to_reproduce: str | None = None
    expected_result: str | None = Field(None, max_length=4000)
    actual_result: str | None = Field(None, max_length=4000)
    environment: str | None = Field(None, max_length=200)
    affected_version: str | None = Field(None, max_length=100)


class BugActivityResponse(BaseModel):
    """缺陷活动事件。"""

    id: int
    bug_id: int
    action: str
    action_label: str = ""
    actor_id: int | None = None
    actor_name: str | None = None
    actor_type: str = "INTERNAL"
    old_status: str | None = None
    new_status: str | None = None
    note: str | None = None
    detail: dict[str, Any] | None = None
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class BugActionResponse(BaseModel):
    """动作结果：最新缺陷与本次活动事件。"""

    bug: BugResponse
    activity: BugActivityResponse


class BugQueueCountsResponse(BaseModel):
    """项目队列计数；与同条件列表总数一致。"""

    project_id: int
    unclosed: int
    pending_confirm: int
    in_progress: int
    pending_verify: int
    reported_by_me: int
    closed: int
    rejected: int
    archived: int
    drafts: int


class BugStatsResponse(BaseModel):
    """质量统计：积压、首次确认耗时、待验证时长与回归失败率。"""

    project_id: int
    period_days: int
    backlog: dict[str, int]
    first_confirm_hours_avg: float | None = None
    first_confirm_sample: int = 0
    pending_verify_hours_avg: float | None = None
    pending_verify_sample: int = 0
    regression_total: int = 0
    regression_failed: int = 0
    regression_failure_rate: float | None = None


class BugBatchActionRequest(BaseModel):
    """批量治理动作：调整优先级、归档、撤销归档。"""

    project_id: int = Field(..., gt=0)
    ids: list[int] = Field(..., min_length=1, max_length=500)
    action: Literal["set_priority", "archive", "restore"]
    priority: BugPriority | None = None
    reason: str | None = Field(None, max_length=500, description="归档原因，归档时必填")


class BugBatchActionItemResult(BaseModel):
    id: int
    succeeded: bool
    error: str | None = None


class BugBatchActionReceipt(BaseModel):
    """部分失败时返回逐项结果。"""

    succeeded: int
    failed: int
    items: list[BugBatchActionItemResult]


class BugArchiveRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500, description="归档原因")


class DefectProjectSettingResponse(BaseModel):
    project_id: int
    queue_enabled: bool = True
    reminder_enabled: bool = False
    stale_reminder_days: int = 7


class DefectProjectSettingUpdate(BaseModel):
    queue_enabled: bool | None = None
    reminder_enabled: bool | None = None
    stale_reminder_days: int | None = Field(None, ge=1, le=90)


class DefectTemplateConfig(BaseModel):
    """模板配置：字段显隐、默认值、优先级与分阶段必填；不含人员指派。"""

    hidden_fields: list[str] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    required_on_create: list[str] = Field(default_factory=list)
    required_on_confirm: list[str] = Field(default_factory=list)
    required_on_regression: list[str] = Field(default_factory=list)


class DefectTemplateCreate(BaseModel):
    config: DefectTemplateConfig


class DefectTemplateResponse(BaseModel):
    id: int
    project_id: int
    version: int
    status: str
    config: dict[str, Any]
    created_by_username: str | None = None
    created_at: datetime
    published_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)


class DefectTemplatePreviewRequest(BaseModel):
    config: DefectTemplateConfig


class DefectTemplatePreviewResponse(BaseModel):
    """发布前预览：示例缺陷按模板渲染后的字段清单。"""

    sample: dict[str, Any]
    hidden_fields: list[str]
    required_on_create: list[str]
    required_on_confirm: list[str]
    required_on_regression: list[str]


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
    "ACTION_LABELS",
    "ACTION_TRANSITIONS",
    "API_METHODS",
    "ASSIGNEE_RETIRED_MESSAGE",
    "BUG_ACTIONS",
    "BUG_CATEGORIES",
    "BUG_CATEGORY_ALIASES",
    "BUG_STATUSES",
    "BugAction",
    "BugActionRequest",
    "BugActionResponse",
    "BugActivityResponse",
    "BugApiFields",
    "BugArchiveRequest",
    "BugBase",
    "BugBatchActionItemResult",
    "BugBatchActionReceipt",
    "BugBatchActionRequest",
    "BugBatchCreate",
    "BugBatchCreateResponse",
    "BugBatchItem",
    "BugCategory",
    "BugCategoryFilter",
    "BugCreate",
    "BugListResponse",
    "BugPriority",
    "BugQueueCountsResponse",
    "BugResponse",
    "BugSeverity",
    "BugStatsResponse",
    "BugStatus",
    "BugUpdate",
    "DefectProjectSettingResponse",
    "DefectProjectSettingUpdate",
    "DefectSourceRequest",
    "DefectSourceResponse",
    "DefectTemplateConfig",
    "DefectTemplateCreate",
    "DefectTemplatePreviewRequest",
    "DefectTemplatePreviewResponse",
    "DefectTemplateResponse",
    "PRIORITY_LABELS",
    "SEVERITY_LABELS",
    "STATUS_DISPLAY",
    "STATUS_EDIT_RETIRED_MESSAGE",
    "UNCATEGORIZED_BUG_CATEGORY",
    "normalize_bug_category",
]