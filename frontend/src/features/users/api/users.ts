import { api } from '@/shared/api/client';
import type { Paginated } from '@/shared/api/contracts';
import type { User } from '@/features/identity/contracts';

import type { UserListQuery, AdminUserCreate, UserUpdate } from '../contracts';






/**
 * 用户管理接口集合，由用户管理页调用（仅平台管理员可用）。
 * 覆盖端点：GET /users、GET /users/{id}、POST /users、PATCH /users/{id}、DELETE /users/{id}。
 */
export const usersApi = {
  /** 分页查询用户列表，可带关键词与启用状态过滤。 */
  list: (params: UserListQuery) =>
    api.get<Paginated<User>>('/users', { params }),
  /** 按主键查询单个用户详情。 */
  get: (id: number) => api.get<User>(`/users/${id}`),
  /** 创建用户，返回新建后的用户对象。 */
  create: (body: AdminUserCreate) => api.post<User>('/users', body),
  /** 部分更新用户：改名 / 改角色 / 启停。 */
  update: (id: number, body: UserUpdate) => api.patch<User>(`/users/${id}`, body),
  /** 删除用户，无返回体。 */
  remove: (id: number) => api.delete<void>(`/users/${id}`),
};
