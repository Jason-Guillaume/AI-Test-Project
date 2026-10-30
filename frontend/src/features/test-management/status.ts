// 测试管理执行状态标签与语义颜色。
import type { CaseExecutionStatus } from './contracts';

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
