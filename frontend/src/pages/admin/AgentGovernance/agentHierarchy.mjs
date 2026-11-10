export const TEST_TYPE_LABELS = { api: '接口测试', web: 'Web UI 测试', security: '安全测试', asr: '语音识别测试', ai: 'AI 质量测试', general: '通用' };
export const MODULE_LABELS = TEST_TYPE_LABELS;
const WORKFLOW_TYPES = { api_test: 'api', web_ui: 'web', security: 'security', asr_evaluation: 'asr', ai_evaluation: 'ai' };
export function agentTestTypes(agent) {
  if (Array.isArray(agent.test_types) && agent.test_types.length) return agent.test_types;
  const tool = (agent.tool_keys ?? []).find((key) => key.startsWith('case_generation.generate_'));
  if (tool) return [tool.slice('case_generation.generate_'.length)];
  if (agent.workflow_template === 'case_generation') return ['api', 'web', 'security', 'asr', 'ai'];
  return [WORKFLOW_TYPES[agent.workflow_template] ?? 'general'];
}
export function agentModule(agent) { return agentTestTypes(agent)[0]; }
export function fixedModel(agent) { return agent.settings_json?.model_binding === 'agent' || (!agent.settings_json?.model_binding && agent.model_config_id != null) ? agent.model_config_id : null; }
export function matchesAgent(agent, type, model) { return (!type || agentTestTypes(agent).includes(type)) && (!model || (model === 'inherit' ? fixedModel(agent) == null : fixedModel(agent) === Number(model))); }
export function filterAgentHierarchy(agents, type, model) {
  const children = new Set(agents.flatMap((agent) => agent.child_agent_ids ?? []));
  return agents.filter((agent) => !children.has(agent.id)).map((agent) => {
    const nodes = (agent.child_agent_ids ?? []).map((id) => agents.find((item) => item.id === id)).filter(Boolean).filter((child) => matchesAgent(child, type, model));
    return { agent, children: nodes, matches: matchesAgent(agent, type, model) };
  }).filter((group) => group.matches || group.children.length);
}
