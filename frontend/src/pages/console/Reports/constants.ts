// 测试报告与飞书通知页常量：选项、标签、Tag 颜色。
// 与后端 features/reports/schemas.py、features/notifications/schemas_channel.py 字面量严格对齐。

import type {
  CaseExecutionStatus,
  NotifyCondition,
  NotifyStatus,
  ReportFailureType,
  ReportRiskLevel,
  ReportStatus,
} from '@/types';

export const REPORT_STATUS_OPTIONS = [
  { value: 'GENERATING' as ReportStatus, label: '生成中 GENERATING' },
  { value: 'COMPLETED' as ReportStatus, label: '已完成 COMPLETED' },
  { value: 'FAILED' as ReportStatus, label: '生成失败 FAILED' },
];

export const REPORT_RISK_OPTIONS = [
  { value: 'LOW' as ReportRiskLevel, label: '低 LOW' },
  { value: 'MEDIUM' as ReportRiskLevel, label: '中 MEDIUM' },
  { value: 'HIGH' as ReportRiskLevel, label: '高 HIGH' },
  { value: 'CRITICAL' as ReportRiskLevel, label: '严重 CRITICAL' },
];

export const REPORT_STATUS_COLOR: Record<ReportStatus, string> = {
  GENERATING: 'processing',
  COMPLETED: 'green',
  FAILED: 'red',
};

export const RISK_COLOR: Record<ReportRiskLevel, string> = {
  LOW: 'green',
  MEDIUM: 'gold',
  HIGH: 'orange',
  CRITICAL: 'red',
};

export const FAILURE_TYPE_OPTIONS = [
  { value: 'ASSERTION_FAILURE' as ReportFailureType, label: '断言失败' },
  { value: 'EXECUTION_ERROR' as ReportFailureType, label: '执行错误' },
  { value: 'ENVIRONMENT_ERROR' as ReportFailureType, label: '环境问题' },
  { value: 'TEST_DATA_ISSUE' as ReportFailureType, label: '测试数据问题' },
  { value: 'POTENTIAL_BUG' as ReportFailureType, label: '疑似产品问题（需人工确认）' },
  { value: 'UNKNOWN' as ReportFailureType, label: '未知' },
];

export const FAILURE_TYPE_COLOR: Record<ReportFailureType, string> = {
  ASSERTION_FAILURE: 'red',
  EXECUTION_ERROR: 'volcano',
  ENVIRONMENT_ERROR: 'orange',
  TEST_DATA_ISSUE: 'gold',
  // 疑似产品问题：仅表示值得人工复核，不是已确认缺陷，故不用最重颜色。
  POTENTIAL_BUG: 'purple',
  UNKNOWN: 'default',
};

export const NOTIFY_CONDITION_OPTIONS = [
  { value: 'ALWAYS' as NotifyCondition, label: '总是发送 ALWAYS' },
  { value: 'ONLY_FAILED' as NotifyCondition, label: '仅失败时 ONLY_FAILED' },
  { value: 'ONLY_HIGH_RISK' as NotifyCondition, label: '仅高风险时 ONLY_HIGH_RISK' },
];

export const NOTIFY_STATUS_OPTIONS = [
  { value: 'PENDING' as NotifyStatus, label: '待发送' },
  { value: 'SUCCESS' as NotifyStatus, label: '发送成功' },
  { value: 'FAILED' as NotifyStatus, label: '发送失败' },
];

export const NOTIFY_STATUS_COLOR: Record<NotifyStatus, string> = {
  PENDING: 'processing',
  SUCCESS: 'green',
  FAILED: 'red',
};

// 报告详情页逐用例执行状态（与执行历史共用同一套状态字面量）。
export const CASE_STATUS_COLOR: Record<CaseExecutionStatus, string> = {
  PENDING: 'default',
  RUNNING: 'processing',
  PASSED: 'green',
  FAILED: 'red',
  SKIPPED: 'default',
  ERROR: 'warning',
};

export const CASE_STATUS_LABEL: Record<CaseExecutionStatus, string> = {
  PENDING: '等待',
  RUNNING: '执行中',
  PASSED: '通过',
  FAILED: '失败',
  SKIPPED: '跳过',
  ERROR: '错误',
};

/** 时间戳渲染：截取到分钟，null 显示占位符。 */
export function fmtTime(v: string | null): string {
  return v ? v.slice(0, 16).replace('T', ' ') : '-';
}
