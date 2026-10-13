import { api } from './client';
import type {
  DashboardOverview,
  ProjectSummaryResponse,
  ReadyResponse,
} from '@/types';

/**
 * 仪表盘接口集合，由首页看板与就绪检查轮询调用。
 * 覆盖端点：GET /dashboard/overview、GET /dashboard/projects、GET /dashboard/ready、GET /dashboard/platform。
 */
export const dashboardApi = {
  /** 组织维度的总览统计数据。 */
  overview: () => api.get<DashboardOverview>('/dashboard/overview'),
  /**
   * 分页的项目摘要列表；params 只含 page 与 page_size 两个分页参数。
   */
  projects: (params: { page: number; page_size: number }) =>
    api.get<ProjectSummaryResponse>('/dashboard/projects', { params }),
  /** 就绪探针，供前端轮询后端是否可用。 */
  ready: () => api.get<ReadyResponse>('/dashboard/ready'),
  /** 平台维度的总览统计（管理员看板用）。 */
  platform: () => api.get<DashboardOverview>('/dashboard/platform'),
};
