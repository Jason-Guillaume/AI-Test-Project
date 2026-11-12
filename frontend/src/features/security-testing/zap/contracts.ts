// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
import type { Paginated } from '@/shared/api/contracts';
import type { SecuritySeverity } from '@/features/security-testing/contracts';


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
