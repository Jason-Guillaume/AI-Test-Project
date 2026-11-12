// 会话代次与身份切换事件。它为 HTTP 客户端、认证 Provider 和作用域 Provider 提供
// 同一个竞态屏障；只维护浏览器内状态，不请求业务接口或保存认证令牌。

/** @typedef {'login-attempt'|'register-attempt'|'logout'|'expired'|'refresh-failed'|'identity-changed'} SessionTransitionReason */
/** @typedef {{ generation: number, reason: SessionTransitionReason }} SessionTransition */

const listeners = new Set();
const scopeStorageKeys = [
  'console.current_org_id',
  'console.current_project_id',
  'console.scope_user_id',
];
let generation = 0;
let expired = false;

/** 通知订阅者身份边界变化，令旧用户状态在同一轮事件中失效。 */
function publish(reason) {
  generation += 1;
  clearPersistedScope();
  const event = { generation, reason };
  for (const listener of [...listeners]) listener(event);
  return generation;
}

/** 清除用户切换后不能复用的项目选择；存储受限时仍继续完成内存态切换。 */
function clearPersistedScope() {
  try {
    for (const key of scopeStorageKeys) globalThis.localStorage?.removeItem(key);
  } catch {
    // 浏览器禁用持久存储时，Provider 仍会收到事件并清除内存作用域。
  }
}

/** 返回当前会话代次，用于拒绝身份切换前发出的迟到请求。 */
export function getSessionGeneration() {
  return generation;
}

/** 判断捕获的代次是否仍属于当前登录身份。 */
export function isSessionGenerationCurrent(value) {
  return value === generation;
}

/** 订阅会话切换事件，并返回可供 React StrictMode 清理的注销函数。 */
export function subscribeToSessionLifecycle(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** 开始登录、注册、登出或身份校正，先屏蔽旧请求和旧作用域再执行网络操作。 */
export function transitionSession(reason) {
  expired = false;
  return publish(reason);
}

/** 只接纳当前会话的首个过期响应，抑制同批并发 401 的重复导航。 */
export function expireSession() {
  if (expired) return false;
  expired = true;
  publish('expired');
  return true;
}

/** 将存储值解析为正安全整数；损坏、零、负数和超出精度的值均拒绝。 */
export function parsePositiveSafeInteger(value) {
  if (typeof value === 'number') {
    return Number.isSafeInteger(value) && value > 0 ? value : null;
  }
  if (typeof value !== 'string' || !/^[1-9]\d*$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}
