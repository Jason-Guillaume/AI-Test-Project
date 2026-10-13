import { api } from './client';
import type { Environment, Paginated } from '@/types';

/** 新建环境的请求体，对应 POST /environments；除 name 外均为可选字段。 */
export interface EnvironmentCreate {
  name: string; // 环境标识（slug），平台内唯一，并用于拼接路径
  display_name?: string; // 展示名称；不传时后端用 name 兜底
  base_url?: string; // 被测服务的 base URL
  gateway_prefix?: string; // 网关前缀，拼接在 base_url 之后
  default_headers?: Record<string, string>; // 默认请求头，如固定的鉴权头
  description?: string; // 环境说明
  is_default?: boolean; // 是否设为默认环境
  is_active?: boolean; // 是否启用；false 表示建好即停用
}

/** 修改环境的请求体，对应 PATCH /environments/{name}；字段全部可选，只提交要改的项。 */
export interface EnvironmentUpdate {
  display_name?: string; // 新的展示名称
  base_url?: string; // 新的被测服务地址
  gateway_prefix?: string; // 新的网关前缀
  default_headers?: Record<string, string>; // 新的默认请求头，整体覆盖原值
  description?: string; // 新的环境说明
  is_default?: boolean; // 是否设为默认环境
  is_active?: boolean; // 启用或停用环境
}

/** 环境列表查询参数，作为 GET /environments 的 query 传给后端。 */
export interface EnvironmentListQuery {
  page?: number; // 页码，从 1 开始；不传时后端返回第一页
  page_size?: number; // 每页条数；不传时后端用默认值
  include_inactive?: boolean; // 是否包含已停用的环境，默认只看启用项
}

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
