import { api } from './client';
import type { TokenResponse, User } from '@/types';

/** 登录表单输入，对应 POST /login。 */
export interface LoginInput {
  username: string; // 登录名
  password: string; // 密码，明文提交，前端不做任何编码
}

/** 注册表单输入，对应 POST /register。 */
export interface RegisterInput {
  username: string; // 新账号的登录名
  password: string; // 新账号密码
}

/** 修改密码的输入，对应 PATCH /me。 */
export interface PasswordChangeInput {
  old_password: string; // 原密码，用于校验当前身份
  new_password: string; // 新密码
}

/**
 * 认证相关接口集合，由登录页、注册页与 AuthProvider 调用。
 * 覆盖端点：POST /login、POST /register、GET /me、PATCH /me、GET /me/organizations、DELETE /logout。
 */
export const authApi = {
  /** 登录，成功后后端返回 access_token，由调用方写入 tokenStore。 */
  login: (body: LoginInput) => api.post<TokenResponse>('/login', body),
  /** 注册新用户。成功后后端直接返回 TokenResponse（含 access_token），注册即自动登录。 */
  register: (body: RegisterInput) =>
    api.post<TokenResponse>('/register', body),
  /** 取当前登录用户信息，刷新页面时用来恢复登录态。 */
  me: () => api.get<User>('/me'),
  /** 修改当前用户密码，成功后后端会让旧 token 失效。 */
  changePassword: (body: PasswordChangeInput) => api.patch<User>('/me', body),
  /** 当前用户名下的组织列表，返回体为 { items, total, page, page_size } 结构。 */
  myOrganizations: () =>
    api.get<{ items: unknown[]; total: number; page: number; page_size: number }>(
      '/me/organizations',
    ),
  /** 登出：通知后端失效令牌，前端另需自行清空本地登录态。 */
  logout: () => api.delete('/logout'),
};
