import { api } from './client';
import type { Paginated, PlatformRole, User } from '@/types';

/** 用户列表查询参数，作为 GET /users 的 query 传给后端。 */
export interface UserListQuery {
  page?: number; // 页码，从 1 开始；不传时后端返回第一页
  page_size?: number; // 每页条数；不传时后端用默认值
  keyword?: string; // 关键词，按用户名或平台角色模糊匹配；纯数字时后端会额外按用户 ID 精确匹配
  is_active?: boolean; // 只筛启用（true）或停用（false）的账号
}

/** 管理员新建用户的请求体，对应 POST /users。 */
export interface AdminUserCreate {
  username: string; // 登录名，平台内唯一
  password: string; // 初始密码，后端按强度规则校验
  role: PlatformRole; // 平台级角色
  is_active: boolean; // 账号是否启用，false 表示建好即停用
}

/** 修改用户的请求体，对应 PATCH /users/{id}；字段全部可选，只提交要改的项。 */
export interface UserUpdate {
  username?: string; // 新的登录名
  role?: PlatformRole; // 调整平台级角色
  is_active?: boolean; // 启用或停用账号
}

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
