// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。

export interface AgentDefinition {
  id: number;
  key: string;
  name: string;
  description: string;
  workflow_template: string;
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
