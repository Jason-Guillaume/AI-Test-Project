// 统一统计卡片。
//
// 背景：现状 13 处以上裸用 Statistic + Row/Col，且 #52c41a / #cf1322 / #faad14
// 硬编码在 valueStyle 里（改主题不会让它们变色）。重构计划 §3.B 的「紧凑统计卡片」
// 与 §2「成功、失败、警告、执行中必须使用统一语义颜色」都在这里落地。
//
// 颜色全部走 theme.useToken() 解析的语义 token，禁止裸 hex。

import { Card, Statistic, theme, Typography } from 'antd';
import { type ReactNode } from 'react';

/** 语义色调，对应 §2 要求统一的成功/失败/警告/执行中四色。 */
export type MetricTone = 'default' | 'success' | 'error' | 'warning' | 'info' | 'processing';

/** tone 到 token 键的映射（用字面量联合避免深路径 import）。 */
type TokenColorKey =
  | 'colorText'
  | 'colorSuccess'
  | 'colorError'
  | 'colorWarning'
  | 'colorInfo'
  | 'colorPrimary';

const TONE_TOKEN: Record<MetricTone, TokenColorKey> = {
  default: 'colorText',
  success: 'colorSuccess',
  error: 'colorError',
  warning: 'colorWarning',
  info: 'colorInfo',
  processing: 'colorPrimary',
};

/**
 * 统计卡片。
 *
 * @param title 指标名称
 * @param value 指标值
 * @param suffix 后缀（如 '%'、'ms'）
 * @param prefix 前缀
 * @param precision 小数位数
 * @param tone 语义色；默认中性，不强调
 * @param hint 卡片底部的一句说明
 * @param loading 加载态
 * @param formatter 自定义值格式化，优先级高于 precision
 * @param style 外层卡片样式
 */
export function MetricCard({
  title,
  value,
  suffix,
  prefix,
  precision,
  tone = 'default',
  hint,
  loading = false,
  formatter,
  style,
}: {
  title: ReactNode;
  value: number | string;
  suffix?: ReactNode;
  prefix?: ReactNode;
  precision?: number;
  tone?: MetricTone;
  hint?: ReactNode;
  loading?: boolean;
  formatter?: (value: number | string) => string;
  style?: React.CSSProperties;
}) {
  const { token } = theme.useToken();
  const color = token[TONE_TOKEN[tone]];

  return (
    <Card
      size="small"
      styles={{ body: { padding: `${token.paddingSM}px ${token.paddingMD}px` } }}
      style={style}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: token.marginXXS }}>
        <Statistic
          title={title}
          value={value}
          suffix={suffix}
          prefix={prefix}
          precision={precision}
          loading={loading}
          formatter={formatter}
          valueStyle={{ color, fontSize: 24, fontWeight: token.fontWeightStrong, lineHeight: 1.2 }}
        />
        {hint ? (
          <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
            {hint}
          </Typography.Text>
        ) : null}
      </div>
    </Card>
  );
}
