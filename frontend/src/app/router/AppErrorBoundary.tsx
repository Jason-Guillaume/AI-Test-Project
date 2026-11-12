// 捕获路由页面与延迟模块渲染错误，避免局部异常把整个应用留成白屏。
import { Component, type ErrorInfo, type ReactNode } from 'react';
import { Button, Result } from 'antd';
import { useLocation } from 'react-router-dom';

interface AppErrorBoundaryProps {
  children: ReactNode;
  scope?: 'root' | 'route';
  path?: string;
}

interface AppErrorBoundaryState {
  error: Error | null;
  errorId: string | null;
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  state: AppErrorBoundaryState = { error: null, errorId: null };

  componentDidUpdate(previousProps: AppErrorBoundaryProps) {
    // Keep a healthy route tree mounted when only route params change (for
    // example, switching ASR runs). If a route failed, let navigation recover
    // the boundary without keying and remounting every child on each location.
    if (this.state.error && previousProps.path !== this.props.path) {
      this.setState({ error: null, errorId: null });
    }
  }

  static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return { error, errorId: crypto.randomUUID() };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const record = {
      event: 'page_render_error', error_id: this.state.errorId,
      path: this.props.path ?? window.location.pathname,
      scope: this.props.scope ?? 'root',
      build: import.meta.env.VITE_BUILD_VERSION ?? import.meta.env.MODE,
      name: error.name, message: error.message, stack: error.stack,
      component_stack: info.componentStack,
      request_id: (error as Error & { requestId?: string; request_id?: string }).requestId
        ?? (error as Error & { request_id?: string }).request_id ?? null,
    };
    // 控制台保留完整结构化记录，页面展示可复制的编号供日志检索。
    console.error('[page-error]', record);
  }

  render() {
    if (this.state.error) {
      return (
        <Result
          status="error"
          title="页面暂时无法显示"
          subTitle={<>错误编号：{this.state.errorId}。页面加载或渲染时遇到问题，可重试或返回工作台；详细记录已写入浏览器控制台。</>}
          extra={[
            <Button key="retry" type="primary" onClick={() => this.setState({ error: null, errorId: null })}>重试当前页面</Button>,
            <Button key="home" href="/console">返回工作台</Button>,
            (this.props.scope ?? 'root') === 'root' && <Button key="reload" onClick={() => window.location.reload()}>重新加载应用</Button>,
          ]}
        />
      );
    }
    return this.props.children;
  }
}

/** 路由出口专用错误隔离：每次导航建立新边界，保留布局中的导航与项目选择器。 */
export function RouteErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return (
    <AppErrorBoundary scope="route" path={location.pathname}>
      {children}
    </AppErrorBoundary>
  );
}
