import { api } from '@/shared/api/client';
import type { AxiosRequestConfig } from 'axios';
import type { Environment } from '@/features/environments/contracts';
import type { OutboundTarget, Project, ProjectDetail, ProjectMember, ProjectRole } from '@/features/projects/contracts';
import type { Paginated } from '@/shared/api/contracts';

import type { ProjectListQuery, ProjectCreate, ProjectUpdate, ProjectMemberCreate, OutboundTargetCreate, OutboundTargetUpdate } from '../contracts';



import type { EnvironmentUpdate, ProjectEnvironmentCreate } from '@/features/environments/contracts';



/**
 * 项目管理接口集合，由项目列表页、项目详情页、成员弹窗与出站目标弹窗调用。
 * 覆盖端点：GET /projects、POST /projects、GET/PATCH/DELETE /projects/{id}、
 * POST /projects/{id}/owner、GET /projects/{id}/members、
 * PUT/PATCH/DELETE /projects/{id}/members/{memberId}、
 * GET/POST /projects/{id}/targets、PATCH/DELETE /projects/{id}/targets/{targetId}。
 */
export const projectsApi = {
  /** 分页查询项目列表，可带关键词与组织过滤。 */
  list: (params: ProjectListQuery, config?: AxiosRequestConfig) =>
    api.get<Paginated<Project>>('/projects', { ...config, params }),
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
  /** 查询项目已绑定环境；响应不包含默认请求头。 */
  listEnvironments: (id: number, include_inactive = false) =>
    api.get<Paginated<Environment>>(`/projects/${id}/environments`, { params: { include_inactive } }),
  /** 新建项目环境，目标地址和默认请求头独立保存在项目绑定上。 */
  createEnvironment: (id: number, body: ProjectEnvironmentCreate) =>
    api.post<Environment>(`/projects/${id}/environments`, body),
  /** 修改项目自己的环境地址与状态。 */
  updateEnvironment: (id: number, environmentId: number, body: EnvironmentUpdate) =>
    api.patch<Environment>(`/projects/${id}/environments/${environmentId}`, body),
  /** 设置项目默认执行环境。 */
  setDefaultEnvironment: (id: number, environmentId: number) =>
    api.post<Environment>(`/projects/${id}/environments/${environmentId}/set-default`),
  /** 停用项目环境绑定，保留模板与历史执行引用。 */
  deactivateEnvironment: (id: number, environmentId: number) =>
    api.delete<void>(`/projects/${id}/environments/${environmentId}`),
};
