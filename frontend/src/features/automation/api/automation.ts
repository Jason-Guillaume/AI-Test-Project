// 自动化测试中心 API。baseURL 已包含 /api/v1。
import { api } from '@/shared/api/client';
import type {
  AutomationExecution,
  AutomationIntegration,
  AutomationProject,
  AutomationReport,
  ConsoleLog,
  JenkinsJobInspect,
  JenkinsJobItem,
  Paginated,
  ReportGrant,
} from '@/features/automation/contracts';

export const automationApi = {
  /** 列出 CI 接入配置。 */
  listIntegrations: (projectId: number) =>
    api.get<Paginated<AutomationIntegration>>(`/projects/${projectId}/automation-integrations`, { params: { page: 1, page_size: 100 } }),
  /** 创建接入配置。令牌只在这次请求中上传。 */
  createIntegration: (projectId: number, body: object) =>
    api.post<AutomationIntegration>(`/projects/${projectId}/automation-integrations`, body),
  /** 更新接入配置。空令牌表示不替换。 */
  updateIntegration: (id: number, body: object) =>
    api.patch<AutomationIntegration>(`/automation-integrations/${id}`, body),
  /** 删除接入配置。 */
  deleteIntegration: (id: number) => api.delete<void>(`/automation-integrations/${id}`),
  /** 测试 Jenkins Job 或云效流水线连接。 */
  testConnection: (id: number, pipelineId: string) =>
    api.post<{ ok: boolean; message: string }>(`/automation-integrations/${id}/test-connection`, undefined, { params: { pipeline_id: pipelineId } }),
  /** 查询 Jenkins 根目录或 Folder 的下一层。 */
  listJenkinsJobs: (id: number, folderPath = '') =>
    api.get<{ folder_path: string; items: JenkinsJobItem[] }>(`/automation-integrations/${id}/jenkins-jobs`, { params: { folder_path: folderPath } }),
  /** 检查 Jenkins Job 参数和可执行状态。 */
  inspectJenkinsJob: (id: number, jobPath: string) =>
    api.get<JenkinsJobInspect>(`/automation-integrations/${id}/jenkins-jobs/inspect`, { params: { job_path: jobPath } }),
  /** 列出自动化项目。 */
  listProjects: (projectId: number) =>
    api.get<Paginated<AutomationProject>>(`/projects/${projectId}/automation-projects`, { params: { page: 1, page_size: 100 } }),
  /** 创建自动化项目。 */
  createProject: (projectId: number, body: object) =>
    api.post<AutomationProject>(`/projects/${projectId}/automation-projects`, body),
  /** 更新自动化项目。 */
  updateProject: (id: number, body: object) =>
    api.patch<AutomationProject>(`/automation-projects/${id}`, body),
  /** 删除自动化项目。 */
  deleteProject: (id: number) => api.delete<void>(`/automation-projects/${id}`),
  /** 验证项目绑定的流水线。 */
  verifyProject: (id: number) => api.post<{ ok: boolean; message: string }>(`/automation-projects/${id}/verify`),
  /** 触发一次统一 CI 执行。 */
  trigger: (id: number, body: object) =>
    api.post<AutomationExecution>(`/automation-projects/${id}/executions`, body),
  /** 执行历史。 */
  listExecutions: (projectId: number, params: Record<string, unknown>) =>
    api.get<Paginated<AutomationExecution>>(`/projects/${projectId}/automation-executions`, { params }),
  /** 执行详情。 */
  getExecution: (id: number) => api.get<AutomationExecution>(`/automation-executions/${id}`),
  /** 取消外部 CI 运行。 */
  cancel: (id: number) => api.post<AutomationExecution>(`/automation-executions/${id}/cancel`),
  /** 立即同步外部 CI 状态。 */
  sync: (id: number) => api.post<AutomationExecution>(`/automation-executions/${id}/sync`),
  /** 读取平台保存或 Jenkins 提供的 Console 日志。 */
  consoleLog: (id: number) => api.get<ConsoleLog>(`/automation-executions/${id}/console-log`),
  /** 报告列表。 */
  listReports: (projectId: number, params: Record<string, unknown> = {}) =>
    api.get<Paginated<AutomationReport>>(`/projects/${projectId}/automation-reports`, { params: { page: 1, page_size: 100, ...params } }),
  /** 报告趋势。 */
  trend: (projectId: number, automationProjectId?: number) =>
    api.get<AutomationReport[]>(`/projects/${projectId}/automation-report-trend`, { params: { automation_project_id: automationProjectId } }),
  /** 报告详情。 */
  getReport: (id: number) => api.get<AutomationReport>(`/automation-reports/${id}`),
  /** 对比两次报告。 */
  compare: (leftId: number, rightId: number) =>
    api.get<{ left: AutomationReport; right: AutomationReport; delta: Record<string, number> }>('/automation-reports/compare', { params: { left_id: leftId, right_id: rightId } }),
  /** 签发 Allure 页面地址。 */
  grant: (id: number) => api.post<ReportGrant>(`/automation-reports/${id}/view-grant`),
};
