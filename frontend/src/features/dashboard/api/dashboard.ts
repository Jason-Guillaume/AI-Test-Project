import { api } from '@/shared/api/client';
import type { DashboardOverview, DashboardCharts } from '@/features/dashboard/contracts';
import type { ProjectSummaryResponse } from '@/features/projects/contracts';
import type { ReadyResponse } from '@/shared/api/contracts';



/**
 * 仪表盘接口集合，由首页看板与就绪检查轮询调用。
 * 覆盖端点：GET /dashboard/overview、/dashboard/charts、/dashboard/projects、/dashboard/ready、/dashboard/platform。
 */
export const dashboardApi = {
  /** 组织维度的总览统计数据。 */
  overview: () => api.get<DashboardOverview>('/dashboard/overview'),
  /** 最近指定天数的工作台图表，按当前可见项目及选择的组织/项目过滤。 */
  charts: (params: { days?: number; organization_id?: number; project_id?: number } = {}) =>
    api.get<DashboardCharts>('/dashboard/charts', { params }),
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
