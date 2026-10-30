// 统一状态徽标：把「枚举字面量 → 颜色 + 中文标签」收敛到一处。
//
// 背景：全项目有 33 份 Record<X, string> 状态色板 + 15 个手写
// `options.find(o => o.value === v)?.label ?? v` 访问器，且已出现语义冲突
// （PROVIDER 的 SKIPPED='orange' 而 CASE 的 SKIPPED='default'）。
// 本组件让每个调用点声明自己的色板，但渲染逻辑只有一份。
//
// 颜色一律用 antd 预设色名而非 hex，浅色/深色模式都由 antd 派生。

import { Tag, theme } from 'antd';
import { type ReactNode } from 'react';
import type { Option } from '@/shared/lib/options';

/**
 * 状态徽标。
 *
 * 优先级：显式 label/color > options（选项列表，含中文标签与色）>
 * labels/colors 映射 > fallback 兜底。
 *
 * @param value 后端字面量；为 null/undefined 时渲染 nullRender
 * @param options 选项列表，取其中 label 与 color
 * @param labels 值到中文标签的映射（无 options 时使用）
 * @param colors 值到 antd 预设色名的映射
 * @param color 显式颜色；缺省取映射，再缺省 'default'
 * @param label 显式标签；缺省取映射，再缺省原样回显 value（便于暴露未知枚举）
 * @param nullRender 空值占位，默认 '-'
 * @param bordered 是否显示边框（默认关闭，与表格内紧凑排版一致）
 */
export function StatusBadge<T extends string>({
  value,
  options,
  labels,
  colors,
  color,
  label,
  nullRender = '-',
  bordered = false,
}: {
  value: T | null | undefined;
  options?: Option<T>[];
  labels?: Partial<Record<T, string>>;
  colors?: Partial<Record<T, string>>;
  color?: string;
  label?: string;
  nullRender?: ReactNode;
  bordered?: boolean;
}) {
  const { token } = theme.useToken();

  if (value == null) {
    return <span style={{ color: token.colorTextTertiary }}>{nullRender}</span>;
  }

  const resolvedColor = color ?? colors?.[value] ?? options?.find((o) => o.value === value)?.color ?? 'default';
  const resolvedLabel =
    label ?? labels?.[value] ?? options?.find((o) => o.value === value)?.label ?? String(value);

  return <Tag color={resolvedColor} bordered={bordered}>{resolvedLabel}</Tag>;
}
