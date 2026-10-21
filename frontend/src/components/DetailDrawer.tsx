// 统一详情抽屉容器。
//
// 背景：现状 5 个 Drawer 宽度有 4 种取值（72% / 640×3 / 760 / 1000），
// 且抽屉内的错误态 100% 缺失（用裸 Alert 或直接不处理）。
// 重构计划 §4 要求用例执行详情改成宽屏 Drawer，§9.7 要求三态完整。
//
// 本组件把宽度口径与三态收敛到一处：宽屏详情统一 880，管理类详情统一 640。

import { Drawer } from 'antd';
import type { ReactNode } from 'react';
import { EmptyState, ErrorState, LoadingState } from '@/components/PageState';

/** 详情抽屉的常用宽度口径。 */
export const DETAIL_DRAWER_WIDTH = {
  /** 管理类详情：单条记录信息 */
  FORM: 640,
  /** 执行详情：步骤时间线 + 证据面板 */
  EXECUTION: 880,
  /** 报告用例详情：需要更多横向空间 */
  WIDE: 1040,
} as const;

/**
 * 统一详情抽屉。
 *
 * 三态内建：loading 优先，其次 error，其次 empty，最后才是 children。
 * 这样调用方不需要在每个抽屉里重复写三态分支。
 *
 * @param open 是否打开
 * @param onClose 关闭回调
 * @param title 抽屉标题
 * @param width 宽度，默认 880（执行详情口径）
 * @param loading 加载中
 * @param error 接口错误；非空时显示 ErrorState
 * @param empty 空态文案；非空且无 error 时显示 EmptyState
 * @param footer 底部操作区
 * @param destroyOnClose 关闭时销毁内容，避免残留上一次的数据
 */
export function DetailDrawer({
  open,
  onClose,
  title,
  width = DETAIL_DRAWER_WIDTH.EXECUTION,
  loading = false,
  error,
  empty,
  footer,
  destroyOnClose = true,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  width?: number | string;
  loading?: boolean;
  error?: unknown;
  empty?: string | null;
  footer?: ReactNode;
  destroyOnClose?: boolean;
  children?: ReactNode;
}) {
  let body: ReactNode = children;
  if (loading) {
    body = <LoadingState />;
  } else if (error != null && error !== false) {
    body = <ErrorState error={error} />;
  } else if (empty != null && empty !== '') {
    body = <EmptyState description={empty} />;
  }

  return (
    <Drawer open={open} onClose={onClose} title={title} width={width} footer={footer} destroyOnClose={destroyOnClose}>
      {body}
    </Drawer>
  );
}
