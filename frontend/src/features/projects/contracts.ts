// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。


/** 项目列表查询参数，作为 GET /projects 的 query 传给后端。 */
export interface ProjectListQuery {
  page?: number; // 页码，从 1 开始；不传时后端返回第一页
  page_size?: number; // 每页条数；不传时后端用默认值
  keyword?: string; // 关键词，按项目名称模糊匹配
  organization_id?: number; // 只看某个组织下的项目
}

/** 新建项目的请求体，对应 POST /projects。 */
export interface ProjectCreate {
  name: string; // 项目名称，平台内唯一
  description?: string; // 项目描述
  organization_id?: number; // 所属组织 ID；不传时项目不归属任何组织
}

/** 修改项目的请求体，对应 PATCH /projects/{id}；字段全部可选，只提交要改的项。 */
export interface ProjectUpdate {
  name?: string; // 新的项目名称
  description?: string; // 新的项目描述
  owner_id?: number; // 新的项目负责人用户 ID
  organization_id?: number; // 把项目挪到另一个组织
}

/** 授予项目成员权限的写入载荷，新增成员与转让负责人共用这一个结构。 */
export interface ProjectMemberCreate {
  user_id: number; // 目标成员的用户 ID
  role: ProjectRole; // 项目内角色：viewer / member / editor
}

/** 新增出站目标（被调用地址白名单条目）的请求体，对应 POST /projects/{id}/targets。 */
export interface OutboundTargetCreate {
  scheme: 'http' | 'https'; // 协议
  host: string; // 目标主机名或 IP
  port: number; // 目标端口
  is_production: boolean; // 是否生产地址；生产地址的审批更严格
}

/** 修改出站目标的请求体，对应 PATCH /projects/{id}/targets/{targetId}；目前只有启停开关。 */
export interface OutboundTargetUpdate {
  enabled: boolean; // 启用或停用该出站目标
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
