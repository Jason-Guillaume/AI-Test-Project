import { api } from '@/shared/api/client';
import type { Organization, OrganizationMember, UserCandidate } from '@/features/organizations/contracts';
import type { Paginated } from '@/shared/api/contracts';

import type { OrganizationCreate, OrganizationUpdate, MemberGrant, ModelOption } from '../contracts';






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
