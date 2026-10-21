// 跨模块复用的执行状态语义色。
//
// 背景：用例执行状态色板在 3 个文件里逐字重复（Reports/constants.ts、
// ExecutionHistory.tsx、ExecutionCenter.tsx），测试运行状态色板也重复 2 份。
// 这里作为唯一真源，各模块改为引用。
//
// 颜色一律使用 antd 预设色名（green/red/processing/...），
// 而不是 hex：这样浅色与深色模式都由 antd 派生，业务代码无需感知主题。
// 这也是重构计划 §2「成功、失败、警告、执行中必须使用统一语义颜色」的落点。

import type { CaseExecutionStatus, ReportFailureType, ReportRiskLevel, ReportStatus } from '@/types';

/** 用例执行状态色（PENDING/RUNNING/PASSED/FAILED/SKIPPED/ERROR）。 */
export const CASE_EXECUTION_STATUS_COLOR: Record<CaseExecutionStatus, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  PASSED: 'green',
  FAILED: 'red',
  SKIPPED: 'default',
  ERROR: 'warning',
};

/** 用例执行状态中文标签。 */
export const CASE_EXECUTION_STATUS_LABEL: Record<CaseExecutionStatus, string> = {
  PENDING: '等待',
  RUNNING: '执行中',
  PASSED: '通过',
  FAILED: '失败',
  SKIPPED: '跳过',
  ERROR: '错误',
};

/** 测试运行状态色。 */
export const TEST_RUN_STATUS_COLOR: Record<string, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  SUCCESS: 'green',
  FAILED: 'red',
  CANCELLED: 'default',
};

/**
 * Web 用例执行记录里的步骤状态色。
 *
 * 后端只写 PASSED / FAILED / ERROR 三种（playwright_executor 在首个失败步骤即 break），
 * 未出现在日志里的步骤表示「未执行」，不是 SKIPPED——不要映射成跳过色，
 * 否则会把超时中断伪装成主动跳过。
 */
export const WEB_STEP_STATUS_COLOR: Record<string, string> = {
  PASSED: 'green',
  FAILED: 'red',
  ERROR: 'warning',
};

/** Web 步骤状态中文标签。 */
export const WEB_STEP_STATUS_LABEL: Record<string, string> = {
  PASSED: '通过',
  FAILED: '失败',
  ERROR: '错误',
};

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
