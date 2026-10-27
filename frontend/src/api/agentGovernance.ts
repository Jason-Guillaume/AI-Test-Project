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
  version: number;
  created_at: string;
  updated_at: string;
}

export type AgentDefinitionInput = Omit<AgentDefinition, 'id' | 'key' | 'version' | 'created_at' | 'updated_at'>;
export type AgentDefinitionPatch = Partial<AgentDefinitionInput>;

export interface SkillDefinition {
  id: number;
  key: string;
  name: string;
  description: string;
  content: string;
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
  agents: () => api.get<AgentDefinition[]>('/agent-governance/agents'),
  createAgent: (body: AgentDefinitionInput) => api.post<AgentDefinition>('/agent-governance/agents', body),
  updateAgent: (id: number, body: AgentDefinitionPatch) => api.patch<AgentDefinition>(`/agent-governance/agents/${id}`, body),
  deleteAgent: (id: number) => api.delete<void>(`/agent-governance/agents/${id}`),
  agentVersions: (id: number) => api.get<DefinitionVersion[]>(`/agent-governance/agents/${id}/versions`),
  skills: () => api.get<SkillDefinition[]>('/agent-governance/skills'),
  createSkill: (body: SkillInput) => api.post<SkillDefinition>('/agent-governance/skills', body),
  updateSkill: (id: number, body: SkillPatch) => api.patch<SkillDefinition>(`/agent-governance/skills/${id}`, body),
  deleteSkill: (id: number) => api.delete<void>(`/agent-governance/skills/${id}`),
  skillVersions: (id: number) => api.get<DefinitionVersion[]>(`/agent-governance/skills/${id}/versions`),
  mcpServers: () => api.get<MCPServer[]>('/agent-governance/mcp-servers'),
  createMcpServer: (body: MCPServerInput) => api.post<MCPServer>('/agent-governance/mcp-servers', body),
  updateMcpServer: (id: number, body: MCPServerPatch) => api.patch<MCPServer>(`/agent-governance/mcp-servers/${id}`, body),
  deleteMcpServer: (id: number) => api.delete<void>(`/agent-governance/mcp-servers/${id}`),
  discoverMcpTools: (id: number) => api.post<MCPServer>(`/agent-governance/mcp-servers/${id}/discover`),
  approveMcpTools: (id: number, tool_names: string[]) => api.put<MCPServer>(`/agent-governance/mcp-servers/${id}/approved-tools`, { tool_names }),
};
