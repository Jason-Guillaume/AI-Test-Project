// 前端入口：全局 Provider（antd ConfigProvider + React Query）→ 路由与认证。
// 职责：装载中文语言包、取得 DOM 挂载节点，再把 App 套进 StrictMode 与全局 Provider。
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import 'dayjs/locale/zh-cn'; // 导入 dayjs 简体中文语言包，必须先于任何渲染完成
import '@/styles/app.css';
import { AppProviders } from '@/app/providers/AppProviders';
import { App } from '@/app/App';

// React 根节点：与 index.html 中的 <div id="root"> 对应，整棵应用树挂载在此。
const rootElement = document.getElementById('root');
if (!rootElement) {
  // 挂载节点缺失时直接抛错：渲染下去只会得到一个空白的“假成功”页面。
  throw new Error('未找到挂载节点 #root');
}

// StrictMode 在开发环境会重复执行渲染与 effect，用来暴露副作用不纯净的问题。
createRoot(rootElement).render(
  <StrictMode>
    <AppProviders>
      <App />
    </AppProviders>
  </StrictMode>,
);
