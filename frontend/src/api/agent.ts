// 接口测试 Agent 相关接口。
// 路由形态（挂载 /api/v1 下）：
//   POST /projects/{project_id}/agent/sessions
//   GET  /projects/{project_id}/agent/sessions
//   GET  /agent/sessions/{session_id}
//   POST /agent/sessions/{session_id}/messages
//   GET  /agent/sessions/{session_id}/workspace
//   DELETE /agent/sessions/{session_id}
//
// 鉴权（§33）：读 viewer+，写 member+，跨项目统一 404。
import { api } from './client';
import type {
  AgentSession,
  AgentSessionDetail,
  AgentTurnResponse,
  AgentWorkspace,
  SendMessageRequest,
} from '@/types';

export const agentApi = {
  // ---- 会话 CRUD ----
  createSession: (projectId: number, body?: { title?: string | null }) =>
    api.post<AgentSession>(`/projects/${projectId}/agent/sessions`, body ?? {}),

  listSessions: (projectId: number) =>
    api.get<AgentSession[]>(`/projects/${projectId}/agent/sessions`),

  getSessionDetail: (sessionId: number) =>
    api.get<AgentSessionDetail>(`/agent/sessions/${sessionId}`),

  deleteSession: (sessionId: number) =>
    api.delete<void>(`/agent/sessions/${sessionId}`),

  // ---- 消息推进 ----
  sendMessage: (sessionId: number, body: SendMessageRequest) =>
    api.post<AgentTurnResponse>(`/agent/sessions/${sessionId}/messages`, body),

  // ---- 工作区 ----
  getWorkspace: (sessionId: number) =>
    api.get<AgentWorkspace>(`/agent/sessions/${sessionId}/workspace`),
};

export type { SendMessageRequest };
