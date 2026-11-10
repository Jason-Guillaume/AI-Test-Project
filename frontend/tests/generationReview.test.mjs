// 生成审核工作台纯逻辑回归：批量审核请求体、待审核统计、失败模块判定、质量汇总。
import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildReviewBody,
  formatMetric,
  hasFailedModule,
  pendingCount,
  pendingModules,
  summarizeQuality,
} from '../src/pages/console/TestManagement/generationReview.mjs';

test('待审核统计只数 PENDING，模块去重保序', () => {
  const drafts = [
    { status: 'PENDING', module: 'api' },
    { status: 'ACCEPTED', module: 'api' },
    { status: 'PENDING', module: 'security' },
    { status: 'REJECTED', module: 'web' },
    { status: 'PENDING', module: 'api' },
  ];
  assert.equal(pendingCount(drafts), 3);
  assert.deepEqual(pendingModules(drafts), ['api', 'security']);
  assert.equal(pendingCount(undefined), 0);
});

test('失败模块判定不含 SKIPPED', () => {
  assert.equal(hasFailedModule([{ status: 'FAILED' }]), true);
  assert.equal(hasFailedModule([{ status: 'SKIPPED' }]), false);
  assert.equal(hasFailedModule([]), false);
});

test('批量审核请求体强制 confirm，模块范围必须带 module', () => {
  assert.deepEqual(buildReviewBody({ action: 'accept', scope: 'all' }), { action: 'accept', scope: 'all', confirm: true });
  assert.deepEqual(
    buildReviewBody({ action: 'reject', scope: 'module', module: 'api', comment: '覆盖不足' }),
    { action: 'reject', scope: 'module', module: 'api', comment: '覆盖不足', confirm: true },
  );
  assert.throws(() => buildReviewBody({ action: 'accept', scope: 'module' }), /module/);
  assert.throws(() => buildReviewBody({ action: 'delete', scope: 'all' }), /非法/);
});

test('质量汇总按级别计数，未知级别忽略', () => {
  assert.deepEqual(
    summarizeQuality([{ level: 'error' }, { level: 'warning' }, { level: 'warning' }, { level: 'other' }]),
    { error: 1, warning: 2, info: 0 },
  );
  assert.deepEqual(summarizeQuality(null), { error: 0, warning: 0, info: 0 });
});

test('指标文本含耗时与 token，缺省有兜底', () => {
  assert.equal(
    formatMetric({ module: 'api', status: 'SUCCEEDED', duration_ms: 1234, usage: { total_tokens: 56 } }),
    'api · SUCCEEDED · 1.2s · total_tokens=56',
  );
  assert.equal(formatMetric({ module: 'web', status: 'FAILED' }), 'web · FAILED · - · token 未上报');
});
