// 统一任务 HTTP 契约；任务运行与业务 TestRun / Report 通过稳定资源引用关联。
import { api } from './client';

export interface TaskRun {
  id: number;
  task_id: number;
  run_number: number;
  status: string;
  stage: string;
  goal_snapshot: string;
  input_snapshot: Record<string, unknown>;
  current_plan_version: number;
  event_seq: number;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
}

export interface Task {
  id: number;
  project_id: number;
  created_by: number | null;
  title: string;
  goal: string;
  environment_id: number | null;
  input_case_ids: number[];
  status: string;
  archived: boolean;
  created_at: string;
  updated_at: string;
  latest_run: TaskRun | null;
}

export interface TaskPlan {
  id: number;
  task_run_id: number;
  version: number;
  status: string;
  plan_json: Record<string, unknown>;
  created_at: string;
  accepted_at: string | null;
}

export interface TaskAgentInstance {
  id: number;
  task_run_id: number;
  instance_key: string;
  role: string;
  display_name: string;
  status: string;
  model_config_id: number | null;
  config_snapshot: Record<string, unknown>;
  skills_json: string[];
  tool_allowlist_json: string[];
  created_at: string;
}

export interface TaskWorkItem {
  id: number;
  task_run_id: number;
  agent_instance_id: number | null;
  work_key: string;
  kind: string;
  sequence: number;
  status: string;
  output_json: Record<string, unknown> | null;
  attempt_count: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface TaskRunDetail {
  run: TaskRun;
  plans: TaskPlan[];
  agents: TaskAgentInstance[];
  work_items: TaskWorkItem[];
}

export interface TaskMessage {
  id: number;
  task_run_id: number;
  agent_instance_id: number;
  sender_type: string;
  sender_user_id: number | null;
  sender_instance_id: number | null;
  message_type: string;
  content: string;
  metadata_json: Record<string, unknown>;
  status: string;
  client_message_id: string;
  created_at: string;
  processed_at: string | null;
}

export interface TaskEvent {
  id: number;
  task_run_id: number;
  event_seq: number;
  event_type: string;
  actor_user_id: number | null;
  agent_instance_id: number | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface TaskResourceRef {
  id: number;
  task_run_id: number;
  agent_instance_id: number | null;
  direction: string;
  resource_type: string;
  resource_id: string;
  version: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface TaskCreateRequest {
  title?: string;
  goal: string;
  environment_id: number;
  case_ids: number[];
  request_key?: string;
}

export interface TaskMessageRequest {
  recipient_instance_id?: number;
  message_type: 'TEXT' | 'GOAL_UPDATE' | 'REQUIREMENT';
  content: string;
  client_message_id: string;
}

export interface TaskCommandRequest {
  command_type: 'APPROVE_PLAN' | 'PAUSE' | 'RESUME' | 'CANCEL' | 'RETRY';
  idempotency_key: string;
  work_item_id?: number;
}

export const tasksApi = {
  list: (params: { page?: number; page_size?: number; project_id?: number; status?: string } = {}) =>
    api.get<{ items: Task[]; total: number; page: number; page_size: number }>('/tasks', { params }),
  create: (projectId: number, body: TaskCreateRequest) =>
    api.post<Task>(`/projects/${projectId}/tasks`, body),
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
  sources: (resourceType: string, resourceId: string) =>
    api.get<TaskResourceRef[]>('/task-resources', { params: { resource_type: resourceType, resource_id: resourceId } }),
};
