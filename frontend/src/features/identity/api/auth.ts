import { api } from '@/shared/api/client';
import type { User } from '@/features/identity/contracts';

import type { LoginInput, RegisterInput, PasswordChangeInput } from '../contracts';






/**
 * 认证相关接口集合，由登录页、注册页与 AuthProvider 调用。
 * 浏览器登录只通过 HttpOnly Cookie 建立会话，JSON 响应不包含访问令牌。
 * 覆盖端点：POST /session/login、POST /session/register、GET /me、PATCH /me、POST /session/logout。
 */
export const authApi = {
  /** 登录并建立 HttpOnly Cookie 会话；页面脚本不接触令牌。 */
  login: (body: LoginInput) => api.post<User>('/session/login', body),
  /** 注册新用户并建立 HttpOnly Cookie 会话。 */
  register: (body: RegisterInput) =>
    api.post<User>('/session/register', body),
  /** 取当前登录用户信息，浏览器自动附带认证 Cookie。 */
  me: () => api.get<User>('/me'),
  /** 修改当前用户密码，成功后后端会让旧 token 失效。 */
  changePassword: (body: PasswordChangeInput) => api.patch<User>('/me', body),
  /** 当前用户名下的组织列表，返回体为 { items, total, page, page_size } 结构。 */
  myOrganizations: () =>
    api.get<{ items: unknown[]; total: number; page: number; page_size: number }>(
      '/me/organizations',
    ),
  /** 登出：服务端清除 HttpOnly Cookie，前端随后清除用户缓存。 */
  logout: () => api.post('/session/logout'),
};
