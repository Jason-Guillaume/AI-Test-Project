// 统一任务 HTTP 契约；任务运行与业务 TestRun / Report 通过稳定资源引用关联。
import { api } from '@/shared/api/client';
import type { AgentTurnResponse } from '@/features/agent/contracts';

import type { Task, TaskRunDetail, TaskMessage, TaskEvent, TaskResourceRef, TaskCreateRequest, AvailableTaskAgent, TaskMessageRequest, TaskCommandRequest, TaskWebAuthoringWorkspace } from '../contracts';






export const tasksApi = {
  list: (params: { page?: number; page_size?: number; project_id?: number; status?: string } = {}) =>
    api.get<{ items: Task[]; total: number; page: number; page_size: number }>('/tasks', { params }),
  create: (projectId: number, body: TaskCreateRequest) =>
    api.post<Task>(`/projects/${projectId}/tasks`, body),
  availableAgents: (projectId: number, params: { target_type: 'API' | 'WEB' | 'SECURITY' }) =>
    api.get<AvailableTaskAgent[]>(`/projects/${projectId}/available-agents`, { params }),
  get: (taskId: number) => api.get<Task>(`/tasks/${taskId}`),
  getRun: (runId: number) => api.get<TaskRunDetail>(`/task-runs/${runId}`),
  messages: (runId: number) => api.get<TaskMessage[]>(`/task-runs/${runId}/messages`),
  sendMessage: (runId: number, body: TaskMessageRequest) =>
    api.post<{ message: TaskMessage; created_run_id: number | null }>(`/task-runs/${runId}/messages`, body),
  command: (runId: number, body: TaskCommandRequest) =>
    api.post<{ id: number; status: string; response_json: Record<string, unknown> }>(`/task-runs/${runId}/commands`, body),
  events: (runId: number, afterSeq = 0) =>
    api.get<TaskEvent[]>(`/task-runs/${runId}/events`, { params: { after_seq: afterSeq } }),
  resources: (runId: number) => api.get<TaskResourceRef[]>(`/task-runs/${runId}/resources`),
  webAuthoring: (runId: number) => api.get<TaskWebAuthoringWorkspace>(`/task-runs/${runId}/web-authoring`),
  restartWebAuthoring: (runId: number) => api.post<TaskWebAuthoringWorkspace>(`/task-runs/${runId}/web-authoring/restart`, {}),
  closeWebAuthoring: (runId: number) => api.post<TaskWebAuthoringWorkspace>(`/task-runs/${runId}/web-authoring/close`, {}),
  webAuthoringTurn: (runId: number, body: { request_key: string; content?: string; action?: 'confirm_web_step' | 'reject_web_step'; web_session_id?: number }) =>
    api.post<AgentTurnResponse>(`/task-runs/${runId}/web-authoring/messages`, body, { timeout: 120000 }),
  promoteWebAuthoring: (runId: number, body: { name?: string; description?: string }) =>
    api.post<{ id: number; name: string; project_id: number; confirmed: boolean }>(`/task-runs/${runId}/web-authoring/draft`, body),
  sources: (resourceType: string, resourceId: string) =>
    api.get<TaskResourceRef[]>('/task-resources', { params: { resource_type: resourceType, resource_id: resourceId } }),
};
