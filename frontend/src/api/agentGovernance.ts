import { api } from './client';

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

export const agentGovernanceApi = {
  workflows: () => api.get<WorkflowTemplate[]>('/agent-governance/workflows'),
  tools: () => api.get<GovernanceTool[]>('/agent-governance/tools'),
  updateTool: (key: string, body: GovernanceToolUpdate) => api.put<GovernanceTool>(`/agent-governance/tools/${encodeURIComponent(key)}`, body),
  restoreToolDefaults: (key: string) => api.post<GovernanceTool>(`/agent-governance/tools/${encodeURIComponent(key)}/restore-defaults`),
  agents: () => api.get<AgentDefinition[]>('/agent-governance/agents'),
  createAgent: (body: AgentDefinitionInput) => api.post<AgentDefinition>('/agent-governance/agents', body),
  updateAgent: (id: number, body: AgentDefinitionPatch) => api.patch<AgentDefinition>(`/agent-governance/agents/${id}`, body),
  deleteAgent: (id: number) => api.delete<void>(`/agent-governance/agents/${id}`),
  agentVersions: (id: number) => api.get<DefinitionVersion[]>(`/agent-governance/agents/${id}/versions`),
  restoreAgentVersion: (id: number, version: number) => api.post<AgentDefinition>(`/agent-governance/agents/${id}/versions/${version}/restore`),
  skills: () => api.get<SkillDefinition[]>('/agent-governance/skills'),
  createSkill: (body: SkillInput) => api.post<SkillDefinition>('/agent-governance/skills', body),
  importSkillZip: (file: File, name = '') => {
    const data = new FormData();
    data.append('file', file);
    data.append('name', name);
    return api.post<SkillDefinition>('/agent-governance/skills/import-zip', data);
  },
  updateSkill: (id: number, body: SkillPatch) => api.patch<SkillDefinition>(`/agent-governance/skills/${id}`, body),
  restoreSkillVersion: (id: number, version: number) => api.post<SkillDefinition>(`/agent-governance/skills/${id}/versions/${version}/restore`),
  skillUsage: (id: number) => api.get<SkillUsage>(`/agent-governance/skills/${id}/usage`),
  deleteSkill: (id: number) => api.delete<void>(`/agent-governance/skills/${id}`),
  skillVersions: (id: number) => api.get<DefinitionVersion[]>(`/agent-governance/skills/${id}/versions`),
  mcpServers: () => api.get<MCPServer[]>('/agent-governance/mcp-servers'),
  createMcpServer: (body: MCPServerInput) => api.post<MCPServer>('/agent-governance/mcp-servers', body),
  updateMcpServer: (id: number, body: MCPServerPatch) => api.patch<MCPServer>(`/agent-governance/mcp-servers/${id}`, body),
  deleteMcpServer: (id: number) => api.delete<void>(`/agent-governance/mcp-servers/${id}`),
  discoverMcpTools: (id: number) => api.post<MCPServer>(`/agent-governance/mcp-servers/${id}/discover`),
  approveMcpTools: (id: number, tool_names: string[]) => api.put<MCPServer>(`/agent-governance/mcp-servers/${id}/approved-tools`, { tool_names }),
};
