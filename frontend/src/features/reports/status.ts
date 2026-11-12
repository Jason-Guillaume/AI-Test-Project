// 报告状态与风险分类的语义颜色。
import type { ReportFailureType, ReportRiskLevel, ReportStatus } from './contracts';

// ---- 报告域：与后端 features/reports/schemas.py 字面量严格对齐 ----
// 报告页是本次重构的验收对象，这里收敛为共享源，避免 TestData / SecurityTesting
// 里已存在的同名色板（RISK_LEVEL_COLOR 等）继续与报告口径冲突。

/** 报告状态色。 */
export const REPORT_STATUS_COLOR: Record<ReportStatus, string> = {
  GENERATING: 'processing',
  COMPLETED: 'green',
  FAILED: 'red',
};

/** 报告风险等级色（以报告页口径为基准）。 */
export const REPORT_RISK_COLOR: Record<ReportRiskLevel, string> = {
  LOW: 'green',
  MEDIUM: 'gold',
  HIGH: 'orange',
  CRITICAL: 'red',
};

/** 失败分类色。 */
export const REPORT_FAILURE_TYPE_COLOR: Record<ReportFailureType, string> = {
  ASSERTION_FAILURE: 'red',
  EXECUTION_ERROR: 'volcano',
  ENVIRONMENT_ERROR: 'orange',
  TEST_DATA_ISSUE: 'gold',
  // 疑似产品问题：仅表示值得人工复核，不是已确认缺陷，故不用最重颜色。
  POTENTIAL_BUG: 'purple',
  UNKNOWN: 'default',
};
