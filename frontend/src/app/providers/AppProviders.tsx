import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { App as AntdApp, ConfigProvider, message } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { type ReactNode, useState } from 'react';
import { buildTheme } from '@/shared/theme';

// 全局 QueryClient：失败重试有限，避免 401 类错误反复重试。
function makeClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: 1, // 查询只重试一次：瞬时网络抖动可恢复，权限类错误重试无意义
        refetchOnWindowFocus: false, // 切回标签页不自动刷新，避免重复打接口
        staleTime: 30_000, // 30 秒内重复请求复用缓存数据
      },
      mutations: { retry: 0 }, // 写操作不重试：重试会造成重复创建等非幂等后果
    },
  });
}

/**
 * 应用级 Provider 组合。
 *
 * 纯配置组件，不发请求：统一注入 antd 中文语言包、主题 token 与全局 QueryClient。
 * QueryClient 用 useState 惰性创建，保证整个应用生命周期内只有一份实例。
 */
export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(makeClient);
  return (
    <ConfigProvider locale={zhCN} theme={buildTheme()}>
      <AntdApp>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </AntdApp>
    </ConfigProvider>
  );
}

// 暴露 antd 静态 message 用于非组件上下文（如 client 拦截器）。
export const staticMessage = message;
