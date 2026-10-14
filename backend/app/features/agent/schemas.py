"""接口测试 Agent：契约定义（Pydantic v2）。

只放枚举字面量、API 请求/响应模型与 LLM 结构化输出模型，不含业务逻辑。
service / router / nodes / tools 共用本文件作为接口契约（与 test_management 风格一致）。

设计要点：
- LLM 结构化输出模型（*Draft）尽量复用 test_management 的 *Create 子实体模型，
  这样 LLM 产出经 Pydantic 校验后可直接喂给 PointService/CaseService（source_type=AI）。
- 所有枚举字段在数据库层均为 String，合法取值由服务/节点层校验。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.features.test_management.schemas import (
    TestCaseDataCreate,
    TestCasePreconditionCreate,
    TestAssertionCreate,
    TestStepCreate,
)

# --------------------------------------------------------------------------- 枚举字面量

# Agent 意图：决定 router 节点跳到哪条边。
AGENT_INTENTS = (
    "GENERATE_TEST_POINTS", "GENERATE_TEST_CASES", "GENERATE_AND_EXECUTE",
    "EXECUTE_EXISTING_CASES", "ANALYZE_RESULT", "QUERY_TEST_ASSET", "CLARIFY",
)
AgentIntent = Literal[
    "GENERATE_TEST_POINTS", "GENERATE_TEST_CASES", "GENERATE_AND_EXECUTE",
    "EXECUTE_EXISTING_CASES", "ANALYZE_RESULT", "QUERY_TEST_ASSET", "CLARIFY",
]

# 工作流阶段：持久化在 agent_session.current_stage，下次请求据此由 router 跳过已完成段。
AGENT_STAGES = (
    "UNDERSTANDING", "CONTEXT_LOADING", "PLANNING", "TEST_POINT_REVIEW",
    "TEST_POINT_GENERATED", "TEST_CASE_REVIEW", "READY_TO_EXECUTE",
    "EXECUTING", "ANALYZING", "COMPLETED", "FAILED", "CLARIFY",
)
AgentStage = Literal[
    "UNDERSTANDING", "CONTEXT_LOADING", "PLANNING", "TEST_POINT_REVIEW",
    "TEST_POINT_GENERATED", "TEST_CASE_REVIEW", "READY_TO_EXECUTE",
    "EXECUTING", "ANALYZING", "COMPLETED", "FAILED", "CLARIFY",
]

# sendMessage 入参 action：人工在 review 暂停点的快捷操作。
AGENT_ACTIONS = (
    "confirm_points", "confirm_cases", "execute", "analyze",
    "regenerate_points", "regenerate_cases", "query", "continue",
)
AgentAction = Literal[
    "confirm_points", "confirm_cases", "execute", "analyze",
    "regenerate_points", "regenerate_cases", "query", "continue",
]

AGENT_SESSION_STATUSES = ("ACTIVE", "COMPLETED", "FAILED")
AgentSessionStatus = Literal["ACTIVE", "COMPLETED", "FAILED"]

AGENT_MESSAGE_ROLES = ("USER", "ASSISTANT", "SYSTEM")
AgentMessageRole = Literal["USER", "ASSISTANT", "SYSTEM"]

AGENT_MESSAGE_TYPES = ("TEXT", "TEST_PLAN", "TEST_POINTS", "TEST_CASES", "EXECUTION", "RESULT", "CLARIFY")
AgentMessageType = Literal["TEXT", "TEST_PLAN", "TEST_POINTS", "TEST_CASES", "EXECUTION", "RESULT", "CLARIFY"]

# 错误码（§36）：节点失败时写入 state.error_code + 人类可读消息。
AGENT_ERROR_CODES = (
    "INTENT_NOT_SUPPORTED", "TARGET_NOT_FOUND", "CONTEXT_LOAD_FAILED", "LLM_FAILED",
    "STRUCTURED_OUTPUT_INVALID", "TEST_POINT_VALIDATION_FAILED",
    "TEST_CASE_VALIDATION_FAILED", "EXECUTION_FAILED", "NO_DEFAULT_MODEL",
    "NO_ENVIRONMENT", "PERMISSION_DENIED",
)

# 结果分析 issue 严重度：区分疑似缺陷 / 测试数据问题 / 执行错误 / 断言失败 / 未知。
# 注意：Agent **不宣称「发现 Bug」**——POTENTIAL_BUG 仅表示「值得人工复核」。
AGENT_ISSUE_SEVERITIES = (
    "POTENTIAL_BUG", "TEST_DATA_ISSUE", "EXECUTION_ERROR", "ASSERTION_FAILURE", "UNKNOWN",
)


# --------------------------------------------------------------------------- 会话 / 消息 API 契约


class AgentSessionCreate(BaseModel):
    """建会话入参（project_id / user_id 由路径与鉴权提供）。"""

    title: str | None = Field(None, max_length=200, description="会话标题（为空时由首条消息生成）")


class AgentSessionResponse(BaseModel):
    id: int
    project_id: int
    user_id: int | None = None
    title: str | None = None
    status: str
    current_stage: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentMessageResponse(BaseModel):
    id: int
    session_id: int
    role: str
    message_type: str
    content: str | None = None
    metadata_json: dict[str, Any] | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentSessionDetailResponse(BaseModel):
    session: AgentSessionResponse
    messages: list[AgentMessageResponse]


class SendMessageRequest(BaseModel):
    """发消息推进 Agent。

    两种推进方式：
    - 普通对话：填 content（自然语言），Agent 走 intent → … 链。
    - review 暂停点快捷操作：填 action（confirm_points/confirm_cases/execute/analyze/...），
      可附带 point_ids/case_ids（子集确认）、environment_id（执行）。
    """

    content: str | None = Field(None, description="用户自然语言消息")
    action: AgentAction | None = Field(None, description="review 暂停点快捷操作")
    point_ids: list[int] | None = Field(None, description="确认/执行选中的测试点ID子集")
    case_ids: list[int] | None = Field(None, description="确认/执行选中的用例ID子集")
    environment_id: int | None = Field(None, gt=0, description="执行环境ID（execute 时必填）")


class AgentWorkspace(BaseModel):
    """工作区快照：按 stage 暴露当前 plan/points/cases/result，供前端右侧面板渲染。"""

    stage: str
    intent: str | None = None
    test_plan: dict[str, Any] | None = None
    test_points: list[dict[str, Any]] = []
    test_cases: list[dict[str, Any]] = []
    test_run_id: int | None = None
    execution_result: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    suggested_actions: list[str] = []


class AgentTurnResponse(BaseModel):
    """一次 sendMessage 的返回：会话状态 + 本次新增消息 + 工作区。"""

    session: AgentSessionResponse
    messages: list[AgentMessageResponse]
    workspace: AgentWorkspace


# --------------------------------------------------------------------------- LLM 结构化输出契约
#
# 这些模型既用于 FakeLLMProvider/LLMProvider 的结构化产出校验，也用于
# ValidatorNode 的业务校验。子实体直接复用 test_management 的 *Create 模型，
# 校验通过后由 test_asset_tool 携带 source_type=AI 落库。


class IntentResult(BaseModel):
    """IntentNode 产出：意图分类 + 目标解析。"""

    intent: AgentIntent
    target_type: Literal["API", "BUSINESS_FLOW", "BUSINESS_ACTION"] | None = None
    target_ids: list[int] = Field(default_factory=list, description="命中的目标ID（API/flow/action）")
    target_description: str | None = None
    clarify_question: str | None = Field(
        None, description="无法确定意图/目标时的澄清提问（intent=CLARIFY 时使用，不猜危险操作）",
    )


class TestPlanDraft(BaseModel):
    """TestPlannerNode 产出：测试计划（不落库，前端展示 + 指导生成）。"""

    target: str = Field(..., description="被测目标摘要")
    strategies: list[str] = Field(default_factory=list, description="覆盖策略类别列表")
    focus: list[str] = Field(default_factory=list, description="重点关注场景")
    estimated_points: int = Field(default=1, ge=1, le=50, description="预计测试点数量")


class TestPointDraft(BaseModel):
    """TestPointGeneratorNode 单条产出。落库时由 tool 补 source_type=AI 等追溯字段。"""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    target_type: Literal["API", "BUSINESS_FLOW", "BUSINESS_ACTION"] = "API"
    strategy_id: int | None = Field(None, gt=0)
    api_id: int | None = Field(None, gt=0)
    business_flow_id: int | None = Field(None, gt=0)
    business_action_id: int | None = Field(None, gt=0)
    rationale: str | None = Field(None, description="生成理由（供人工 review 判断）")


class TestPointDraftList(BaseModel):
    """TestPointGeneratorNode 产出的集合包装（LLM 结构化输出根对象）。"""

    points: list[TestPointDraft]


class TestCaseDraft(BaseModel):
    """TestCaseGeneratorNode 单条产出：用例 + 子实体。子实体复用 test_management Create 模型。"""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=1000)
    priority: Literal["P0", "P1", "P2", "P3"] = "P1"
    case_type: Literal[
        "FUNCTIONAL", "BUSINESS", "NEGATIVE", "BOUNDARY", "PERMISSION", "SECURITY", "EXCEPTION"
    ] = "FUNCTIONAL"
    target_type: Literal["API", "BUSINESS_FLOW", "BUSINESS_ACTION"] = "API"
    test_point_id: int | None = Field(None, gt=0, description="源自哪个已确认测试点")
    api_id: int | None = Field(None, gt=0)
    business_flow_id: int | None = Field(None, gt=0)
    business_action_id: int | None = Field(None, gt=0)
    preconditions: list[TestCasePreconditionCreate] = Field(default_factory=list)
    test_data: list[TestCaseDataCreate] = Field(default_factory=list)
    steps: list[TestStepCreate] = Field(default_factory=list)
    assertions: list[TestAssertionCreate] = Field(default_factory=list, description="至少 1 条断言")
    rationale: str | None = None


class TestCaseDraftList(BaseModel):
    """TestCaseGeneratorNode 产出的集合包装。"""

    cases: list[TestCaseDraft]


class AnalysisIssue(BaseModel):
    """ResultAnalyzerNode 单条 issue。"""

    severity: Literal["POTENTIAL_BUG", "TEST_DATA_ISSUE", "EXECUTION_ERROR", "ASSERTION_FAILURE", "UNKNOWN"]
    case_id: int | None = None
    summary: str
    detail: str | None = None


class ResultAnalysis(BaseModel):
    """ResultAnalyzerNode 产出：执行结果分析（不宣称「发现 Bug」）。"""

    summary: str
    issues: list[AnalysisIssue] = Field(default_factory=list)
    recommendation: str | None = None
