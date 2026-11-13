// Shared right-side drawer for resource details and editing.
import { App, Drawer } from 'antd';
import type { ReactNode } from 'react';
import { EmptyState, ErrorState, LoadingState } from '@/shared/ui/PageState';

/** Common width presets for detail drawers. */
export const DETAIL_DRAWER_WIDTH = {
  FORM: 640,
  EXECUTION: 880,
  WIDE: 1040,
} as const;

/**
 * Shared drawer with consistent loading/error/empty states and optional dirty-close guard.
 * Existing consumers can keep using the original state props.
 */
export function DetailDrawer({
  open,
  onClose,
  title,
  extra,
  width = DETAIL_DRAWER_WIDTH.EXECUTION,
  loading = false,
  error,
  empty,
  footer,
  destroyOnClose = true,
  dirty = false,
  dirtyMessage = '关闭会丢弃尚未保存的修改。',
  children,
}: {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  extra?: ReactNode;
  width?: number | string;
  loading?: boolean;
  error?: unknown;
  empty?: string | null;
  footer?: ReactNode;
  destroyOnClose?: boolean;
  dirty?: boolean;
  dirtyMessage?: ReactNode;
  children?: ReactNode;
}) {
  const { modal } = App.useApp();
  const requestClose = () => {
    if (!dirty) { onClose(); return; }
    modal.confirm({
      title: '放弃未保存修改？',
      content: dirtyMessage,
      okText: '放弃修改',
      cancelText: '继续编辑',
      okButtonProps: { danger: true },
      onOk: onClose,
    });
  };
  let body: ReactNode = children;
  if (loading) body = <LoadingState />;
  else if (error != null && error !== false) body = <ErrorState error={error} />;
  else if (empty != null && empty !== '') body = <EmptyState description={empty} />;

  return (
    <Drawer
      className="resource-detail-drawer"
      open={open}
      onClose={requestClose}
      title={title}
      extra={extra}
      width={width}
      footer={footer}
      destroyOnClose={destroyOnClose}
    >
      {body}
    </Drawer>
  );
}
