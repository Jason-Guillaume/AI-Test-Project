import { api } from './client';
import type {
  Organization,
  OrganizationMember,
  OrganizationRole,
  Paginated,
  UserCandidate,
} from '@/types';

/** 新建组织的请求体，对应 POST /organizations。 */
export interface OrganizationCreate {
  name: string; // 组织名称，平台内唯一
}

/** 修改组织的请求体，对应 PATCH /organizations/{id}；只提交要改的字段。 */
export interface OrganizationUpdate {
  name?: string; // 新的组织名称
}

/** 授予或调整组织成员权限的写入载荷，对应 PUT /organizations/{orgId}/members/{memberId}。 */
export interface MemberGrant {
  user_id: number; // 目标成员的用户 ID
  role: OrganizationRole; // 组织内角色：owner / admin / member
  agent_enabled: boolean; // 是否允许该成员通过 Agent 调用大模型
  allowed_model_ids: string[]; // 允许调用的模型配置 ID 白名单；空数组表示不额外限制
}

/** 组织可选用的模型条目，供成员权限弹窗里的模型白名单选择器使用。 */
export interface ModelOption {
  domain_id: string; // 模型配置 ID，勾选后放进 allowed_model_ids 提交
  label: string; // 展示名称
}

/**
 * 组织管理接口集合，由组织管理页与成员管理弹窗调用。
 * 覆盖端点：GET /organizations、POST /organizations、PATCH /organizations/{id}、
 * GET /organizations/{id}/members、GET /organizations/{id}/candidates、
 * GET /organizations/{id}/models、PUT/DELETE /organizations/{orgId}/members/{memberId}、
 * POST /organizations/{orgId}/members/{memberId}/upgrade。
 */
export const organizationsApi = {
  /** 分页查询当前用户可见的组织列表。 */
  list: () =>
    api.get<Paginated<Organization>>('/organizations'),
  /** 新建组织；创建人会自动成为该组织的拥有者。 */
  create: (body: OrganizationCreate) =>
    api.post<Organization>('/organizations', body),
  /** 修改组织信息。 */
  update: (id: number, body: OrganizationUpdate) =>
    api.patch<Organization>(`/organizations/${id}`, body),
  /** 查询组织成员列表，返回 { items, total } 结构（不是分页信封）。 */
  members: (id: number) =>
    api.get<{ items: OrganizationMember[]; total: number }>(
      `/organizations/${id}/members`,
    ),
  /** 按用户名查找可邀请的候选人；查不到时后端返回 item 为 null。 */
  findCandidate: (id: number, username: string) =>
    api.get<{ item: UserCandidate | null }>(
      `/organizations/${id}/candidates`,
      { params: { username } },
    ),
  /** 取组织可选用的模型列表，供成员权限里的模型白名单勾选。 */
  availableModels: (id: number) =>
    api.get<{ items: ModelOption[]; total: number }>(
      `/organizations/${id}/models`,
    ),
  /** 创建或更新成员权限：角色、Agent 开关与模型白名单一起提交。 */
  upsertMember: (orgId: number, memberId: number, body: MemberGrant) =>
    api.put<OrganizationMember>(
      `/organizations/${orgId}/members/${memberId}`,
      body,
    ),
  /** 移除组织成员，无返回体。 */
  removeMember: (orgId: number, memberId: number) =>
    api.delete<void>(`/organizations/${orgId}/members/${memberId}`),
  /** 把成员提升为组织拥有者，用于转让组织归属。 */
  transferOwnership: (orgId: number, memberId: number) =>
    api.post<Organization>(
      `/organizations/${orgId}/members/${memberId}/upgrade`,
    ),
};
