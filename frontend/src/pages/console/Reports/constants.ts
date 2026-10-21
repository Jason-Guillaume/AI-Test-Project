// 测试报告页常量：报告状态 / 风险等级 / 失败分类的下拉选项。
// 与后端 features/reports/schemas.py 字面量严格对齐。
//
// 说明（避免继续增长为第三份色板）：
// - 报告/用例执行/失败分类的状态色已收敛到 @/shared/status（REPORT_STATUS_COLOR、
//   REPORT_RISK_COLOR、REPORT_FAILURE_TYPE_COLOR、CASE_EXECUTION_STATUS_COLOR / LABEL），
//   各页面统一从那里取，本文件不再重复定义。
// - 飞书通知域的 NOTIFY_CONDITION_OPTIONS / NOTIFY_STATUS_OPTIONS / NOTIFY_STATUS_COLOR
//   被报告页与通知渠道页共同消费，属通知域，已上提到 @/shared/notify。
// - 时间格式化统一走 @/shared/format（fmtTime / fmtTimeSec / fmtDuration）。
// - 本文件只保留报告域专属的「选项列表」，供 ./ReportList 与 ./ReportDetail 共用。

import type { ReportFailureType, ReportRiskLevel, ReportStatus } from '@/types';

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

export const FAILURE_TYPE_OPTIONS = [
  { value: 'ASSERTION_FAILURE' as ReportFailureType, label: '断言失败' },
  { value: 'EXECUTION_ERROR' as ReportFailureType, label: '执行错误' },
  { value: 'ENVIRONMENT_ERROR' as ReportFailureType, label: '环境问题' },
  { value: 'TEST_DATA_ISSUE' as ReportFailureType, label: '测试数据问题' },
  { value: 'POTENTIAL_BUG' as ReportFailureType, label: '疑似产品问题（需人工确认）' },
  { value: 'UNKNOWN' as ReportFailureType, label: '未知' },
];
