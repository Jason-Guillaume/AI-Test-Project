// Web UI 管理客户端：统一使用平台 api 实例、JWT 和错误处理，不接收可执行脚本。
import { api } from '@/api/client';
import type {
  Paginated, TestRun, WebAgentObservation, WebAgentSession,
  WebAuthProfile, WebCase, WebCaseInput, WebEnvironment, WebExecution, WebPage, WebPageInput,
} from '@/types';

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

export const webUIApi = {
  /** 项目可见的环境元信息，支持服务端搜索。 */
  environments: (id: number, keyword: string) => api.get<Paginated<WebEnvironment>>(`/projects/${id}/web-environments`, { params: { keyword } }),
  /** 项目内页面对象。 */
  pages: (id: number) => api.get<Paginated<WebPage>>(`/projects/${id}/web-pages`),
  /** 原子保存页面元素。 */
  savePage: (id: number, body: WebPageInput, pageId?: number) => pageId
    ? api.put<WebPage>(`/projects/${id}/web-pages/${pageId}`, body)
    : api.post<WebPage>(`/projects/${id}/web-pages`, body),
  /** 删除页面对象。 */
  deletePage: (id: number) => api.delete<void>(`/web-pages/${id}`),
  /** 读取 Web 用例。 */
  cases: (id: number, page = 1) => api.get<Paginated<WebCase>>(`/projects/${id}/web-cases`, { params: { page, page_size: 20 } }),
  /** 按用例编号读取项目授权后的结构化 Web 资产。 */
  case: (id: number) => api.get<WebCase>(`/web-cases/${id}`),
  /** 保存结构化步骤，旧确认自动失效。 */
  saveCase: (id: number, body: WebCaseInput, caseId?: number) => caseId
    ? api.put<WebCase>(`/projects/${id}/web-cases/${caseId}`, body)
    : api.post<WebCase>(`/projects/${id}/web-cases`, body),
  /** 删除测试资产。 */
  deleteCase: (id: number) => api.delete<void>(`/web-cases/${id}`),
  /** 人工按钮确认当前版本。 */
  confirm: (id: number, revision: number) => api.post<WebCase>(`/web-cases/${id}/confirm`, { revision }),
  /** 单例调试仍创建原有 TestRun，超时覆盖标准客户端 30 秒。 */
  debug: (id: number, environment_id: number) => api.post<TestRun>(`/web-cases/${id}/debug`, { environment_id }, { timeout: 660000 }),
  /** 查询脱敏认证配置列表。 */
  auth: (id: number, page = 1, pageSize = 50) => api.get<Paginated<WebAuthProfile>>(`/projects/${id}/web-auth-profiles`, { params: { page, page_size: pageSize } }),
  /** 凭据只写，整体替换。 */
  saveAuth: (id: number, body: unknown, authId?: number) => authId
    ? api.put<WebAuthProfile>(`/projects/${id}/web-auth-profiles/${authId}`, body)
    : api.post<WebAuthProfile>(`/projects/${id}/web-auth-profiles`, body),
  /** 撤销认证配置。 */
  deleteAuth: (id: number) => api.delete<void>(`/web-auth-profiles/${id}`),
  /** 原有执行记录的 Web 视图。 */
  history: (id: number, page: number) => api.get<Paginated<WebExecution>>(`/projects/${id}/web-executions`, { params: { page, page_size: 20 } }),
  /** 下载附件时沿用 JWT，令牌不放 URL。 */
  artifact: (id: string) => api.get<Blob>(`/web-artifacts/${id}`, { responseType: 'blob' }),
  /** 读取脱敏动作 Trace，不上传到外部网站。 */
  trace: (id: string) => api.get<{ events: Record<string, unknown>[] }>(`/web-artifacts/${id}/events`),
  /** 复用平台默认模型，仅生成未确认草稿。 */
  generate: (id: number, body: { instruction: string; flow_id?: number; page_object_ids: number[] }) => api.post<WebCase>(`/projects/${id}/web-agent/draft`, body, { timeout: 120000 }),
  /** 显式选择业务动作的 WEB 通道。 */
  bind: (actionId: number, web_case_id: number) => api.post(`/business-actions/${actionId}/web-binding`, { web_case_id }),
};

// Web UI 智能体二期：受控浏览器会话、脱敏观测与提升。
// 会话只绑定平台环境（TargetPolicy 出站白名单在会话打开时生效）；
// 观测返回脱敏语义树与遮罩截图，不返回原始 DOM；提升只产出未确认草稿。
export const webAgentApi = {
  /** 列出项目内的受控浏览器会话。 */
  sessions: (id: number, page = 1, pageSize = 50) => api.get<Paginated<WebAgentSession>>(`/projects/${id}/web-agent/sessions`, { params: { page, page_size: pageSize } }),
  /** 启动受控会话：选环境、登录态与目标页后打开浏览器。 */
  start: (id: number, body: WebAgentStartBody) => api.post<WebAgentSession>(`/projects/${id}/web-agent/sessions`, body, { timeout: 120000 }),
  /** 读取会话元信息与当前步数。 */
  detail: (id: number) => api.get<WebAgentSession>(`/web-agent/sessions/${id}`),
  /** 观察当前页面：脱敏语义树与遮罩截图。 */
  observe: (id: number) => api.post<WebAgentObservation>(`/web-agent/sessions/${id}/observe`, {}, { timeout: 66000 }),
  /** 关闭会话并释放浏览器资源。 */
  close: (id: number) => api.post<WebAgentSession>(`/web-agent/sessions/${id}/close`),
  /** 提升为正式 Web 用例：产物始终未确认，正式执行仍需人工确认。 */
  promote: (id: number, body: WebAgentPromoteBody) => api.post<WebCase>(`/web-agent/sessions/${id}/promote`, body),
};
