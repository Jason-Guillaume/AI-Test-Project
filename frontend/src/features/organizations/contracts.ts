// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。


/** 新建组织的请求体，对应 POST /organizations。 */
export interface OrganizationCreate {
  name: string; // 组织名称，平台内唯一
}

/** 修改组织的请求体，对应 PATCH /organizations/{id}；只提交要改的字段。 */
export interface OrganizationUpdate {
  name?: string; // 新的组织名称
}// 新增/修改组织成员的写入载荷（只提交可变字段）。
export interface MemberGrant {
  user_id: number; // 目标成员用户 ID
  role: OrganizationRole; // 要授予的组织角色
  agent_enabled: boolean; // 是否开启 Agent 调用
  allowed_model_ids: string[]; // 模型白名单
}

/** 组织可选用的模型条目，供成员权限弹窗里的模型白名单选择器使用。 */
export interface ModelOption {
  domain_id: string; // 模型配置 ID，勾选后放进 allowed_model_ids 提交
  label: string; // 展示名称
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

// 选人器里的候选人（用于“邀请成员”搜索框）。
export interface UserCandidate {
  id: number; // 用户 ID
  username: string; // 用户名
  role: string; // 平台级角色，仅用于展示提示
  is_active: boolean; // 是否启用；停用的用户不可被邀请
}
