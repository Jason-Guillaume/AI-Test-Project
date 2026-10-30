// 会话生命周期的行为回归，直接验证代次屏障、并发过期抑制和安全范围解析。
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  expireSession,
  getSessionGeneration,
  isSessionGenerationCurrent,
  parsePositiveSafeInteger,
  subscribeToSessionLifecycle,
  transitionSession,
} from '../src/shared/session/sessionLifecycle.mjs';

/** 验证身份切换只接受切换后的代次，旧查询回调不能继续更新状态。 */
test('身份切换推进代次并通知订阅者', () => {
  const seen = [];
  const unsubscribe = subscribeToSessionLifecycle((event) => seen.push(event));
  const previous = getSessionGeneration();
  const current = transitionSession('login-attempt');
  unsubscribe();

  assert.equal(current, previous + 1);
  assert.equal(isSessionGenerationCurrent(previous), false);
  assert.equal(isSessionGenerationCurrent(current), true);
  assert.equal(seen.at(-1).reason, 'login-attempt');
});

/** 验证并发的同会话 401 只能触发一次状态转换。 */
test('同一会话过期通知只接纳一次', () => {
  transitionSession('login-attempt');
  const before = getSessionGeneration();

  assert.equal(expireSession(), true);
  assert.equal(expireSession(), false);
  assert.equal(getSessionGeneration(), before + 1);
});

/** 验证本地作用域 ID 不能以 NaN、零、负数或超精度整数进入查询参数。 */
test('范围 ID 只接受正安全整数', () => {
  assert.equal(parsePositiveSafeInteger('42'), 42);
  assert.equal(parsePositiveSafeInteger(Number.MAX_SAFE_INTEGER), Number.MAX_SAFE_INTEGER);
  for (const invalid of ['0', '-1', '01', '1.5', 'NaN', '9007199254740992', null]) {
    assert.equal(parsePositiveSafeInteger(invalid), null);
  }
});
