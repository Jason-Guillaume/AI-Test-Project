// 缺陷管理相关接口。字段命名与后端 BugCreate/BugUpdate/BugResponse 严格对齐（snake_case）。
// 权限：读 = 项目可见（viewer+）；写（建/改/删）= 项目 member+。
import { api } from '@/shared/api/client';
import { dataLifecycleApi } from '@/features/data-lifecycle/api';
import type { Bug, BugListQuery } from '@/features/defects/contracts';
import type { Paginated } from '@/shared/api/contracts';

import type { BugCreate, BugUpdate, DefectShareDetail, DefectShareOptions, DefectSharePreview, DefectSharePushResult, DefectShareSummary, DefectSourceType, DefectSourceLink, DefectSourceContext } from '../contracts';






/**
 * 缺陷管理接口集合，由缺陷列表页调用。
 * 覆盖端点：GET /bugs、POST /bugs、GET/PUT/DELETE /bugs/{id}。
 */
export const bugsApi = {
  /** 读取授权后的来源定位信息与关联，不复制证据。 */
  sourceContext: (source_type: DefectSourceType, source_id: number) => api.get<DefectSourceContext>('/bugs/sources/context', { params: { source_type, source_id } }),
  sources: (source_type: DefectSourceType, source_id: number) => api.get<DefectSourceLink[]>('/bugs/sources', { params: { source_type, source_id } }),
  bugSources: (id: number) => api.get<DefectSourceLink[]>(`/bugs/${id}/sources`),
  linkSource: (body: { source_type: DefectSourceType; source_id: number; request_key: string; bug_id?: number; bug?: BugCreate }) => api.post<DefectSourceLink>('/bugs/sources', body),
  /** 分页查询可见项目下的缺陷，支持 project_id/status/severity/keyword 过滤。 */
  list: (params: BugListQuery) =>
    api.get<Paginated<Bug>>('/bugs', { params }),
  /** 新建缺陷，返回创建后的 Bug。 */
  create: (body: BugCreate) => api.post<Bug>('/bugs', body),
  /** 按主键查询缺陷详情。 */
  get: (id: number) => api.get<Bug>(`/bugs/${id}`),
  /** 更新缺陷，返回更新后的 Bug。 */
  update: (id: number, body: BugUpdate) => api.put<Bug>(`/bugs/${id}`, body),
  /** 删除缺陷，无返回体。 */
  remove: (id: number) => api.delete<void>(`/bugs/${id}`),
  removeMany: (projectId: number, ids: number[]) =>
    dataLifecycleApi.deleteMany('bug', projectId, ids),
  /** 预览飞书推送，不创建分享。 */
  previewShare: (body: DefectShareOptions & { bug_ids: number[] }) =>
    api.post<DefectSharePreview>('/bugs/shares/preview', body),
  /** 推送一条缺陷。 */
  share: (bugId: number, body: DefectShareOptions) =>
    api.post<DefectSharePushResult>(`/bugs/${bugId}/shares`, body),
  /** 批量推送同一项目的缺陷。 */
  shareBatch: (body: DefectShareOptions & { bug_ids: number[] }) =>
    api.post<{ items: DefectSharePushResult[]; card_count: number }>('/bugs/shares/batch', body),
  /** 分享历史。 */
  listShares: (bugId: number) => api.get<{ items: DefectShareSummary[] }>(`/bugs/${bugId}/shares`),
  /** 分享详情，含外部修复记录。 */
  getShare: (bugId: number, shareId: string) =>
    api.get<DefectShareDetail>(`/bugs/${bugId}/shares/${shareId}`),
  /** 撤销一条分享。 */
  revokeShare: (bugId: number, shareId: string) =>
    api.post<DefectShareSummary>(`/bugs/${bugId}/shares/${shareId}/revoke`),
  /** 重新推送。传入 access_token 时不轮换凭证。 */
  retryShare: (bugId: number, shareId: string, accessToken?: string) =>
    api.post<DefectSharePushResult>(`/bugs/${bugId}/shares/${shareId}/retry`, { access_token: accessToken ?? null }),
  /** 批量撤销。 */
  revokeShares: (items: Array<{ bug_id: number; share_id: string }>) =>
    api.post<DefectShareSummary[]>('/bugs/shares/revoke-batch', { items }),
};
