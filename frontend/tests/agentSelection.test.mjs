import assert from 'node:assert/strict';
import { test } from 'node:test';
import { explicitSelection, toggleAllSelection } from '../src/pages/console/Agent/agentSelection.mjs';

test('显式选择拒绝零选和已失效资产，并保留合法子集', () => {
  assert.equal(explicitSelection([], [1, 2]), null);
  assert.deepEqual(explicitSelection([2, 2], [1, 2]), [2]);
  assert.equal(explicitSelection([3], [1, 2]), null);
});

test('全选控制只选择当前工作区资产，完整选择后可清空', () => {
  assert.deepEqual(toggleAllSelection([], [1, 2]), [1, 2]);
  assert.deepEqual(toggleAllSelection([1], [1, 2]), [1, 2]);
  assert.deepEqual(toggleAllSelection([1, 2], [1, 2]), []);
  assert.deepEqual(toggleAllSelection([99], []), []);
});
