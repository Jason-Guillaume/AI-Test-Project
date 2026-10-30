


// 接口管理（API Catalog）

// 接口生命周期状态。
export type ApiStatus = 'ACTIVE' | 'DRAFT' | 'DEPRECATED' | 'DEVELOPING' | 'MOCK';

// 接口来源：手工录入或从某种外部格式导入。
export type ApiSourceType = 'MANUAL' | 'CURL' | 'OPENAPI' | 'SWAGGER' | 'POSTMAN' | 'APIFOX';

// 请求参数位置。
export type ParamLocation = 'PATH' | 'QUERY' | 'HEADER' | 'COOKIE' | 'BODY';

// 请求体类型：none 无 body / json / form / multipart / raw。
export type BodyType = 'none' | 'json' | 'form' | 'multipart' | 'raw';

// 接口间关联类型：前置条件 / 输出输入传递 / 后续步骤。
export type RelationType = 'PRECONDITION' | 'OUTPUT_INPUT' | 'FOLLOW_UP';

// 变更记录类型：创建/更新/参数增删/参数类型变/必填变/响应变/模块变。
export type ChangeType =
  | 'CREATED'
  | 'UPDATED'
  | 'PARAM_ADDED'
  | 'PARAM_REMOVED'
  | 'PARAM_TYPE_CHANGED'
  | 'REQUIRED_CHANGED'
  | 'RESPONSE_CHANGED'
  | 'MODULE_CHANGED';

// 导入预览分类：新增 / 已存在不改 / 有变更 / 无变化。
export type ImportClassification = 'NEW' | 'EXISTING' | 'CHANGED' | 'UNCHANGED';

// Internal API Schema —— 统一中间表示（所有 parser 输出，服务层消费，不依赖原始格式）。
export interface InternalParameter {
  name: string; // 参数名
  location: ParamLocation; // 参数位置
  type: string; // 参数类型，如 string/integer/boolean
  required: boolean; // 是否必填
  description: string | null; // 说明
  example: string | null; // 示例值
  default_value: string | null; // 默认值
  schema_json: Record<string, unknown> | null; // JSON Schema 片段
  sort: number; // 排序权重
}

export interface InternalBody {
  body_type: BodyType; // 请求体类型
  content_type: string | null; // Content-Type
  schema_json: Record<string, unknown> | null; // 结构定义（JSON Schema 或 form 字段结构）
  raw_text: string | null; // raw 模式下的原始文本
}

export interface InternalResponse {
  status_code: number; // HTTP 状态码
  description: string | null; // 说明
  schema_json: Record<string, unknown> | null; // 响应结构
  example_json: string | null; // 示例响应体
  sort: number; // 排序权重
}

export interface InternalApiSchema {
  name: string; // 接口名称
  description: string | null; // 描述
  method: string; // HTTP 方法（大写）
  path: string; // 路径（以 / 开头）
  auth_type: string; // 鉴权类型
  content_type: string; // Content-Type
  parameters: InternalParameter[]; // 请求参数
  body: InternalBody; // 请求体
  responses: InternalResponse[]; // 响应
  tags: string[]; // 标签（用于模块推断）
  suggested_module: string | null; // 推荐模块名（parser 推断，不落库）
  source_type: ApiSourceType; // 来源
  source_hash: string | null; // 结构指纹（导入时计算）
}

// 接口管理实体（响应 DTO，snake_case，与后端 Pydantic Response 模型逐字段对齐）。
export interface ApiModule {
  id: number; // 模块主键
  project_id: number; // 所属项目 ID
  name: string; // 模块名（最多两级）
  parent_id: number | null; // 父模块 ID；一级为 null
  sort: number; // 排序权重
  is_default: boolean; // 是否为项目级「未分类」默认模块
  interface_count: number; // 模块下接口数（服务端聚合）
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
}

export interface ApiParameter {
  id: number; // 参数主键
  interface_id: number; // 所属接口 ID
  name: string; // 参数名
  location: ParamLocation; // 参数位置
  type: string; // 参数类型
  required: boolean; // 是否必填
  description: string | null; // 说明
  example: string | null; // 示例值
  default_value: string | null; // 默认值
  schema_json: Record<string, unknown> | null; // JSON Schema 片段
  sort: number; // 排序权重
}

export interface ApiRequestBody {
  id: number | null; // 请求体主键；无 body 时为 null
  interface_id: number; // 所属接口 ID
  body_type: BodyType; // 请求体类型
  content_type: string | null; // Content-Type
  schema_json: Record<string, unknown> | null; // 结构定义
  raw_text: string | null; // raw 模式原始文本
}

export interface ApiResponseDef {
  id: number; // 响应主键
  interface_id: number; // 所属接口 ID
  status_code: number; // HTTP 状态码
  description: string | null; // 说明
  schema_json: Record<string, unknown> | null; // 响应结构
  example_json: string | null; // 示例响应体
  sort: number; // 排序权重
}

// 接口基本信息（列表项）。
export interface ApiInterface {
  id: number; // 接口主键
  project_id: number; // 所属项目 ID
  module_id: number | null; // 所属模块 ID；null 表示未分类
  module_name: string | null; // 模块名（服务端 join）
  name: string; // 接口名
  description: string | null; // 描述
  method: string; // HTTP 方法
  path: string; // 路径
  auth_type: string; // 鉴权类型
  content_type: string; // Content-Type
  status: ApiStatus; // 生命周期状态
  source_type: ApiSourceType; // 来源
  version: number; // 版本号，每次更新 +1
  source_hash: string | null; // 结构指纹
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
}

// 接口详情：基本信息 + 参数 + body + 响应概要。
export interface ApiInterfaceDetail extends ApiInterface {
  parameters: ApiParameter[]; // 请求参数
  body: ApiRequestBody | null; // 请求体
  responses: ApiResponseDef[]; // 响应
}

export interface ApiRelation {
  id: number; // 关联主键
  project_id: number; // 所属项目 ID
  source_api_id: number; // 源接口 ID
  target_api_id: number; // 目标接口 ID
  source_api_name: string | null; // 源接口名（服务端 join）
  target_api_name: string | null; // 目标接口名（服务端 join）
  relation_type: RelationType; // 关联类型
  variable_name: string | null; // 传递变量名
  extract_path: string | null; // 提取路径
  created_at: string; // 创建时间
}

export interface ApiImportRecord {
  id: number; // 导入记录主键
  project_id: number; // 所属项目 ID
  source_type: ApiSourceType; // 来源
  file_name: string | null; // 文件名
  source_hash: string | null; // 批次结构指纹
  total: number; // 总条数
  created_count: number; // 新建数
  updated_count: number; // 更新数
  skipped_count: number; // 跳过数
  created_by: number | null; // 操作人 ID
  created_at: string; // 导入时间
}

export interface ApiChangeLog {
  id: number; // 变更记录主键
  interface_id: number; // 所属接口 ID
  change_type: ChangeType; // 变更类型
  diff_json: Record<string, unknown> | null; // 差异明细
  source_hash_before: string | null; // 变更前指纹
  source_hash_after: string | null; // 变更后指纹
  summary: string | null; // 摘要
  created_by: number | null; // 操作人 ID
  created_at: string; // 变更时间
}

// 写入载荷（请求体 DTO，snake_case，与后端 *Create/*Update/*In 模型对齐）。
export interface ApiModuleCreate {
  name: string; // 模块名（必填）
  parent_id?: number | null; // 父模块 ID；null 为一级
  sort?: number; // 排序
}

export interface ApiModuleUpdate {
  name?: string; // 改名（未分类不可改）
  sort?: number; // 改排序
}

export interface ApiModuleMove {
  parent_id?: number | null; // 目标父模块；null 移到一级
}

export interface ApiParameterIn {
  name: string; // 参数名
  location: ParamLocation; // 位置
  type?: string; // 类型，默认 string
  required?: boolean; // 是否必填
  description?: string | null; // 说明
  example?: string | null; // 示例
  default_value?: string | null; // 默认值
  schema_json?: Record<string, unknown> | null; // JSON Schema 片段
  sort?: number; // 排序
}

export interface ApiBodyIn {
  body_type?: BodyType; // 类型
  content_type?: string | null; // Content-Type
  schema_json?: Record<string, unknown> | null; // 结构
  raw_text?: string | null; // 原始文本
}

export interface ApiResponseIn {
  status_code: number; // 状态码（100-599）
  description?: string | null; // 说明
  schema_json?: Record<string, unknown> | null; // 响应结构
  example_json?: string | null; // 示例
  sort?: number; // 排序
}

export interface ApiInterfaceCreate {
  module_id?: number | null; // 所属模块；null 归未分类
  name: string; // 接口名
  description?: string | null; // 描述
  method: string; // HTTP 方法
  path: string; // 路径
  auth_type?: string; // 鉴权类型
  content_type?: string; // Content-Type
  status?: ApiStatus; // 状态
  parameters?: ApiParameterIn[]; // 请求参数
  body?: ApiBodyIn; // 请求体
  responses?: ApiResponseIn[]; // 响应
}

export interface ApiInterfaceUpdate {
  module_id?: number | null; // 移动模块
  name?: string; // 改名
  description?: string | null; // 改描述
  method?: string; // 改方法
  path?: string; // 改路径
  auth_type?: string; // 改鉴权
  content_type?: string; // 改 Content-Type
  status?: ApiStatus; // 改状态
}

export interface ApiInterfaceMove {
  module_id?: number | null; // 目标模块；null 归未分类
}

export interface ApiRequestBundle {
  parameters: ApiParameterIn[]; // 参数（整体替换）
  body: ApiBodyIn; // 请求体（整体替换）
}

export interface ApiRequestBundleResponse {
  parameters: ApiParameter[]; // 参数列表
  body: ApiRequestBody | null; // 请求体
}

export interface ApiResponsesBundle {
  responses: ApiResponseIn[]; // 响应列表（整体替换）
}

export interface ApiResponsesBundleResponse {
  responses: ApiResponseDef[]; // 响应列表
}

export interface ApiRelationCreate {
  source_api_id: number; // 源接口 ID
  target_api_id: number; // 目标接口 ID
  relation_type: RelationType; // 关联类型
  variable_name?: string | null; // 传递变量名
  extract_path?: string | null; // 提取路径
}

// 接口列表查询参数。
export interface ApiListQuery {
  page?: number; // 页码
  page_size?: number; // 每页条数
  keyword?: string; // 关键字：命中 name/path
  method?: string; // HTTP 方法过滤
  module_id?: number; // 模块过滤
  status?: ApiStatus; // 状态过滤
}

// {items, total} 形态的列表响应（关联 / 变更记录 / 导入记录）。
export interface ApiItemListResponse<T> {
  items: T[]; // 数据项
  total: number; // 总条数
}

// 导入预览/确认/调试 DTO。
export interface ApiImportPreviewRequest {
  source_type: ApiSourceType; // 来源类型
  content: string; // cURL、OpenAPI/Swagger 或 Postman 文档文本
  file_name?: string | null; // 文件名（可选）
  user_module_id?: number | null; // 用户指定的目标模块
  tag_to_module_map?: Record<string, number> | null; // tag→模块映射
}

export interface ApiImportPreviewItem {
  classification: ImportClassification; // 分类
  schema: InternalApiSchema; // 解析后的内部 schema
  proposed_module_id: number | null; // 推荐模块 ID（已存在则非空，待建为 null）
  proposed_module_name: string; // 推荐模块名
  existing_interface_id: number | null; // 命中的已有接口 ID
  diff_summary: Record<string, unknown> | null; // 差异摘要
  warnings: string[]; // 解析告警
}

export interface ApiImportPreviewResponse {
  project_id: number; // 项目 ID
  source_type: ApiSourceType; // 来源
  source_hash: string | null; // 批次指纹
  total: number; // 总条数
  new_count: number; // 新增数
  existing_count: number; // 已存在数
  changed_count: number; // 有变更数
  unchanged_count: number; // 无变化数
  items: ApiImportPreviewItem[]; // 预览项
}

export interface ApiImportConfirmRequest {
  source_type: ApiSourceType; // 来源
  content: string; // 原始文本（重新解析，不信任预览缓存）
  file_name?: string | null; // 文件名
  user_module_id?: number | null; // 目标模块
  tag_to_module_map?: Record<string, number> | null; // tag→模块映射
  selected_items?: number[] | null; // 选中的预览项序号（0-based）；null 全部
  overwrite_changed?: boolean; // 是否覆盖有变更项
}

export interface ApiImportConfirmResponse {
  record_id: number; // 导入记录 ID
  total: number; // 总条数
  created_count: number; // 新建数
  updated_count: number; // 更新数
  skipped_count: number; // 跳过数
  source_hash: string | null; // 批次指纹
}

// 调试请求（仅平台管理员）。override_* 字段覆盖接口默认参数/头/体。
export interface ApiDebugRequest {
  environment_name: string; // 环境标识
  override_headers?: Record<string, string> | null; // 覆盖请求头
  override_path_params?: Record<string, string> | null; // 覆盖路径参数
  override_query?: Record<string, string> | null; // 覆盖 query 参数
  override_body?: unknown | null; // 覆盖请求体
  timeout?: number; // 超时秒（1-120）
}

export interface ApiDebugResult {
  status_code: number; // 响应状态码
  response_body: string; // 响应体文本（截断保护）
  response_headers: Record<string, string>; // 响应头
  response_time_ms: number; // 耗时毫秒
  request_url: string; // 实际请求 URL
  outbound_target_id: number | null; // 命中的出站白名单条目 ID
}
