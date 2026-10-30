// 浏览器创作受控会话接口；观测与提升仍受服务端会话授权约束。
import { api } from '@/shared/api/client';
import type { Paginated } from '@/shared/api/contracts';
import type { WebCase } from '@/features/web-testing/contracts';
import type { WebAgentObservation, WebAgentSession, WebAgentStartBody, WebAgentPromoteBody } from './contracts';

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
