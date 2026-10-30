import { api } from '@/shared/api/client';
import type { Environment } from '@/features/environments/contracts';
import type { Paginated } from '@/shared/api/contracts';

import type { EnvironmentCreate, EnvironmentUpdate, EnvironmentListQuery } from '../contracts';






/**
 * 环境管理接口集合，由环境配置页调用（配置被测网关地址与默认请求头）。
 * 覆盖端点：GET /environments、POST /environments、GET/PATCH /environments/{name}、
 * POST /environments/{name}/set-default、DELETE /environments/{name}。
 * 注意：本组端点用环境标识 name 定位资源，而不是数据库主键 id。
 */
export const environmentsApi = {
  /** 分页查询环境列表，可带 include_inactive 控制是否含停用项。 */
  list: (params: EnvironmentListQuery) =>
    api.get<Paginated<Environment>>('/environments', { params }),
  /** 新建环境。 */
  create: (body: EnvironmentCreate) =>
    api.post<Environment>('/environments', body),
  /** 按环境标识 name 查询单个环境详情。 */
  get: (name: string) => api.get<Environment>(`/environments/${name}`),
  /** 部分更新环境。 */
  update: (name: string, body: EnvironmentUpdate) =>
    api.patch<Environment>(`/environments/${name}`, body),
  /** 把指定环境设为默认环境。 */
  setDefault: (name: string) =>
    api.post<Environment>(`/environments/${name}/set-default`),
  /** 删除环境，无返回体。 */
  remove: (name: string) => api.delete<void>(`/environments/${name}`),
};
