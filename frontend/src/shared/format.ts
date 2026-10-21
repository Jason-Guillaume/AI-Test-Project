// 时间与数值的统一格式化。
//
// 背景：全项目有 9 处重复的 `v?.slice(0, 16).replace('T', ' ')` 时间切片写法
// （含一个 toLocaleString() 第三变体），且 ReportDetail 在两处各自把 duration_ms
// 手算成秒。这里上提为单一实现，避免各页格式漂移。

import dayjs from 'dayjs';

/**
 * 时间戳渲染：截取到分钟，null 显示占位符。
 *
 * 后端统一返回 ISO 8601（如 2026-10-19T08:30:00），前端只做展示包装，
 * 不改动传参语义。
 */
export function fmtTime(v: string | null | undefined): string {
  if (!v) return '-';
  return v.slice(0, 16).replace('T', ' ');
}

/**
 * 时间戳渲染：完整到秒，用于报告与执行详情的时间线。
 */
export function fmtTimeSec(v: string | null | undefined): string {
  if (!v) return '-';
  return v.slice(0, 19).replace('T', ' ');
}

/**
 * 耗时渲染：毫秒转成人类可读的紧凑串。
 *
 * - < 1 秒：直接给毫秒（步骤级耗时常见量级）
 * - < 1 分钟：给秒，保留 1 位小数
 * - ≥ 1 分钟：给分 + 秒
 *
 * null 或负数返回占位符，不吞掉异常值。
 */
export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return '-';
  if (ms < 0) return '-';
  if (ms < 1000) return `${ms} ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const sec = ms / 1000;
  const m = Math.floor(sec / 60);
  // 秒位必须用 floor 而不是 round：round 会把 119_999ms 算成「1 分 60 秒」。
  // s = floor(sec) - m*60 即 floor(sec) % 60，恒在 [0, 59]，不会越界。
  const s = Math.floor(sec) - m * 60;
  return `${m} 分 ${s} 秒`;
}

/**
 * 通过率渲染：保留两位小数，分母为 0 时按后端约定返回 0。
 */
export function fmtPercent(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '-';
  return v.toFixed(2);
}

/**
 * 大号数字渲染：千分位，用于统计卡片。
 */
export function fmtNumber(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '-';
  return v.toLocaleString('zh-CN');
}

/**
 * 相对时间：用于列表页的「x 分钟前」提示。
 *
 * dayjs 已按 main.tsx 的约定加载 zh-cn 语言包。
 */
export function fmtRelative(v: string | null | undefined): string {
  if (!v) return '-';
  const d = dayjs(v);
  if (!d.isValid()) return '-';
  const diff = dayjs().diff(d, 'minute');
  if (diff <= 0) return '刚刚';
  if (diff < 60) return `${diff} 分钟前`;
  if (diff < 1440) return `${Math.floor(diff / 60)} 小时前`;
  return `${Math.floor(diff / 1440)} 天前`;
}
