// 缺陷管理相关接口。字段命名与后端 BugCreate/BugUpdate/BugResponse 严格对齐（snake_case）。
// 权限：读 = 项目可见（viewer+）；写（建/改/删）= 项目 member+。
import { api } from '@/shared/api/client';
import type { Bug, BugListQuery } from '@/features/defects/contracts';
import type { Paginated } from '@/shared/api/contracts';

import type { BugCreate, BugUpdate, DefectSourceType, DefectSourceLink, DefectSourceContext } from '../contracts';






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
};
