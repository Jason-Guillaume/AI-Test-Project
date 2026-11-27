// 缺陷管理页面常量：前后端划分、状态与严重度选项及标签配色，与后端 defects/schemas.py 严格对齐。

import type { ApiMethod, BugAction, BugCategory, BugPriority, BugSeverity, BugStatus } from '@/features/defects/contracts';

/** 接口缺陷请求方法表单选项。 */
export const API_METHOD_OPTIONS: { label: string; value: ApiMethod }[] = (
  ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'] as ApiMethod[]
).map((m) => ({ label: m, value: m }));

/** 前后端划分合法值；原「后端」已并入「接口」，「前后端」保留自身类型。 */
export const BUG_CATEGORIES: BugCategory[] = ['前端', '前后端', '接口'];

/** 前后端划分表单选项。 */
export const CATEGORY_OPTIONS: { label: string; value: BugCategory }[] = BUG_CATEGORIES.map((c) => ({
  label: c,
  value: c,
}));

/** 前后端划分标签颜色。 */
export const CATEGORY_COLOR: Record<BugCategory, string> = {
  前端: 'blue',
  前后端: 'cyan',
  接口: 'geekblue',
};

/** 缺陷状态合法值，与后端 BUG_STATUSES 保持同步。 */
export const BUG_STATUSES: BugStatus[] = ['待确认', '处理中', '已修复', '已关闭', '已拒绝'];

/** 展示状态：已修复对外展示为「待验证」，与后端 STATUS_DISPLAY 对齐。 */
export const STATUS_DISPLAY: Record<BugStatus, string> = {
  待确认: '待确认',
  处理中: '处理中',
  已修复: '待验证',
  已关闭: '已关闭',
  已拒绝: '已拒绝',
};

/** 缺陷状态表单选项（按展示口径）。 */
export const STATUS_OPTIONS: { label: string; value: BugStatus }[] = BUG_STATUSES.map((s) => ({
  label: STATUS_DISPLAY[s],
  value: s,
}));

/** 缺陷严重度表单选项。 */
export const SEVERITY_OPTIONS: { label: string; value: BugSeverity }[] = [
  { label: '1 低', value: 1 },
  { label: '2 中', value: 2 },
  { label: '3 高', value: 3 },
  { label: '4 严重', value: 4 },
];

/** 缺陷状态标签配色。 */
export const STATUS_COLOR: Record<BugStatus, string> = {
  待确认: 'orange',
  处理中: 'blue',
  已修复: 'cyan',
  已关闭: 'default',
  已拒绝: 'red',
};

/** 缺陷严重度标签配色。 */
export const SEVERITY_COLOR: Record<BugSeverity, string> = {
  1: 'gold',
  2: 'orange',
  3: 'volcano',
  4: 'red',
};

/** 处理优先级表单选项，与后端 PRIORITY_LABELS 对齐。 */
export const PRIORITY_OPTIONS: { label: string; value: BugPriority }[] = [
  { label: '1 低', value: 1 },
  { label: '2 中', value: 2 },
  { label: '3 高', value: 3 },
  { label: '4 紧急', value: 4 },
];

/** 处理优先级标签配色。 */
export const PRIORITY_COLOR: Record<BugPriority, string> = {
  1: 'default',
  2: 'blue',
  3: 'orange',
  4: 'red',
};

export const PRIORITY_LABELS: Record<BugPriority, string> = {
  1: '低',
  2: '中',
  3: '高',
  4: '紧急',
};

/** 队列动作文案，与后端 ACTION_LABELS 对齐。 */
export const ACTION_LABELS: Record<BugAction, string> = {
  confirm: '确认问题',
  ready_for_regression: '登记可回归',
  regression_pass: '回归通过',
  regression_fail: '回归失败',
  reject: '拒绝',
  mark_duplicate: '判重',
  reopen: '重开',
};
