// 安全测试（Security Testing Phase 1）接口客户端。
// 字段命名与后端 features/security_testing/schemas.py 严格对齐（snake_case）。
//
// 路由形态（挂载 /api/v1 下，管理面 = 平台 JWT）：
//   GET/PUT   /projects/{pid}/security-setting
//   GET/POST  /projects/{pid}/security-strategies（GET 支持 category/enabled 过滤）
//   GET/PATCH/DELETE /security-strategies/{id}
//   POST      /security-strategies/{id}/rules
//   PATCH/DELETE /security-rules/{id}
//   POST      /projects/{pid}/security-plans/preview
//   POST      /security-plans/{id}/confirm、/discard
//   GET       /projects/{pid}/security-cases（支持 api_id/strategy_id/mutation_type/enabled）
//   GET/PATCH /security-cases/{id}（PATCH 只改启用状态）
//   POST      /security-cases/{id}/confirm-risk（人工高风险确认；Agent 工具不调用）
//   POST      /projects/{pid}/security-runs（批量执行，复用既有 TestRun）
//   GET       /security-executions/{id}
//   GET       /projects/{pid}/security-findings（支持 severity/status/api_id）
//   GET/PATCH /security-findings/{id}（PATCH 只改状态）
//
// 安全红线（§需求说明）：
//   - 安全模块只改请求与解释结果；不做注入 / 扫描器 / 自动建缺陷；
//   - 不在生产环境发安全变异请求（allow_production 恒不生效）；
//   - confirm-risk 与 execute 都只能由人在本页触发，不会自动执行；
//   - 疑似问题文案统一「疑似问题」，SecurityFinding.bug_id 恒为 null，无「转 Bug」入口。
import { api } from './client';
import type {
  MutationRule,
  MutationRuleCreate,
  MutationRuleUpdate,
  Paginated,
  PlanConfirmRequest,
  PlanConfirmResponse,
  PlanPreviewRequest,
  PlanPreviewResponse,
  SecurityCase,
  SecurityCaseDetail,
  SecurityCaseListResponse,
  SecurityCaseUpdate,
  SecurityExecution,
  SecurityFinding,
  SecurityFindingListResponse,
  SecurityFindingUpdate,
  SecurityPlan,
  SecurityRunRequest,
  SecuritySetting,
  SecuritySettingUpdate,
  SecuritySeverity,
  SecurityStrategy,
  SecurityStrategyCreate,
  SecurityStrategyListResponse,
  SecurityStrategyUpdate,
  TestRun,
} from '@/types';

/** 安全测试管理面接口集合（全部走平台 JWT）。 */
export const securityApi = {
  // ------------------------------------------------------------------ 项目设置
  getSetting: (projectId: number) =>
    api.get<SecuritySetting>(`/projects/${projectId}/security-setting`),
  updateSetting: (projectId: number, body: SecuritySettingUpdate) =>
    api.put<SecuritySetting>(`/projects/${projectId}/security-setting`, body),

  // ------------------------------------------------------------------ 策略
  listStrategies(
    projectId: number,
    params: { category?: string; enabled?: boolean; page?: number; page_size?: number } = {},
  ) {
    return api.get<SecurityStrategyListResponse>(`/projects/${projectId}/security-strategies`, {
      params,
    });
  },
  createStrategy: (projectId: number, body: SecurityStrategyCreate) =>
    api.post<SecurityStrategy>(`/projects/${projectId}/security-strategies`, body),
  getStrategy: (strategyId: number) =>
    api.get<SecurityStrategy>(`/security-strategies/${strategyId}`),
  updateStrategy: (strategyId: number, body: SecurityStrategyUpdate) =>
    api.patch<SecurityStrategy>(`/security-strategies/${strategyId}`, body),
  removeStrategy: (strategyId: number) =>
    api.delete<void>(`/security-strategies/${strategyId}`),

  // ------------------------------------------------------------------ 变异规则
  createRule: (strategyId: number, body: MutationRuleCreate) =>
    api.post<MutationRule>(`/security-strategies/${strategyId}/rules`, body),
  updateRule: (ruleId: number, body: MutationRuleUpdate) =>
    api.patch<MutationRule>(`/security-rules/${ruleId}`, body),
  removeRule: (ruleId: number) => api.delete<void>(`/security-rules/${ruleId}`),

  // ------------------------------------------------------------------ 计划（preview/confirm/discard）
  /** 预览：只算一遍，不落 TestCase。落库的 security_plan 是未确认快照。 */
  previewPlan: (projectId: number, body: PlanPreviewRequest) =>
    api.post<PlanPreviewResponse>(`/projects/${projectId}/security-plans/preview`, body),
  /** 把选中的预览项写成 case_type='SECURITY' 的用例 + security_case 扩展行。 */
  confirmPlan: (planId: number, body: PlanConfirmRequest) =>
    api.post<PlanConfirmResponse>(`/security-plans/${planId}/confirm`, body),
  discardPlan: (planId: number) =>
    api.post<SecurityPlan>(`/security-plans/${planId}/discard`),

  // ------------------------------------------------------------------ 用例
  listCases(
    projectId: number,
    params: {
      api_id?: number;
      strategy_id?: number;
      mutation_type?: string;
      enabled?: boolean;
      page?: number;
      page_size?: number;
    } = {},
  ) {
    return api.get<SecurityCaseListResponse>(`/projects/${projectId}/security-cases`, {
      params,
    });
  },
  getCase: (securityCaseId: number) =>
    api.get<SecurityCaseDetail>(`/security-cases/${securityCaseId}`),
  updateCase: (securityCaseId: number, body: SecurityCaseUpdate) =>
    api.patch<SecurityCase>(`/security-cases/${securityCaseId}`, body),
  /** 高风险确认只能人工走这个端点；Agent 工具不调用它。 */
  confirmRisk: (securityCaseId: number) =>
    api.post<SecurityCase>(`/security-cases/${securityCaseId}/confirm-risk`),
  /** 批量执行：内部临时 TestPlan + Suite，复用既有 RunService。 */
  runSecurity: (projectId: number, body: SecurityRunRequest) =>
    api.post<TestRun>(`/projects/${projectId}/security-runs`, body),

  // ------------------------------------------------------------------ 执行记录
  getExecution: (securityExecutionId: number) =>
    api.get<SecurityExecution>(`/security-executions/${securityExecutionId}`),

  // ------------------------------------------------------------------ 疑似问题（Finding）
  listFindings(
    projectId: number,
    params: {
      severity?: string;
      status?: string;
      api_id?: number;
      page?: number;
      page_size?: number;
    } = {},
  ) {
    return api.get<SecurityFindingListResponse>(`/projects/${projectId}/security-findings`, {
      params,
    });
  },
  getFinding: (findingId: number) =>
    api.get<SecurityFinding>(`/security-findings/${findingId}`),
  /** 只允许改状态；非法迁移由服务层 400。 */
  updateFinding: (findingId: number, body: SecurityFindingUpdate) =>
    api.patch<SecurityFinding>(`/security-findings/${findingId}`, body),

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

// --------------------------------------------------------------------------- ZAP 类型定义
// 字段命名与后端 features/security_testing/zap/schemas.py 严格对齐（snake_case）。
// 集中放在本文件而不是 @/types：Phase 1 的类型都在 @/types 里，Phase 2 的 ZAP 域
// 独立成组，避免把几百行的中央类型文件再撑大一轮。

/** 扫描目标形态：API = 只喂 OpenAPI；WEB = 只爬页面；HYBRID = 两者都做。 */
export type ScanTargetType = 'API' | 'WEB' | 'HYBRID';

/** 六档扫描模式（需求 §五）。带 _ACTIVE / FULL_AUTHORIZED 的是受控主动扫描。 */
export type ScanMode =
  | 'API_PASSIVE'
  | 'WEB_PASSIVE'
  | 'HYBRID_PASSIVE'
  | 'API_ACTIVE'
  | 'WEB_ACTIVE'
  | 'FULL_AUTHORIZED';

/** 认证方式（需求 §十一/§十二/§十三）。 */
export type ScanAuthMode = 'NONE' | 'BEARER_TOKEN' | 'HEADER_BASED' | 'BROWSER_AUTH' | 'MANUAL';

/** 目标授权状态：PENDING 待确认 / AUTHORIZED 已授权 / REVOKED 已撤销。 */
export type ScanAuthorizationStatus = 'PENDING' | 'AUTHORIZED' | 'REVOKED';

/** 登录态验证结果：只有 LOGGED_IN 允许继续爬业务页面。 */
export type ScanAuthStatus = 'LOGGED_IN' | 'LOGGED_OUT' | 'UNVERIFIABLE';

/** 扫描任务状态（需求 §七），progress 为 -1 表示无法给出精确百分比。 */
export type ScanJobStatus =
  | 'PENDING'
  | 'PREPARING'
  | 'AUTHENTICATING'
  | 'CRAWLING'
  | 'PASSIVE_SCANNING'
  | 'ACTIVE_SCANNING'
  | 'IMPORTING_RESULTS'
  | 'COMPLETED'
  | 'FAILED'
  | 'CANCELLED'
  | 'TIMED_OUT';

/** 一个扫描对象的覆盖阶段（需求 §三十一）。 */
export type CoverageStage =
  | 'DISCOVERED'
  | 'REQUESTED'
  | 'RESPONDED'
  | 'PASSIVE_ANALYZED'
  | 'ACTIVE_SCANNED'
  | 'NOT_COVERED';

/** ZAP 服务健康检查：只读配置，不含密钥，也不发起网络请求。 */
export interface ZapHealth {
  enabled: boolean;
  available: boolean;
  version: string | null;
  reachable: boolean;
  api_key_configured: boolean;
  message: string;
}

/** 单个 ZAP 能力探测结果。supported=false 时必须显示「受限」而不是假装可用。 */
export interface ZapCapability {
  name: string;
  supported: boolean;
  detail: string;
}

/** ZAP 版本与能力清单。 */
export interface ZapCapabilities {
  version: string | null;
  addon_names: string[];
  addon_versions: Record<string, string>;
  capabilities: ZapCapability[];
}

// --------------------------------------------------------------------------- 扫描目标

export interface ScanTarget {
  id: number;
  project_id: number;
  environment_id: number | null;
  name: string;
  target_type: ScanTargetType;
  base_url: string;
  entry_url: string | null;
  enabled: boolean;
  authorization_status: ScanAuthorizationStatus;
  authorization_note: string | null;
  active_scan_allowed: boolean;
  allowed_hosts: string[];
  include_paths: string[];
  exclude_paths: string[];
  /** 目标落在生产环境时该字段为 True，主动扫描请求会被后端直接拒绝。 */
  is_production: boolean;
  created_by: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScanTargetCreate {
  name: string;
  target_type: ScanTargetType;
  base_url: string;
  entry_url?: string | null;
  environment_id?: number | null;
  enabled?: boolean;
  authorization_status?: ScanAuthorizationStatus;
  authorization_note?: string | null;
  active_scan_allowed?: boolean;
  allowed_hosts?: string[];
  include_paths?: string[];
  exclude_paths?: string[];
}

/** 修改扫描目标。只允许改传入的字段。 */
export type ScanTargetUpdate = Partial<ScanTargetCreate>;

export type ScanTargetListResponse = Paginated<ScanTarget>;

// --------------------------------------------------------------------------- 认证配置

/** 认证配置响应：**只回显掩码字段，绝不含凭据明文**。 */
export interface ScanAuthProfile {
  id: number;
  project_id: number;
  name: string;
  auth_mode: ScanAuthMode;
  enabled: boolean;
  session_method: string | null;
  session_header: string | null;
  session_name: string | null;
  has_credential: boolean;
  token_fingerprint: string | null;
  credential_updated_at: string | null;
  credential_expires_at: string | null;
  authentication_check_url: string | null;
  logged_in_indicator: string | null;
  logged_out_indicator: string | null;
  expected_user_id: string | null;
  auth_expiry_policy: string;
  description: string | null;
  created_by: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScanAuthProfileCreate {
  name: string;
  auth_mode?: ScanAuthMode;
  session_method?: string | null;
  session_header?: string | null;
  session_name?: string | null;
  /** 明文凭据，只用于落库加密；响应中永不回显。 */
  credential?: string | null;
  authentication_check_url?: string | null;
  logged_in_indicator?: string | null;
  logged_out_indicator?: string | null;
  expected_user_id?: string | null;
  auth_expiry_policy?: string;
  credential_expires_at?: string | null;
  description?: string | null;
}

/** 修改认证配置。credential 传空字符串 / remove_credential 表示删除凭据。 */
export type ScanAuthProfileUpdate = Partial<ScanAuthProfileCreate> & {
  enabled?: boolean;
  remove_credential?: boolean;
};

export type ScanAuthProfileListResponse = Paginated<ScanAuthProfile>;

// --------------------------------------------------------------------------- 扫描策略

export interface ScanProfile {
  id: number;
  project_id: number | null;
  code: string | null;
  /** 平台内置策略：全项目共享，任何项目内的编辑/删除都会被后端 400 拒绝。 */
  is_builtin: boolean;
  name: string;
  scan_mode: ScanMode;
  /** 由后端按 scan_mode 判定，不可由前端字符串绕过。 */
  is_active_scan: boolean;
  spider_enabled: boolean;
  client_spider_enabled: boolean;
  passive_enabled: boolean;
  active_enabled: boolean;
  authentication_profile_id: number | null;
  max_duration: number;
  max_depth: number;
  max_concurrency: number;
  request_delay: number;
  max_alerts_per_rule: number | null;
  max_request_budget: number | null;
  include_paths: string[];
  exclude_paths: string[];
  selected_rule_ids: string[];
  enabled: boolean;
  description: string | null;
  created_by: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScanProfileCreate {
  name: string;
  scan_mode: ScanMode;
  spider_enabled?: boolean;
  client_spider_enabled?: boolean;
  passive_enabled?: boolean;
  active_enabled?: boolean;
  authentication_profile_id?: number | null;
  max_duration?: number;
  max_depth?: number;
  max_concurrency?: number;
  request_delay?: number;
  max_alerts_per_rule?: number | null;
  max_request_budget?: number | null;
  include_paths?: string[];
  exclude_paths?: string[];
  selected_rule_ids?: string[];
  enabled?: boolean;
  description?: string | null;
}

export type ScanProfileUpdate = Partial<ScanProfileCreate>;

export type ScanProfileListResponse = Paginated<ScanProfile>;

// --------------------------------------------------------------------------- 扫描任务

/** 发起扫描。主动扫描需要显式 confirmed，并由后端校验真实的人类批准行为。 */
export interface ScanJobCreate {
  target_id: number;
  scan_profile_id: number;
  test_run_id?: number | null;
  confirmed?: boolean;
  approval_note?: string | null;
  idempotency_key?: string | null;
}

export interface ScanJob {
  id: number;
  project_id: number;
  target_id: number;
  target_name: string | null;
  environment_id: number | null;
  environment_name: string | null;
  scan_profile_id: number;
  scan_profile_name: string | null;
  scan_mode: ScanMode;
  status: ScanJobStatus;
  /** -1 表示无法给出精确百分比，只展示阶段与计数。 */
  progress: number;
  stage: string | null;
  authentication_mode: ScanAuthMode | null;
  authentication_status: ScanAuthStatus | null;
  browser_session_established: boolean;
  initiated_by: number | null;
  approved_by: number | null;
  zap_scan_reference: string | null;
  test_run_id: number | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  total_alerts: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  info_count: number;
  urls_discovered: number;
  requests_made: number;
  new_findings_count: number;
  duplicate_findings_count: number;
  coverage_summary: Record<string, number>;
  error_code: string | null;
  error_message: string | null;
  cancel_requested: boolean;
  worker_owner: string | null;
  heartbeat_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export type ScanJobListResponse = Paginated<ScanJob>;

export interface ScanJobProgress {
  id: number;
  status: ScanJobStatus;
  stage: string | null;
  progress: number;
  urls_discovered: number;
  requests_made: number;
  total_alerts: number;
  high_count: number;
  medium_count: number;
  low_count: number;
  info_count: number;
  cancel_requested: boolean;
  duration_ms: number | null;
}

// --------------------------------------------------------------------------- 过程事件 / 告警 / 覆盖率 / Finding

export interface ScanEvent {
  id: number;
  job_id: number;
  seq: number;
  event_type: string;
  stage: string | null;
  message: string | null;
  payload_json: Record<string, unknown> | null;
  created_at: string | null;
}

export type ScanEventListResponse = Paginated<ScanEvent>;

/** 一条归一化后的 ZAP 告警（已脱敏）。confidence 与 severity 是两个独立维度。 */
export interface ScanAlert {
  rule_id: string;
  name: string;
  /** ZAP 原始 Risk 文本（如 "High"），不做翻译不做映射。 */
  risk: string;
  /** ZAP 原始 Confidence（1-5），与 severity 是独立维度。 */
  confidence: number;
  /** 平台归一化后的严重级别。 */
  severity: SecuritySeverity;
  url: string;
  method: string;
  parameter: string;
  description: string;
  remediation: string;
  evidence: string;
  cwe_id: number | null;
  wasc_id: number | null;
  reference: string;
}

export interface ScanAlertCounts {
  total: number;
  high: number;
  medium: number;
  low: number;
  info: number;
}

export interface ScanAlertListResponse {
  items: ScanAlert[];
  total: number;
  page: number;
  page_size: number;
  counts: ScanAlertCounts;
}

export interface ScanCoverageRow {
  identifier: string;
  stage: CoverageStage;
  method: string;
  status_code: number | null;
  passive_analyzed: boolean;
  active_scanned: boolean;
}

export interface ScanCoverage {
  items: ScanCoverageRow[];
  total: number;
  page: number;
  page_size: number;
  summary: Record<string, number>;
}

/** 扫描任务与 Finding 的关联（Finding 本体复用 Phase 1 的 security_finding）。 */
export interface ScanFindingLink {
  id: number;
  job_id: number;
  finding_id: number;
  source: string;
  source_rule_id: string | null;
  source_alert_name: string | null;
  risk: string | null;
  confidence: number | null;
  url: string | null;
  method: string | null;
  parameter: string | null;
  fingerprint: string | null;
  evidence_json: Record<string, unknown> | null;
  first_seen_in_job: boolean;
  repeat_count: number;
  created_at: string | null;
}

export type ScanFindingListResponse = Paginated<ScanFindingLink>;

// --------------------------------------------------------------------------- 扫描计划（人工确认前置）

/** 扫描前的计划预览：计划里必须包含将被提交给 ZAP 的实际范围。 */
export interface ScanPlan {
  target: Record<string, unknown>;
  profile: Record<string, unknown>;
  environment: Record<string, unknown>;
  is_active_scan: boolean;
  /** 生产环境目标：该字段为 True 时提交会被后端拒绝。 */
  production_blocked: boolean;
  authentication_mode: ScanAuthMode | null;
  browser_session_established: boolean;
  zap_available: boolean;
  /** 能力受限 / 被拒绝项清单。 */
  limitations: string[];
  estimated_requests: number | null;
  max_duration_minutes: number;
  max_depth: number;
  max_concurrency: number;
  request_delay_ms: number;
  exclude_paths: string[];
  warning: string | null;
}

// --------------------------------------------------------------------------- 扫描报告

/** 独立安全扫描报告：所有数字都来自真实的任务记录，不接受前端传入。 */
export interface ScanReport {
  job: ScanJob;
  target: ScanTarget | null;
  profile: ScanProfile | null;
  alert_counts: ScanAlertCounts;
  high_risk_alerts: ScanAlert[];
  coverage_summary: Record<string, number>;
  findings: ScanFindingLink[];
  generated_at: string | null;
}
