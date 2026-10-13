// 认证上下文：管理当前用户与令牌，提供登录/退出/注册。
//
// 令牌存储在 localStorage，刷新页面后通过 /me 恢复当前用户；
// 401/账户禁用时由 client 清除登录态并触发 onAuthExpired 跳转登录。
//
// 状态来源：tokenStore（localStorage 令牌）→ authApi.me() → userStore（内存用户缓存）→ 组件 user 状态。
// 失效条件：令牌缺失/401、/me 请求失败、登出、账户被平台禁用。
// 对子树的副作用：ready 由 false 变 true 时才允许渲染受保护路由，避免权限判断用到空用户。
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { authApi } from '@/api/auth';
import {
  registerAuthExpiredHandler,
  tokenStore,
  userStore,
} from '@/api/client';
import type { User } from '@/types';

/**
 * AuthContext 对外暴露的登录态与操作集合。
 * 所有字段都是稳定引用（由 useMemo 聚合），子组件按需取值即可。
 */
interface AuthState {
  user: User | null; // 当前登录用户；未登录或已失效时为 null
  ready: boolean; // /me 恢复流程是否结束；false 表示登录态还在恢复中
  isPlatformAdmin: boolean; // 是否为平台管理员，等价于 user.role === 'admin'
  login: (username: string, password: string) => Promise<User>; // 登录并写入令牌与用户缓存
  register: (
    username: string,
    password: string,
    captchaId: string,
    captchaCode: string,
  ) => Promise<User>; // 注册并自动登录，一次性拿到 access_token
  logout: () => Promise<void>; // 登出并清除本地登录态
  refresh: () => Promise<void>; // 用本地令牌重新拉取 /me 刷新用户信息
}

// null 表示上下文尚未挂载；useAuth 会在未包裹时直接抛错而不是返回默认值。
const AuthContext = createContext<AuthState | null>(null);

/**
 * 认证 Provider：持有登录态，并负责刷新页面后的登录态恢复。
 *
 * 会发请求：挂载时若无令牌则直接置 ready；有令牌则调用 /me 恢复用户。
 * 失败呈现：/me 失败即清除令牌并置 user 为 null，由路由守卫跳转登录页，
 * 而不是在此处抛错或展示错误页。
 *
 * @param props.children 被保护的路由子树
 * @param props.onAuthExpired 令牌失效/账户禁用时的回调，用于跳转登录页
 */
export function AuthProvider({
  children,
  onAuthExpired,
}: {
  children: ReactNode; // 需要登录态的整棵子树
  onAuthExpired: () => void; // 登录态失效时的通知回调（如跳转 /login）
}) {
  const [user, setUser] = useState<User | null>(null); // 当前用户，null 表示未登录
  const [ready, setReady] = useState(false); // 登录态是否已恢复到可判定状态

  /**
   * 用本地令牌重新调用 /me，恢复或清空当前用户。
   *
   * 副作用：无令牌时不会发请求，直接置 user 为 null；成功后把用户写入 userStore 缓存。
   * 无论成功失败都在 finally 置 ready 为 true，保证守卫不会永久卡在加载态。
   */
  const refresh = useCallback(async () => {
    if (!tokenStore.get()) {
      // 本地没有令牌：无登录态，不再请求 /me。
      setUser(null);
      setReady(true);
      return;
    }
    try {
      const me = await authApi.me();
      setUser(me);
      userStore.set(me);
    } catch {
      // 401 或网络失败：令牌无效，清除本地态让守卫走登录流程。
      tokenStore.clear();
      setUser(null);
    } finally {
      // 恢复流程结束，允许子树做权限判断。
      setReady(true);
    }
  }, []);

  useEffect(() => {
    // 先用内存缓存立即填充，避免页面闪烁“未登录”；随后再由 refresh 校正为最新值。
    const cached = userStore.get<User>();
    if (cached) setUser(cached);
    refresh();
  }, [refresh]);

  useEffect(() => {
    // 注册全局失效回调：任意请求拿到 401 时都能触发这里传入的跳转。
    registerAuthExpiredHandler(onAuthExpired);
  }, [onAuthExpired]);

  // 登录成功：令牌写入 localStorage，用户写入内存缓存并进入 React 状态。
  const login = useCallback(
    async (username: string, password: string) => {
      const res = await authApi.login({ username, password });
      tokenStore.set(res.access_token);
      userStore.set(res.user);
      setUser(res.user);
      return res.user;
    },
    [],
  );

  // 注册即自动登录：后端返回 TokenResponse（含 access_token + user），
  // 这里一次性把 token 与 user 都写入缓存，调用方无需再走一次 login。
  const register = useCallback(
    async (
      username: string,
      password: string,
      captchaId: string,
      captchaCode: string,
    ) => {
      const res = await authApi.register({
        username,
        password,
        captcha_id: captchaId,
        captcha_code: captchaCode,
      });
      tokenStore.set(res.access_token);
      userStore.set(res.user);
      setUser(res.user);
      return res.user;
    },
    [],
  );

  // 登出：即使后端接口失败也必须清除本地态，否则会停留在“半登录”状态。
  const logout = useCallback(async () => {
    try {
      await authApi.logout();
    } catch {
      /* 退出时即使接口失败也清除本地态 */
    }
    tokenStore.clear();
    setUser(null);
  }, []);

  // 聚合为稳定对象，避免每次渲染都产生新的 context value 触发子树重渲染。
  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      isPlatformAdmin: user?.role === 'admin',
      login,
      register,
      logout,
      refresh,
    }),
    [user, ready, login, register, logout, refresh],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/**
 * 读取认证上下文。
 *
 * 必须在 <AuthProvider> 子树内调用；未包裹时直接抛错，便于在开发期暴露 Provider 层级问题。
 * 不发请求。
 *
 * @returns 当前登录态与登录/注册/登出/刷新操作
 */
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
