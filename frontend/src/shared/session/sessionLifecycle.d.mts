// 会话生命周期模块的 TypeScript 合同；运行时代码位于相邻的 .mjs 文件。

/** 登录身份跨越或会话被服务端撤销时的原因。 */
export type SessionTransitionReason =
  | 'login-attempt'
  | 'register-attempt'
  | 'logout'
  | 'expired'
  | 'refresh-failed'
  | 'identity-changed';

/** 一次身份切换的代次与来源。 */
export interface SessionTransition {
  generation: number;
  reason: SessionTransitionReason;
}

/** 返回当前会话代次。 */
export function getSessionGeneration(): number;
/** 判断请求捕获的代次是否仍然有效。 */
export function isSessionGenerationCurrent(value: number): boolean;
/** 订阅会话变化，并返回注销函数。 */
export function subscribeToSessionLifecycle(
  listener: (event: SessionTransition) => void,
): () => void;
/** 在登录、注册、登出或恢复失败时建立新身份边界。 */
export function transitionSession(reason: SessionTransitionReason): number;
/** 对当前会话执行一次性过期转换；重复调用返回 false。 */
export function expireSession(): boolean;
/** 只接受正安全整数的数值或十进制字符串。 */
export function parsePositiveSafeInteger(value: unknown): number | null;
