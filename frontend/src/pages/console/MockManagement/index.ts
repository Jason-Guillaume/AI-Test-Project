// 接口 Mock 与依赖异常模拟模块对外导出（用户控制台页面）。
// 各页面文件保持独立，此处仅做 barrel re-export，供 App.tsx 路由按模块导入。
export { ConsoleMockManagementPage } from './ServiceList';
export { ConsoleMockServiceDetailPage } from './ServiceDetail';
export { ConsoleMockEndpointPage } from './EndpointView';
export { ConsoleMockExecutionListPage } from './ExecutionList';
