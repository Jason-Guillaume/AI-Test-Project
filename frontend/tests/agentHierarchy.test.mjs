import test from 'node:test';
import assert from 'node:assert/strict';
import { agentModule, filterAgentHierarchy, fixedModel, matchesAgent } from '../src/pages/admin/AgentGovernance/agentHierarchy.mjs';
const agent = (id, tools = [], children = [], model = null) => ({ id, tool_keys: tools, child_agent_ids: children, workflow_template: 'case_generation', model_config_id: model, settings_json: { model_binding: model ? 'agent' : 'task_or_global' } });
const main = agent(1, [], [2,3]);
const api = agent(2, ['case_generation.generate_api'], [], 10);
const asr = agent(3, ['case_generation.generate_asr']);
test('searching a child retains all parent paths and their inherited model rules', () => {
  const otherParent = { ...main, id: 4, name: '第二组' };
  const child = { ...asr, name: '退款子节点', settings_json: {}, model_config_id: 9 };
  const groups = filterAgentHierarchy([main, api, child, otherParent], undefined, undefined, (row) => row.id === 3);
  assert.deepEqual(groups.map((group) => [group.agent.id, group.matches, group.children.map((row) => row.id)]),
    [[1, false, [3]], [4, false, [3]]]);
  assert.equal(fixedModel(child, main), null);
  assert.equal(fixedModel(child, { ...main, workflow_template: 'api_test' }), 9);
});
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
