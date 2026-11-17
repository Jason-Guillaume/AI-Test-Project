// 公开分享凭证的内存生命周期。
// - 只在页面首次进入时从 URL Fragment（#token=...）读取一次；
// - 读到之后立即用 history.replaceState 把 Fragment 从地址栏、历史记录里去掉；
// - 之后只保存在本模块的内存 Map 中，不写 localStorage / sessionStorage / Cookie，不打印日志；
// - React StrictMode 重复执行初始化函数、组件卸载后重新挂载时，都从内存取回同一凭证，
//   不会因为地址栏已被清理而提前丢失；
// - 整页刷新后内存清空、Fragment 也已不在，调用方据此提示“请重新使用分享链接进入”。
// 本文件不导入任何依赖，便于在 Node 测试里直接编译执行。

/** 凭证读取结果：present 表示拿到凭证；missing 表示地址里从来没有凭证（或刷新后已失效）。 */
export type ShareTokenState =
  | { status: 'present'; token: string }
  | { status: 'missing' };

const MAX_TOKEN_LENGTH = 200;
const memory = new Map<string, string>();

/** 浏览器环境的最小依赖，测试可以注入替身。 */
export interface ShareTokenEnvironment {
  location: { hash: string; pathname: string; search: string };
  history: { state: unknown; replaceState: (data: unknown, unused: string, url?: string) => void };
}

function browserEnvironment(): ShareTokenEnvironment | null {
  if (typeof window === 'undefined') return null;
  return { location: window.location, history: window.history };
}

/** 从 Fragment 中解析 token。格式不合规的值直接视为没有凭证，不尝试修复。 */
function parseFragmentToken(hash: string): string {
  const raw = hash.startsWith('#') ? hash.slice(1) : hash;
  if (!raw) return '';
  const token = new URLSearchParams(raw).get('token')?.trim() ?? '';
  if (!token || token.length > MAX_TOKEN_LENGTH || /\s/.test(token)) return '';
  return token;
}

/**
 * 从地址栏移除 Fragment，保留 pathname、search 和 history.state。
 * 保留 state 是为了不打乱 React Router 记录的历史索引。
 */
function scrubFragment(env: ShareTokenEnvironment): void {
  if (!env.location.hash) return;
  try {
    env.history.replaceState(env.history.state, '', `${env.location.pathname}${env.location.search}`);
  } catch {
    // 某些嵌入式浏览器禁止 replaceState；此时凭证仍只在内存使用，不做其他兜底写入。
  }
}

/**
 * 取得某个分享的访问凭证。
 * 第一次调用读取并清理 Fragment；之后（包括 StrictMode 二次调用、组件重新挂载）直接返回内存值。
 * 如果地址栏又带来了新的凭证（例如用户在同一标签页打开了重新推送后的新链接），以新凭证为准。
 */
export function captureShareToken(shareId: string, env: ShareTokenEnvironment | null = browserEnvironment()): ShareTokenState {
  if (!shareId) return { status: 'missing' };
  if (env) {
    const fromFragment = parseFragmentToken(env.location.hash);
    if (env.location.hash) scrubFragment(env);
    if (fromFragment) {
      memory.set(shareId, fromFragment);
      return { status: 'present', token: fromFragment };
    }
  }
  const remembered = memory.get(shareId);
  return remembered ? { status: 'present', token: remembered } : { status: 'missing' };
}

/** 服务端确认凭证无效、过期或撤销后丢弃内存凭证，避免继续携带。 */
export function forgetShareToken(shareId: string): void {
  memory.delete(shareId);
}

/** 仅供测试：清空内存，模拟整页刷新。 */
export function resetShareTokenMemoryForTests(): void {
  memory.clear();
}
