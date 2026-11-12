// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。

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

/** 新建项目环境配置；base_url 必填，地址只保存在指定项目。 */
export interface ProjectEnvironmentCreate extends EnvironmentCreate {
  base_url: string;
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
  project_id?: number; // 管理端指定项目时，返回该项目自己的环境配置
}


// 环境配置

// 测试环境条目：描述被测网关的地址与默认请求头。
export interface Environment {
  id: number | null; // 环境 ID；null 表示尚未保存的新建草稿
  project_id?: number | null; // 项目环境配置的归属项目；全局模板为 null
  name: string; // 环境标识（slug），用于 URL 拼接
  display_name: string; // 展示名称
  base_url: string; // 被测服务 base URL
  gateway_prefix: string; // 网关前缀，拼在 base_url 之后
  default_headers: Record<string, string>; // 默认请求头，如固定鉴权头
  description: string | null; // 环境说明
  is_default: boolean; // 是否为默认环境
  is_active: boolean; // 是否启用
  created_by: number | null; // 创建人用户 ID
  updated_by: number | null; // 最后修改人用户 ID
  created_at: string | null; // 创建时间；草稿态为 null
  updated_at: string | null; // 更新时间；草稿态为 null
}
