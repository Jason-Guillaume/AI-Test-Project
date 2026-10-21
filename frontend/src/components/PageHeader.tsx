// 统一页面标题栏。
//
// 背景：现状各页手写 Typography.Title（level 4 与 5 混用、间距 12 与 16 混用）共 4 处以上。
// 重构计划 §3.A 要求报告页头部集中展示报告名称、编号、所属项目、环境、执行时间、
// 状态与主操作，必须收敛成一处实现。

import { Breadcrumb, Button, Flex, Space, theme, Typography } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { type ReactNode } from 'react';

/** 头部的一条事实：左侧中文标签，右侧值。 */
export interface PageHeaderMeta {
  label: string;
  value: ReactNode;
}

/**
 * 页面标题栏。
 *
 * 布局：可选返回按钮 + 标题（含内联标签）+ 右侧主操作区；
 * 标题下方可选一条紧凑事实带（meta），用于报告页的编号/项目/环境/执行时间等元信息。
 *
 * @param title 页面或对象名称
 * @param titleExtra 标题右侧的内联元素（状态徽标等）
 * @param subtitle 副标题
 * @param meta 标题下方的事实带，紧凑排布
 * @param extra 右侧主操作区
 * @param back 是否显示返回按钮，点击调用 onBack
 * @param breadcrumb 面包屑路径
 */
export function PageHeader({
  title,
  titleExtra,
  subtitle,
  meta,
  extra,
  back = false,
  onBack,
  breadcrumb,
}: {
  title: ReactNode;
  titleExtra?: ReactNode;
  subtitle?: ReactNode;
  meta?: PageHeaderMeta[];
  extra?: ReactNode;
  back?: boolean;
  onBack?: () => void;
  breadcrumb?: string[];
}) {
  const { token } = theme.useToken();

  return (
    <div style={{ marginBottom: token.marginLG }}>
      {breadcrumb && breadcrumb.length > 0 ? (
        <Breadcrumb items={breadcrumb.map((t) => ({ title: t }))} style={{ marginBottom: token.marginXS }} />
      ) : null}

      <Flex align="flex-start" justify="space-between" gap={token.margin} wrap="wrap">
        <Flex align="flex-start" gap={token.marginXS} style={{ minWidth: 0, flex: '1 1 auto' }}>
          {back ? (
            <Button type="text" icon={<ArrowLeftOutlined />} onClick={onBack} aria-label="返回" />
          ) : null}
          <div style={{ minWidth: 0 }}>
            <Flex align="center" gap={token.marginXS} wrap="wrap">
              <Typography.Title level={4} style={{ margin: 0 }} ellipsis={{ tooltip: true }}>
                {title}
              </Typography.Title>
              {titleExtra}
            </Flex>
            {subtitle ? (
              <Typography.Text type="secondary">{subtitle}</Typography.Text>
            ) : null}
          </div>
        </Flex>
        {extra ? <Space size="small" wrap style={{ flexShrink: 0 }}>{extra}</Space> : null}
      </Flex>

      {meta && meta.length > 0 ? (
        <Flex
          align="center"
          gap={token.marginLG}
          wrap="wrap"
          style={{
            marginTop: token.margin,
            paddingTop: token.marginSM,
            borderTop: `1px solid ${token.colorBorderSecondary}`,
          }}
        >
          {meta.map((m, i) => (
            <Flex key={i} align="baseline" gap={token.marginXXS} wrap="nowrap">
              <Typography.Text type="secondary" style={{ fontSize: token.fontSizeSM }}>
                {m.label}
              </Typography.Text>
              <Typography.Text strong style={{ fontSize: token.fontSize, wordBreak: 'break-all' }}>
                {m.value}
              </Typography.Text>
            </Flex>
          ))}
        </Flex>
      ) : null}
    </div>
  );
}
