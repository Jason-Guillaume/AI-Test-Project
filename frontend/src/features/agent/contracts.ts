// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
import type { WebAgentObservation } from '@/features/browser-authoring/contracts';


// ---- 接口测试 Agent ----

export type AgentStage =
  | 'UNDERSTANDING'
  | 'CONTEXT_LOADING'
  | 'PLANNING'
  | 'TEST_POINT_REVIEW'
  | 'TEST_POINT_GENERATED'
  | 'TEST_CASE_REVIEW'
  | 'READY_TO_EXECUTE'
  | 'EXECUTING'
  | 'ANALYZING'
  // Phase 2：报告闭环与飞书通知阶段
  | 'REPORT_GENERATING'
  | 'REPORT_REVIEW'
  | 'NOTIFYING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CLARIFY'
  // Web UI 智能体二期：步骤提案待人工确认的暂停点
  | 'WEB_STEP_REVIEW';

export type AgentAction =
  | 'confirm_points'
  | 'confirm_cases'
  | 'execute'
  | 'analyze'
  | 'regenerate_points'
  | 'regenerate_cases'
  | 'query'
  | 'continue'
  // Phase 2：报告 review 暂停点的两个出口
  | 'confirm_report'
  | 'skip_notification'
  // Web UI 智能体二期：沙箱步骤 review 暂停点的两个出口
  | 'confirm_web_step'
  | 'reject_web_step';

export type AgentMessageRole = 'USER' | 'ASSISTANT' | 'SYSTEM';

export type AgentMessageType =
  | 'TEXT'
  | 'TEST_PLAN'
  | 'TEST_POINTS'
  | 'TEST_CASES'
  | 'EXECUTION'
  | 'RESULT'
  | 'CLARIFY'
  // Phase 2：报告与通知产物消息（metadata_json 为脱敏 brief）
  | 'REPORT'
  | 'NOTIFICATION'
  // Web UI 智能体二期：步骤提案留痕与页面观测留痕（metadata_json 已脱敏）
  | 'WEB_AGENT_STEP'
  | 'WEB_OBSERVATION';

export interface AgentSession {
  id: number;
  project_id: number;
  user_id: number | null;
  title: string | null;
  status: string;
  current_stage: string;
  created_at: string;
  updated_at: string;
}

export interface AgentMessage {
  id: number;
  session_id: number;
  role: AgentMessageRole;
  message_type: AgentMessageType;
  content: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

export interface AgentSessionDetail {
  session: AgentSession;
  messages: AgentMessage[];
}

export interface SendMessageRequest {
  content?: string | null;
  action?: AgentAction | null;
  point_ids?: number[] | null;
  case_ids?: number[] | null;
  environment_id?: number | null;
  /** Phase 2：飞书通知渠道ID（confirm_report 时可选，缺省取项目首个启用渠道） */
  channel_id?: number | null;
  /** Web UI 智能体二期：绑定的受控浏览器会话 ID（交互式编写时必填） */
  web_session_id?: number | null;
}

export interface AgentWorkspace {
  stage: AgentStage;
  intent: string | null;
  test_plan: Record<string, unknown> | null;
  test_points: Array<Record<string, unknown>>;
  test_cases: Array<Record<string, unknown>>;
  test_run_id: number | null;
  execution_result: Record<string, unknown> | null;
  analysis: Record<string, unknown> | null;
  /** Phase 2：已生成报告的ID */
  report_id: number | null;
  /** Phase 2：脱敏报告摘要（report_no/风险/通过率/AI 总结） */
  report_brief: Record<string, unknown> | null;
  /** Phase 2：飞书通知结果（status/error_message/skipped/channel_name） */
  notification_brief: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  suggested_actions: string[];
  /** Web UI 智能体二期：当前绑定的受控浏览器会话 */
  web_agent_session_id: number | null;
  /** Web UI 智能体二期：用户自然语言目标 */
  web_goal: string | null;
  /** Web UI 智能体二期：步数预算上限 */
  web_step_budget: number;
  /** Web UI 智能体二期：已执行的步骤（含执行结果） */
  web_proposed_steps: Array<Record<string, unknown>>;
  /** Web UI 智能体二期：当前待人工确认的提案 */
  web_current_step: Record<string, unknown> | null;
  /** Web UI 智能体二期：最近一次脱敏页面观测 */
  web_observation: WebAgentObservation | null;
}

export interface AgentTurnResponse {
  session: AgentSession;
  messages: AgentMessage[];
  workspace: AgentWorkspace;
}
