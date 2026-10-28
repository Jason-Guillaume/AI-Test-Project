// 统一 HTTP 请求客户端。
//
// baseURL 为 /api/v1，与后端版本前缀一致；开发期由 Vite 代理转发到后端，
// 代理不再删除 /api 前缀（区别于旧项目的 rewrite），避免前后端前缀错位。
//
// 401：令牌无效/过期/被撤销 → 清除本地登录态并跳转登录页。
// 403「该账户已被禁用」：账号被管理员停用 → 同样清除登录态并提示。
//
// 本模块只做传输与错误归一化，不关心具体业务字段；各业务模块通过 api.get/post/...
// 拿到已经解包过的 data 部分。
import axios, { AxiosError, type AxiosInstance, type AxiosRequestConfig } from 'axios';
import type { ApiErrorBody } from '@/types';

const TOKEN_KEY = 'access_token'; // 清理旧版本持久化令牌的键
const USER_KEY = 'user'; // localStorage 中缓存当前用户对象的键
let inMemoryToken: string | null = null;

// 浏览器认证已迁移到 HttpOnly Cookie；移除旧版本令牌，避免继续留在可读存储中。
try {
  localStorage.removeItem(TOKEN_KEY);
} catch {
  // 存储不可用时仍可使用服务端 Cookie 完成认证。
}

/** 所有请求的前缀，与后端 /api/v1 版本前缀保持一致。 */
export const API_BASE = '/api/v1';

/**
 * 兼容旧 Bearer 调用方的内存令牌存取封装；浏览器登录改由 HttpOnly Cookie 认证。
 */
export const tokenStore = {
  /** 取当前页面内存中的兼容令牌；刷新页面后返回 null。 */
  get(): string | null {
    return inMemoryToken;
  },
  /** 仅在页面内存中保留兼容 Bearer 令牌，不写入浏览器持久存储。 */
  set(token: string) {
    inMemoryToken = token;
  },
  /** 清除内存令牌与用户缓存；HttpOnly Cookie 由服务端登出接口清除。 */
  clear() {
    inMemoryToken = null;
    try {
      localStorage.removeItem(TOKEN_KEY);
    } catch {
      // 存储不可用时内存态仍会被清除。
    }
    localStorage.removeItem(USER_KEY);
  },
};

/** 当前用户对象在 localStorage 的缓存，供刷新页面后即时读取角色等信息。 */
export const userStore = {
  /** 取出缓存的用户，泛型 T 由调用方决定形状；无缓存或 JSON 损坏时返回 null。 */
  get<T>(): T | null {
    const raw = localStorage.getItem(USER_KEY);
    if (!raw) return null;
    try {
      return JSON.parse(raw) as T;
    } catch {
      // 缓存内容损坏：当作用户不存在处理
      return null;
    }
  },
  /** 写入缓存的用户对象。 */
  set(user: unknown) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  },
};

/** axios 实例：全局共享，超时 30 秒。 */
export const client: AxiosInstance = axios.create({
  baseURL: API_BASE, // 相对路径都会拼这个前缀
  timeout: 30000, // 30 秒无响应即视为超时
  withCredentials: true,
});

client.interceptors.request.use((config) => {
  // 浏览器会话由 HttpOnly Cookie 携带；仅兼容尚未迁移的内存 Bearer 调用方。
  const token = tokenStore.get();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 登录过期回调，由 AuthProvider 通过 registerAuthExpiredHandler 注入
let onAuthExpired: (() => void) | null = null;

/** 注入登录过期回调（由 AuthProvider 注册），避免 client 直接依赖 router。 */
export function registerAuthExpiredHandler(handler: () => void) {
  onAuthExpired = handler;
}

/**
 * 从任意错误对象里提取后端错误信封。
 * 后端统一返回 { code, message, request_id }；若不是这种结构（例如纯字符串），
 * 则包成 code 为 ERR_HTTP 的信封，保证上层总能读到 message。
 */
export function extractErrorBody(error: unknown): ApiErrorBody | null {
  if (error instanceof AxiosError && error.response?.data) {
    const data = error.response.data as Partial<ApiErrorBody> | string;
    if (typeof data === 'object' && data !== null && 'message' in data) {
      return data as ApiErrorBody;
    }
    return { code: 'ERR_HTTP', message: String(data), request_id: '' };
  }
  return null;
}

/** 取可读错误文案，取不到时用 fallback（默认「请求失败」）。 */
export function getErrorMessage(error: unknown, fallback = '请求失败'): string {
  return extractErrorBody(error)?.message ?? fallback;
}

client.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    const status = error.response?.status;
    const body = extractErrorBody(error);
    // 401：令牌失效；403 且为账户禁用：清登录态并跳登录。
    const isAccountDisabled =
      status === 403 && body?.message === '该账户已被禁用';
    if (status === 401 || isAccountDisabled) {
      tokenStore.clear();
      onAuthExpired?.();
    }
    // 其余错误不在此处处理，原样抛给调用方的 catch
    return Promise.reject(error);
  },
);

/** 便捷请求方法，返回 data 部分。 */
export const api = {
  /** GET 请求，已解包为响应体 data。 */
  get: <T>(url: string, config?: AxiosRequestConfig) =>
    client.get<T>(url, config).then((r) => r.data),
  /** POST 请求，data 作为请求体。 */
  post: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.post<T>(url, data, config).then((r) => r.data),
  /** PUT 请求，整体替换资源。 */
  put: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.put<T>(url, data, config).then((r) => r.data),
  /** PATCH 请求，部分更新资源。 */
  patch: <T>(url: string, data?: unknown, config?: AxiosRequestConfig) =>
    client.patch<T>(url, data, config).then((r) => r.data),
  /** DELETE 请求。 */
  delete: <T>(url: string, config?: AxiosRequestConfig) =>
    client.delete<T>(url, config).then((r) => r.data),
};
