import type { AgentDefinition } from '@/features/agent-governance/contracts';
export const MODULE_LABELS: Record<string, string>;
export function agentModule(agent: AgentDefinition): string;
export function fixedModel(agent: AgentDefinition): number | null;
export function filterAgentHierarchy(agents: AgentDefinition[], module?: string, model?: string): {agent: AgentDefinition; children: AgentDefinition[]; matches: boolean}[];

export const TEST_TYPE_LABELS: Record<string, string>;
export function agentTestTypes(agent: AgentDefinition): string[];
export function matchesAgent(agent: AgentDefinition, type?: string, model?: string): boolean;
