// 统一 JSON 快照只读视图。
//
// 背景：现状有 4 份手写 JSON 视图（ApiCatalog/JsonView.tsx 的完整版 + 3 份裸 <pre>，
// 其中 3 份逐字相同：ExecutionHistory、TestData/ExecutionDetailDrawer、ReportDetail）。
// 报告页与执行详情的请求/响应/上下文面板都依赖它。

import { App, Button, Empty, Flex, theme, Tooltip, Typography } from 'antd';
import { CopyOutlined } from '@ant-design/icons';
import { type ReactNode } from 'react';

/**
 * JSON 快照只读视图。
 *
 * 纯展示组件，不发请求。null/undefined 显示空态；对象与数组自动缩进两格。
 *
 * @param value 任意可序列化值
 * @param maxHeight 滚动容器最大高度，默认 360
 * @param emptyText 空态文案
 * @param title 可选标题
 * @param copyable 是否显示复制按钮
 */
export function JsonView({
  value,
  maxHeight = 360,
  emptyText = '无数据',
  title,
  copyable = true,
}: {
  value: unknown;
  maxHeight?: number;
  emptyText?: ReactNode;
  title?: ReactNode;
  copyable?: boolean;
}) {
  const { token } = theme.useToken();
  const { message } = App.useApp();

  const isEmpty = value == null;
  const text = isEmpty
    ? ''
    : JSON.stringify(value, (_k, v: unknown) => {
        // 截断超长字符串：脱敏后的密文或大响应体不应撑爆视图
        return typeof v === 'string' && v.length > 4000 ? `${v.slice(0, 4000)} …（已截断）` : v;
      }, 2);

  if (isEmpty) {
    return (
      <Flex align="center" justify="center" style={{ padding: token.paddingMD }}>
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyText} />
      </Flex>
    );
  }

  return (
    <div>
      {(title != null || copyable) && (
        <Flex align="center" justify="space-between" style={{ marginBottom: token.marginXS }}>
          <Typography.Text strong style={{ fontSize: token.fontSize }}>{title ?? '内容'}</Typography.Text>
          {copyable ? (
            <Tooltip title="复制内容">
              <Button
                size="small"
                type="text"
                icon={<CopyOutlined />}
                onClick={() => {
                  navigator.clipboard
                    .writeText(text)
                    .then(() => message.success('已复制'))
                    .catch(() => message.error('复制失败'));
                }}
              />
            </Tooltip>
          ) : null}
        </Flex>
      )}
      <pre
        style={{
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-all',
          maxHeight,
          overflow: 'auto',
          background: token.colorFillQuaternary,
          color: token.colorText,
          padding: token.paddingSM,
          borderRadius: token.borderRadiusSM,
          fontSize: token.fontSizeSM,
          fontFamily: token.fontFamilyCode,
          lineHeight: 1.6,
          margin: 0,
        }}
      >
        {text}
      </pre>
    </div>
  );
}
