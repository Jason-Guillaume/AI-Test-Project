// 安全扫描（ZAP）子模块的选项与标签常量。
// 取值与后端 features/security_testing/zap/contracts.py、schemas.py 的 Literal 严格对齐。
// 严重级别复用 ../constants 的 SEVERITY_OPTIONS（字面量一致：INFO/LOW/MEDIUM/HIGH/CRITICAL）。

import type {
  CoverageStage,
  ScanAuthMode,
  ScanAuthStatus,
  ScanAuthorizationStatus,
  ScanJobStatus,
  ScanMode,
  ScanTargetType,
} from '@/api/securityTesting';
import type { Option } from '@/shared/options';

// --------------------------------------------------------------------------- 扫描目标类型

export const TARGET_TYPE_OPTIONS: Option<ScanTargetType>[] = [
  { value: 'API', label: 'API 接口面' },
  { value: 'WEB', label: 'Web 页面' },
  { value: 'HYBRID', label: '混合（API + Web）' },
];

export const targetTypeLabel = (v: string) =>
  TARGET_TYPE_OPTIONS.find((o) => o.value === v)?.label ?? v;

// --------------------------------------------------------------------------- 扫描模式（六档）

export const SCAN_MODE_OPTIONS: Option<ScanMode>[] = [
  { value: 'API_PASSIVE', label: 'API 被动' },
  { value: 'WEB_PASSIVE', label: 'Web 被动' },
  { value: 'HYBRID_PASSIVE', label: '混合被动' },
  { value: 'API_ACTIVE', label: 'API 主动' },
  { value: 'WEB_ACTIVE', label: 'Web 主动' },
  { value: 'FULL_AUTHORIZED', label: '全量授权' },
];

export const scanModeLabel = (v: string) =>
  SCAN_MODE_OPTIONS.find((o) => o.value === v)?.label ?? v;

/**
 * 该模式是否属于受控主动扫描。
 *
 * 后端 is_active_scan 由 scan_mode 判定；这里只是前端判断「是否需要勾选确认」的
 * 兜底——最终以 ScanProfile.is_active_scan 与计划预览的 is_active_scan 为准。
 */
export const ACTIVE_SCAN_MODES = new Set<ScanMode>(['API_ACTIVE', 'WEB_ACTIVE', 'FULL_AUTHORIZED']);

// --------------------------------------------------------------------------- 认证模式（五档）

export const AUTH_MODE_OPTIONS: Option<ScanAuthMode>[] = [
  { value: 'NONE', label: '无认证' },
  { value: 'BEARER_TOKEN', label: 'Bearer Token' },
  { value: 'HEADER_BASED', label: '自定义请求头' },
  { value: 'BROWSER_AUTH', label: '浏览器登录态' },
  { value: 'MANUAL', label: '人工登录' },
];

export const authModeLabel = (v: string) =>
  AUTH_MODE_OPTIONS.find((o) => o.value === v)?.label ?? v;

/** 需要「浏览器里真实存在登录态」才能扫出业务页面的两档。 */
export const BROWSER_AUTH_MODES = new Set<ScanAuthMode>(['BROWSER_AUTH', 'MANUAL']);

// --------------------------------------------------------------------------- 目标授权状态

export const AUTHORIZATION_STATUS_OPTIONS: Option<ScanAuthorizationStatus>[] = [
  { value: 'PENDING', label: '待确认授权', color: 'orange' },
  { value: 'AUTHORIZED', label: '已授权', color: 'green' },
  { value: 'REVOKED', label: '授权已撤销', color: 'red' },
];

export const authStatusLabel = (v: string) =>
  AUTHORIZATION_STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v;
export const authStatusColor = (v: string) =>
  AUTHORIZATION_STATUS_OPTIONS.find((o) => o.value === v)?.color ?? 'default';

// --------------------------------------------------------------------------- 登录态验证结果

export const AUTH_RESULT_OPTIONS: Option<ScanAuthStatus>[] = [
  { value: 'LOGGED_IN', label: '已登录', color: 'green' },
  { value: 'LOGGED_OUT', label: '未登录', color: 'red' },
  { value: 'UNVERIFIABLE', label: '无法验证', color: 'orange' },
];

export const authResultLabel = (v: string) =>
  AUTH_RESULT_OPTIONS.find((o) => o.value === v)?.label ?? v;
export const authResultColor = (v: string) =>
  AUTH_RESULT_OPTIONS.find((o) => o.value === v)?.color ?? 'default';

// --------------------------------------------------------------------------- 任务状态

export const JOB_STATUS_OPTIONS: Option<ScanJobStatus>[] = [
  { value: 'PENDING', label: '等待执行', color: 'default' },
  { value: 'PREPARING', label: '准备中', color: 'processing' },
  { value: 'AUTHENTICATING', label: '认证中', color: 'processing' },
  { value: 'CRAWLING', label: '爬取中', color: 'processing' },
  { value: 'PASSIVE_SCANNING', label: '被动扫描中', color: 'processing' },
  { value: 'ACTIVE_SCANNING', label: '主动扫描中', color: 'volcano' },
  { value: 'IMPORTING_RESULTS', label: '导入结果中', color: 'processing' },
  { value: 'COMPLETED', label: '已完成', color: 'green' },
  { value: 'FAILED', label: '失败', color: 'red' },
  { value: 'CANCELLED', label: '已取消', color: 'default' },
  { value: 'TIMED_OUT', label: '已超时', color: 'warning' },
];

export const jobStatusLabel = (v: string) =>
  JOB_STATUS_OPTIONS.find((o) => o.value === v)?.label ?? v;
export const jobStatusColor = (v: string) =>
  JOB_STATUS_OPTIONS.find((o) => o.value === v)?.color ?? 'default';

/** 未结束的状态：列表与详情在这些状态下才轮询进度、才允许取消。 */
export const RUNNING_JOB_STATUSES = new Set<ScanJobStatus>([
  'PENDING',
  'PREPARING',
  'AUTHENTICATING',
  'CRAWLING',
  'PASSIVE_SCANNING',
  'ACTIVE_SCANNING',
  'IMPORTING_RESULTS',
]);

export const isRunningJob = (v: string) => RUNNING_JOB_STATUSES.has(v as ScanJobStatus);

// --------------------------------------------------------------------------- 覆盖阶段

export const COVERAGE_STAGE_OPTIONS: Option<CoverageStage>[] = [
  { value: 'DISCOVERED', label: '已发现', color: 'default' },
  { value: 'REQUESTED', label: '已请求', color: 'blue' },
  { value: 'RESPONDED', label: '已响应', color: 'cyan' },
  { value: 'PASSIVE_ANALYZED', label: '被动已分析', color: 'green' },
  { value: 'ACTIVE_SCANNED', label: '主动已扫描', color: 'volcano' },
  { value: 'NOT_COVERED', label: '未覆盖', color: 'orange' },
];

export const coverageStageLabel = (v: string) =>
  COVERAGE_STAGE_OPTIONS.find((o) => o.value === v)?.label ?? v;
export const coverageStageColor = (v: string) =>
  COVERAGE_STAGE_OPTIONS.find((o) => o.value === v)?.color ?? 'default';

// --------------------------------------------------------------------------- ZAP 置信度

/**
 * ZAP 原始置信度 1-5，与严重级别（Severity）是两个独立维度：
 * confidence 表达「这条告警有多可能是真问题」，severity 表达「真问题的危害有多大」。
 * 列表里必须分列展示，不能合并成一列。
 */
export const CONFIDENCE_COLORS: Record<number, string> = {
  1: 'default',
  2: 'blue',
  3: 'cyan',
  4: 'orange',
  5: 'red',
};

export const confidenceColor = (v: number | null) =>
  v == null ? 'default' : (CONFIDENCE_COLORS[v] ?? 'default');

export const CONFIDENCE_TIP = 'ZAP 置信度 1-5，独立于严重级别：数值越高越可能是真问题。';
