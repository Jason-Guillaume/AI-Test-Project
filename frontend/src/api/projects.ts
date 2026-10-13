import { api } from './client';
import type {
  OutboundTarget,
  Paginated,
  Project,
  ProjectDetail,
  ProjectMember,
  ProjectRole,
} from '@/types';

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

/**
 * 项目管理接口集合，由项目列表页、项目详情页、成员弹窗与出站目标弹窗调用。
 * 覆盖端点：GET /projects、POST /projects、GET/PATCH/DELETE /projects/{id}、
 * POST /projects/{id}/owner、GET /projects/{id}/members、
 * PUT/PATCH/DELETE /projects/{id}/members/{memberId}、
 * GET/POST /projects/{id}/targets、PATCH/DELETE /projects/{id}/targets/{targetId}。
 */
export const projectsApi = {
  /** 分页查询项目列表，可带关键词与组织过滤。 */
  list: (params: ProjectListQuery) =>
    api.get<Paginated<Project>>('/projects', { params }),
  /** 新建项目，返回创建后的项目对象。 */
  create: (body: ProjectCreate) => api.post<Project>('/projects', body),
  /** 按主键查询项目详情，返回体比列表项多成员等明细字段。 */
  get: (id: number) => api.get<ProjectDetail>(`/projects/${id}`),
  /** 部分更新项目。 */
  update: (id: number, body: ProjectUpdate) =>
    api.patch<Project>(`/projects/${id}`, body),
  /** 删除项目，无返回体。 */
  remove: (id: number) => api.delete<void>(`/projects/${id}`),
  /** 转让项目负责人；body 复用 ProjectMemberCreate，role 指定接手人的项目内角色。 */
  transferOwner: (id: number, body: ProjectMemberCreate) =>
    api.post<Project>(`/projects/${id}/owner`, body),
  /** 分页查询项目成员列表。 */
  listMembers: (id: number, params: { page: number; page_size: number }) =>
    api.get<Paginated<ProjectMember>>(`/projects/${id}/members`, { params }),
  /** 创建或更新项目成员及其角色。 */
  upsertMember: (id: number, memberId: number, body: ProjectMemberCreate) =>
    api.put<ProjectMember>(`/projects/${id}/members/${memberId}`, body),
  /** 仅调整已有成员的角色，只提交 role 一个字段。 */
  updateMemberRole: (id: number, memberId: number, role: ProjectRole) =>
    api.patch<ProjectMember>(`/projects/${id}/members/${memberId}`, { role }),
  /** 移除项目成员，无返回体。 */
  removeMember: (id: number, memberId: number) =>
    api.delete<void>(`/projects/${id}/members/${memberId}`),
  /** 查询项目的出站目标列表。 */
  listTargets: (id: number) =>
    api.get<OutboundTarget[]>(`/projects/${id}/targets`),
  /** 新增出站目标。 */
  createTarget: (id: number, body: OutboundTargetCreate) =>
    api.post<OutboundTarget>(`/projects/${id}/targets`, body),
  /** 启停出站目标。 */
  updateTarget: (id: number, targetId: number, body: OutboundTargetUpdate) =>
    api.patch<OutboundTarget>(`/projects/${id}/targets/${targetId}`, body),
  /** 删除出站目标，无返回体。 */
  removeTarget: (id: number, targetId: number) =>
    api.delete<void>(`/projects/${id}/targets/${targetId}`),
};
