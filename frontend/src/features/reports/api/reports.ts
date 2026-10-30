// 正式测试报告相关接口。字段命名与后端 features/reports/schemas.py 严格对齐（snake_case）。
//
// 路由形态（挂载 /api/v1 下）：
//   POST   /test-runs/{run_id}/report                    为一次执行生成报告（member+）
//   GET    /projects/{project_id}/reports                项目报告列表（viewer+）
//   GET    /reports/{report_id}                          报告详情（viewer+）
//   DELETE /reports/{report_id}                          删除报告（member+，仅删报告记录）
//   POST   /reports/{report_id}/regenerate-ai-summary    重生成 AI 总结（member+）
//
// 权限（服务端为准）：读 viewer+，写 member+，越权统一 404，前端不展示。
// 幂等：同一 test_run_id 已有 COMPLETED 报告时默认返回已有；regenerate=true 仅重生成 AI 总结。
import { api } from '@/shared/api/client';
import type { ReportGenerateRequest, ReportGenerateResponse, ReportListQuery, TestReportDetail, TestReportListResponse, TestReport } from '@/features/reports/contracts';



export const reportsApi = {
  /** 为一次 TestRun 生成正式报告（统计由后端代码计算，AI 只做总结）。 */
  generate: (runId: number, body: ReportGenerateRequest = {}) =>
    api.post<ReportGenerateResponse>(`/test-runs/${runId}/report`, body),

  /** 项目报告列表（分页信封 {items,total,page,page_size}）。 */
  list: (projectId: number, params: ReportListQuery = {}) =>
    api.get<TestReportListResponse>(`/projects/${projectId}/reports`, {
      params: { page: 1, page_size: 20, ...params },
    }),

  /** 报告详情：报告本体 + TestRun 摘要 + 逐用例执行 + 失败聚类。 */
  get: (reportId: number) => api.get<TestReportDetail>(`/reports/${reportId}`),

  /** 删除报告记录（不删 TestRun / CaseExecution）。 */
  remove: (reportId: number) => api.delete<void>(`/reports/${reportId}`),

  /** 重生成 AI 总结（统计字段不变）。 */
  regenerateAiSummary: (reportId: number) =>
    api.post<TestReport>(`/reports/${reportId}/regenerate-ai-summary`),
};
