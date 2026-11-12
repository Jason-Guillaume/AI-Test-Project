import test from 'node:test';
import assert from 'node:assert/strict';
import { agentModule, filterAgentHierarchy, matchesAgent } from '../src/pages/admin/AgentGovernance/agentHierarchy.mjs';
const agent = (id, tools = [], children = [], model = null) => ({ id, tool_keys: tools, child_agent_ids: children, workflow_template: 'case_generation', model_config_id: model, settings_json: { model_binding: model ? 'agent' : 'task_or_global' } });
const main = agent(1, [], [2,3]);
const api = agent(2, ['case_generation.generate_api'], [], 10);
const asr = agent(3, ['case_generation.generate_asr']);
test('module filtering preserves parent path and selected child', () => {
  const groups = filterAgentHierarchy([main,api,asr], 'asr');
  assert.equal(groups.length, 1);
  assert.equal(groups[0].agent.id, 1);
  assert.deepEqual(groups[0].children.map((item) => item.id), [3]);
  assert.equal(agentModule(api), 'api');
});
test('model filtering finds fixed child and preserves inheritance label', () => {
  assert.deepEqual(filterAgentHierarchy([main,api,asr], undefined, '10')[0].children.map((item) => item.id), [2]);
  assert.deepEqual(filterAgentHierarchy([main,api,asr], 'asr', '10'), []);
  assert.deepEqual(filterAgentHierarchy([main,api,asr], 'asr', 'inherit')[0].children.map((item) => item.id), [3]);
});
test('matching parent does not expose nonmatching children; cards use direct matches', () => {
  assert.deepEqual(filterAgentHierarchy([main, api, asr], 'api')[0].children.map((item) => item.id), [2]);
  assert.equal(matchesAgent(main, 'api'), true);
  assert.equal(matchesAgent(asr, 'api'), false);
});
