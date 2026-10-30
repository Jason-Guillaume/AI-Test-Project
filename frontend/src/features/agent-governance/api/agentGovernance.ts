import { api } from '@/shared/api/client';
import type { AgentDefinition, AgentDefinitionInput, AgentDefinitionPatch, SkillDefinition, SkillInput, SkillPatch, MCPServer, MCPServerInput, MCPServerPatch, GovernanceTool, GovernanceToolUpdate, SkillUsage, WorkflowTemplate, DefinitionVersion } from '../contracts';




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
