import { api } from './client';
import type { ModelConfiguration, Paginated } from '@/types';

/** 模型供应商标目项，用于新建/编辑表单的服务商下拉框。 */
export interface ProviderCatalogItem {
  value: string; // 服务商标识，提交给后端的 provider 值
  label: string; // 展示名称
}

/** 新建模型配置的请求体，对应 POST /model-configs。 */
export interface ModelConfigurationCreate {
  domain_id: string; // 业务域标识，用于区分模型归属领域
  label: string; // 展示名称
  provider: string; // 服务商标识，如 openai / dashscope
  api_base: string; // 服务端点 base URL
  api_key?: string; // 调用密钥，明文提交；后端只在响应里回脱敏串
  model_name: string; // 实际调用的模型名
  temperature?: number; // 采样温度
  max_tokens?: number; // 单次响应最大 token 数
  timeout?: number; // 单次调用超时，单位秒
  cost_per_1k_input?: number; // 每 1k 输入 token 成本
  cost_per_1k_output?: number; // 每 1k 输出 token 成本
  is_enabled?: boolean; // 是否启用（停用后不出现在可选模型中）
  is_default?: boolean; // 是否为该域默认模型
  fallback_model_ids?: number[]; // 按顺序尝试的备用模型配置 ID，最多三个
  sort_order?: number; // 排序权重，越小越靠前
}

/** 修改模型配置的请求体：创建体的可选化版本，所有字段均可省略，只提交要改的项。 */
export type ModelConfigurationUpdate = Partial<ModelConfigurationCreate>;

/** 模型配置列表查询参数，作为 GET /model-configs 的 query 传给后端。 */
export interface ModelConfigurationListQuery {
  page?: number; // 页码，从 1 开始；不传时后端返回第一页
  page_size?: number; // 每页条数；不传时后端用默认值
  keyword?: string; // 关键词，按名称模糊匹配
  is_enabled?: boolean; // 只筛启用（true）或停用（false）的配置
}

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
