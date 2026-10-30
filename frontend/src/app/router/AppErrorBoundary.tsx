// 捕获路由页面与延迟模块渲染错误，避免局部异常把整个应用留成白屏。
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button, Result } from 'antd';

interface AppErrorBoundaryProps {
  children: ReactNode;
}

interface AppErrorBoundaryState {
  error: Error | null;
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // 保留可诊断信息；页面展示只给出稳定的恢复动作，不回显堆栈。
    console.error('页面渲染失败', error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <Result
          status="error"
          title="页面暂时无法显示"
          subTitle="页面加载或渲染时遇到问题，请重新加载后再试。"
          extra={<Button type="primary" onClick={() => window.location.reload()}>重新加载</Button>}
        />
      );
    }
    return this.props.children;
  }
}
