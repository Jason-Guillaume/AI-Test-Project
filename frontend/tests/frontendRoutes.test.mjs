// 路由迁移回归：基线由原始静态审查提取，确保页面迁移没有丢失入口。
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const routes = JSON.parse(await readFile(new URL('../../docs/agent-cluster-refactor/frontend-refactor-validation/baseline-routes.json', import.meta.url), 'utf8'));
const app = await readFile(new URL('../src/app/App.tsx', import.meta.url), 'utf8');
const routeCount = [...app.matchAll(/<Route\b/g)].length;
const currentPaths = new Set([...app.matchAll(/\bpath=\"([^\"]+)\"/g)].map((match) => match[1]));

test('all original route declarations remain registered after relocation and new task, ASR and model-center pages are additive', () => {
  assert.equal(routeCount, routes.length + 14);
  for (const item of routes) {
    if (!item.route.path) continue;
    const path = JSON.parse(item.route.path);
    assert.ok(currentPaths.has(path), `missing route: ${path}`);
  }
  assert.ok(currentPaths.has('tasks/inbox'));
  assert.ok(currentPaths.has('tasks/templates'));
  assert.ok(currentPaths.has('asr/audio'));
  assert.ok(currentPaths.has('asr/connections'));
  assert.ok(currentPaths.has('asr/jobs'));
  assert.ok(currentPaths.has('asr/jobs/:jobId'));
  assert.ok(currentPaths.has('asr/comparisons'));
  assert.ok(currentPaths.has('asr/comparisons/:comparisonId'));
  assert.ok(currentPaths.has('asr/experiments'));
  assert.ok(currentPaths.has('asr/runs/:runId'));
  assert.ok(currentPaths.has('asr/runs/:runId/listen'));
  assert.ok(currentPaths.has('asr/funasr'));
  assert.ok(currentPaths.has('model-center'));
  assert.ok(currentPaths.has('knowledge'));
});
