// OWASP ZAP 安全扫描 API；主动扫描仍必须经过计划预览和人工确认。
import { api } from '@/shared/api/client';
import type { ZapHealth, ZapCapabilities, ScanTarget, ScanTargetCreate, ScanTargetUpdate, ScanTargetListResponse, ScanAuthProfile, ScanAuthProfileCreate, ScanAuthProfileUpdate, ScanAuthProfileListResponse, ScanProfile, ScanProfileCreate, ScanProfileUpdate, ScanProfileListResponse, ScanJobCreate, ScanJob, ScanJobListResponse, ScanJobProgress, ScanEventListResponse, ScanAlertListResponse, ScanCoverage, ScanFindingListResponse, ScanPlan, ScanReport } from './contracts';

export const zapApi = {
// =================================================================== ZAP 安全扫描（Phase 2）
// 路由形态（挂载 /api/v1 下）：
//   GET /security/zap/health、GET /security/zap/capabilities（平台管理员，基础设施可观测性）
//   GET/POST /projects/{pid}/security/scan-targets；GET/PATCH/DELETE /scan-targets/{id}
//   GET/POST /projects/{pid}/security/scan-profiles；GET/PATCH/DELETE /scan-profiles/{id}
//   GET/POST /projects/{pid}/security/scan-auth-profiles；GET/PATCH/DELETE /scan-auth-profiles/{id}
//   POST /projects/{pid}/security/scan-jobs/plan（纯读取的计划预览）
//   POST /projects/{pid}/security/scan-jobs（202 登记任务）
//   GET /projects/{pid}/security/scan-jobs；GET /scan-jobs/{id}
//   POST /scan-jobs/{id}/cancel；GET /scan-jobs/{id}/progress
//   GET /scan-jobs/{id}/events、/alerts、/findings、/coverage、/report
// 安全红线：主动扫描必须由人在「计划预览」后显式确认（confirmed + approval_note）；
//   生产环境目标由后端 gate 直接拒绝；认证配置永不回显凭据明文。
getZapHealth: () => api.get<ZapHealth>('/security/zap/health'),
getZapCapabilities: () => api.get<ZapCapabilities>('/security/zap/capabilities'),

// ------------------------------------------------------------- 扫描目标
listScanTargets(
  projectId: number,
  params: { enabled?: boolean; page?: number; page_size?: number } = {},
) {
  return api.get<ScanTargetListResponse>(`/projects/${projectId}/security/scan-targets`, {
    params,
  });
},
createScanTarget: (projectId: number, body: ScanTargetCreate) =>
  api.post<ScanTarget>(`/projects/${projectId}/security/scan-targets`, body),
getScanTarget: (projectId: number, scanTargetId: number) =>
  api.get<ScanTarget>(`/projects/${projectId}/security/scan-targets/${scanTargetId}`),
updateScanTarget: (projectId: number, scanTargetId: number, body: ScanTargetUpdate) =>
  api.patch<ScanTarget>(
    `/projects/${projectId}/security/scan-targets/${scanTargetId}`,
    body,
  ),
removeScanTarget: (projectId: number, scanTargetId: number) =>
  api.delete<void>(`/projects/${projectId}/security/scan-targets/${scanTargetId}`),

// ------------------------------------------------------------- 扫描策略
listScanProfiles(
  projectId: number,
  params: {
    enabled?: boolean;
    is_builtin?: boolean;
    page?: number;
    page_size?: number;
  } = {},
) {
  return api.get<ScanProfileListResponse>(
    `/projects/${projectId}/security/scan-profiles`,
    { params },
  );
},
createScanProfile: (projectId: number, body: ScanProfileCreate) =>
  api.post<ScanProfile>(`/projects/${projectId}/security/scan-profiles`, body),
getScanProfile: (projectId: number, scanProfileId: number) =>
  api.get<ScanProfile>(`/projects/${projectId}/security/scan-profiles/${scanProfileId}`),
updateScanProfile: (projectId: number, scanProfileId: number, body: ScanProfileUpdate) =>
  api.patch<ScanProfile>(
    `/projects/${projectId}/security/scan-profiles/${scanProfileId}`,
    body,
  ),
removeScanProfile: (projectId: number, scanProfileId: number) =>
  api.delete<void>(`/projects/${projectId}/security/scan-profiles/${scanProfileId}`),

// ------------------------------------------------------------- 认证配置
listScanAuthProfiles(
  projectId: number,
  params: { enabled?: boolean; page?: number; page_size?: number } = {},
) {
  return api.get<ScanAuthProfileListResponse>(
    `/projects/${projectId}/security/scan-auth-profiles`,
    { params },
  );
},
createScanAuthProfile: (projectId: number, body: ScanAuthProfileCreate) =>
  api.post<ScanAuthProfile>(`/projects/${projectId}/security/scan-auth-profiles`, body),
getScanAuthProfile: (projectId: number, authProfileId: number) =>
  api.get<ScanAuthProfile>(
    `/projects/${projectId}/security/scan-auth-profiles/${authProfileId}`,
  ),
updateScanAuthProfile: (projectId: number, authProfileId: number, body: ScanAuthProfileUpdate) =>
  api.patch<ScanAuthProfile>(
    `/projects/${projectId}/security/scan-auth-profiles/${authProfileId}`,
    body,
  ),
removeScanAuthProfile: (projectId: number, authProfileId: number) =>
  api.delete<void>(`/projects/${projectId}/security/scan-auth-profiles/${authProfileId}`),

// ------------------------------------------------------------- 扫描任务
/** 计划预览：纯读取，不写库、不发 ZAP 请求。提交前必须先过这一步。 */
planScanJob: (projectId: number, body: ScanJobCreate) =>
  api.post<ScanPlan>(`/projects/${projectId}/security/scan-jobs/plan`, body),
/** 登记扫描任务，202 立即返回；真正执行由后台 Worker 完成。 */
createScanJob: (projectId: number, body: ScanJobCreate) =>
  api.post<ScanJob>(`/projects/${projectId}/security/scan-jobs`, body),
listScanJobs(
  projectId: number,
  params: {
    status?: string;
    target_id?: number;
    page?: number;
    page_size?: number;
  } = {},
) {
  return api.get<ScanJobListResponse>(`/projects/${projectId}/security/scan-jobs`, {
    params,
  });
},
getScanJob: (projectId: number, scanJobId: number) =>
  api.get<ScanJob>(`/projects/${projectId}/security/scan-jobs/${scanJobId}`),
/** 只置持久化取消位，由 Worker 在下一个检查点真正停止。 */
cancelScanJob: (projectId: number, scanJobId: number) =>
  api.post<ScanJob>(`/projects/${projectId}/security/scan-jobs/${scanJobId}/cancel`),
getScanProgress: (projectId: number, scanJobId: number) =>
  api.get<ScanJobProgress>(`/projects/${projectId}/security/scan-jobs/${scanJobId}/progress`),
listScanEvents(
  projectId: number,
  scanJobId: number,
  params: { event_type?: string; page?: number; page_size?: number } = {},
) {
  return api.get<ScanEventListResponse>(
    `/projects/${projectId}/security/scan-jobs/${scanJobId}/events`,
    { params },
  );
},
listScanAlerts(
  projectId: number,
  scanJobId: number,
  params: { rule_id?: string; severity?: string; page?: number; page_size?: number } = {},
) {
  return api.get<ScanAlertListResponse>(
    `/projects/${projectId}/security/scan-jobs/${scanJobId}/alerts`,
    { params },
  );
},
listScanFindings(
  projectId: number,
  scanJobId: number,
  params: { source_rule_id?: string; page?: number; page_size?: number } = {},
) {
  return api.get<ScanFindingListResponse>(
    `/projects/${projectId}/security/scan-jobs/${scanJobId}/findings`,
    { params },
  );
},
getScanCoverage: (projectId: number, scanJobId: number, page = 1, page_size = 100) =>
  api.get<ScanCoverage>(`/projects/${projectId}/security/scan-jobs/${scanJobId}/coverage`, {
    params: { page, page_size },
  }),
getScanReport: (projectId: number, scanJobId: number) =>
  api.get<ScanReport>(`/projects/${projectId}/security/scan-jobs/${scanJobId}/report`),
};
