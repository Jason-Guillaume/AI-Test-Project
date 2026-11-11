// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。

export interface AgentDefinition {
  id: number;
  key: string;
  name: string;
  description: string;
  workflow_template: string;
  test_types: string[];
  purpose: string;
  instruction: string;
  model_config_id: number | null;
  skill_keys: string[];
  tool_keys: string[];
  child_agent_ids: number[];
  is_enabled: boolean;
  settings_json: AgentRuntimeSettings;
  triggers_json: AgentTrigger[];
  version: number;
  created_at: string;
  updated_at: string;
}

export interface AgentRuntimeSettings {
  model_binding: 'task_or_global' | 'agent';
  max_loop_count: number;
  timeout_seconds: number;
  network_search_enabled: boolean;
  interactive_shell_enabled: boolean;
  close_step_prompt: string;
  close_step_max_loops: number;
  close_task_timeout_prompt: string;
  close_task_timeout_max_loops: number;
  runtime_variables: { name: string; value: string }[];
}

export type AgentTrigger = {
  id: string;
  event: 'schedule' | 'finding.discovered' | 'objective.achieved' | 'task.timeout' | 'tool.call' | 'task.created';
  enabled: boolean;
  message: string;
  schedule: string;
  tool_keys: string[];
  queue_policy: 'serial' | 'parallel';
  coalesce_by: 'task' | 'all' | 'none';
  max_concurrency: number;
};

export type AgentDefinitionInput = Omit<AgentDefinition, 'id' | 'key' | 'version' | 'created_at' | 'updated_at'>;

export interface AgentRuntimeOverview {
  metric_definition_version: string;
  window: { from: string; to: string; project_id: number | null };
  data_watermark: { task_runs: string | null; model_calls: string | null; runtime_events: string | null };
  summary: {
    task_runs: number; successful_runs: number; partial_runs: number; failed_runs: number;
    cancelled_runs: number; terminal_runs: number; reconciliation_required_runs: number;
    superseded_runs: number; nonterminal_runs: number;
    success_rate: number | null; partial_completion_rate: number | null;
    failure_rate: number | null; cancellation_rate: number | null; execution_success_rate: number | null;
    average_duration_ms: number | null; p95_duration_ms: number | null;
    duration_sample_count: number; retried_work_items: number; started_work_items: number; work_items: number; retry_rate: number | null;
    subagent_failed_work_items: number; subagent_terminal_work_items: number;
    subagent_reconciliation_required_work_items: number; subagent_failure_rate: number | null;
    subagent_runtime_events: number; subagent_runtime_failures: number;
    subagent_failed_instances: number; subagent_terminal_instances: number;
    model_calls: number; model_success_rate: number | null; model_failures: number; model_tokens: number;
    known_usage_calls: number; unknown_usage_calls: number; cost_amount: number | null;
    cost_currency: string | null; cost_by_currency: { currency: string | null; amount: number; calls: number }[];
    priced_model_calls: number; unpriced_model_calls: number; durable_tool_invocations: number;
    durable_tool_success_rate: number | null; traced_tool_success_rate: number | null; traced_tool_calls: number; knowledge_retrievals: number;
    context_assemblies: number; durable_tool_terminal_invocations: number;
    skill_loads: number; skill_load_failures: number; skill_load_success_rate: number | null;
    manual_reviewed_drafts: number; manual_rejection_rate: number | null; manual_edit_rate: number | null;
  };
  model_statuses: Record<string, number>;
  run_statuses: Record<string, number>;
  models: { model_config_id: number | null; model_name: string; model_revision: string | null; cost_currency: string | null; calls: number; succeeded: number; failed: number; tokens: number; cost: number | null; avg_latency_ms: number | null }[];
  agents_by_revision: { agent_definition_id: number | null; agent_name: string; revision_id: number | null; cost_currency: string | null; calls: number; succeeded: number; failed: number; tokens: number; cost: number | null; avg_latency_ms: number | null }[];
  tools: { tool_key: string; calls: number; succeeded: number; failed: number; avg_latency_ms: number | null }[];
  skills: { skill_key: string; skill_version: number | null; loads: number; succeeded: number; failed: number; avg_latency_ms: number | null }[];
  anomalies: { kind: string; severity: string; current: number; baseline: number; current_samples: number; baseline_samples: number; model_name?: string; model_revision?: string | null; tool_key?: string; skill_key?: string; skill_version?: number | null; agent_name?: string; revision_id?: number; currency?: string | null }[];
  manual_feedback: { reviewed_drafts: number; accepted_drafts: number; rejected_drafts: number; edited_reviewed_drafts: number; rejection_rate: number | null; edit_rate: number | null };
  definitions: Record<string, string>;
}

export type AgentDefinitionPatch = Partial<AgentDefinitionInput>;

export interface SkillDefinition {
  id: number;
  key: string;
  name: string;
  description: string;
  content: string;
  files_json: Record<string, string>;
  mcp_tool_keys_json: string[];
  is_enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export type SkillInput = Omit<SkillDefinition, 'id' | 'key' | 'version' | 'created_at' | 'updated_at'>;

export type SkillPatch = Partial<SkillInput>;

export interface MCPDiscoveredTool {
  name: string;
  description: string;
  inputSchema?: Record<string, unknown>;
  annotations?: {
    readOnlyHint?: boolean;
    destructiveHint?: boolean;
    idempotentHint?: boolean;
    openWorldHint?: boolean;
  };
}

export interface MCPServer {
  id: number;
  name: string;
  endpoint: string;
  auth_type: 'none' | 'bearer';
  has_auth: boolean;
  is_enabled: boolean;
  connection_status: 'unknown' | 'connected' | 'error';
  discovered_tools_json: MCPDiscoveredTool[];
  approved_tools_json: string[];
  last_checked_at: string | null;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export type MCPServerInput = {
  name: string;
  endpoint: string;
  auth_type: 'none' | 'bearer';
  auth_token?: string;
  is_enabled: boolean;
};

export type MCPServerPatch = Partial<MCPServerInput>;

export interface GovernanceTool {
  key: string;
  name: string;
  category: string;
  risk: string;
  description: string;
  parameters: GovernanceToolParameter[];
  runtime_details: GovernanceToolRuntimeDetails;
  parameter_overrides_json: Record<string, { description?: string; default?: string }>;
  is_enabled: boolean;
  agent_ids: number[];
}

export interface GovernanceToolRuntimeDetails {
  status: 'active' | 'catalog_only';
  status_label: string;
  runtime_name: string | null;
  runtime_role: string;
  input_context: { name: string; source: string; description: string; type?: string; required?: boolean }[];
  output: string;
  constraints: string[];
  audit: string;
  executor_registered?: boolean;
  handler_registered?: boolean;
  catalog_status?: string | null;
  allowed_channels?: string[];
}

export interface GovernanceToolParameter {
  name: string;
  type: string;
  required: boolean;
  description: string;
  default?: string;
}

export interface GovernanceToolUpdate {
  description: string;
  agent_ids: number[];
  parameter_overrides_json: Record<string, { description?: string; default?: string }>;
  is_enabled: boolean;
}

export interface SkillUsage {
  total_loads: number;
  task_count: number;
  last_used_at: string | null;
  agents: { id: number; name: string; loads: number }[];
  recent_tasks: { task_id: number; title: string; run_number: number; used_at: string }[];
}

export interface WorkflowTemplate {
  key: string;
  label: string;
  description: string;
}

export interface DefinitionVersion {
  version: number;
  snapshot_json: Record<string, unknown>;
  created_at: string;
}
