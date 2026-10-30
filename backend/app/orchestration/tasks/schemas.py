"""统一任务 HTTP 契约。

本模块定义任务创建、分页读取、运行、参与者消息、控制命令、事件和资源引用 DTO；
字段与 tasks ORM / React API 一一对应，敏感模型凭据不会出现在响应内。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from app.agents.session_schemas import SendMessageRequest


class TaskSecurityAssessmentSelection(BaseModel):
    """自研安全评估范围；目标和策略都必须属于当前项目或平台模板。"""

    model_config = ConfigDict(extra="forbid")

    api_ids: list[int] = Field(default_factory=list, max_length=10)
    # 兼容上一版单 API 客户端；新客户端统一传 api_ids。
    api_id: int | None = Field(default=None, gt=0)
    web_session_id: int | None = Field(default=None, gt=0)
    strategy_ids: list[int] = Field(min_length=1, max_length=50)


class TaskWebAuthoringSelection(BaseModel):
    """交互式 Web 编写的受控会话范围。"""

    model_config = ConfigDict(extra="forbid")

    auth_profile_id: int | None = Field(default=None, gt=0)
    target_page_path: str = Field(default="", max_length=2000)
    step_budget: int = Field(default=20, ge=1, le=100)


class TaskCreate(BaseModel):
    """创建 API / Web / 自研安全评估任务并登记首个异步运行。"""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=200)
    goal: str = Field(min_length=3, max_length=8000)
    agent_definition_id: int | None = Field(default=None, gt=0)
    environment_id: int = Field(gt=0)
    case_ids: list[int] = Field(default_factory=list, max_length=100)
    security_assessment: TaskSecurityAssessmentSelection | None = None
    task_mode: Literal["TEST_EXECUTION", "WEB_AUTHORING"] = "TEST_EXECUTION"
    web_authoring: TaskWebAuthoringSelection | None = None
    request_key: str | None = Field(None, max_length=100)


class AvailableTaskAgentResponse(BaseModel):
    """当前项目与执行类型可选择的 Agent 摘要，不返回内部指令或 Skill 内容。"""

    id: int
    name: str
    description: str
    workflow_template: str
    version: int


class TaskRunResponse(BaseModel):
    """任务运行权威状态与计划游标。"""

    id: int
    task_id: int
    run_number: int
    status: str
    stage: str
    goal_snapshot: str
    input_snapshot: dict[str, Any]
    current_plan_version: int
    event_seq: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskResponse(BaseModel):
    """任务列表行；最新运行由服务层按 run_number 计算。"""

    id: int
    project_id: int
    created_by: int | None = None
    title: str
    goal: str
    environment_id: int | None = None
    input_case_ids: list[int]
    status: str
    task_mode: str = "TEST_EXECUTION"
    archived: bool
    created_at: datetime
    updated_at: datetime
    latest_run: TaskRunResponse | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskListResponse(BaseModel):
    """统一任务分页响应。"""

    items: list[TaskResponse]
    total: int
    page: int
    page_size: int


class TaskPlanResponse(BaseModel):
    """单个不可变编排方案版本。"""

    id: int
    task_run_id: int
    version: int
    status: str
    plan_json: dict[str, Any]
    created_at: datetime
    accepted_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskAgentInstanceResponse(BaseModel):
    """某次运行的参与者实例与独立会话配置。"""

    id: int
    task_run_id: int
    instance_key: str
    role: str
    display_name: str
    status: str
    model_config_id: int | None = None
    config_snapshot: dict[str, Any]
    skills_json: list[str]
    tool_allowlist_json: list[str]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskWorkItemResponse(BaseModel):
    """运行内工作项的调度状态，不回传内部锁令牌。"""

    id: int
    task_run_id: int
    agent_instance_id: int | None = None
    work_key: str
    kind: str
    sequence: int
    status: str
    output_json: dict[str, Any] | None = None
    attempt_count: int
    retryable: bool = False
    retry_block_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskToolInvocationResponse(BaseModel):
    """对任务成员公开的工具调用审计摘要；不返回工具参数或远端结果。"""

    id: int
    work_item_id: int
    agent_instance_id: int | None = None
    tool_name: str
    status: str
    error_code: str | None = None
    created_at: datetime
    finished_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskRunDetailResponse(BaseModel):
    """运行详情聚合：运行、方案、参与者与工作项。"""

    run: TaskRunResponse
    plans: list[TaskPlanResponse]
    agents: list[TaskAgentInstanceResponse]
    work_items: list[TaskWorkItemResponse]
    tool_invocations: list[TaskToolInvocationResponse]


class TaskMessageCreate(BaseModel):
    """向任务主 Agent 调目标，或向指定 Worker 发送补充要求。"""

    recipient_instance_id: int | None = Field(None, gt=0)
    message_type: Literal["TEXT", "GOAL_UPDATE", "REQUIREMENT"] = "TEXT"
    content: str = Field(min_length=1, max_length=8000)
    client_message_id: str = Field(min_length=1, max_length=100)


class TaskWebAuthoringTurn(SendMessageRequest):
    """任务 Web 对话的幂等客户端键；动作集合由任务服务再次收窄。"""

    request_key: str = Field(min_length=1, max_length=100)


class TaskMessageResponse(BaseModel):
    """独立参与者会话消息及其接收/处理状态。"""

    id: int
    task_run_id: int
    agent_instance_id: int
    sender_type: str
    sender_user_id: int | None = None
    sender_instance_id: int | None = None
    message_type: str
    content: str
    metadata_json: dict[str, Any]
    status: str
    client_message_id: str
    created_at: datetime
    processed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskCommandCreate(BaseModel):
    """显式任务状态命令；重复请求由幂等键去重。"""

    command_type: Literal["APPROVE_PLAN", "PAUSE", "RESUME", "CANCEL", "RETRY"]
    idempotency_key: str = Field(min_length=1, max_length=100)
    work_item_id: int | None = Field(None, gt=0)
    security_risk_confirmed: bool = False


class TaskCommandResponse(BaseModel):
    """已接受或重复命中的命令回执。"""

    id: int
    task_run_id: int
    command_type: str
    idempotency_key: str
    status: str
    response_json: dict[str, Any]
    created_at: datetime
    processed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskEventResponse(BaseModel):
    """一个可按 event_seq 续读的持久化系统事件。"""

    id: int
    task_run_id: int
    event_seq: int
    event_type: str
    actor_user_id: int | None = None
    agent_instance_id: int | None = None
    payload: dict[str, Any]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TaskResourceRefResponse(BaseModel):
    """原业务资源的方向、类型、稳定 ID 与可读关联名称。"""

    id: int
    task_run_id: int
    agent_instance_id: int | None = None
    direction: str
    resource_type: str
    resource_id: str
    version: str | None = None
    metadata_json: dict[str, Any]
    created_at: datetime
    display_name: str | None = None
    task_id: int | None = None
    task_title: str | None = None
    run_number: int | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskPlanOutput(BaseModel):
    """Planner 可接受的结构化方案摘要；业务资源选择由服务端锁定。"""

    summary: str = Field(min_length=1, max_length=2000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=12)

    model_config = ConfigDict(extra="forbid")


class ApiWorkerSelection(BaseModel):
    """API Worker 对已授权用例做范围内筛选，不得增加用例 ID。"""

    case_ids: list[int] = Field(min_length=1, max_length=100)
    explanation: str = Field(min_length=1, max_length=2000)

    model_config = ConfigDict(extra="forbid")


class TaskReviewOutput(BaseModel):
    """审阅 Agent 对正式报告覆盖范围与验收条件的结构化结论。"""

    approved: bool
    findings: list[str] = Field(default_factory=list, max_length=12)

    model_config = ConfigDict(extra="forbid")
