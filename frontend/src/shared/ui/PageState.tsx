// 统一的状态占位：加载中、空数据、接口失败。
import { Alert, Empty, Spin } from 'antd';
import { type ReactNode } from 'react';
import { getErrorMessage } from '@/shared/api/client';

/**
 * 加载中占位。
 *
 * 纯展示组件，不发请求：调用方在接口返回前渲染它。
 * tip 是转圈下方的提示文案，可省略。
 */
export function LoadingState({ tip = '加载中…' }: { tip?: string }) {
  return (
    <div style={{ padding: 48, textAlign: 'center' }}>
      <Spin tip={tip} size="large" />
    </div>
  );
}

/**
 * 空数据占位。
 *
 * 纯展示组件，不发请求：数据加载成功但列表为空时渲染它。
 * description 是空态文案，默认为“暂无数据”。
 */
export function EmptyState({ description = '暂无数据' }: { description?: string }) {
  return (
    <div style={{ padding: 32, textAlign: 'center' }}>
      <Empty description={description} />
    </div>
  );
}

/**
 * 接口失败占位。
 *
 * 纯展示组件，不发请求：渲染红色告警条，并用 getErrorMessage 提取可读错误信息。
 * onRetry 传入时显示“重试”链接，点击由调用方负责重新触发请求。
 */
export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown; // 接口抛出的原始错误对象，类型不确定
  onRetry?: () => void; // 可选的重试回调；不传则不显示重试按钮
}) {
  return (
    <Alert
      type="error"
      showIcon
      message="加载失败"
      description={getErrorMessage(error)}
      action={
        onRetry ? (
          <a onClick={onRetry}>重试</a>
        ) : undefined
      }
    />
  );
}

/**
 * 页面容器。
 *
 * 纯排版组件，不发请求：统一各页面的内边距，保证视觉一致。
 */
export function PageContainer({ children }: { children: ReactNode }) {
  return <div className="page-container">{children}</div>;
}
