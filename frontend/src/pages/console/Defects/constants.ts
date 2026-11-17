// 缺陷管理页面常量：前后端划分、状态与严重度选项及标签配色，与后端 defects/schemas.py 严格对齐。

import type { ApiMethod, BugCategory, BugSeverity, BugStatus } from '@/features/defects/contracts';

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

/** 缺陷状态表单选项。 */
export const STATUS_OPTIONS: { label: string; value: BugStatus }[] = BUG_STATUSES.map((s) => ({
  label: s,
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
