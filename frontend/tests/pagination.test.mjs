import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/api/pagination.ts', import.meta.url), 'utf8');
const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2022 } }).outputText;
const { collectPages, collectArrayPages } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);

test('collects every page and preserves response metadata', async () => {
  const calls = [];
  const result = await collectPages(async page => {
    calls.push(page);
    return { items: page === 1 ? [1, 2] : [3], total: 3, page_size: 2 };
  });
  assert.deepEqual(result.items, [1, 2, 3]);
  assert.equal(result.page_size, 2);
  assert.deepEqual(calls, [1, 2]);
  assert.deepEqual(await collectArrayPages(async page => page === 1 ? [1, 2] : [3], 2), [1, 2, 3]);
});

test('does not silently return incomplete data when a page fails or is empty', async () => {
  await assert.rejects(collectPages(async page => ({ items: page === 1 ? [1] : [], total: 2 })));
  await assert.rejects(collectPages(async page => {
    if (page === 2) throw Error('network');
    return { items: [1], total: 2 };
  }));
});

test('bounds bulk reads and reports when the total exceeds the safety limit', async () => {
  let calls = 0;
  await assert.rejects(collectPages(async () => {
    calls += 1;
    return { items: [1], total: 5001 };
  }), /批量加载上限/);
  assert.equal(calls, 1);

  await assert.rejects(collectArrayPages(async () => Array(100).fill(1), 100), /批量加载上限/);
});
