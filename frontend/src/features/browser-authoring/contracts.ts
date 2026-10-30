// browser-authoring 领域类型合同；仅暴露当前模块稳定使用的请求、响应与查询类型。
import type { WebOperation, WebLocator, WebStep } from '@/features/web-testing/contracts';


// Web UI 智能体二期：受控浏览器会话、脱敏页面观测、步骤提案与提升契约。
export type WebAgentSessionStatus = 'ACTIVE' | 'CLOSED' | 'FAILED';

export interface WebAgentSession {
  id: number; // 会话 ID，也是进程内浏览器句柄的键
  project_id: number; // 所属项目
  environment_id: number; // 执行环境
  auth_profile_id: number | null; // 加密登录态配置
  base_url: string; // 环境基础地址
  target_page_path: string; // 目标页相对路径
  status: WebAgentSessionStatus; // 会话状态
  status_reason?: string | null; // 句柄不可用时提示重新启动
  step_budget: number; // 智能体步数预算上限
  step_count: number; // 已执行步数
  created_at: string | null; // 创建时间
}

/** 页面观测结果：只有脱敏后的语义树与遮罩截图，不含原始 DOM 或凭据。 */
export interface WebAgentObservation {
  url: string; // 当前页面地址
  title: string; // 页面标题
  accessibility_tree: string; // 已脱敏的 accessibility tree
  screenshot_b64: string; // 已遮罩输入的 base64 截图
}

/** 智能体提案 / 已执行步骤：提案与执行结果一起保留，供人工采纳。 */
export interface WebAgentStepProposal {
  name: string; // 步骤名称
  operation: WebOperation; // 白名单操作
  locator?: WebLocator | null; // 定位器
  value?: string | null; // 输入或导航值
  assertion?: WebStep['assertion']; // 断言来源
  expected?: string | null; // 断言期望值
  status: string; // PROPOSED / ACCEPTED / FAILED
  result?: Record<string, unknown> | null; // 执行结果摘要（已脱敏）
}

export type WebDecideDecision = 'PROPOSE' | 'OBSERVE' | 'DONE';

/** 启动受控浏览器会话的入参：只选环境、登录态与目标页。 */
export interface WebAgentStartBody {
  environment_id: number;
  auth_profile_id?: number | null;
  target_page_path?: string;
  step_budget?: number;
}

/** 把沙箱会话提升为正式用例的入参：提升只产出未确认草稿。
 *  步骤不由前端提交——后端只取会话内已人工确认的 ACCEPTED 步骤，
 *  前端传来的步骤会被严格模型拒绝（extra=forbid）。 */
export interface WebAgentPromoteBody {
  name?: string;
  description?: string;
  timeout_ms?: number;
  total_timeout_ms?: number;
}

