// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。

/** 模型供应商标目项，用于新建/编辑表单的服务商下拉框。 */
export interface ProviderCatalogItem {
  value: string; // 服务商标识，提交给后端的 provider 值
  label: string; // 展示名称
}

/** 新建模型配置的请求体，对应 POST /model-configs。 */
export interface ModelConfigurationCreate {
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


// 模型配置

// 单个大模型调用配置。
export interface ModelConfiguration {
  id: number; // 配置主键 ID
  domain_id: string; // 后端生成的内部稳定标识，用于组织授权与模型路由，不在模型配置页展示
  label: string; // 展示名称
  provider: string; // 服务商标识，如 openai / dashscope
  api_base: string; // 服务端点 base URL
  model_name: string; // 实际调用的模型名
  temperature: number; // 采样温度
  max_tokens: number; // 单次响应最大 token 数
  timeout: number; // 单次调用超时，单位秒
  cost_per_1k_input: number; // 每 1k 输入 token 成本
  cost_per_1k_output: number; // 每 1k 输出 token 成本
  is_enabled: boolean; // 是否启用（停用后不出现在可选模型中）
  is_default: boolean; // 是否为该域默认模型
  fallback_model_ids: number[]; // 按顺序尝试的备用模型配置 ID
  sort_order: number; // 排序权重，越小越靠前
  has_api_key: boolean; // 是否已配置密钥（前端只读，不回传密钥明文）
  masked_api_key: string; // 掩码后的密钥，仅用于展示已配置状态
  created_by: number | null; // 创建人用户 ID
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
}
