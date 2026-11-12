// reports 领域类型合同；仅暴露当前模块稳定使用的请求、响应与查询类型。
import type { Paginated } from '@/shared/api/contracts';


// ---- 正式测试报告（Phase 2）----
// 字段与后端 features/reports/schemas.py 严格对齐（snake_case）。

export type ReportStatus = 'GENERATING' | 'COMPLETED' | 'FAILED';

export type ReportRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';

// 失败分类：POTENTIAL_BUG 仅表示「疑似产品问题，需人工确认」，不是已确认缺陷。
export type ReportFailureType =
  | 'ASSERTION_FAILURE'
  | 'EXECUTION_ERROR'
  | 'TEST_DATA_ISSUE'
  | 'ENVIRONMENT_ERROR'
  | 'POTENTIAL_BUG'
  | 'UNKNOWN';

export interface ReportGenerateRequest {
  /** 是否调用 LLM 生成结构化总结（失败不影响报告状态） */
  generate_ai_summary?: boolean;
  /** 已有 COMPLETED 报告时仅重生成 AI 总结（统计字段不可变） */
  regenerate?: boolean;
}

export interface ReportGenerateResponse {
  report_id: number;
  status: ReportStatus;
}

/** 报告详情内的单用例执行摘要（快照已脱敏）。 */
export interface CaseExecutionSummary {
  id: number;
  test_case_id: number | null;
  case_name: string;
  priority: string;
  case_type: string | null;
  status: string;
  failure_type: ReportFailureType | null;
  executor_type: string | null;
  duration_ms: number | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  request_snapshot: Record<string, unknown> | null;
  response_snapshot: Record<string, unknown> | null;
  assertion_results: Array<Record<string, unknown>> | null;
  context_json: Record<string, unknown> | null;
}

/** 报告详情里附带的一次性 TestRun 摘要。 */
export interface TestRunBrief {
  id: number;
  status: string;
  environment_id: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface TestReport {
  id: number;
  project_id: number;
  test_run_id: number | null;
  report_no: string;
  title: string;
  environment_id: number | null;
  status: ReportStatus;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  error_cases: number;
  skipped_cases: number;
  /** 通过率 0-100，保留两位小数（passed/(total-skipped)*100，分母 0 记 0） */
  pass_rate: number;
  duration_ms: number | null;
  /** 代码统计的结构化汇总（failure_clusters / case_failure_types），不可变 */
  summary: Record<string, unknown> | null;
  /** LLM 结构化总结；生成失败时为空（报告仍 COMPLETED） */
  ai_summary: Record<string, unknown> | null;
  ai_summary_version: string | null;
  risk_level: ReportRiskLevel;
  created_by: number | null;
  created_at: string;
  updated_at: string;
}

/** 报告列表项（不含 AI 总结等大字段）。 */
export interface TestReportListItem {
  id: number;
  report_no: string;
  title: string;
  test_run_id: number | null;
  environment_id: number | null;
  status: ReportStatus;
  total_cases: number;
  passed_cases: number;
  failed_cases: number;
  error_cases: number;
  skipped_cases: number;
  pass_rate: number;
  duration_ms: number | null;
  risk_level: ReportRiskLevel;
  created_at: string;
}

// list_reports 返回分页信封（后端 TestReportListResponse）。
export type TestReportListResponse = Paginated<TestReportListItem>;

/** 报告详情：报告本体 + TestRun 摘要 + 逐用例执行 + 失败分类聚类。 */
export interface TestReportDetail {
  report: TestReport;
  test_run: TestRunBrief | null;
  case_executions: CaseExecutionSummary[];
  failure_clusters: Array<Record<string, unknown>>;
}

export interface ReportListQuery {
  page?: number;
  page_size?: number;
  environment_id?: number;
  risk_level?: ReportRiskLevel;
  status?: ReportStatus;
  test_run_id?: number;
}
