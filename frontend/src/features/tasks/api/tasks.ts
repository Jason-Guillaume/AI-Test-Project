// 统一任务 HTTP 契约；任务运行与业务 TestRun / Report 通过稳定资源引用关联。
import { api } from '@/shared/api/client';
import type { AgentTurnResponse } from '@/features/agent/contracts';

import type { Task, TaskRunDetail, TaskMessage, TaskEvent, TaskTracePage, TaskResourceRef, TaskCreateRequest, AvailableTaskAgent, TaskMessageRequest, TaskCommandRequest, TaskWebAuthoringWorkspace, TaskTemplate, TaskInboxResponse, TaskSummary } from '../contracts';






export const tasksApi = {
  list: (params: { page?: number; page_size?: number; project_id?: number; status?: string } = {}) =>
    api.get<{ items: Task[]; total: number; page: number; page_size: number }>('/tasks', { params }),
  create: (projectId: number, body: TaskCreateRequest) =>
    api.post<Task>(`/projects/${projectId}/tasks`, body),
  verifyBug: (bugId: number, body: { source_case_execution_id: number; environment_id: number; request_key: string }) =>
    api.post<Task>(`/bugs/${bugId}/verification-tasks`, body),
  inbox: (params: { page?: number; page_size?: number; project_id?: number; category?: string } = {}) =>
    api.get<TaskInboxResponse>('/tasks/inbox', { params }),
  summary: () => api.get<TaskSummary>('/tasks/summary'),
  templates: (projectId: number, params: { keyword?: string; include_inactive?: boolean } = {}) =>
    api.get<TaskTemplate[]>(`/projects/${projectId}/task-templates`, { params }),
  getTemplate: (id: number) => api.get<TaskTemplate>(`/task-templates/${id}`),
  createTemplate: (projectId: number, body: { name: string; description: string; config: TaskTemplate['config']; is_active?: boolean }) =>
    api.post<TaskTemplate>(`/projects/${projectId}/task-templates`, body),
  updateTemplate: (id: number, body: { expected_version: number; name: string; description: string; config: TaskTemplate['config']; is_active?: boolean }) =>
    api.put<TaskTemplate>(`/task-templates/${id}`, body),
  setTemplateActive: (id: number, expected_version: number, is_active: boolean) =>
    api.patch<TaskTemplate>(`/task-templates/${id}/status`, { expected_version, is_active }),
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
  trace: (runId: number, cursor?: string | null) =>
    api.get<TaskTracePage>(`/task-runs/${runId}/trace`, { params: cursor ? { cursor } : {} }),
  replayTrace: (runId: number) =>
    api.post<{ registered: number; requeued: number }>(`/task-runs/${runId}/trace/replay`, {}),
  resources: (runId: number) => api.get<TaskResourceRef[]>(`/task-runs/${runId}/resources`),
  webAuthoring: (runId: number) => api.get<TaskWebAuthoringWorkspace>(`/task-runs/${runId}/web-authoring`),
  restartWebAuthoring: (runId: number) => api.post<TaskWebAuthoringWorkspace>(`/task-runs/${runId}/web-authoring/restart`, {}),
  closeWebAuthoring: (runId: number) => api.post<TaskWebAuthoringWorkspace>(`/task-runs/${runId}/web-authoring/close`, {}),
  webAuthoringTurn: (runId: number, body: { request_key: string; content?: string; action?: 'confirm_web_step' | 'reject_web_step'; web_session_id?: number }) =>
    api.post<AgentTurnResponse>(`/task-runs/${runId}/web-authoring/messages`, body, { timeout: 120000 }),
  promoteWebAuthoring: (runId: number, body: { name?: string; description?: string }) =>
    api.post<{ id: number; name: string; project_id: number; confirmed: boolean }>(`/task-runs/${runId}/web-authoring/draft`, body),
  sources: (resourceType: string, resourceId: string, projectId?: number) =>
    api.get<TaskResourceRef[]>('/task-resources', { params: { resource_type: resourceType, resource_id: resourceId, project_id: projectId } }),
};
