// 与后端 /api/v1 契约对齐的共享类型定义。
// 后端响应统一信封：列表 { items, total, page, page_size }，错误 { code, message, request_id }。
// 本文件是前端侧契约的事实来源：后端新增或改名字段时必须同步这里的字段与注释。

// 平台级角色（登录后可在顶栏切换/展示的身份）。三个成员含义：
//   admin —— 平台管理员，全站最高权限，可管理用户、模型配置等全局资源；
//   test  —— 测试工程师，常规业务身份，主要在组织与项目内执行测试；
//   dev   —— 开发工程师，以开发视角查看与配置资源。
export type PlatformRole = 'admin' | 'test' | 'dev';

// 平台用户（/users 列表与当前登录用户共用同一结构）。
export interface User {
  id: number; // 用户主键 ID
  username: string; // 登录用户名，全平台唯一
  role: PlatformRole; // 平台级角色，决定全站可见范围与菜单权限
  is_active: boolean; // 账号是否启用；被停用后无法登录
  created_at: string; // 创建时间，ISO 8601 字符串
  updated_at: string; // 最后更新时间，ISO 8601 字符串
}

// 登录接口的返回体：token 与用户信息一起下发。
export interface TokenResponse {
  access_token: string; // JWT 访问令牌，写入 Authorization: Bearer 头
  token_type: string; // 令牌类型，固定为 bearer
  expires_in: number; // 令牌剩余有效期，单位秒
  user: User; // 当前登录用户快照，前端据此判断权限
}

// 后端统一的分页信封：所有列表接口都按这个形状返回。
export interface Paginated<T> {
  items: T[]; // 当前页数据
  total: number; // 过滤条件下的总条数（不是当前页条数）
  page: number; // 当前页码，从 1 开始
  page_size: number; // 每页条数
}

// 组织

// 组织级角色。三个成员含义：
//   owner —— 组织拥有者，可管理成员与移出组织；
//   admin —— 组织管理员，可管理成员但非最终负责人；
//   member —— 普通成员，只有组织内的常规访问权。
export type OrganizationRole = 'owner' | 'admin' | 'member';

// 组织条目（列表页与成员管理共用）。
export interface Organization {
  id: number; // 组织主键 ID
  name: string; // 组织名称
  owner_id: number; // 组织拥有者的用户 ID
  my_role: string | null; // 当前登录用户在该组织的角色；null 表示未加入
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
  member_count: number; // 成员总数，用于展示人数
}

// 组织成员条目（含 Agent 调用开关与模型白名单）。
export interface OrganizationMember {
  user_id: number; // 成员用户 ID
  role: OrganizationRole; // 该成员在组织内的角色
  agent_enabled: boolean; // 是否允许该成员通过 Agent 调用大模型
  allowed_model_ids: string[]; // 允许调用的模型配置 ID 白名单；空数组表示不额外限制
  is_org_owner: boolean; // 是否组织拥有者（拥有者不可被移出/降级）
  created_at: string; // 加入时间
}

// 新增/修改组织成员的写入载荷（只提交可变字段）。
export interface MemberGrant {
  user_id: number; // 目标成员用户 ID
  role: OrganizationRole; // 要授予的组织角色
  agent_enabled: boolean; // 是否开启 Agent 调用
  allowed_model_ids: string[]; // 模型白名单
}

// 选人器里的候选人（用于“邀请成员”搜索框）。
export interface UserCandidate {
  id: number; // 用户 ID
  username: string; // 用户名
  role: string; // 平台级角色，仅用于展示提示
  is_active: boolean; // 是否启用；停用的用户不可被邀请
}

// 项目

// 项目级角色。三个成员含义：
//   viewer —— 只读查看者；
//   member —— 普通成员，可执行测试但不改配置；
//   editor —— 编辑者，可修改项目配置与成员。
export type ProjectRole = 'viewer' | 'member' | 'editor';

// 项目条目（列表页展示用，不含成员明细）。
export interface Project {
  id: number; // 项目主键 ID
  name: string; // 项目名称
  description: string | null; // 项目描述，可为空
  owner_id: number; // 项目负责人的用户 ID
  owner_username: string | null; // 负责人用户名（后端查不到时为 null）
  organization_id: number | null; // 所属组织 ID；null 表示未归属任何组织
  organization_name: string | null; // 所属组织名称；null 表示未归属
  my_role: string | null; // 当前登录用户在项目内的角色；null 表示无权限
  member_count: number; // 项目成员数
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
}

// 项目详情页返回：项目字段 + 成员列表。
export interface ProjectDetail extends Project {
  members: ProjectMember[]; // 项目成员明细
}

// 项目成员条目。
export interface ProjectMember {
  user_id: number; // 成员用户 ID
  username: string | null; // 成员用户名（被删除的用户显示为 null）
  role: string; // 项目内角色，取值见 ProjectRole
  is_owner: boolean; // 是否为项目负责人（负责人不可被移出）
  created_by: number | null; // 谁拉他进来的（操作用户 ID），可为空
  created_at: string; // 加入时间
  updated_at: string; // 角色最后变更时间
}

// 出站白名单目标：测试流量允许访问的外部地址。
export interface OutboundTarget {
  id: number; // 白名单条目 ID
  project_id: number; // 所属项目 ID
  scheme: string; // 协议，如 http / https
  host: string; // 目标主机名或 IP
  port: number; // 目标端口
  is_production: boolean; // 是否生产地址（生产地址审批更严格）
  enabled: boolean; // 是否生效
  approved_by: number; // 审批人用户 ID
  created_at: string; // 创建时间
}

// 模型配置

// 单个大模型调用配置。
export interface ModelConfiguration {
  id: number; // 配置主键 ID
  domain_id: string; // 业务域标识，用于区分模型归属领域
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
  sort_order: number; // 排序权重，越小越靠前
  has_api_key: boolean; // 是否已配置密钥（前端只读，不回传密钥明文）
  masked_api_key: string; // 掩码后的密钥，仅用于展示已配置状态
  created_by: number | null; // 创建人用户 ID
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
}

// 环境配置

// 测试环境条目：描述被测网关的地址与默认请求头。
export interface Environment {
  id: number | null; // 环境 ID；null 表示尚未保存的新建草稿
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

// 通知

// 单条通知。
export interface Notification {
  id: number; // 通知 ID
  event_type: string; // 事件类型，决定前端如何渲染与跳转
  title: string; // 通知标题
  body: string | null; // 通知正文，可为空
  payload: Record<string, unknown> | null; // 事件附加数据，结构随 event_type 变化
  project_id: number | null; // 关联项目 ID；null 表示非项目级事件
  organization_id: number | null; // 关联组织 ID；null 表示非组织级事件
  is_read: boolean; // 是否已读
  read_at: string | null; // 已读时间；未读为 null
  created_at: string; // 产生时间
}

// 通知列表返回：分页信封 + 未读总数。
export interface NotificationList extends Paginated<Notification> {
  unread_total: number; // 当前用户未读通知总数，用于角标
}

// 通知概览统计（角标/提醒条用）。
export interface NotificationSummary {
  total: number; // 通知总数
  unread_total: number; // 未读总数
}

// 看板

// 看板统计口径：告诉前端这次统计的范围与依据。
export interface DashboardScope {
  subject: string; // 口径描述文本，直接展示给用户
  user_id: number; // 被统计的用户 ID
  role: string; // 该用户的平台角色
  is_platform_admin: boolean; // 是否为平台管理员（管理员看全站数据）
  organization_ids: number[]; // 纳入统计的组织 ID 列表
  project_ids: number[]; // 纳入统计的项目 ID 列表
}

// 看板单个统计卡片。
export interface StatCard {
  key: string; // 卡片标识，用于前端按位渲染
  label: string; // 卡片标题
  value: number; // 数值
  hint: string | null; // 辅助说明，如环比或口径备注；可为空
}

// 看板总览接口返回。
export interface DashboardOverview {
  scope: DashboardScope; // 统计口径
  stats: StatCard[]; // 卡片数据列表
}

// 项目摘要条目（看板/搜索场景的精简项目视图）。
export interface ProjectSummaryItem {
  id: number; // 项目 ID
  name: string; // 项目名称
  description: string | null; // 描述
  owner_id: number; // 负责人用户 ID
  owner_username: string | null; // 负责人用户名
  organization_id: number | null; // 所属组织 ID
  organization_name: string | null; // 所属组织名称
  my_role: string | null; // 当前用户角色；null 表示无权限
  member_count: number; // 成员数
  updated_at: string | null; // 最后更新时间；已删除项目为 null
}

// 项目摘要列表返回。
export interface ProjectSummaryResponse {
  total: number; // 命中总数
  items: ProjectSummaryItem[]; // 命中条目
}

// 缺陷（bug 表对应的 DTO）。字段全部与后端 BugResponse 对齐，snake_case。
export type BugStatus = '待确认' | '处理中' | '已修复' | '已关闭' | '已拒绝';
export type BugSeverity = 1 | 2 | 3 | 4;

export interface Bug {
  id: number; // 缺陷主键
  project_id: number; // 所属项目 ID
  project_name: string | null; // 项目名称；服务端 join 后填充
  title: string; // 缺陷标题
  description: string | null; // 描述
  severity: BugSeverity; // 严重度 1-4（1=致命，4=轻微）
  status: BugStatus; // 状态
  steps_to_reproduce: string | null; // 复现步骤
  environment: string | null; // 环境
  reporter_id: number; // 报告人用户 ID
  reporter_username: string | null; // 报告人用户名
  assignee_id: number | null; // 处理人用户 ID；未分配为 null
  assignee_username: string | null; // 处理人用户名
  created_at: string; // 创建时间
  updated_at: string; // 最后更新时间
}

// 缺陷列表查询参数。
export interface BugListQuery {
  page?: number; // 页码，从 1 开始
  page_size?: number; // 每页条数
  project_id?: number; // 按项目过滤
  status?: BugStatus; // 按状态过滤
  severity?: BugSeverity; // 按严重度过滤
  assignee_id?: number; // 按处理人过滤
  keyword?: string; // 关键字：命中 title / description
}

// 健康检查项（/ready 接口用）。
export interface ReadyCheckItem {
  name: string; // 检查项名称，如 database / redis
  status: string; // 检查状态，如 ok / fail
  detail: string | null; // 失败原因或补充信息；正常时为 null
}

// 健康检查整体返回。
export interface ReadyResponse {
  status: string; // 整体状态，如 ready / degraded
  checks: ReadyCheckItem[]; // 各项检查明细
}

// 统一错误体

// 后端统一错误信封：所有非 2xx 响应都长这样。
export interface ApiErrorBody {
  code: string; // 机器可读的错误码，前端按它做分支处理
  message: string; // 可直接展示给用户的错误描述
  request_id: string; // 请求追踪 ID，用于联系后端排查
}

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
  content: string; // curl 串或 openapi/swagger 文本
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

// ============================================================ 业务管理
// 字段命名与后端 business schemas 严格对齐（snake_case）。
// 第一阶段 10 个实体 + 聚合详情（BusinessFlowDetail / BusinessActionDetail / BusinessBindingDetail）。
// 权限：读 = 项目可见（viewer+）；写 = 项目成员（member+）；越权按 404 返回，前端不展示。

export type BusinessDomainStatus = 'ACTIVE' | 'INACTIVE';
export type BusinessFlowStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
export type BusinessActionType = 'API' | 'WEB' | 'MOBILE';
export type BusinessBindingType = 'API' | 'WEB' | 'MOBILE';
export type BusinessPreconditionType = 'VARIABLE' | 'STATE' | 'BUSINESS' | 'TEXT';
export type BusinessPreconditionOperator = 'EQ' | 'NE' | 'IN' | 'CONTAINS';
export type BusinessVariableDirection = 'INPUT' | 'OUTPUT';
export type BusinessVariableDataType =
  | 'STRING' | 'INTEGER' | 'NUMBER' | 'BOOLEAN' | 'OBJECT' | 'ARRAY';
export type BusinessApiMappingDirection = 'INPUT' | 'OUTPUT';
export type BusinessApiLocation = 'BODY' | 'HEADER' | 'QUERY' | 'PATH' | 'RESPONSE';
export type BusinessRuleType = 'GENERAL' | 'CONSTRAINT' | 'PRECONDITION';

// ---- 业务域 ----
export interface BusinessDomain {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  sort: number;
  status: string;
  created_at: string;
  updated_at: string;
}
export interface BusinessDomainCreate {
  name: string;
  description?: string | null;
  sort?: number;
  status?: BusinessDomainStatus;
}
export interface BusinessDomainUpdate {
  name?: string;
  description?: string | null;
  sort?: number;
  status?: BusinessDomainStatus;
}
export type BusinessDomainListResponse = Paginated<BusinessDomain>;

// ---- 业务流程 ----
export interface BusinessFlow {
  id: number;
  project_id: number;
  domain_id: number;
  name: string;
  description: string | null;
  status: string;
  version: number;
  created_at: string;
  updated_at: string;
}
export interface BusinessFlowCreate {
  name: string;
  description?: string | null;
  status?: BusinessFlowStatus;
  domain_id: number;
}
export interface BusinessFlowUpdate {
  name?: string;
  description?: string | null;
  status?: BusinessFlowStatus;
}
export type BusinessFlowListResponse = Paginated<BusinessFlow>;

// ---- 业务动作 ----
export interface BusinessAction {
  id: number;
  flow_id: number;
  name: string;
  description: string | null;
  action_key: string;
  sort: number;
  action_type: BusinessActionType;
  created_at: string;
  updated_at: string;
}
export interface BusinessActionCreate {
  name: string;
  description?: string | null;
  action_key: string;
  sort?: number;
  action_type?: BusinessActionType;
}
export interface BusinessActionUpdate {
  name?: string;
  description?: string | null;
  action_key?: string;
  sort?: number;
  action_type?: BusinessActionType;
}
export interface BusinessActionReorderItem {
  action_id: number;
  sort: number;
}
export interface BusinessActionReorder {
  items: BusinessActionReorderItem[];
}

// ---- 前置条件 ----
export interface BusinessPrecondition {
  id: number;
  action_id: number;
  type: BusinessPreconditionType;
  target: string;
  operator: BusinessPreconditionOperator;
  expected_value: string | null;
  description: string | null;
  sort: number;
  created_at: string;
  updated_at: string;
}
export interface BusinessPreconditionCreate {
  type: BusinessPreconditionType;
  target: string;
  operator?: BusinessPreconditionOperator;
  expected_value?: string | null;
  description?: string | null;
  sort?: number;
}
export interface BusinessPreconditionUpdate {
  type?: BusinessPreconditionType;
  target?: string;
  operator?: BusinessPreconditionOperator;
  expected_value?: string | null;
  description?: string | null;
  sort?: number;
}

// ---- 业务变量 ----
export interface BusinessVariable {
  id: number;
  action_id: number;
  direction: BusinessVariableDirection;
  name: string;
  data_type: BusinessVariableDataType;
  required: boolean;
  description: string | null;
  sort: number;
  created_at: string;
  updated_at: string;
}
export interface BusinessVariableCreate {
  direction: BusinessVariableDirection;
  name: string;
  data_type?: BusinessVariableDataType;
  required?: boolean;
  description?: string | null;
  sort?: number;
}
export interface BusinessVariableUpdate {
  direction?: BusinessVariableDirection;
  name?: string;
  data_type?: BusinessVariableDataType;
  required?: boolean;
  description?: string | null;
  sort?: number;
}

// ---- 业务状态 ----
export interface BusinessState {
  id: number;
  action_id: number;
  entity: string;
  pre_state: string | null;
  post_state: string | null;
  created_at: string;
  updated_at: string;
}
export interface BusinessStateCreate {
  entity: string;
  pre_state?: string | null;
  post_state?: string | null;
}
export interface BusinessStateUpdate {
  entity?: string;
  pre_state?: string | null;
  post_state?: string | null;
}

// ---- 变量引用 ----
export interface BusinessVariableRef {
  id: number;
  flow_id: number;
  source_action_id: number;
  source_variable: string;
  target_action_id: number;
  target_variable: string;
  created_at: string;
  updated_at: string;
}
export interface BusinessVariableRefCreate {
  source_action_id: number;
  source_variable: string;
  target_action_id: number;
  target_variable: string;
}

// ---- 业务绑定 ----
export interface BusinessBinding {
  id: number;
  action_id: number;
  binding_type: BusinessBindingType;
  api_id: number | null;
  config_json: Record<string, unknown> | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface BusinessBindingCreate {
  binding_type?: BusinessBindingType;
  api_id?: number | null;
  config_json?: Record<string, unknown> | null;
  enabled?: boolean;
}
export interface BusinessBindingUpdate {
  binding_type?: BusinessBindingType;
  api_id?: number | null;
  config_json?: Record<string, unknown> | null;
  enabled?: boolean;
}
export interface BusinessBindingDetail extends BusinessBinding {
  valid: boolean;
  invalid_reason: string | null;
  api_name: string | null;
  api_method: string | null;
  api_path: string | null;
  api_status: string | null;
  input_mappings: BusinessApiMapping[];
  output_mappings: BusinessApiMapping[];
}

// ---- API 映射 ----
export interface BusinessApiMapping {
  id: number;
  binding_id: number;
  direction: BusinessApiMappingDirection;
  business_variable: string;
  api_location: BusinessApiLocation;
  api_field: string | null;
  expression: string | null;
  created_at: string;
  updated_at: string;
}
export interface BusinessApiMappingCreate {
  direction: BusinessApiMappingDirection;
  business_variable: string;
  api_location: BusinessApiLocation;
  api_field?: string | null;
  expression?: string | null;
}
export interface BusinessApiMappingUpdate {
  direction?: BusinessApiMappingDirection;
  business_variable?: string;
  api_location?: BusinessApiLocation;
  api_field?: string | null;
  expression?: string | null;
}

// ---- 业务规则 ----
export interface BusinessRule {
  id: number;
  project_id: number;
  flow_id: number | null;
  action_id: number | null;
  name: string;
  description: string | null;
  rule_type: BusinessRuleType;
  expression: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface BusinessRuleCreate {
  name: string;
  description?: string | null;
  rule_type?: BusinessRuleType;
  expression?: string | null;
  enabled?: boolean;
  flow_id?: number | null;
  action_id?: number | null;
}
export interface BusinessRuleUpdate {
  name?: string;
  description?: string | null;
  rule_type?: BusinessRuleType;
  expression?: string | null;
  enabled?: boolean;
}
export type BusinessRuleListResponse = Paginated<BusinessRule>;

// ---- 聚合详情 ----
export interface BusinessActionDetail extends BusinessAction {
  preconditions: BusinessPrecondition[];
  input_variables: BusinessVariable[];
  output_variables: BusinessVariable[];
  states: BusinessState[];
  binding: BusinessBindingDetail | null;
}
export interface BusinessFlowDetail extends BusinessFlow {
  domain_name: string | null;
  actions: BusinessActionDetail[];
  variable_refs: BusinessVariableRef[];
  rules: BusinessRule[];
}
