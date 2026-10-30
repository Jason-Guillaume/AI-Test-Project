// 本领域请求、响应与查询合同；HTTP 适配器只负责调用服务端接口。
// ---- 安全测试（Security Testing Phase 1）----
// 字段与后端 features/security_testing/schemas.py 严格对齐（snake_case）。
// 安全红线：本页只改请求与解释结果，不做注入 / 扫描器；不在生产环境发安全变异请求；
// 疑似问题文案统一为「疑似问题」，不写「已发现漏洞」；不提供「转 Bug」入口，
// SecurityFinding.bug_id 恒为 null。Finding evidence 不在本页 Agent brief 展示，
// 变异详情抽屉里按需从 security-executions 读（后端已脱敏）。

/** 严重级别 / 风险级别（策略与规则复用同一套值）。 */
export type SecuritySeverity = 'INFO' | 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

/** 安全结论五态（不改既有枚举表）。 */
export type SecurityResult =
  | 'PASS'
  | 'POTENTIAL_ISSUE'
  | 'FAILED_EXECUTION'
  | 'INCONCLUSIVE'
  | 'SKIPPED';

/** Finding 状态与合法迁移由服务层校验。 */
export type SecurityFindingStatus =
  | 'OPEN'
  | 'CONFIRMED'
  | 'FALSE_POSITIVE'
  | 'RESOLVED'
  | 'IGNORED';

/** 计划状态。 */
export type PlanStatus = 'DRAFT' | 'CONFIRMED' | 'DISCARDED';

/** 安全期望（算子允许的期望由后端校验，前端只透传）。 */
export type SecurityExpectation =
  | 'EXPECTED_DENY'
  | 'EXPECTED_ALLOW'
  | 'EXPECTED_VALIDATION_ERROR'
  | 'EXPECTED_IDEMPOTENT';

/** 报告概览六类覆盖口径（前端聚合用，与后端 COVERAGE_CATEGORIES 一致）。 */
export type CoverageCategory =
  | 'AUTHENTICATION'
  | 'AUTHORIZATION'
  | 'IDOR'
  | 'PARAMETER'
  | 'REPLAY'
  | 'BUSINESS';

/** 项目级环境开关。production_enforced 恒 false（生产永远拒绝）。 */
export interface SecuritySetting {
  id: number | null;
  project_id: number | null;
  allow_dev: boolean;
  allow_test: boolean;
  allow_staging: boolean;
  allow_production: boolean;
  /** 恒为 false：列上即使存了 true，执行器也不读它。 */
  production_enforced: boolean;
  updated_by: number | null;
  created_at: string | null;
  updated_at: string | null;
  revision: number;
}

export interface SecuritySettingUpdate {
  allow_dev?: boolean;
  allow_test?: boolean;
  allow_staging?: boolean;
  /** 可传入但永不生效（存库后仍拒绝）。 */
  allow_production?: boolean;
  revision?: number;
}

/** 变异规则（响应）。mutation_config 一律结构化，禁止脚本键。 */
export interface MutationRule {
  id: number;
  project_id: number | null;
  strategy_id: number;
  name: string;
  mutation_type: string;
  target_location: string;
  target_field: string | null;
  operator: string;
  mutation_config: Record<string, unknown>;
  expected_security_behavior: string;
  expected_status_codes: number[] | null;
  severity: string;
  enabled: boolean;
  confirmation_required: boolean;
  sort: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface MutationRuleCreate {
  name: string;
  mutation_type: string;
  target_location: string;
  target_field?: string | null;
  operator?: string | null;
  mutation_config: Record<string, unknown>;
  expected_security_behavior?: string | null;
  expected_status_codes?: number[] | null;
  severity?: string | null;
  enabled?: boolean;
  confirmation_required?: boolean;
  sort?: number;
}

export interface MutationRuleUpdate {
  name?: string;
  mutation_type?: string;
  target_location?: string;
  target_field?: string | null;
  operator?: string | null;
  mutation_config?: Record<string, unknown> | null;
  expected_security_behavior?: string | null;
  expected_status_codes?: number[] | null;
  severity?: string | null;
  enabled?: boolean | null;
  confirmation_required?: boolean | null;
  sort?: number | null;
}

/** 安全策略（响应，可携带规则列表）。系统模板 builtin=true 不可改不可删。 */
export interface SecurityStrategy {
  id: number;
  project_id: number | null;
  scope: 'SYSTEM' | 'PROJECT';
  name: string;
  strategy_key: string;
  category: string;
  description: string | null;
  enabled: boolean;
  risk_level: string;
  builtin: boolean;
  created_by: number | null;
  created_at: string | null;
  updated_at: string | null;
  revision: number;
  rules: MutationRule[];
}

export interface SecurityStrategyCreate {
  name: string;
  strategy_key: string;
  category: string;
  description?: string | null;
  enabled?: boolean;
  risk_level?: string;
  rules?: MutationRuleCreate[];
}

export interface SecurityStrategyUpdate {
  name?: string;
  description?: string | null;
  enabled?: boolean | null;
  risk_level?: string | null;
  revision?: number;
}

export interface SecurityStrategyListResponse {
  items: SecurityStrategy[];
  total: number;
  page: number;
  page_size: number;
}

/** 安全计划预览项（形状即后端 PlanPreviewItem）。 */
export interface PlanPreviewItem {
  index: number;
  name: string;
  mutation_type: string;
  target_type: string;
  api_id: number | null;
  business_action_id: number | null;
  method: string | null;
  /** 来自 mutation_config，规则列声明时可能为 null。 */
  location: string | null;
  field: string | null;
  expectation: string;
  expected_status_codes: number[] | null;
  severity: string;
  risk_level: string | null;
  confirmation_required: boolean;
  blocked_reason: string | null;
  mutation_config: Record<string, unknown>;
  source_rule_id: number | null;
  source_strategy_id: number | null;
}

export interface PlanPreviewRequest {
  /** 三者必须且只能给一个（§16.3）。 */
  baseline_case_id?: number | null;
  api_id?: number | null;
  business_action_id?: number | null;
  strategy_ids: number[];
  environment_id?: number | null;
  name?: string | null;
}

export interface PlanPreviewResponse {
  plan_id: number;
  status: string;
  estimated_count: number;
  truncated: boolean;
  items: PlanPreviewItem[];
  /** 按 API / 业务动作目标生成时解析出的基线用例。 */
  baseline_case_id: number | null;
  baseline_case_name: string | null;
}

export interface PlanConfirmRequest {
  accepted_item_indexes: number[];
  plan_name?: string | null;
}

export interface PlanConfirmResponse {
  plan_id: number;
  status: string;
  created_case_ids: number[];
  created_count: number;
  skipped_count: number;
}

export interface SecurityPlan {
  id: number;
  project_id: number;
  name: string;
  target_type: string;
  api_id: number | null;
  baseline_case_id: number | null;
  business_action_id: number | null;
  strategy_ids: number[] | null;
  status: string;
  preview_json: unknown;
  estimated_count: number;
  environment_id: number | null;
  created_by: number | null;
  confirmed_by: number | null;
  confirmed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
  revision: number;
}

/** 安全用例扩展数据（读模型）。 */
export interface SecurityCase {
  id: number;
  project_id: number;
  test_case_id: number;
  plan_id: number | null;
  baseline_case_id: number | null;
  strategy_id: number | null;
  rule_id: number | null;
  api_id: number | null;
  business_action_id: number | null;
  mutation_type: string;
  mutation_config: Record<string, unknown>;
  security_expectation: string;
  risk_level: string | null;
  confirmation_required: boolean;
  confirmed_by: number | null;
  confirmed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SecurityCaseDetail extends SecurityCase {
  enabled: boolean;
  case_name: string | null;
  baseline_case_name: string | null;
  api_name: string | null;
  rule_name: string | null;
  latest_execution: SecurityExecution | null;
}

export interface SecurityCaseListResponse {
  items: SecurityCaseDetail[];
  total: number;
  page: number;
  page_size: number;
}

export interface SecurityCaseUpdate {
  /** 只允许改启用状态；事实来源是 test_case.enabled。 */
  enabled: boolean;
}

export interface SecurityRunRequest {
  security_case_ids: number[];
  environment_id?: number | null;
  plan_name?: string | null;
}

/** 安全执行记录（mutation_trace / evidence 均已脱敏）。 */
export interface SecurityExecution {
  id: number;
  project_id: number;
  test_run_id: number | null;
  case_execution_id: number | null;
  security_case_id: number;
  environment_id: number | null;
  actor_id: number | null;
  baseline_status: 'PASSED' | 'FAILED' | null;
  baseline_http_status: number | null;
  security_result: SecurityResult;
  classification: string | null;
  mutation_trace: Array<Record<string, unknown>>;
  replay_count: number;
  actual_status_codes: number[];
  evidence: Record<string, unknown> | null;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string | null;
}

/** 疑似问题（Phase 1 不写 bug_id，恒为 null）。 */
export interface SecurityFinding {
  id: number;
  project_id: number;
  test_run_id: number | null;
  case_execution_id: number | null;
  security_execution_id: number | null;
  api_id: number | null;
  business_action_id: number | null;
  strategy_id: number | null;
  security_case_id: number | null;
  mutation_type: string;
  severity: SecuritySeverity;
  status: SecurityFindingStatus;
  title: string;
  description: string | null;
  evidence: Record<string, unknown> | null;
  recommendation: string | null;
  fingerprint: string;
  bug_id: number | null;
  created_by: number | null;
  resolved_by: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SecurityFindingUpdate {
  status: SecurityFindingStatus;
}

export interface SecurityFindingListResponse {
  items: SecurityFinding[];
  total: number;
  page: number;
  page_size: number;
}

/** 报告 summary.security 形状（后端代码计算，无安全用例时为 null）。 */
export interface SecuritySummary {
  cases: number;
  pass: number;
  potential_issues: number;
  inconclusive: number;
  failed_execution: number;
  skipped: number;
  /** 各严重级别条数（INFO/LOW/MEDIUM/HIGH/CRITICAL 五键齐全）。 */
  findings: Record<string, number>;
  /** 最多 5 条，按严重级别降序；不含 evidence 正文。 */
  top_findings: Array<{
    id: number;
    severity: string;
    title: string;
    api_id: number | null;
    mutation_type: string;
  }>;
}
