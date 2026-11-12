import { api } from '@/shared/api/client';
import type { ModelConfiguration } from '@/features/model-configuration/contracts';
import type { Paginated } from '@/shared/api/contracts';

import type { ProviderCatalogItem, ModelConfigurationCreate, ModelConfigurationUpdate, ModelConfigurationListQuery } from '../contracts';






/**
 * 模型配置接口集合，由模型配置页调用（管理可调用的大模型及其调用参数）。
 * 覆盖端点：GET /model-configs、POST /model-configs、GET /model-configs/providers、
 * PATCH /model-configs/{id}、POST /model-configs/{id}/set-default、DELETE /model-configs/{id}。
 * 注意：响应体里密钥字段是 masked_api_key 脱敏串，前端拿不到明文。
 */
export const modelConfigsApi = {
  /** 分页查询模型配置列表，可带关键词与启用状态过滤。 */
  list: (params: ModelConfigurationListQuery) =>
    api.get<Paginated<ModelConfiguration>>('/model-configs', { params }),
  /** 取已有服务商目录，供服务商下拉框渲染选项。 */
  providers: () =>
    api.get<ProviderCatalogItem[]>('/model-configs/providers'),
  /** 新建模型配置；返回体只带脱敏后的密钥信息。 */
  create: (body: ModelConfigurationCreate) =>
    api.post<ModelConfiguration>('/model-configs', body),
  /** 部分更新模型配置。 */
  update: (id: number, body: ModelConfigurationUpdate) =>
    api.patch<ModelConfiguration>(`/model-configs/${id}`, body),
  /** 把指定配置设为该域默认模型。 */
  setDefault: (id: number) =>
    api.post<ModelConfiguration>(`/model-configs/${id}/set-default`),
  /** 删除模型配置，无返回体。 */
  remove: (id: number) => api.delete<void>(`/model-configs/${id}`),
};
