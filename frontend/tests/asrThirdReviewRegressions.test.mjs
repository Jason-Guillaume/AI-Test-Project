import assert from 'node:assert/strict';
import test from 'node:test';
import { createRequire } from 'node:module';
import { clearMatchingReviewDraft } from '../src/features/asr-evaluation/reviewDraftMutation.mjs';
import { createDraftNavigationController } from '../src/features/asr-evaluation/draftNavigationController.mjs';
import { fetchCompletePlaybackWindow } from '../src/features/asr-evaluation/components/playbackSegmentWindow.mjs';
import { clearSpeakerDrafts, updateSpeakerNameDraft } from '../src/features/asr-evaluation/speakerNameDraft.mjs';
import { enteredTerminalJobState, shouldPollBatchSummary } from '../src/features/asr-evaluation/batchRefresh.mjs';
import { experimentStatusLabel, parameterChangeSummary, parameterDiffs } from '../src/features/asr-evaluation/experimentPresentation.mjs';
import { modelSwitchOption } from '../src/features/asr-evaluation/modelSwitchOption.mjs';

const require = createRequire(import.meta.url);
const { QueryClient, MutationObserver } = require('../node_modules/@tanstack/query-core');

test('delayed review success clears only the submitted block and unchanged draft revision', () => {
  const submitted = { comparisonId: 10, blockId: 101, submittedText: 'A draft', submittedRevision: 1, savesDraft: true };
  const current = { 101: 'A draft', 202: 'B draft' };
  const revisions = { 101: 1, 202: 1 };
  assert.deepEqual(clearMatchingReviewDraft(current, revisions, submitted), { 202: 'B draft' });
  assert.deepEqual(clearMatchingReviewDraft({ 101: 'new A edit', 202: 'B draft' }, { 101: 2, 202: 1 }, submitted),
    { 101: 'new A edit', 202: 'B draft' });
  assert.deepEqual(clearMatchingReviewDraft({ 202: 'B draft' }, { 202: 1 }, submitted), { 202: 'B draft' });
  assert.deepEqual(clearMatchingReviewDraft(current, revisions, { ...submitted, savesDraft: false }), current);
});

test('TanStack delayed save keeps another block and a newer same-block edit after selection moves', async () => {
  const client = new QueryClient();
  let resolveRequest;
  let signalStarted;
  const started = new Promise((resolve) => { signalStarted = resolve; });
  let drafts = { 101: 'A draft', 202: 'B draft' };
  const revisions = { 101: 1, 202: 1 };
  const options = (selectedBlock) => ({
    mutationFn: () => { signalStarted(); return new Promise((resolve) => { resolveRequest = resolve; }); },
    onSuccess: (_data, variables) => { drafts = clearMatchingReviewDraft(drafts, revisions, variables); },
  });
  const observer = new MutationObserver(client, options(101));
  const unsubscribe = observer.subscribe(() => {});
  const pending = observer.mutate({ comparisonId: 1, blockId: 101, submittedText: 'A draft', submittedRevision: 1, savesDraft: true });
  await started;
  drafts[101] = 'A revised while saving';
  revisions[101] = 2;
  observer.setOptions(options(202));
  resolveRequest({ saved: true });
  await pending;
  assert.deepEqual(drafts, { 101: 'A revised while saving', 202: 'B draft' });
  unsubscribe();
  client.clear();
});

class FakeWindow {
  constructor() {
    this.location = { href: 'http://local.test/edit' };
    this.listeners = [];
    this.history = new FakeHistory(this);
  }
  addEventListener(type, listener, capture = false) { this.listeners.push({ type, listener, capture }); }
  removeEventListener(type, listener) { this.listeners = this.listeners.filter((item) => item.listener !== listener); }
  dispatch(type, event) {
    for (const item of this.listeners.filter((listener) => listener.type === type).sort((a, b) => Number(b.capture) - Number(a.capture))) {
      item.listener(event);
      if (event.immediateStopped) break;
    }
  }
}

class FakeHistory {
  constructor(host) { this.host = host; this.entries = [{ href: host.location.href, state: { idx: 0 } }]; this.position = 0; }
  get state() { return this.entries[this.position].state; }
  pushState(state, _unused, url) {
    this.entries = this.entries.slice(0, this.position + 1);
    this.entries.push({ href: new URL(String(url), this.host.location.href).href, state });
    this.position++;
    this.host.location.href = this.entries[this.position].href;
  }
  replaceState(state, _unused, url) {
    this.entries[this.position] = { href: new URL(String(url ?? this.host.location.href), this.host.location.href).href, state };
    this.host.location.href = this.entries[this.position].href;
  }
  go(delta) {
    const position = this.position + delta;
    if (position < 0 || position >= this.entries.length) return;
    this.position = position;
    const current = this.entries[position];
    this.host.location.href = current.href;
    const event = {
      state: current.state, prevented: false, immediateStopped: false,
      preventDefault() { this.prevented = true; },
      stopImmediatePropagation() { this.immediateStopped = true; },
    };
    this.host.dispatch('popstate', event);
  }
  back() { this.go(-1); }
  forward() { this.go(1); }
}

test('draft navigation controller protects programmatic push, back, forward, and unload; cancel preserves route state', () => {
  const target = new FakeWindow();
  let allow = true;
  let routerPopCount = 0;
  let routerPath = target.location.href;
  target.addEventListener('popstate', () => { routerPopCount++; routerPath = target.location.href; });
  const guard = createDraftNavigationController(target, () => allow);
  guard.setHasDrafts(true);
  allow = false;
  target.history.pushState({ idx: 1 }, '', '/other');
  assert.equal(target.location.href, 'http://local.test/edit');
  assert.equal(target.history.entries.length, 1);

  guard.setHasDrafts(false);
  target.history.pushState({ idx: 1 }, '', '/other');
  guard.setHasDrafts(true);
  allow = true;
  target.history.back();
  assert.equal(target.location.href, 'http://local.test/edit');
  assert.equal(routerPopCount, 1, 'accepted back reaches the router');
  guard.setHasDrafts(true);
  allow = false;
  target.history.forward();
  assert.equal(target.location.href, 'http://local.test/edit');
  assert.equal(routerPopCount, 2, 'restoration pop reaches the router at the preserved previous URL');
  assert.equal(routerPath, 'http://local.test/edit');

  const unload = { prevented: false, returnValue: undefined, preventDefault() { this.prevented = true; } };
  target.dispatch('beforeunload', unload);
  assert.equal(unload.prevented, true, 'refresh/close path requests native confirmation');
  guard.dispose();
});

test('playback window collects dense and overlapping segments beyond the first 100 rows with bounded concurrency', async () => {
  const all = Array.from({ length: 451 }, (_, index) => ({ id: index + 1, start_ms: 4000, end_ms: 9000 }));
  let active = 0;
  let maxActive = 0;
  const result = await fetchCompletePlaybackWindow(async (page, signal) => {
    assert.equal(signal.aborted, false);
    active++;
    maxActive = Math.max(maxActive, active);
    await new Promise((resolve) => setTimeout(resolve, page === 2 ? 8 : page === 3 ? 1 : 3));
    active--;
    const pageSize = 100;
    return { items: all.slice((page - 1) * pageSize, page * pageSize), total: all.length, page, page_size: pageSize };
  }, new AbortController().signal, 2);
  assert.equal(result.items.length, 451);
  assert.equal(result.items.at(-1).id, 451);
  assert.deepEqual(result.items.slice(0, 3).map((item) => item.id), [1, 2, 3], 'late page responses retain server ordering');
  assert.ok(maxActive <= 2);
});

test('speaker rename reverting to saved value removes dirty state and confirmed discard clears all names', () => {
  let drafts = updateSpeakerNameDraft({}, 5, '新名称', '原名称');
  assert.deepEqual(drafts, { 5: '新名称' });
  drafts = updateSpeakerNameDraft(drafts, 5, '原名称', '原名称');
  assert.deepEqual(drafts, {});
  assert.deepEqual(clearSpeakerDrafts({ 5: '新名称', 7: '另一个名称' }), {});
});

test('batch summary remains live for ASR and both review types, and terminal transition triggers one closeout', () => {
  assert.equal(shouldPollBatchSummary('RUNNING', { review_active: 0, ab_active: 0 }), true);
  assert.equal(shouldPollBatchSummary('COMPLETED', { review_active: 1, ab_active: 0 }), true);
  assert.equal(shouldPollBatchSummary('COMPLETED', { review_active: 0, ab_active: 1 }), true);
  assert.equal(shouldPollBatchSummary('COMPLETED', { review_active: 0, ab_active: 0 }), false);
  assert.equal(enteredTerminalJobState('RUNNING', 'PARTIAL_FAILED'), true);
  assert.equal(enteredTerminalJobState('RUNNING', 'RUNNING'), false);
});

test('experiment labels distinguish uncertain state, missing baseline snapshot, and no parameter changes', () => {
  assert.equal(experimentStatusLabel('RECONCILIATION_REQUIRED'), '状态待核实');
  assert.equal(experimentStatusLabel('RUNNING'), '复跑中');
  assert.equal(parameterChangeSummary({ temperature: 0.2 }, { temperature: 0.2 }), '无参数差异');
  assert.equal(parameterChangeSummary(null, { temperature: 0.45 }), '缺少基线快照');
  assert.equal(parameterChangeSummary({ temperature: 0.2 }, { temperature: 0.45 }), '1 项 · /temperature');
  assert.deepEqual(parameterDiffs({ nested: { temperature: 0.2 } }, { nested: { temperature: 0.45 } }), [
    { path: '/nested/temperature', baseline: 0.2, candidate: 0.45 },
  ]);
});

test('same-audio model switch options show frozen slot, connection name, model and status', () => {
  const jobSnapshot = {
    connections: [{ id: 2, name: '参考合成模型 A' }],
    model_slots: [{ legacy_connection_id: 2, slot: 'REFERENCE_A' }],
  };
  const option = modelSwitchOption({
    id: 22, connection_id: 2, role: 'REFERENCE', status: 'SUCCEEDED',
    request_snapshot: { model_id: 'synthetic-asr-a', parameter_set: { name: '候选参数' } },
  }, jobSnapshot, (status) => status === 'SUCCEEDED' ? '已完成' : status);
  assert.equal(option.value, 22);
  assert.equal(option.label, '参考模型 A · 参考合成模型 A · synthetic-asr-a · 候选参数 · 已完成');
  const historical = modelSwitchOption({
    id: 23, connection_id: 3, role: 'REFERENCE', status: 'SUCCEEDED', request_snapshot: { model_id: 'legacy-model' },
  }, { connections: [{ id: 3, name: '旧参考模型' }] }, (status) => status);
  assert.match(historical.label, /参考模型（具体槽位未记录） · 旧参考模型 · legacy-model · 参数未报告 · SUCCEEDED/);
});
