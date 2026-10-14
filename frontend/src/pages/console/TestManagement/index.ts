// 测试管理模块聚合导出（用户控制台页面）。
// 各页面文件保持独立，此处仅做 barrel re-export，供 App.tsx 路由按模块导入。
export { ConsoleTestAssetPage } from './TestAsset';
export { ConsoleTestSuitesPage } from './TestSuites';
export { ConsoleTestPlansPage } from './TestPlans';
export { ConsoleExecutionCenterPage } from './ExecutionCenter';
export { ConsoleExecutionHistoryPage } from './ExecutionHistory';
