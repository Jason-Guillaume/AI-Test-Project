// 缺陷管理相关接口。字段命名与后端 BugCreate/BugUpdate/BugResponse 严格对齐（snake_case）。
// 权限：读 = 项目可见（viewer+）；写（建/改/删）= 项目 member+。
import { api } from './client';
import type { Bug, BugListQuery, BugStatus, Paginated } from '@/types';

/** 新建缺陷的请求体。 */
export interface BugCreate {
  project_id: number; // 所属项目 ID
  title: string; // 缺陷标题（必填）
  description?: string; // 描述
  severity?: 1 | 2 | 3 | 4; // 严重度 1-4，默认 2
  status?: BugStatus; // 状态，默认 '待确认'
  steps_to_reproduce?: string; // 复现步骤
  environment?: string; // 环境标识
  assignee_id?: number | null; // 处理人；必须是项目成员；null 表示清空
}

/** 修改缺陷的请求体；全部字段可选，只提交要改的项。 */
export interface BugUpdate {
  title?: string;
  description?: string;
  severity?: 1 | 2 | 3 | 4;
  status?: BugStatus;
  steps_to_reproduce?: string;
  environment?: string;
  assignee_id?: number | null;
}

export type DefectSourceType = 'CASE_EXECUTION' | 'SECURITY_FINDING';
export interface DefectSourceLink {
  id: number;
  project_id: number;
  bug_id: number;
  case_execution_id: number | null;
  security_finding_id: number | null;
  created_at: string;
}
export interface DefectSourceContext {
  project_id: number;
  source_type: DefectSourceType;
  source_id: number;
  test_run_id: number | null;
}

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
