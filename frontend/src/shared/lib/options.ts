// 下拉选项与枚举标签的通用工具。
//
// 背景：全项目有 15 处手写 `options.find(o => o.value === v)?.label ?? v` 变体
// （SecurityTesting 7 处、ReportDetail 4 处、ExecutionHistory 2 处、MockManagement 2 处），
// 且 TestData/constants.ts 里早已有一个 labelOf 却从未被其它模块复用。
// 这里上提为共享实现，供 StatusBadge 与各页面共用。

/** 通用下拉选项：label 为中文展示，value 为后端字面量，color 为 antd Tag 预设色名。 */
export interface Option<T extends string = string> {
  label: string;
  value: T;
  color?: string;
}

/**
 * 从选项列表取中文标签。
 *
 * @param options 选项列表
 * @param value 后端字面量；为空或未命中时返回空占位符
 * @param fallback 未命中时的兜底文案，默认原样回显 value（便于暴露未知枚举）
 */
export function labelOf<T extends string>(
  options: Option<T>[],
  value: T | null | undefined,
  fallback = value as string | undefined,
): string {
  if (value == null) return fallback ?? '-';
  return options.find((o) => o.value === value)?.label ?? fallback ?? String(value);
}

/**
 * 从选项列表取 antd Tag 预设色名。
 *
 * 用 antd 预设色名（green/red/orange/...）而不是 hex，
 * 这样浅色与深色模式下都由 antd 派生，无需业务代码再处理主题。
 */
export function colorOf<T extends string>(
  options: Option<T>[],
  value: T | null | undefined,
  fallback = 'default',
): string {
  if (value == null) return fallback;
  return options.find((o) => o.value === value)?.color ?? fallback;
}

/**
 * 判断值是否属于选项集合，用于表格筛选时的合法性校验。
 */
export function isOptionValue<T extends string>(options: Option<T>[], value: unknown): value is T {
  return typeof value === 'string' && options.some((o) => o.value === value);
}
