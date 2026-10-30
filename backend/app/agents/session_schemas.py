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
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- 枚举字面量

# Agent 意图：决定 router 节点跳到哪条边。
# 安全类意图（Phase F）：LLM 只选目标与已加载策略，变异清单由 PlanService.preview 生成。
AGENT_INTENTS = (
    "GENERATE_TEST_POINTS", "GENERATE_TEST_CASES", "GENERATE_AND_EXECUTE",
    "EXECUTE_EXISTING_CASES", "ANALYZE_RESULT", "QUERY_TEST_ASSET", "CLARIFY",
    "GENERATE_SECURITY_TEST", "EXECUTE_SECURITY_TEST",
    "ANALYZE_SECURITY_RESULT", "QUERY_SECURITY_FINDING", "REQUEST_SECURITY_SCAN",
    # Phase 2：交互式 Web 用例编写（observe→decide→act 循环）。
    "INTERACTIVE_WEB_AUTHORING",
)
AgentIntent = Literal[
    "GENERATE_TEST_POINTS", "GENERATE_TEST_CASES", "GENERATE_AND_EXECUTE",
    "EXECUTE_EXISTING_CASES", "ANALYZE_RESULT", "QUERY_TEST_ASSET", "CLARIFY",
    "GENERATE_SECURITY_TEST", "EXECUTE_SECURITY_TEST",
    "ANALYZE_SECURITY_RESULT", "QUERY_SECURITY_FINDING", "REQUEST_SECURITY_SCAN",
    "INTERACTIVE_WEB_AUTHORING",
]

# 工作流阶段：持久化在 agent_session.current_stage，下次请求据此由 router 跳过已完成段。
# SECURITY_PLAN_REVIEW（Phase F）：安全计划已生成但未确认，用例还没落库。
AGENT_STAGES = (
    "UNDERSTANDING", "CONTEXT_LOADING", "PLANNING", "TEST_POINT_REVIEW",
    "TEST_POINT_GENERATED", "TEST_CASE_REVIEW", "READY_TO_EXECUTE",
    "EXECUTING", "ANALYZING", "REPORT_GENERATING", "REPORT_REVIEW",
    "NOTIFYING", "COMPLETED", "FAILED", "CLARIFY",
    "SECURITY_PLAN_REVIEW",
    # Phase 2：ZAP 扫描计划已生成但未确认，任务还没创建。
    "ZAP_SCAN_REVIEW",
    # Phase 2：Web 智能体步骤提案已生成但未确认，等待人工 review。
    "WEB_STEP_REVIEW",
)
AgentStage = Literal[
    "UNDERSTANDING", "CONTEXT_LOADING", "PLANNING", "TEST_POINT_REVIEW",
    "TEST_POINT_GENERATED", "TEST_CASE_REVIEW", "READY_TO_EXECUTE",
    "EXECUTING", "ANALYZING", "REPORT_GENERATING", "REPORT_REVIEW",
    "NOTIFYING", "COMPLETED", "FAILED", "CLARIFY",
    "SECURITY_PLAN_REVIEW",
    "ZAP_SCAN_REVIEW",
    "WEB_STEP_REVIEW",
]

# sendMessage 入参 action：人工在 review 暂停点的快捷操作。
# confirm_security_risk 只由人工触发；LLM 工具里没有这个参数。
AGENT_ACTIONS = (
    "confirm_points", "confirm_cases", "execute", "analyze",
    "regenerate_points", "regenerate_cases", "query", "continue",
    # Phase 2：报告 review 暂停点的快捷操作（confirm_report 触发飞书通知，skip 跳过）。
    "confirm_report", "skip_notification",
    # Phase F：安全计划确认 / 高风险人工确认。
    "confirm_security_plan", "confirm_security_risk", "confirm_security_scan",
    # Phase 2：Web 智能体步骤提案确认 / 拒绝；提升通过 Web Agent 专用端点完成。
    "confirm_web_step", "reject_web_step",
)
AgentAction = Literal[
    "confirm_points", "confirm_cases", "execute", "analyze",
    "regenerate_points", "regenerate_cases", "query", "continue",
    "confirm_report", "skip_notification",
    "confirm_security_plan", "confirm_security_risk", "confirm_security_scan",
    "confirm_web_step", "reject_web_step",
]

AGENT_SESSION_STATUSES = ("ACTIVE", "COMPLETED", "FAILED")
AgentSessionStatus = Literal["ACTIVE", "COMPLETED", "FAILED"]

AGENT_MESSAGE_ROLES = ("USER", "ASSISTANT", "SYSTEM")
AgentMessageRole = Literal["USER", "ASSISTANT", "SYSTEM"]

AGENT_MESSAGE_TYPES = (
    "TEXT", "TEST_PLAN", "TEST_POINTS", "TEST_CASES", "EXECUTION", "RESULT", "CLARIFY",
    # Phase 2：报告与通知产物消息（metadata 存脱敏 brief，不含 webhook/sign）。
    "REPORT", "NOTIFICATION",
    # Phase F：安全计划（PlanService.preview 的代码生成结果，未落 TestCase）。
    "SECURITY_PLAN",
    # Phase 2：ZAP 扫描计划预览（job_service.plan 的结果，确认前不创建任务）。
    "SECURITY_SCAN_PLAN",
    # Phase 2：Web 智能体步骤提案与页面观测。
    "WEB_AGENT_STEP", "WEB_OBSERVATION",
)
AgentMessageType = Literal[
    "TEXT", "TEST_PLAN", "TEST_POINTS", "TEST_CASES", "EXECUTION", "RESULT", "CLARIFY",
    "REPORT", "NOTIFICATION",
    "SECURITY_PLAN",
    "SECURITY_SCAN_PLAN",
    "WEB_AGENT_STEP", "WEB_OBSERVATION",
]

# 错误码（§36）：节点失败时写入 state.error_code + 人类可读消息。
AGENT_ERROR_CODES = (
    "INTENT_NOT_SUPPORTED", "TARGET_NOT_FOUND", "CONTEXT_LOAD_FAILED", "LLM_FAILED",
    "STRUCTURED_OUTPUT_INVALID", "TEST_POINT_VALIDATION_FAILED",
    "TEST_CASE_VALIDATION_FAILED", "EXECUTION_FAILED", "NO_DEFAULT_MODEL",
    "NO_ENVIRONMENT", "PERMISSION_DENIED",
    # Phase 2：报告生成 / 飞书发送失败（独立于 TestRun/Report 状态，§二十八）。
    "REPORT_GENERATION_FAILED", "FEISHU_SEND_FAILED",
    # Phase F：安全上下文加载 / 安全计划生成或确认失败。
    "SECURITY_CONTEXT_FAILED", "SECURITY_PLAN_FAILED",
    # Phase 2：ZAP 扫描计划生成 / 扫描任务创建失败（含缺少人工批准）。
    "SECURITY_SCAN_PLAN_FAILED", "SECURITY_SCAN_NOT_AUTHORIZED",
    # Web 智能体二轮：受控会话缺失 / 观测或执行失败 / 提案不合法 / 步数预算耗尽。
    "WEB_SESSION_CLOSED", "WEB_OBSERVE_FAILED", "WEB_STEP_INVALID",
    "WEB_BUDGET_EXCEEDED", "WEB_STEP_FAILED", "WEB_STEP_MISSING",
)

# 结果分析 issue 严重度：区分疑似缺陷 / 测试数据问题 / 执行错误 / 断言失败 / 未知。
# 注意：Agent **不宣称「发现 Bug」**——POTENTIAL_BUG 仅表示「值得人工复核」。
AGENT_ISSUE_SEVERITIES = (
    "POTENTIAL_BUG", "TEST_DATA_ISSUE", "EXECUTION_ERROR", "ASSERTION_FAILURE", "UNKNOWN",
)


# --------------------------------------------------------------------------- 会话 / 消息 API 接口 契约


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
    channel_id: int | None = Field(None, gt=0, description="飞书通知渠道ID（confirm_report 时可选，缺省取项目首个启用渠道）")
    security_item_indexes: list[int] | None = Field(
        None, description="confirm_security_plan 时接受的预览项 index（缺省 = 全部未阻断项）",
    )
    security_case_ids: list[int] | None = Field(
        None, description="confirm_security_risk 时待确认高风险的安全用例 TestCase ID（缺省 = 全部待确认项）",
    )
    # ZAP 扫描计划只接受用户显式选择；任务创建仍须后续人工 confirm_security_scan。
    zap_scan_target_id: int | None = Field(None, gt=0, description="ZAP 扫描计划的项目目标 ID")
    zap_scan_profile_id: int | None = Field(None, gt=0, description="ZAP 扫描计划的项目策略 ID")
    approval_note: str | None = Field(
        None, max_length=500, description="人工确认主动扫描时填写的批准说明",
    )
    # Web 智能体二轮：显式绑定受控浏览器会话（经 POST /projects/{id}/web-agent/sessions 创建）。
    # 归属校验在后端做：会话不属于本 Agent 会话所在项目时统一 404。
    web_session_id: int | None = Field(
        None, gt=0, description="Web 智能体绑定的受控浏览器会话 ID（交互式编写时必填）",
    )


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
    # Phase 2：报告闭环 + 飞书通知产物（脱敏 brief，不含 webhook/sign）。
    report_id: int | None = None
    report_brief: dict[str, Any] | None = None
    notification_brief: dict[str, Any] | None = None
    # Phase F：安全计划（代码生成的预览项，未确认前不落 TestCase）与 Finding 摘要。
    security_plan: dict[str, Any] | None = None
    security_findings: list[dict[str, Any]] = []
    # Phase 2：ZAP 扫描计划预览与确认结果（§二十三）。
    zap_scan_plan: dict[str, Any] | None = None
    zap_scan_job_id: int | None = None
    zap_scan_note: str | None = None
    # Web 智能体二轮：交互式编写的工作区快照（观测含遮罩截图，提案含执行结果）。
    web_agent_session_id: int | None = None
    web_goal: str | None = None
    web_step_budget: int = 20  # 与会话默认步数预算一致（SessionStartInput.step_budget 默认 20）
    web_proposed_steps: list[dict[str, Any]] = Field(default_factory=list)
    web_current_step: dict[str, Any] | None = None
    web_observation: dict[str, Any] | None = None
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
    security_strategy_keys: list[str] = Field(
        default_factory=list,
        description="安全意图选中的策略 strategy_key，只能取自已加载策略清单（GENERATE_SECURITY_TEST 时用）",
    )


class TestPlanDraft(BaseModel):
    """TestPlannerNode 产出：测试计划（不落库，前端展示 + 指导生成）。"""

    target: str = Field(..., description="被测目标摘要")
    strategies: list[str] = Field(default_factory=list, description="覆盖策略类别列表")
    focus: list[str] = Field(default_factory=list, description="重点关注场景")
    estimated_points: int = Field(default=1, ge=1, le=50, description="预计测试点数量")


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


# --------------------------------------------------------------------------- Web 智能体（Phase 2）

class WebDecideDraft(BaseModel):
    """WebDecideNode 产出：LLM 对当前页面的决策（结构化输出）。

    decision:
        - PROPOSE：提出下一步操作（step 非空），进入 web_step_review 暂停点。
        - OBSERVE：继续观察（不做操作），回到 web_decide。
        - DONE：目标达成，结束循环。
    step: WebStep 格式的操作提案（仅 decision=PROPOSE 时非空）。
    rationale: 决策理由（人工可读，不直接入 prompt）。
    """

    decision: Literal["PROPOSE", "OBSERVE", "DONE"]
    step: dict[str, Any] | None = None
    rationale: str | None = Field(None, max_length=500)
