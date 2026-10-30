// 路由迁移回归：基线由原始静态审查提取，确保页面迁移没有丢失入口。
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const routes = JSON.parse(await readFile(new URL('../../docs/agent-cluster-refactor/frontend-refactor-validation/baseline-routes.json', import.meta.url), 'utf8'));
const app = await readFile(new URL('../src/app/App.tsx', import.meta.url), 'utf8');
const routeCount = [...app.matchAll(/<Route\b/g)].length;
const currentPaths = new Set([...app.matchAll(/\bpath=\"([^\"]+)\"/g)].map((match) => match[1]));

test('all original route declarations remain registered after relocation', () => {
  assert.equal(routeCount, routes.length);
  for (const item of routes) {
    if (!item.route.path) continue;
    const path = JSON.parse(item.route.path);
    assert.ok(currentPaths.has(path), `missing route: ${path}`);
  }
});
