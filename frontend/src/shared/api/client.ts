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
import type { ApiErrorBody } from '@/shared/api/contracts';

import {
  expireSession,
  getSessionGeneration,
  isSessionGenerationCurrent,
  subscribeToSessionLifecycle,
} from '../session/sessionLifecycle.mjs';

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
      localStorage.removeItem(USER_KEY);
    } catch {
      // 存储不可用时内存态仍会被清除。
    }
  },
};

/** 当前用户对象在 localStorage 的缓存，供刷新页面后即时读取角色等信息。 */
export const userStore = {
  /** 取出缓存的用户，泛型 T 由调用方决定形状；无缓存或 JSON 损坏时返回 null。 */
  get<T>(): T | null {
    try {
      const raw = localStorage.getItem(USER_KEY);
      if (!raw) return null;
      return JSON.parse(raw) as T;
    } catch {
      // 缓存内容损坏：当作用户不存在处理
      return null;
    }
  },
  /** 写入缓存的用户对象。 */
  set(user: unknown) {
    try {
      localStorage.setItem(USER_KEY, JSON.stringify(user));
    } catch {
      // Cookie 是认证事实来源；缓存写入失败不应阻止登录继续。
    }
  },
  /** 清除用户资料缓存，存储被浏览器禁用时保持静默。 */
  clear() {
    try {
      localStorage.removeItem(USER_KEY);
    } catch {
      // 内存态由 AuthProvider 同步清理。
    }
  },
};

/** axios 实例：全局共享，超时 30 秒。 */
export const client: AxiosInstance = axios.create({
  baseURL: API_BASE, // 相对路径都会拼这个前缀
  timeout: 30000, // 30 秒无响应即视为超时
  withCredentials: true,
});

client.interceptors.request.use((config) => {
  const generation = getSessionGeneration();
  requestGenerations.set(config, generation);
  if (config.method === 'get' || config.method === 'head') {
    const controller = new AbortController();
    const signals = [config.signal, controller.signal].filter(Boolean) as AbortSignal[];
    config.signal = signals.length === 1 ? signals[0] : AbortSignal.any(signals);
    readControllers.set(config, controller);
    const controllers = pendingReads.get(generation) ?? new Set<AbortController>();
    controllers.add(controller);
    pendingReads.set(generation, controllers);
  }
  // 浏览器会话由 HttpOnly Cookie 携带；仅兼容尚未迁移的内存 Bearer 调用方。
  const token = tokenStore.get();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 登录过期回调，由 AuthProvider 通过 registerAuthExpiredHandler 注入
let onAuthExpired: (() => void) | null = null;

// 每个读取请求独立 AbortController；身份改变时只终止旧读取，不伪称写操作已回滚。
const requestGenerations = new WeakMap<object, number>();
const readControllers = new WeakMap<object, AbortController>();
const pendingReads = new Map<number, Set<AbortController>>();

/** 释放请求控制器登记，避免已完成请求留在会话代次集合中。 */
function releaseRequest(config: object | undefined) {
  if (!config) return;
  const generation = requestGenerations.get(config);
  const controller = readControllers.get(config);
  if (generation === undefined || !controller) return;
  const controllers = pendingReads.get(generation);
  controllers?.delete(controller);
  if (controllers?.size === 0) pendingReads.delete(generation);
}

// 身份变化会终止旧 GET/HEAD 轮询；写请求可能已在服务端提交，只屏蔽迟到结果。
subscribeToSessionLifecycle(({ generation }) => {
  for (const [requestGeneration, controllers] of pendingReads) {
    if (requestGeneration >= generation) continue;
    for (const controller of controllers) controller.abort();
    pendingReads.delete(requestGeneration);
  }
});

/** 注入登录过期回调（由 AuthProvider 注册），避免 client 直接依赖 router。 */
export function registerAuthExpiredHandler(handler: () => void): () => void {
  onAuthExpired = handler;
  return () => {
    if (onAuthExpired === handler) onAuthExpired = null;
  };
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
  (response) => {
    releaseRequest(response.config);
    const generation = requestGenerations.get(response.config);
    if (generation !== undefined && !isSessionGenerationCurrent(generation)) {
      // 旧身份的成功响应不能写回 React Query 或恢复旧组件状态。
      throw new axios.CanceledError('会话已切换，忽略旧请求结果');
    }
    return response;
  },
  (error: AxiosError) => {
    releaseRequest(error.config);
    const generation = error.config && requestGenerations.get(error.config);
    if (generation !== undefined && !isSessionGenerationCurrent(generation)) {
      return Promise.reject(new axios.CanceledError('会话已切换，忽略旧请求结果'));
    }
    const status = error.response?.status;
    const body = extractErrorBody(error);
    // 401：令牌失效；403 且为账户禁用：清登录态并跳登录。
    const isAccountDisabled =
      status === 403 && body?.message === '该账户已被禁用';
    const url = (error.config?.url ?? '').split('?')[0].replace(/\/+$/, '');
    const isAuthEntry = ['/session/login', '/session/register', '/session/logout']
      .some((path) => url === path || url.endsWith(path));
    if (!isAuthEntry && (status === 401 || isAccountDisabled)) {
      tokenStore.clear();
      if (expireSession()) onAuthExpired?.();
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
