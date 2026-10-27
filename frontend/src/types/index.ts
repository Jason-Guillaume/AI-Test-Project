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

// 工作台统计图。
export interface DashboardExecutionTrendItem {
  date: string;
  total: number;
  passed: number;
  failed: number;
}

export interface DashboardDailyCount {
  date: string;
  count: number;
}

export interface DashboardDefectSeverityItem {
  severity: 1 | 2 | 3 | 4;
  label: string;
  value: number;
}

export interface DashboardCharts {
  scope: DashboardScope;
  days: number;
  execution_trend: DashboardExecutionTrendItem[];
  defect_severity: DashboardDefectSeverityItem[];
  case_generation: DashboardDailyCount[];
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

// ============================================================ 业务管理
// 字段命名与后端 business schemas 严格对齐（snake_case）。
// 第一阶段 10 个实体 + 聚合详情（BusinessFlowDetail / BusinessActionDetail / BusinessBindingDetail）。
// 权限：读 = 项目可见（viewer+）；写 = 项目成员（member+）；越权按 404 返回，前端不展示。

export type BusinessDomainStatus = 'ACTIVE' | 'INACTIVE';
export type BusinessFlowStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
export type BusinessActionType = 'NORMAL';
export type BusinessBindingType = 'API' | 'WEB';
export type BusinessPreconditionType = 'VARIABLE' | 'STATE' | 'BUSINESS' | 'TEXT';
export type BusinessPreconditionOperator = 'EQ' | 'NE' | 'IN' | 'CONTAINS' | 'EXISTS' | 'NOT_EXISTS';
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
  revision: number;
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
  revision?: number;
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
  action_type: string;
  revision: number;
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
  revision?: number;
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
  source_variable_id: number | null;
  target_action_id: number;
  target_variable: string;
  target_variable_id: number | null;
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
  name: string | null;
  is_default: boolean;
  sort: number;
  config_json: Record<string, unknown> | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
}
export interface BusinessBindingCreate {
  binding_type?: BusinessBindingType;
  api_id?: number | null;
  name?: string | null;
  is_default?: boolean;
  sort?: number;
  config_json?: Record<string, unknown> | null;
  enabled?: boolean;
}
export interface BusinessBindingUpdate {
  binding_type?: BusinessBindingType;
  api_id?: number | null;
  name?: string | null;
  is_default?: boolean;
  sort?: number;
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

// ---- 执行引擎 ----
export type FlowExecutionStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED';
export type ActionExecutionStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED';

export interface FlowExecutionRequest {
  environment_id: number;
  variables?: Record<string, unknown>;
}

export interface FlowExecution {
  id: number;
  project_id: number;
  flow_id: number;
  environment_id: number | null;
  status: FlowExecutionStatus;
  started_at: string | null;
  finished_at: string | null;
  context_json: Record<string, unknown> | null;
  error_message: string | null;
  error_code: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

export interface ActionExecution {
  id: number;
  flow_execution_id: number;
  action_id: number | null;
  binding_id: number | null;
  sequence: number;
  status: ActionExecutionStatus;
  request_snapshot: Record<string, unknown> | null;
  response_snapshot: Record<string, unknown> | null;
  input_context: Record<string, unknown> | null;
  output_context: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
  error_code: string | null;
  unverified_preconditions: Array<Record<string, unknown>> | null;
  created_at: string;
  updated_at: string;
}

export type FlowExecutionActionListResponse = Paginated<ActionExecution>;

// ============================================================ 测试管理
// 字段命名与后端 test_management schemas 严格对齐（snake_case）。
// 覆盖：测试资产 TestStrategy / TestPoint / TestCase（含前置条件 / 测试数据 / 步骤 / 断言
// 子实体 + 聚合详情 TestCaseDetail）、测试管理 TestSuite / TestPlan / TestRun / CaseExecution。
// §27：source_type 预留 AI 取值（当前仅 MANUAL，后端校验；前端下拉只给 MANUAL）。
// §25：所有测试资产归属 Project，跨项目访问按 404 返回，前端不展示。
// §26：TestCase.revision 乐观锁——并发更新冲突返回 409，前端提示「当前测试用例已被其他用户修改」。
// §16：TestCase 通过 target_type 路由执行器：API→ApiRequestExecutor、
//      BUSINESS_FLOW→BusinessFlowExecutor、BUSINESS_ACTION→复用业务执行器单步。

// ---- 枚举字面量（与后端 Literal/常量元组逐项对齐）----
export type TestStrategyCategory =
  | 'FUNCTIONAL' | 'PARAMETER' | 'BOUNDARY' | 'AUTH' | 'PERMISSION'
  | 'BUSINESS' | 'EXCEPTION' | 'IDEMPOTENCY' | 'SECURITY' | 'DATA_CONSISTENCY';
export type TestPriority = 'P0' | 'P1' | 'P2' | 'P3';
export type TestTargetType = 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION' | 'WEB';
export type TestStatus = 'DRAFT' | 'ACTIVE' | 'DEPRECATED';
export type TestSourceType = 'MANUAL' | 'AI'; // §27：AI 预留，当前不产生
export type TestCaseType =
  | 'FUNCTIONAL' | 'BUSINESS' | 'NEGATIVE' | 'BOUNDARY' | 'PERMISSION' | 'SECURITY' | 'EXCEPTION';
export type TestPreconditionType =
  | 'VARIABLE' | 'TEXT' | 'FIXTURE' | 'API' | 'BUSINESS_ACTION' | 'BUSINESS_FLOW';
export type TestOperator =
  | 'EQ' | 'NE' | 'GT' | 'GE' | 'LT' | 'LE' | 'IN' | 'CONTAINS' | 'EXISTS' | 'NOT_EXISTS';
export type TestValueType = 'STRING' | 'INTEGER' | 'NUMBER' | 'BOOLEAN' | 'OBJECT' | 'ARRAY';
export type TestDataSourceType = 'STATIC' | 'ENVIRONMENT' | 'VARIABLE' | 'RUNTIME' | 'FAKER' | 'FIXTURE';
export type TestStepType = 'SETUP' | 'ACTION' | 'ASSERT' | 'CLEANUP';
export type TestAssertionType =
  | 'STATUS_CODE' | 'JSON_PATH' | 'HEADER' | 'RESPONSE_TIME' | 'CONTAINS' | 'NOT_CONTAINS';
export type TestSuiteType = 'SMOKE' | 'REGRESSION' | 'BUSINESS' | 'CUSTOM';
export type TestPlanStatus = 'DRAFT' | 'ACTIVE' | 'DISABLED';
export type TestExecutionMode = 'MANUAL' | 'SCHEDULED' | 'CI';
export type TestRunStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'CANCELLED';
export type CaseExecutionStatus = 'PENDING' | 'RUNNING' | 'PASSED' | 'FAILED' | 'SKIPPED' | 'ERROR';
export type CaseExecutorType = 'API' | 'BUSINESS_FLOW' | 'BUSINESS_ACTION'; // §16 路由依据

// ---- 测试策略 ----
export interface TestStrategy {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  category: string;
  enabled: boolean;
  source_type: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface TestStrategyCreate {
  name: string;
  description?: string | null;
  category?: TestStrategyCategory;
  enabled?: boolean;
}
export interface TestStrategyUpdate {
  name?: string;
  description?: string | null;
  category?: TestStrategyCategory;
  enabled?: boolean;
}

// ---- 测试点 ----
export interface TestPoint {
  id: number;
  project_id: number;
  strategy_id: number | null;
  name: string;
  description: string | null;
  priority: string;
  target_type: string;
  api_id: number | null;
  business_flow_id: number | null;
  business_action_id: number | null;
  status: string;
  source_type: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface TestPointCreate {
  name: string;
  description?: string | null;
  priority?: TestPriority;
  target_type?: TestTargetType;
  strategy_id?: number | null;
  api_id?: number | null;
  business_flow_id?: number | null;
  business_action_id?: number | null;
  status?: TestStatus;
}
export interface TestPointUpdate {
  name?: string;
  description?: string | null;
  priority?: TestPriority;
  target_type?: TestTargetType;
  strategy_id?: number | null;
  api_id?: number | null;
  business_flow_id?: number | null;
  business_action_id?: number | null;
  status?: TestStatus;
}

// ---- 测试用例 ----
export interface TestCase {
  id: number;
  project_id: number;
  test_point_id: number | null;
  name: string;
  description: string | null;
  priority: string;
  case_type: string;
  target_type: string;
  api_id: number | null;
  business_flow_id: number | null;
  business_action_id: number | null;
  status: string;
  enabled: boolean;
  revision: number; // §26 乐观锁版本号
  source_type: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface TestCaseCreate {
  name: string;
  description?: string | null;
  priority?: TestPriority;
  case_type?: TestCaseType;
  target_type?: TestTargetType;
  test_point_id?: number | null;
  api_id?: number | null;
  business_flow_id?: number | null;
  business_action_id?: number | null;
  status?: TestStatus;
  enabled?: boolean;
}
export interface TestCaseUpdate {
  name?: string;
  description?: string | null;
  priority?: TestPriority;
  case_type?: TestCaseType;
  target_type?: TestTargetType;
  test_point_id?: number | null;
  api_id?: number | null;
  business_flow_id?: number | null;
  business_action_id?: number | null;
  status?: TestStatus;
  enabled?: boolean;
  revision?: number; // §26：更新时携带当前 revision，不匹配 → 409
}

// ---- 用例子实体：前置条件 ----
export interface TestCasePrecondition {
  id: number;
  test_case_id: number;
  type: string;
  target: string | null;
  operator: string;
  expected_value: string | null;
  description: string | null;
  config_json: Record<string, unknown> | null;
  sort: number;
  created_at: string;
  updated_at: string;
}
export interface TestCasePreconditionCreate {
  type?: TestPreconditionType;
  target?: string | null;
  operator?: TestOperator;
  expected_value?: string | null;
  description?: string | null;
  config_json?: Record<string, unknown> | null;
  sort?: number;
}
export interface TestCasePreconditionUpdate {
  type?: TestPreconditionType;
  target?: string | null;
  operator?: TestOperator;
  expected_value?: string | null;
  description?: string | null;
  config_json?: Record<string, unknown> | null;
  sort?: number;
}

// ---- 用例子实体：测试数据 ----
export interface TestCaseData {
  id: number;
  test_case_id: number;
  name: string;
  value_type: string;
  value: string | null;
  source_type: string;
  required: boolean;
  description: string | null;
  config_json: Record<string, unknown> | null;
  sort: number;
  created_at: string;
  updated_at: string;
}
export interface TestCaseDataCreate {
  name: string;
  value_type?: TestValueType;
  value?: string | null;
  source_type?: TestDataSourceType;
  required?: boolean;
  description?: string | null;
  config_json?: Record<string, unknown> | null;
  sort?: number;
}
// 注意：Update 不含 name（数据项名不可改，与后端 TestCaseDataUpdate 一致）。
export interface TestCaseDataUpdate {
  value_type?: TestValueType;
  value?: string | null;
  source_type?: TestDataSourceType;
  required?: boolean;
  description?: string | null;
  config_json?: Record<string, unknown> | null;
  sort?: number;
}

// ---- 用例子实体：所需 Fixture（执行前由平台按依赖顺序生成）----
export interface TestCaseFixture {
  id: number;
  test_case_id: number;
  fixture_id: number;
  fixture_key: string;
  name: string;
  entity_type: string | null;
  scope: 'PROJECT' | 'GLOBAL';
  status: string;
  outputs: string[];
  sort: number;
}
export interface TestCaseFixtureCreate {
  fixture_key: string;
  sort?: number;
}

// ---- 用例子实体：步骤 ----
export interface TestStep {
  id: number;
  test_case_id: number;
  name: string;
  step_type: string;
  target_type: string | null;
  target_id: number | null;
  sort: number;
  config_json: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}
export interface TestStepCreate {
  name: string;
  step_type?: TestStepType;
  target_type?: TestTargetType | null;
  target_id?: number | null;
  sort?: number;
  config_json?: Record<string, unknown> | null;
}
export interface TestStepUpdate {
  name?: string;
  step_type?: TestStepType;
  target_type?: TestTargetType | null;
  target_id?: number | null;
  sort?: number;
  config_json?: Record<string, unknown> | null;
}

// ---- 用例子实体：断言 ----
export interface TestAssertion {
  id: number;
  test_case_id: number;
  step_id: number | null;
  assertion_type: string;
  source: string | null;
  path: string | null;
  operator: string;
  expected_value: string | null;
  required: boolean;
  sort: number;
  created_at: string;
  updated_at: string;
}
export interface TestAssertionCreate {
  assertion_type?: TestAssertionType;
  source?: string | null;
  path?: string | null;
  operator?: TestOperator;
  expected_value?: string | null;
  required?: boolean;
  step_id?: number | null;
  sort?: number;
}
export interface TestAssertionUpdate {
  assertion_type?: TestAssertionType;
  source?: string | null;
  path?: string | null;
  operator?: TestOperator;
  expected_value?: string | null;
  required?: boolean;
  step_id?: number | null;
  sort?: number;
}

// ---- 用例聚合详情（编辑器一次性拉取，减少往返）----
export interface TestCaseDetail extends TestCase {
  preconditions: TestCasePrecondition[];
  test_data: TestCaseData[];
  steps: TestStep[];
  assertions: TestAssertion[];
  fixtures: TestCaseFixture[];
}

// ---- 测试套件 ----
export interface TestSuite {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  suite_type: string;
  enabled: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface TestSuiteCreate {
  name: string;
  description?: string | null;
  suite_type?: TestSuiteType;
  enabled?: boolean;
}
export interface TestSuiteUpdate {
  name?: string;
  description?: string | null;
  suite_type?: TestSuiteType;
  enabled?: boolean;
}
export interface TestSuiteCaseAdd {
  test_case_id: number;
  sort?: number;
  enabled?: boolean;
}
export interface TestSuiteCaseResponse {
  id: number;
  suite_id: number;
  test_case_id: number;
  sort: number;
  enabled: boolean;
  created_at: string;
}

// ---- 测试计划 ----
export interface TestPlan {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  environment_id: number | null;
  status: string;
  execution_mode: string;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface TestPlanCreate {
  name: string;
  description?: string | null;
  environment_id?: number | null;
  status?: TestPlanStatus;
  execution_mode?: TestExecutionMode;
}
export interface TestPlanUpdate {
  name?: string;
  description?: string | null;
  environment_id?: number | null;
  status?: TestPlanStatus;
  execution_mode?: TestExecutionMode;
}
export interface TestPlanSuiteAdd {
  suite_id: number;
  sort?: number;
}
export interface TestPlanSuiteResponse {
  id: number;
  plan_id: number;
  suite_id: number;
  sort: number;
  created_at: string;
}

// ---- 测试执行 ----
export interface TestRunCreateRequest {
  environment_id?: number | null; // 覆盖计划环境；为空用计划环境
}
export interface TestRun {
  id: number;
  project_id: number;
  plan_id: number | null;
  environment_id: number | null;
  status: string;
  total: number;
  passed: number;
  failed: number;
  skipped: number;
  error: number;
  started_at: string | null;
  finished_at: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
// list_runs 返回分页信封（后端 TestRunListResponse）。
export type TestRunListResponse = Paginated<TestRun>;

export interface CaseExecution {
  id: number;
  test_run_id: number;
  test_case_id: number | null;
  status: string;
  executor_type: string | null;
  request_snapshot: Record<string, unknown> | null;
  response_snapshot: Record<string, unknown> | null;
  assertion_results: Array<Record<string, unknown>> | null;
  context_json: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}
// list_case_executions 返回分页信封（后端 CaseExecutionListResponse）。
export type CaseExecutionListResponse = Paginated<CaseExecution>;

// ---- 接口测试 Agent ----

export type AgentStage =
  | 'UNDERSTANDING'
  | 'CONTEXT_LOADING'
  | 'PLANNING'
  | 'TEST_POINT_REVIEW'
  | 'TEST_POINT_GENERATED'
  | 'TEST_CASE_REVIEW'
  | 'READY_TO_EXECUTE'
  | 'EXECUTING'
  | 'ANALYZING'
  // Phase 2：报告闭环与飞书通知阶段
  | 'REPORT_GENERATING'
  | 'REPORT_REVIEW'
  | 'NOTIFYING'
  | 'COMPLETED'
  | 'FAILED'
  | 'CLARIFY'
  // Web UI 智能体二期：步骤提案待人工确认的暂停点
  | 'WEB_STEP_REVIEW';

export type AgentAction =
  | 'confirm_points'
  | 'confirm_cases'
  | 'execute'
  | 'analyze'
  | 'regenerate_points'
  | 'regenerate_cases'
  | 'query'
  | 'continue'
  // Phase 2：报告 review 暂停点的两个出口
  | 'confirm_report'
  | 'skip_notification'
  // Web UI 智能体二期：沙箱步骤 review 暂停点的两个出口
  | 'confirm_web_step'
  | 'reject_web_step';

export type AgentMessageRole = 'USER' | 'ASSISTANT' | 'SYSTEM';

export type AgentMessageType =
  | 'TEXT'
  | 'TEST_PLAN'
  | 'TEST_POINTS'
  | 'TEST_CASES'
  | 'EXECUTION'
  | 'RESULT'
  | 'CLARIFY'
  // Phase 2：报告与通知产物消息（metadata_json 为脱敏 brief）
  | 'REPORT'
  | 'NOTIFICATION'
  // Web UI 智能体二期：步骤提案留痕与页面观测留痕（metadata_json 已脱敏）
  | 'WEB_AGENT_STEP'
  | 'WEB_OBSERVATION';

export interface AgentSession {
  id: number;
  project_id: number;
  user_id: number | null;
  title: string | null;
  status: string;
  current_stage: string;
  created_at: string;
  updated_at: string;
}

export interface AgentMessage {
  id: number;
  session_id: number;
  role: AgentMessageRole;
  message_type: AgentMessageType;
  content: string | null;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

export interface AgentSessionDetail {
  session: AgentSession;
  messages: AgentMessage[];
}

export interface SendMessageRequest {
  content?: string | null;
  action?: AgentAction | null;
  point_ids?: number[] | null;
  case_ids?: number[] | null;
  environment_id?: number | null;
  /** Phase 2：飞书通知渠道ID（confirm_report 时可选，缺省取项目首个启用渠道） */
  channel_id?: number | null;
  /** Web UI 智能体二期：绑定的受控浏览器会话 ID（交互式编写时必填） */
  web_session_id?: number | null;
}

export interface AgentWorkspace {
  stage: AgentStage;
  intent: string | null;
  test_plan: Record<string, unknown> | null;
  test_points: Array<Record<string, unknown>>;
  test_cases: Array<Record<string, unknown>>;
  test_run_id: number | null;
  execution_result: Record<string, unknown> | null;
  analysis: Record<string, unknown> | null;
  /** Phase 2：已生成报告的ID */
  report_id: number | null;
  /** Phase 2：脱敏报告摘要（report_no/风险/通过率/AI 总结） */
  report_brief: Record<string, unknown> | null;
  /** Phase 2：飞书通知结果（status/error_message/skipped/channel_name） */
  notification_brief: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
  suggested_actions: string[];
  /** Web UI 智能体二期：当前绑定的受控浏览器会话 */
  web_agent_session_id: number | null;
  /** Web UI 智能体二期：用户自然语言目标 */
  web_goal: string | null;
  /** Web UI 智能体二期：步数预算上限 */
  web_step_budget: number;
  /** Web UI 智能体二期：已执行的步骤（含执行结果） */
  web_proposed_steps: Array<Record<string, unknown>>;
  /** Web UI 智能体二期：当前待人工确认的提案 */
  web_current_step: Record<string, unknown> | null;
  /** Web UI 智能体二期：最近一次脱敏页面观测 */
  web_observation: WebAgentObservation | null;
}

export interface AgentTurnResponse {
  session: AgentSession;
  messages: AgentMessage[];
  workspace: AgentWorkspace;
}

// ---- 正式测试报告（Phase 2）----
// 字段与后端 features/reports/schemas.py 严格对齐（snake_case）。

export type ReportStatus = 'GENERATING' | 'COMPLETED' | 'FAILED';
export type ReportRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
// 失败分类：POTENTIAL_BUG 仅表示「疑似产品问题，需人工确认」，不是已确认缺陷。
export type ReportFailureType =
  | 'ASSERTION_FAILURE'
  | 'EXECUTION_ERROR'
  | 'TEST_DATA_ISSUE'
  | 'ENVIRONMENT_ERROR'
  | 'POTENTIAL_BUG'
  | 'UNKNOWN';

export interface ReportGenerateRequest {
  /** 是否调用 LLM 生成结构化总结（失败不影响报告状态） */
  generate_ai_summary?: boolean;
  /** 已有 COMPLETED 报告时仅重生成 AI 总结（统计字段不可变） */
  regenerate?: boolean;
}

export interface ReportGenerateResponse {
  report_id: number;
  status: ReportStatus;
}

/** 报告详情内的单用例执行摘要（快照已脱敏）。 */
export interface CaseExecutionSummary {
  id: number;
  test_case_id: number | null;
  case_name: string;
  priority: string;
  case_type: string | null;
  status: string;
  failure_type: ReportFailureType | null;
  executor_type: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  request_snapshot: Record<string, unknown> | null;
  response_snapshot: Record<string, unknown> | null;
  assertion_results: Array<Record<string, unknown>> | null;
  context_json: Record<string, unknown> | null;
}

/** 报告详情里附带的一次性 TestRun 摘要。 */
export interface TestRunBrief {
  id: number;
  status: string;
  environment_id: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface TestReport {
  id: number;
  project_id: number;
  test_run_id: number | null;
  report_no: string;
  title: string;
  environment_id: number | null;
  status: ReportStatus;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  error_cases: number;
  skipped_cases: number;
  /** 通过率 0-100，保留两位小数（passed/(total-skipped)*100，分母 0 记 0） */
  pass_rate: number;
  duration_ms: number | null;
  /** 代码统计的结构化汇总（failure_clusters / case_failure_types），不可变 */
  summary: Record<string, unknown> | null;
  /** LLM 结构化总结；生成失败时为空（报告仍 COMPLETED） */
  ai_summary: Record<string, unknown> | null;
  ai_summary_version: string | null;
  risk_level: ReportRiskLevel;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

/** 报告列表项（不含 AI 总结等大字段）。 */
export interface TestReportListItem {
  id: number;
  report_no: string;
  title: string;
  test_run_id: number | null;
  environment_id: number | null;
  status: ReportStatus;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  error_cases: number;
  skipped_cases: number;
  pass_rate: number;
  duration_ms: number | null;
  risk_level: ReportRiskLevel;
  created_at: string;
}

// list_reports 返回分页信封（后端 TestReportListResponse）。
export type TestReportListResponse = Paginated<TestReportListItem>;

/** 报告详情：报告本体 + TestRun 摘要 + 逐用例执行 + 失败分类聚类。 */
export interface TestReportDetail {
  report: TestReport;
  test_run: TestRunBrief | null;
  case_executions: CaseExecutionSummary[];
  failure_clusters: Array<Record<string, unknown>>;
}

export interface ReportListQuery {
  page?: number;
  page_size?: number;
  environment_id?: number;
  risk_level?: ReportRiskLevel;
  status?: ReportStatus;
  test_run_id?: number;
}

// ---- 飞书通知渠道与发送记录（Phase 2）----
// 字段与后端 features/notifications/schemas_channel.py 严格对齐（snake_case）。
// 安全红线：后端响应**永不**回吐 webhook_url / secret 明文，仅回 webhook_configured
// （布尔）与 webhook_masked（脱敏 URL）。

export type NotifyCondition = 'ALWAYS' | 'ONLY_FAILED' | 'ONLY_HIGH_RISK';
export type NotifyStatus = 'PENDING' | 'SUCCESS' | 'FAILED';

export interface ChannelCreateRequest {
  name: string;
  channel_type?: 'FEISHU_WEBHOOK';
  /** 飞书 webhook URL（明文入参，后端加密入库；仅写入不回读） */
  webhook_url: string;
  /** 飞书签名密钥（明文入参，后端加密入库；不填则不签名） */
  secret?: string | null;
  enabled?: boolean;
  notify_condition?: NotifyCondition;
  keyword?: string | null;
}

/** 更新渠道；webhook_url / secret 留空（undefined）表示不变，传空串表示清除。 */
export interface ChannelUpdateRequest {
  name?: string;
  webhook_url?: string;
  secret?: string;
  enabled?: boolean;
  notify_condition?: NotifyCondition;
  keyword?: string;
}

export interface NotificationChannel {
  id: number;
  project_id: number;
  name: string;
  channel_type: string;
  enabled: boolean;
  notify_condition: NotifyCondition;
  /** 是否已配置 webhook URL（不含 URL 本身） */
  webhook_configured: boolean;
  /** 脱敏 webhook URL，如 https://open.feishu.cn/...**** */
  webhook_masked: string;
  keyword: string | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

// list_channels 返回分页信封。
export type ChannelListResponse = Paginated<NotificationChannel>;

/** 发送审计记录（不含卡片原文 request_snapshot）。 */
export interface NotificationRecord {
  id: number;
  project_id: number;
  channel_id: number;
  report_id: number | null;
  status: NotifyStatus;
  error_message: string | null;
  sent_at: string | null;
  created_at: string;
}

// 发送记录列表返回分页信封。
export type NotificationRecordListResponse = Paginated<NotificationRecord>;

/** 触发发送（手动 / 连通性测试）的即时结果。 */
export interface SendResult {
  record_id: number | null;
  status: NotifyStatus;
  error_message: string | null;
  /** 因渠道禁用或通知条件不满足而跳过（未发送） */
  skipped: boolean;
}

export interface NotifyReportRequest {
  /** 渠道 ID；省略时后端取项目首个启用渠道，均无则跳过（skipped=true），而不是 422。 */
  channel_id?: number;
}

// ===========================================================================
// 测试数据中心 / Data Factory（features/test_data/schemas.py 对齐，snake_case）
// 列表接口统一走 Paginated<T>；写操作的请求体与后端 Pydantic 入参一致。
// 安全约定：Provider 配置 extra=forbid；连接响应只回 password_set；value/payload 已脱敏。
// ===========================================================================

// Fixture 作用域 / 状态 / 清理策略 / 步骤类型等字面量类型，供下拉与表单复用。
export type FixtureScope = 'CASE' | 'RUN' | 'PROJECT' | 'GLOBAL';
export type FixtureStatus = 'DRAFT' | 'ACTIVE' | 'DISABLED';
export type FixtureCleanupPolicy = 'AFTER_CASE' | 'AFTER_RUN' | 'MANUAL' | 'NEVER';
export type FixturePhase = 'GENERATE' | 'CLEANUP';
export type FixtureStepType =
  | 'FIXTURE' | 'API' | 'BUSINESS_ACTION' | 'BUSINESS_FLOW'
  | 'FAKER' | 'STATIC' | 'DATABASE_INSERT' | 'DATABASE_PATCH'
  | 'WAIT' | 'DATABASE_QUERY' | 'EXTERNAL_PROVIDER';
export type FixtureOnFailure = 'ABORT' | 'CONTINUE';
export type ValueType = 'STRING' | 'INTEGER' | 'NUMBER' | 'BOOLEAN' | 'OBJECT' | 'ARRAY';
export type ProviderType =
  | 'STATIC' | 'ENVIRONMENT' | 'FAKER' | 'API_CREATE'
  | 'BUSINESS_ACTION' | 'BUSINESS_FLOW' | 'EXISTING_POOL'
  | 'DATABASE_INSERT' | 'DATABASE_PATCH';
export type RiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type AssetSource = 'STATIC' | 'POOL' | 'FIXTURE';
export type AssetStatus = 'ACTIVE' | 'DISABLED' | 'EXPIRED';
export type PoolStatus = 'ACTIVE' | 'DISABLED';
export type PoolItemStatus = 'AVAILABLE' | 'OCCUPIED' | 'EXPIRED' | 'DISABLED';
export type LeaseStatus = 'ACTIVE' | 'RELEASED' | 'EXPIRED';
export type DbOperation = 'INSERT' | 'UPDATE' | 'SELECT' | 'DELETE';
export type DbEnvironmentClass = 'DEV' | 'TEST' | 'STAGING' | 'PRODUCTION';
export type DataExecutionStatus =
  | 'PENDING' | 'GENERATING' | 'READY' | 'FAILED'
  | 'EXPIRED' | 'DIRTY' | 'CLEANING' | 'CLEANED';
export type ProviderExecutionStatus = 'PENDING' | 'RUNNING' | 'SUCCESS' | 'FAILED' | 'SKIPPED';
export type CleanupStatus = 'PENDING' | 'SUCCESS' | 'FAILED' | 'SKIPPED';

// ---- Fixture ----

/** Fixture 步骤（响应）。config_json 为自由结构，按 step_type 解释。 */
export interface FixtureStep {
  id: number;
  fixture_id: number;
  phase: FixturePhase;
  step_type: FixtureStepType;
  name: string;
  sort: number;
  provider_id: number | null;
  config_json: Record<string, unknown> | null;
  on_failure: FixtureOnFailure;
}

/** 输出契约（响应）。 */
export interface FixtureOutput {
  id: number;
  fixture_id: number;
  name: string;
  value_type: ValueType;
  source_path: string;
  description: string | null;
  sort: number;
}

/** 依赖边（响应，附被依赖方 key/name/类型，便于画树）。 */
export interface FixtureDependency {
  id: number;
  fixture_id: number;
  depends_on_fixture_id: number;
  sort: number;
  depends_on_key: string | null;
  depends_on_name: string | null;
  depends_on_entity_type: string | null;
}

/** Fixture 列表项（含聚合计数）。 */
export interface FixtureBrief {
  id: number;
  project_id: number;
  name: string;
  fixture_key: string;
  entity_type: string;
  description: string | null;
  scope: FixtureScope;
  status: FixtureStatus;
  cache_enabled: boolean;
  cleanup_policy: FixtureCleanupPolicy;
  output_names: string[];
  step_count: number;
  generate_step_count: number;
  cleanup_step_count: number;
  dependency_count: number;
  referenced_case_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

/** Fixture 详情（列表项 + 步骤 + 输出 + 依赖 + 引用用例）。 */
export interface FixtureDetail extends FixtureBrief {
  steps: FixtureStep[];
  outputs: FixtureOutput[];
  dependencies: FixtureDependency[];
  referenced_cases: { test_case_id: number; sort: number }[];
}

/** 依赖树节点（含子依赖）。 */
export interface FixtureTreeNode {
  id: number;
  fixture_key: string;
  name: string;
  entity_type: string;
  scope: FixtureScope;
  status: FixtureStatus;
  depth: number;
  children: FixtureTreeNode[];
}

// 写入入参
export interface FixtureStepInput {
  phase?: FixturePhase;
  step_type: FixtureStepType;
  name: string;
  sort?: number;
  provider_id?: number | null;
  config_json?: Record<string, unknown> | null;
  on_failure?: FixtureOnFailure;
}
export interface FixtureOutputInput {
  name: string;
  value_type?: ValueType;
  source_path: string;
  description?: string | null;
  sort?: number;
}
export interface FixtureCreate {
  name: string;
  fixture_key: string;
  entity_type: string;
  description?: string | null;
  scope?: FixtureScope;
  status?: FixtureStatus;
  cache_enabled?: boolean;
  cleanup_policy?: FixtureCleanupPolicy;
  steps?: FixtureStepInput[];
  outputs?: FixtureOutputInput[];
  dependencies?: number[];
}
export interface FixtureUpdate {
  name?: string;
  description?: string | null;
  scope?: FixtureScope;
  status?: FixtureStatus;
  cache_enabled?: boolean;
  cleanup_policy?: FixtureCleanupPolicy;
}
export interface FixtureStepsReplace {
  steps: FixtureStepInput[];
}
export interface FixtureOutputsReplace {
  outputs: FixtureOutputInput[];
}

export type FixtureListResponse = Paginated<FixtureBrief>;

// ---- 测试数据目录 ----
export interface TestDataAsset {
  id: number;
  project_id: number;
  name: string;
  entity_type: string;
  source: AssetSource;
  scope: FixtureScope;
  status: AssetStatus;
  fixture_id: number | null;
  value_json: Record<string, unknown> | null; // 已脱敏，敏感值为 ******
  description: string | null;
  referenced_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface TestDataAssetCreate {
  name: string;
  entity_type: string;
  source?: AssetSource;
  scope?: FixtureScope;
  status?: AssetStatus;
  fixture_id?: number | null;
  value_json?: Record<string, unknown> | null;
  description?: string | null;
}
export interface TestDataAssetUpdate {
  name?: string;
  entity_type?: string;
  source?: AssetSource;
  scope?: FixtureScope;
  status?: AssetStatus;
  fixture_id?: number | null;
  value_json?: Record<string, unknown> | null;
  description?: string | null;
}
export type TestDataAssetListResponse = Paginated<TestDataAsset>;

// ---- Data Provider ----
export interface DataProvider {
  id: number;
  project_id: number;
  name: string;
  provider_type: ProviderType;
  config_json: Record<string, unknown>; // 不含密码；DATABASE 类只回 connection_id
  enabled: boolean;
  risk_level: RiskLevel;
  description: string | null;
  usage_count: number;
  last_status: ProviderExecutionStatus | null;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface DataProviderCreate {
  name: string;
  provider_type: ProviderType;
  config_json?: Record<string, unknown>;
  enabled?: boolean;
  risk_level?: RiskLevel | null;
  description?: string | null;
}
export interface DataProviderUpdate {
  name?: string;
  provider_type?: ProviderType;
  config_json?: Record<string, unknown> | null;
  enabled?: boolean;
  risk_level?: RiskLevel | null;
  description?: string | null;
}
export interface DataProviderTestRequest {
  environment_id: number;
  variables?: Record<string, unknown>;
}
/** 手工试跑 Fixture 的请求体：scope 只接收不生效，试跑一律按 CASE 处理。 */
export interface FixtureGenerateRequest {
  environment_id: number;
  scope?: string;
  variables?: Record<string, unknown>;
}
export type DataProviderListResponse = Paginated<DataProvider>;

// ---- 数据池 ----
export interface DataPool {
  id: number;
  project_id: number;
  asset_id: number | null;
  pool_key: string;
  name: string;
  scope: FixtureScope;
  max_concurrency: number;
  lease_ttl_seconds: number;
  status: PoolStatus;
  item_count: number;
  available_count: number;
  active_lease_count: number;
  created_at: string;
  updated_at: string;
}
export interface DataPoolItem {
  id: number;
  pool_id: number;
  status: PoolItemStatus;
  payload_json: Record<string, unknown>; // 已脱敏
  occupied_count: number;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}
export interface DataPoolCreate {
  name: string;
  pool_key: string;
  asset_id?: number | null;
  scope?: FixtureScope;
  max_concurrency?: number;
  lease_ttl_seconds?: number;
  status?: PoolStatus;
}
export interface DataPoolItemCreate {
  payload_json?: Record<string, unknown>;
  expires_at?: string | null;
  status?: PoolItemStatus;
}
export type DataPoolListResponse = Paginated<DataPool>;
export type DataPoolItemListResponse = Paginated<DataPoolItem>;

// ---- 被测库连接与策略 ----
export interface TargetDbConnection {
  id: number;
  project_id: number;
  environment_id: number;
  environment_name: string | null;
  environment_class: DbEnvironmentClass | null;
  name: string;
  host: string;
  port: number;
  database_name: string;
  username: string;
  schema_name: string | null;
  enabled: boolean;
  password_set: boolean; // 只回是否存在密码，绝不回显
  referenced_count: number;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface TargetDbConnectionCreate {
  environment_id: number;
  name: string;
  host: string;
  port?: number;
  database_name: string;
  username: string;
  password: string; // 创建时唯一一次明文
  schema_name?: string | null;
  enabled?: boolean;
}
export interface TargetDbConnectionUpdate {
  name?: string;
  host?: string;
  port?: number;
  database_name?: string;
  username?: string;
  password?: string;
  schema_name?: string | null;
  enabled?: boolean;
}
export type TargetDbConnectionListResponse = Paginated<TargetDbConnection>;

export interface DatabasePolicy {
  id: number;
  project_id: number;
  environment_id: number;
  enabled: boolean;
  allowed_tables: string[];
  allowed_operations: DbOperation[];
  environment_name: string | null;
  environment_display_name: string | null;
  environment_class: DbEnvironmentClass;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}
export interface DatabasePolicyUpsert {
  enabled: boolean;
  allowed_tables?: string[];
  allowed_operations?: DbOperation[];
}
export type DatabasePolicyListResponse = Paginated<DatabasePolicy>;

// ---- 执行记录（只读；Phase A 列表恒空） ----
export interface ProviderExecution {
  id: number;
  fixture_execution_id: number | null;
  data_execution_id: number | null;
  project_id: number;
  provider_id: number | null;
  provider_type: string;
  step_id: number | null;
  status: ProviderExecutionStatus;
  input_snapshot: Record<string, unknown> | null; // 已脱敏
  output_snapshot: Record<string, unknown> | null; // 已脱敏
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  cleanup_status: CleanupStatus | null;
}
export interface FixtureExecution {
  id: number;
  data_execution_id: number;
  project_id: number;
  fixture_id: number | null;
  fixture_key: string;
  status: DataExecutionStatus;
  scope: string;
  cache_hit: boolean;
  input_snapshot: Record<string, unknown> | null;
  output_snapshot: Record<string, unknown> | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  cleanup_status: CleanupStatus | null;
  cleanup_error_code: string | null;
  cleanup_error_message: string | null;
  provider_executions: ProviderExecution[];
}
export interface DataExecution {
  id: number;
  project_id: number;
  test_run_id: number | null;
  case_execution_id: number | null;
  environment_id: number | null;
  status: DataExecutionStatus;
  scope: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  cleanup_status: CleanupStatus | null;
  cleanup_error_code: string | null;
  cleanup_error_message: string | null;
  fixture_key_count: number;
  provider_step_count: number;
  created_at: string;
}
export interface DataExecutionDetail extends DataExecution {
  fixture_executions: FixtureExecution[];
  /**
   * 没有归属 Fixture 的步骤记录：手工试跑单个 Provider 时
   * fixture_execution_id 为空，只能挂在这一层。
   */
  provider_executions: ProviderExecution[];
}
export interface DataExecutionListQuery {
  status?: DataExecutionStatus;
  test_run_id?: number;
  page?: number;
  page_size?: number;
}
export type DataExecutionListResponse = Paginated<DataExecution>;

// 接口 Mock 与依赖异常模拟（Mock Management Phase 1）
//
// 字段命名与后端 features/mock_management/schemas.py 严格对齐（snake_case）。
// 安全约定：MockService 只返回 runtime_token_set 布尔值，绝不回显 token hash；
// 明文 runtime_token 仅在创建 / 重置接口响应里出现一次。

export type MockBehaviorType = 'STATIC_RESPONSE' | 'DELAY_RESPONSE' | 'TIMEOUT' | 'EMPTY_RESPONSE';
export type MockMatcherSource = 'METHOD' | 'PATH' | 'QUERY' | 'HEADER' | 'BODY';
export type MockMatcherOperator =
  | 'EQ'
  | 'NE'
  | 'EXISTS'
  | 'NOT_EXISTS'
  | 'CONTAINS'
  | 'IN'
  | 'JSON_PATH_EQ'
  | 'JSON_PATH_EXISTS';
export type MockContextStatus = 'ACTIVE' | 'CLOSED' | 'EXPIRED';
export type MockScope = 'SETUP' | 'EXECUTION' | 'BOTH';

/** Mock 依赖服务（maps / 支付 / AI 模型…）。 */
export interface MockService {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  service_key: string;
  base_path: string | null;
  enabled: boolean;
  default_scenario_id: number | null;
  public_runtime: boolean;
  /** 是否已配置 Runtime Token；token 本身永不回显。 */
  runtime_token_set: boolean;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  revision: number;
  runtime_url: string | null;
  endpoint_count: number;
  scenario_count: number;
}

export interface MockServiceCreate {
  name: string;
  description?: string | null;
  service_key: string;
  base_path?: string | null;
  enabled?: boolean;
  public_runtime?: boolean;
  /** 可选自定义明文 token；不传则后端自动生成。 */
  runtime_token?: string | null;
}

export interface MockServiceUpdate {
  name?: string;
  description?: string | null;
  base_path?: string | null;
  enabled?: boolean;
  public_runtime?: boolean;
  default_scenario_id?: number | null;
  /** 乐观锁版本号，不匹配返回 409。 */
  revision: number;
}

/** 创建 / 重置 token 的响应：明文 token 只在这里出现一次。 */
export interface MockServiceCreateResponse {
  service: MockService;
  runtime_token: string;
}

export type MockServiceListResponse = Paginated<MockService>;

/** Mock 接口。(service, method, path) 唯一。 */
export interface MockEndpoint {
  id: number;
  project_id: number;
  mock_service_id: number;
  api_id: number | null;
  name: string;
  method: string;
  path: string;
  description: string | null;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  revision: number;
  scenario_count: number;
}

export interface MockEndpointCreate {
  name: string;
  method: string;
  path: string;
  description?: string | null;
  api_id?: number | null;
  enabled?: boolean;
}

export interface MockEndpointUpdate {
  name?: string;
  method?: string;
  path?: string;
  description?: string | null;
  enabled?: boolean;
  revision: number;
}

export type MockEndpointListResponse = Paginated<MockEndpoint>;

/** 场景的匹配规则（source/field/operator/expected_value）。 */
export interface MockMatcher {
  id: number;
  scenario_id: number;
  source: MockMatcherSource;
  field: string;
  operator: MockMatcherOperator;
  expected_value: unknown;
  priority: number;
  enabled: boolean;
  created_at: string;
}

export interface MockMatcherCreate {
  source: MockMatcherSource;
  field: string;
  operator: MockMatcherOperator;
  expected_value?: unknown;
  priority?: number;
  enabled?: boolean;
}

export interface MockMatchersReplace {
  matchers: MockMatcherCreate[];
  /** 乐观锁：整体替换是重建式写入，带上 revision 可避免并发会话互相覆盖。 */
  revision?: number;
}

/** 一个 Endpoint 的一个行为场景。 */
export interface MockScenario {
  id: number;
  project_id: number;
  mock_endpoint_id: number;
  name: string;
  scenario_key: string;
  description: string | null;
  enabled: boolean;
  is_default: boolean;
  priority: number;
  behavior_type: MockBehaviorType;
  delay_ms: number | null;
  status_code: number;
  response_headers: Record<string, string> | null;
  response_body: unknown;
  response_template: unknown;
  created_by: number | null;
  created_at: string;
  updated_at: string;
  revision: number;
  matchers: MockMatcher[];
  call_count: number;
}

export interface MockScenarioCreate {
  name: string;
  scenario_key: string;
  description?: string | null;
  enabled?: boolean;
  is_default?: boolean;
  priority?: number;
  behavior_type?: MockBehaviorType;
  delay_ms?: number | null;
  status_code?: number;
  response_headers?: Record<string, string> | null;
  response_body?: unknown;
  response_template?: unknown;
  matchers?: MockMatcherCreate[];
}

export interface MockScenarioUpdate {
  name?: string;
  description?: string | null;
  enabled?: boolean;
  is_default?: boolean;
  priority?: number;
  behavior_type?: MockBehaviorType;
  delay_ms?: number | null;
  status_code?: number;
  response_headers?: Record<string, string> | null;
  response_body?: unknown;
  response_template?: unknown;
  revision: number;
}

export type MockScenarioListResponse = Paginated<MockScenario>;

/** 场景试跑请求：模拟一个请求验证 Matcher + 响应构建，不真调被测系统。 */
export interface ScenarioTestRequest {
  method?: string;
  path?: string;
  query?: Record<string, unknown>;
  headers?: Record<string, string>;
  body?: unknown;
}

export interface ScenarioTestResponse {
  matched: boolean;
  scenario_id: number | null;
  scenario_key: string | null;
  status_code: number | null;
  headers: Record<string, string>;
  body: unknown;
  duration_ms: number;
  delay_ms: number;
}

/** Mock 调用记录（请求 / 响应快照已脱敏）。 */
export interface MockExecution {
  id: number;
  project_id: number;
  mock_service_id: number | null;
  mock_endpoint_id: number | null;
  mock_scenario_id: number | null;
  request_id: string | null;
  method: string;
  path: string;
  query_snapshot: unknown;
  header_snapshot: unknown;
  body_snapshot: unknown;
  response_status: number | null;
  response_header_snapshot: unknown;
  response_body_snapshot: unknown;
  matched: boolean;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  test_run_id: number | null;
  case_execution_id: number | null;
  mock_context_id: string | null;
  created_at: string;
  service_key: string | null;
  service_name: string | null;
  endpoint_path: string | null;
  scenario_key: string | null;
}

export interface MockExecutionListQuery {
  /** 后端查询参数名为 service_id。 */
  service_id?: number;
  matched?: boolean;
  test_run_id?: number;
  case_execution_id?: number;
  context_id?: string;
  page?: number;
  page_size?: number;
}

export type MockExecutionListResponse = Paginated<MockExecution>;

/** 用例执行激活的 Mock 上下文（scenario_overrides，支持并发隔离）。 */
export interface MockContext {
  id: number;
  context_id: string;
  project_id: number;
  test_run_id: number | null;
  case_execution_id: number | null;
  scenario_overrides: unknown;
  status: MockContextStatus;
  expires_at: string;
  created_at: string;
  closed_at: string | null;
}

/** 用例声明的 required_mocks（关联 service/endpoint/scenario + scope）。 */
export interface TestCaseMock {
  id: number;
  test_case_id: number;
  mock_service_id: number;
  mock_endpoint_id: number;
  mock_scenario_id: number;
  scope: MockScope;
  sort: number;
  created_at: string;
  service_key: string | null;
  service_name: string | null;
  endpoint_path: string | null;
  endpoint_method: string | null;
  scenario_key: string | null;
  scenario_name: string | null;
}

export interface TestCaseMockCreate {
  mock_service_id: number;
  mock_endpoint_id: number;
  mock_scenario_id: number;
  scope?: MockScope;
  sort?: number;
}

export interface TestCaseMocksReplace {
  mocks: TestCaseMockCreate[];
}

/** 从 API Catalog 一键创建 Mock（service + endpoint + 推荐场景模板）。 */
export interface CreateMockFromApiRequest {
  service_key: string;
  service_name?: string | null;
  endpoint_name?: string | null;
  templates?: string[];
  public_runtime?: boolean;
  runtime_token?: string | null;
}

export interface CreateMockFromApiResponse {
  service: MockService;
  endpoint_id: number;
  scenario_ids: number[];
  runtime_token: string | null;
}

// ---- 安全测试（Security Testing Phase 1）----
// 字段与后端 features/security_testing/schemas.py 严格对齐（snake_case）。
// 安全红线：本页只改请求与解释结果，不做注入 / 扫描器；不在生产环境发安全变异请求；
// 疑似问题文案统一为「疑似问题」，不写「已发现漏洞」；不提供「转 Bug」入口，
// SecurityFinding.bug_id 恒为 null。Finding evidence 不在本页 Agent brief 展示，
// 变异详情抽屉里按需从 security-executions 读（后端已脱敏）。

/** 严重级别 / 风险级别（策略与规则复用同一套值）。 */
export type SecuritySeverity = 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

/** 安全结论五态（不改既有枚举表）。 */
export type SecurityResult =
  | 'PASS'
  | 'POTENTIAL_ISSUE'
  | 'FAILED_EXECUTION'
  | 'INCONCLUSIVE'
  | 'SKIPPED';

/** Finding 状态与合法迁移由服务层校验。 */
export type SecurityFindingStatus =
  | 'OPEN'
  | 'CONFIRMED'
  | 'FALSE_POSITIVE'
  | 'RESOLVED'
  | 'IGNORED';

/** 计划状态。 */
export type PlanStatus = 'DRAFT' | 'CONFIRMED' | 'DISCARDED';

/** 安全期望（算子允许的期望由后端校验，前端只透传）。 */
export type SecurityExpectation =
  | 'EXPECTED_DENY'
  | 'EXPECTED_ALLOW'
  | 'EXPECTED_VALIDATION_ERROR'
  | 'EXPECTED_IDEMPOTENT';

/** 报告概览六类覆盖口径（前端聚合用，与后端 COVERAGE_CATEGORIES 一致）。 */
export type CoverageCategory =
  | 'AUTHENTICATION'
  | 'AUTHORIZATION'
  | 'IDOR'
  | 'PARAMETER'
  | 'REPLAY'
  | 'BUSINESS';

/** 项目级环境开关。production_enforced 恒 false（生产永远拒绝）。 */
export interface SecuritySetting {
  id: number | null;
  project_id: number | null;
  allow_dev: boolean;
  allow_test: boolean;
  allow_staging: boolean;
  allow_production: boolean;
  /** 恒为 false：列上即使存了 true，执行器也不读它。 */
  production_enforced: boolean;
  updated_by: number | null;
  created_at: string | null;
  updated_at: string | null;
  revision: number;
}

export interface SecuritySettingUpdate {
  allow_dev?: boolean;
  allow_test?: boolean;
  allow_staging?: boolean;
  /** 可传入但永不生效（存库后仍拒绝）。 */
  allow_production?: boolean;
  revision?: number;
}

/** 变异规则（响应）。mutation_config 一律结构化，禁止脚本键。 */
export interface MutationRule {
  id: number;
  project_id: number | null;
  strategy_id: number;
  name: string;
  mutation_type: string;
  target_location: string;
  target_field: string | null;
  operator: string;
  mutation_config: Record<string, unknown>;
  expected_security_behavior: string;
  expected_status_codes: number[] | null;
  severity: string;
  enabled: boolean;
  confirmation_required: boolean;
  sort: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface MutationRuleCreate {
  name: string;
  mutation_type: string;
  target_location: string;
  target_field?: string | null;
  operator?: string | null;
  mutation_config: Record<string, unknown>;
  expected_security_behavior?: string | null;
  expected_status_codes?: number[] | null;
  severity?: string | null;
  enabled?: boolean;
  confirmation_required?: boolean;
  sort?: number;
}

export interface MutationRuleUpdate {
  name?: string;
  mutation_type?: string;
  target_location?: string;
  target_field?: string | null;
  operator?: string | null;
  mutation_config?: Record<string, unknown> | null;
  expected_security_behavior?: string | null;
  expected_status_codes?: number[] | null;
  severity?: string | null;
  enabled?: boolean | null;
  confirmation_required?: boolean | null;
  sort?: number | null;
}

/** 安全策略（响应，可携带规则列表）。系统模板 builtin=true 不可改不可删。 */
export interface SecurityStrategy {
  id: number;
  project_id: number | null;
  scope: 'SYSTEM' | 'PROJECT';
  name: string;
  strategy_key: string;
  category: string;
  description: string | null;
  enabled: boolean;
  risk_level: string;
  builtin: boolean;
  created_by: number | null;
  created_at: string | null;
  updated_at: string | null;
  revision: number;
  rules: MutationRule[];
}

export interface SecurityStrategyCreate {
  name: string;
  strategy_key: string;
  category: string;
  description?: string | null;
  enabled?: boolean;
  risk_level?: string;
  rules?: MutationRuleCreate[];
}

export interface SecurityStrategyUpdate {
  name?: string;
  description?: string | null;
  enabled?: boolean | null;
  risk_level?: string | null;
  revision?: number;
}

export interface SecurityStrategyListResponse {
  items: SecurityStrategy[];
  total: number;
  page: number;
  page_size: number;
}

/** 安全计划预览项（形状即后端 PlanPreviewItem）。 */
export interface PlanPreviewItem {
  index: number;
  name: string;
  mutation_type: string;
  target_type: string;
  api_id: number | null;
  business_action_id: number | null;
  method: string | null;
  /** 来自 mutation_config，规则列声明时可能为 null。 */
  location: string | null;
  field: string | null;
  expectation: string;
  expected_status_codes: number[] | null;
  severity: string;
  risk_level: string | null;
  confirmation_required: boolean;
  blocked_reason: string | null;
  mutation_config: Record<string, unknown>;
  source_rule_id: number | null;
  source_strategy_id: number | null;
}

export interface PlanPreviewRequest {
  /** 三者必须且只能给一个（§16.3）。 */
  baseline_case_id?: number | null;
  api_id?: number | null;
  business_action_id?: number | null;
  strategy_ids: number[];
  environment_id?: number | null;
  name?: string | null;
}

export interface PlanPreviewResponse {
  plan_id: number;
  status: string;
  estimated_count: number;
  truncated: boolean;
  items: PlanPreviewItem[];
  /** 按 API / 业务动作目标生成时解析出的基线用例。 */
  baseline_case_id: number | null;
  baseline_case_name: string | null;
}

export interface PlanConfirmRequest {
  accepted_item_indexes: number[];
  plan_name?: string | null;
}

export interface PlanConfirmResponse {
  plan_id: number;
  status: string;
  created_case_ids: number[];
  created_count: number;
  skipped_count: number;
}

export interface SecurityPlan {
  id: number;
  project_id: number;
  name: string;
  target_type: string;
  api_id: number | null;
  baseline_case_id: number | null;
  business_action_id: number | null;
  strategy_ids: number[] | null;
  status: string;
  preview_json: unknown;
  estimated_count: number;
  environment_id: number | null;
  created_by: number | null;
  confirmed_by: number | null;
  confirmed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  revision: number;
}

/** 安全用例扩展数据（读模型）。 */
export interface SecurityCase {
  id: number;
  project_id: number;
  test_case_id: number;
  plan_id: number | null;
  baseline_case_id: number | null;
  strategy_id: number | null;
  rule_id: number | null;
  api_id: number | null;
  business_action_id: number | null;
  mutation_type: string;
  mutation_config: Record<string, unknown>;
  security_expectation: string;
  risk_level: string | null;
  confirmation_required: boolean;
  confirmed_by: number | null;
  confirmed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SecurityCaseDetail extends SecurityCase {
  enabled: boolean;
  case_name: string | null;
  baseline_case_name: string | null;
  api_name: string | null;
  rule_name: string | null;
  latest_execution: SecurityExecution | null;
}

export interface SecurityCaseListResponse {
  items: SecurityCaseDetail[];
  total: number;
  page: number;
  page_size: number;
}

export interface SecurityCaseUpdate {
  /** 只允许改启用状态；事实来源是 test_case.enabled。 */
  enabled: boolean;
}

export interface SecurityRunRequest {
  security_case_ids: number[];
  environment_id?: number | null;
  plan_name?: string | null;
}

/** 安全执行记录（mutation_trace / evidence 均已脱敏）。 */
export interface SecurityExecution {
  id: number;
  project_id: number;
  test_run_id: number | null;
  case_execution_id: number | null;
  security_case_id: number;
  environment_id: number | null;
  actor_id: number | null;
  baseline_status: 'PASSED' | 'FAILED' | null;
  baseline_http_status: number | null;
  security_result: SecurityResult;
  classification: string | null;
  mutation_trace: Array<Record<string, unknown>>;
  replay_count: number;
  actual_status_codes: number[];
  evidence: Record<string, unknown> | null;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
}

/** 疑似问题（Phase 1 不写 bug_id，恒为 null）。 */
export interface SecurityFinding {
  id: number;
  project_id: number;
  test_run_id: number | null;
  case_execution_id: number | null;
  security_execution_id: number | null;
  api_id: number | null;
  business_action_id: number | null;
  strategy_id: number | null;
  security_case_id: number | null;
  mutation_type: string;
  severity: SecuritySeverity;
  status: SecurityFindingStatus;
  title: string;
  description: string | null;
  evidence: Record<string, unknown> | null;
  recommendation: string | null;
  fingerprint: string;
  bug_id: number | null;
  created_by: number | null;
  resolved_by: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SecurityFindingUpdate {
  status: SecurityFindingStatus;
}

export interface SecurityFindingListResponse {
  items: SecurityFinding[];
  total: number;
  page: number;
  page_size: number;
}

/** 报告 summary.security 形状（后端代码计算，无安全用例时为 null）。 */
export interface SecuritySummary {
  cases: number;
  pass: number;
  potential_issues: number;
  inconclusive: number;
  failed_execution: number;
  skipped: number;
  /** 各严重级别条数（INFO/LOW/MEDIUM/HIGH/CRITICAL 五键齐全）。 */
  findings: Record<string, number>;
  /** 最多 5 条，按严重级别降序；不含 evidence 正文。 */
  top_findings: Array<{
    id: number;
    severity: string;
    title: string;
    api_id: number | null;
    mutation_type: string;
  }>;
}


// Web UI 自动化：既有测试执行的扩展视图，字段与后端结构化契约一致。
export type WebOperation = 'NAVIGATE' | 'CLICK' | 'FILL' | 'SELECT' | 'UPLOAD' | 'WAIT' | 'ASSERT';
export interface WebLocator {
  strategy: 'TEST_ID' | 'ROLE' | 'LABEL' | 'TEXT' | 'CSS' | 'XPATH'; // 定位策略
  value: string; // 定位值
  name?: string | null; // Role 可访问名称
  exact?: boolean; // 精确匹配
}
export interface WebStep {
  name: string; // 步骤名称
  operation: WebOperation; // 白名单操作
  locator?: WebLocator | null; // 直接定位器
  page_object_id?: number | null; // 页面对象引用
  element_key?: string | null; // 命名元素
  value?: string | null; // 输入或导航值，可引用变量
  timeout_ms?: number | null; // 步骤超时
  wait_state?: 'visible' | 'hidden' | 'attached' | 'detached'; // 等待状态
  assertion?: 'TEXT' | 'VALUE' | 'VISIBLE' | 'COUNT' | 'URL' | 'TITLE'; // 断言来源
  operator?: 'EQ' | 'NE' | 'CONTAINS' | 'GT' | 'GE' | 'LT' | 'LE'; // 平台断言操作符
  expected?: string | null; // 断言期望值
  sensitive?: boolean; // 输入或元素敏感
  upload?: { name: string; mime_type?: string; content_base64: string } | null; // 内存上传，禁止服务器路径
  output_variable?: string | null; // 断言值输出到业务上下文
}
export interface WebCaseInput {
  name: string; // 用例名称
  description?: string; // 描述
  auth_profile_id?: number | null; // 加密凭据配置
  timeout_ms?: number; // 默认操作超时
  total_timeout_ms?: number; // 用例总超时
  revision?: number | null; // 乐观锁
  steps: WebStep[]; // 顺序即执行顺序
}
export interface WebCase extends WebCaseInput {
  id: number; // 既有 TestCase ID
  project_id: number; // 项目 ID
  revision: number; // 当前版本
  source_type: string; // 人工或 Agent
  confirmed: boolean; // 当前依赖指纹已人工确认
}
export interface WebPageInput {
  name: string; // 页面名
  path: string; // 环境相对路径
  elements: { key: string; locator: WebLocator }[]; // 命名元素
  revision?: number | null; // 乐观锁
}
export interface WebPage extends WebPageInput {
  id: number; // 页面 ID
  project_id: number; // 项目 ID
  revision: number; // 当前版本
}
export interface WebAuthProfile {
  id: number; // 配置 ID
  project_id: number; // 项目 ID
  environment_id: number; // 环境 ID
  name: string; // 配置名称
  configured: boolean; // 仅表示已配置，敏感值永不回传
  expires_at: string; // UTC 过期时间
}
export interface WebArtifact {
  id: string; // 不透明附件 ID
  kind: string; // 截图或 Trace
  url: string; // 受 JWT 保护的下载地址
}
export interface WebExecution {
  id: number; // CaseExecution ID
  test_run_id: number; // TestRun ID
  test_case_id: number | null; // 用例 ID
  status: string; // 既有执行状态
  duration_ms: number | null; // 耗时
  error_code: string | null; // 失败错误码
  error_message: string | null; // 中文错误定位
  started_at: string | null; // 执行时间
  response_snapshot: { web?: { steps?: Record<string, unknown>[]; artifacts?: WebArtifact[] } } | null; // 脱敏步骤及附件
  report_id: number | null; // 已生成报告
}

// Web UI 智能体二期：受控浏览器会话、脱敏页面观测、步骤提案与提升契约。
export type WebAgentSessionStatus = 'ACTIVE' | 'CLOSED' | 'FAILED';
export interface WebAgentSession {
  id: number; // 会话 ID，也是进程内浏览器句柄的键
  project_id: number; // 所属项目
  environment_id: number; // 执行环境
  auth_profile_id: number | null; // 加密登录态配置
  base_url: string; // 环境基础地址
  target_page_path: string; // 目标页相对路径
  status: WebAgentSessionStatus; // 会话状态
  status_reason?: string | null; // 句柄不可用时提示重新启动
  step_budget: number; // 智能体步数预算上限
  step_count: number; // 已执行步数
  created_at: string | null; // 创建时间
}
/** 页面观测结果：只有脱敏后的语义树与遮罩截图，不含原始 DOM 或凭据。 */
export interface WebAgentObservation {
  url: string; // 当前页面地址
  title: string; // 页面标题
  accessibility_tree: string; // 已脱敏的 accessibility tree
  screenshot_b64: string; // 已遮罩输入的 base64 截图
}
/** 智能体提案 / 已执行步骤：提案与执行结果一起保留，供人工采纳。 */
export interface WebAgentStepProposal {
  name: string; // 步骤名称
  operation: WebOperation; // 白名单操作
  locator?: WebLocator | null; // 定位器
  value?: string | null; // 输入或导航值
  assertion?: WebStep['assertion']; // 断言来源
  expected?: string | null; // 断言期望值
  status: string; // PROPOSED / ACCEPTED / FAILED
  result?: Record<string, unknown> | null; // 执行结果摘要（已脱敏）
}
export type WebDecideDecision = 'PROPOSE' | 'OBSERVE' | 'DONE'; // 单轮决策结论

// Web 调试环境候选只展示元信息，不暴露管理端请求头与凭据。
export type WebEnvironment = Pick<Environment, 'id' | 'name' | 'display_name' | 'is_active'>;
