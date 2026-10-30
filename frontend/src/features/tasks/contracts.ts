// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
import type { AgentMessage, AgentSession, AgentTurnResponse } from '@/features/agent/contracts';
import type { WebAgentSession } from '@/features/browser-authoring/contracts';


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
  task_mode: 'TEST_EXECUTION' | 'WEB_AUTHORING';
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
  retryable: boolean;
  retry_block_reason: string | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface TaskToolInvocation {
  id: number;
  work_item_id: number;
  agent_instance_id: number | null;
  tool_name: string;
  status: string;
  error_code: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface TaskRunDetail {
  run: TaskRun;
  plans: TaskPlan[];
  agents: TaskAgentInstance[];
  work_items: TaskWorkItem[];
  tool_invocations: TaskToolInvocation[];
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
  display_name?: string | null;
  task_id?: number | null;
  task_title?: string | null;
  run_number?: number | null;
}

export interface TaskCreateRequest {
  title?: string;
  goal: string;
  agent_definition_id?: number;
  environment_id: number;
  case_ids: number[];
  task_mode?: 'TEST_EXECUTION' | 'WEB_AUTHORING';
  web_authoring?: { auth_profile_id?: number; target_page_path?: string; step_budget?: number };
  security_assessment?: { api_ids?: number[]; api_id?: number; web_session_id?: number; strategy_ids: number[] };
  request_key?: string;
}

export interface AvailableTaskAgent {
  id: number;
  name: string;
  description: string;
  workflow_template: string;
  version: number;
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
  security_risk_confirmed?: boolean;
}

export interface TaskWebAuthoringWorkspace {
  task_id: number;
  project_id: number;
  run: TaskRun;
  agent: { id: number; role: string; display_name: string; model_config_id: number | null; status: string };
  agent_session: AgentSession;
  web_session: WebAgentSession;
  messages: AgentMessage[];
  workspace: AgentTurnResponse['workspace'];
}
