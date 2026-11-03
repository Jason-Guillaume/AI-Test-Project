// 应用路由表：
// - /admin/*  平台管理端（仅平台管理员，RequireAdmin + AdminLayout）
// - /console/* 用户控制台（登录用户，RequireAuth + ConsoleLayout + 作用域上下文）
// 两个入口共用登录、请求客户端、基础组件与类型定义。
import { lazy, Suspense, useCallback, type ComponentType } from 'react';
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom';
import { Spin } from 'antd';
import { Result, Button } from 'antd';
import { AuthProvider, useAuth } from '@/app/providers/AuthProvider';
import { ConsoleScopeProvider } from '@/app/providers/ConsoleScopeProvider';
import { GuestOnly, RequireAdmin, RequireAuth } from '@/app/router/RouteGuards';
import { AppErrorBoundary } from '@/app/router/AppErrorBoundary';
import { ForbiddenPage, NotFoundPage } from '@/pages/errors/ResultPages';

// 页面模块延迟到路由命中时再下载，减小应用启动时的代码体积。
/**
 * 把页面模块的具名导出包装成 React.lazy 可用的异步组件。
 * 路由首次匹配时触发动态导入；加载错误会由 React.lazy 向上抛出。
 */
function lazyNamedPage<M, K extends keyof M>(loader: () => Promise<M>, exportName: K) {
  return lazy(async () => ({
    default: (await loadPageModule(loader))[exportName] as ComponentType,
  }));
}

/** Stale deployment chunks get one bounded refresh; repeated failure is reported by the route boundary. */
async function loadPageModule<M>(loader: () => Promise<M>): Promise<M> {
  try {
    const module = await loader();
    try { sessionStorage.removeItem(`page-chunk-refresh:${window.location.pathname}`); } catch { /* storage may be blocked */ }
    return module;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    if (/dynamically imported module|loading chunk|chunkloaderror|importing a module script failed/i.test(message)) {
      const key = `page-chunk-refresh:${window.location.pathname}`;
      try {
        if (!sessionStorage.getItem(key)) {
          sessionStorage.setItem(key, '1');
          window.location.reload();
        }
      } catch { /* the route boundary remains the fallback when storage is unavailable */ }
    }
    throw error;
  }
}

/** Compatibility path for retired model pages; authorization still comes from the existing admin guard. */
function LegacyModelEntry() {
  const { user } = useAuth();
  if (user?.role === 'admin') return <Navigate to="/admin/model-configs?category=ASR" replace />;
  return <Result
    status="info"
    title="模型配置由平台管理员维护"
    subTitle="此旧入口不提供模型管理权限。你仍可在 ASR 评测页查看任务和可用模型；如需新增或授权模型，请联系平台管理员。"
    extra={<Button type="primary" href="/console/asr/jobs">返回 ASR 评测任务</Button>}
  />;
}

const AdminLayout = lazyNamedPage(() => import('@/app/layouts/AdminLayout'), 'AdminLayout');
const ConsoleLayout = lazyNamedPage(() => import('@/app/layouts/ConsoleLayout'), 'ConsoleLayout');
const LoginPage = lazyNamedPage(() => import('@/pages/auth/Login'), 'LoginPage');
const RegisterPage = lazyNamedPage(() => import('@/pages/auth/Register'), 'RegisterPage');
const AdminDashboardPage = lazyNamedPage(() => import('@/pages/admin/Dashboard'), 'AdminDashboardPage');
const AdminUsersPage = lazyNamedPage(() => import('@/pages/admin/Users'), 'AdminUsersPage');
const AdminOrganizationsPage = lazyNamedPage(() => import('@/pages/admin/Organizations'), 'AdminOrganizationsPage');
const AdminProjectsPage = lazyNamedPage(() => import('@/pages/admin/Projects'), 'AdminProjectsPage');
const AdminModelConfigsPage = lazyNamedPage(() => import('@/pages/admin/ModelConfigs'), 'AdminModelConfigsPage');
const AdminEnvironmentsPage = lazyNamedPage(() => import('@/pages/admin/Environments'), 'AdminEnvironmentsPage');
const AdminAgentGovernancePage = lazyNamedPage(() => import('@/pages/admin/AgentGovernance'), 'AdminAgentGovernancePage');
const ConsoleWorkbenchPage = lazyNamedPage(() => import('@/pages/console/Workbench'), 'ConsoleWorkbenchPage');
const ConsoleProjectsPage = lazyNamedPage(() => import('@/pages/console/Projects'), 'ConsoleProjectsPage');
const ConsoleProjectDetailPage = lazyNamedPage(() => import('@/pages/console/Projects/ProjectDetail'), 'ConsoleProjectDetailPage');
const ConsoleNotificationsPage = lazyNamedPage(() => import('@/pages/console/Notifications'), 'ConsoleNotificationsPage');
const ConsoleProfilePage = lazyNamedPage(() => import('@/pages/console/Profile'), 'ConsoleProfilePage');
const ConsoleDefectsPage = lazyNamedPage(() => import('@/pages/console/Defects'), 'ConsoleDefectsPage');
const ConsoleApiCatalogPage = lazyNamedPage(() => import('@/pages/console/ApiCatalog'), 'ConsoleApiCatalogPage');
const ConsoleBusinessManagementPage = lazyNamedPage(() => import('@/pages/console/BusinessManagement'), 'ConsoleBusinessManagementPage');
const ConsoleTestAssetPage = lazyNamedPage(() => import('@/pages/console/TestManagement/TestAsset'), 'ConsoleTestAssetPage');
const ConsoleTestSuitesPage = lazyNamedPage(() => import('@/pages/console/TestManagement/TestSuites'), 'ConsoleTestSuitesPage');
const ConsoleTestPlansPage = lazyNamedPage(() => import('@/pages/console/TestManagement/TestPlans'), 'ConsoleTestPlansPage');
const ConsoleExecutionCenterPage = lazyNamedPage(() => import('@/pages/console/TestManagement/ExecutionCenter'), 'ConsoleExecutionCenterPage');
const ConsoleExecutionHistoryPage = lazyNamedPage(() => import('@/pages/console/TestManagement/ExecutionHistory'), 'ConsoleExecutionHistoryPage');
const ConsoleAgentPage = lazyNamedPage(() => import('@/pages/console/Agent/AgentPage'), 'AgentPage');
const ConsoleReportListPage = lazyNamedPage(() => import('@/pages/console/Reports/ReportList'), 'ConsoleReportListPage');
const ConsoleReportDetailPage = lazyNamedPage(() => import('@/pages/console/Reports/ReportDetail'), 'ConsoleReportDetailPage');
const ConsoleNotificationChannelsPage = lazyNamedPage(() => import('@/pages/console/NotificationChannels'), 'ConsoleNotificationChannelsPage');
const ConsoleTestDataPage = lazyNamedPage(() => import('@/pages/console/TestData'), 'ConsoleTestDataPage');
const ConsoleMockManagementPage = lazyNamedPage(() => import('@/pages/console/MockManagement/ServiceList'), 'ConsoleMockManagementPage');
const ConsoleMockServiceDetailPage = lazyNamedPage(() => import('@/pages/console/MockManagement/ServiceDetail'), 'ConsoleMockServiceDetailPage');
const ConsoleMockEndpointPage = lazyNamedPage(() => import('@/pages/console/MockManagement/EndpointView'), 'ConsoleMockEndpointPage');
const ConsoleMockExecutionListPage = lazyNamedPage(() => import('@/pages/console/MockManagement/ExecutionList'), 'ConsoleMockExecutionListPage');
const ConsoleWebUIPage = lazyNamedPage(() => import('@/pages/console/WebUI'), 'ConsoleWebUIPage');
const ConsoleWebUIAgentPage = lazyNamedPage(() => import('@/pages/console/WebUIAgent'), 'ConsoleWebUIAgentPage');
const ConsoleSecurityTestingPage = lazyNamedPage(() => import('@/pages/console/SecurityTesting'), 'ConsoleSecurityTestingPage');
const ConsoleTasksPage = lazyNamedPage(() => import('@/pages/console/Tasks/TaskListPage'), 'ConsoleTasksPage');
const ConsoleTaskDetailPage = lazyNamedPage(() => import('@/pages/console/Tasks/TaskDetailPage'), 'ConsoleTaskDetailPage');
const ConsoleTaskInboxPage = lazyNamedPage(() => import('@/pages/console/Tasks/TaskInboxPage'), 'ConsoleTaskInboxPage');
const ConsoleTaskTemplatesPage = lazyNamedPage(() => import('@/pages/console/Tasks/TaskTemplatesPage'), 'ConsoleTaskTemplatesPage');
const AsrAudioPage = lazyNamedPage(() => import('@/pages/console/ASREvaluation/AudioPage'), 'AudioPage');
const AsrJobsPage = lazyNamedPage(() => import('@/pages/console/ASREvaluation/JobsPage'), 'JobsPage');
const AsrJobDetailPage = lazyNamedPage(() => import('@/pages/console/ASREvaluation/JobsPage'), 'JobDetailPage');
const AsrComparisonsPage = lazyNamedPage(() => import('@/pages/console/ASREvaluation/ComparisonsPage'), 'ComparisonsPage');
const AsrComparisonDetailPage = lazyNamedPage(() => import('@/pages/console/ASREvaluation/ComparisonsPage'), 'ComparisonDetailPage');
const AsrExperimentsPage = lazyNamedPage(() => import('@/pages/console/ASREvaluation/ExperimentsPage'), 'ExperimentsPage');
const AsrRunWorkbenchPage = lazyNamedPage(() => import('@/pages/console/ASREvaluation/RunWorkbenchPage'), 'RunWorkbenchPage');

/**
 * 认证外壳：把整棵路由树包在 AuthProvider 里，并注入统一的令牌失效回调。
 *
 * 不发请求（登录态恢复由 AuthProvider 内部完成）。作用域仅覆盖其子树，
 * 因此挂在 <BrowserRouter> 之内、AuthProvider 之外，登出跳转也能生效。
 */
function AuthShell() {
  const navigate = useNavigate();
  // 令牌失效或账户被禁用时统一回到登录页。
  const onAuthExpired = useCallback(() => {
    // replace 避免留下登录页的历史记录，用户点“后退”不会回到受保护页面。
    navigate('/login', { replace: true });
  }, [navigate]);

  return (
    <AppErrorBoundary>
      <AuthProvider onAuthExpired={onAuthExpired}>
        <AppRoutes />
      </AuthProvider>
    </AppErrorBoundary>
  );
}

/**
 * 根路径跳转：登录用户统一进入用户工作台，未登录用户进入登录页。
 *
 * 不发请求（复用 useAuth 已恢复的登录态）；ready 为 false 时（/me 还在跑）显示全屏加载圈，
 * 而不是直接跳登录页，否则会闪现错误的跳转。
 */
function HomeRedirect() {
  const { ready, user } = useAuth();
  if (!ready) {
    // 登录态尚未恢复，先展示加载态等待。
    return (
      <div style={{ padding: 64, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }
  return (
    <Navigate
      replace
      to={
        // 所有登录用户默认进入工作台；管理员可从工作台顶部切换到管理后台。
        user ? '/console' : '/login'
      }
    />
  );
}

/**
 * 全部路由声明：管理端与用户控制台两条独立分支，外加 403/404 兜底页。
 *
 * 权限边界靠 RouteGuards 在父路由层做：RequireAdmin 拦截 /admin 整支，
 * RequireAuth 拦截 /console 整支，GuestOnly 把已登录用户挡在登录/注册页外。
 */
function AppRoutes() {
  return (
    // 异步页面模块加载期间保留统一占位，避免切换路由时出现空白页。
    <Suspense
      fallback={
        <div style={{ minHeight: '100vh', display: 'grid', placeItems: 'center' }}>
          <Spin size="large" />
        </div>
      }
    >
      <Routes>
        <Route path="/" element={<HomeRedirect />} />

        <Route
          path="/login"
          element={
            // 仅游客可见：已登录用户访问会被重定向回各自入口。
            <GuestOnly>
              <LoginPage />
            </GuestOnly>
          }
        />
        <Route
          path="/register"
          element={
            <GuestOnly>
              <RegisterPage />
            </GuestOnly>
          }
        />

        <Route
          path="/admin"
          element={
            // 平台管理员专属分支；非 admin 命中 403 页。
            <RequireAdmin>
              <AdminLayout />
            </RequireAdmin>
          }
        >
          <Route index element={<Navigate to="/admin/dashboard" replace />} />
          <Route path="dashboard" element={<AdminDashboardPage />} />
          <Route path="users" element={<AdminUsersPage />} />
          <Route path="organizations" element={<AdminOrganizationsPage />} />
          <Route path="projects" element={<AdminProjectsPage />} />
          <Route path="model-configs" element={<AdminModelConfigsPage />} />
          <Route path="environments" element={<AdminEnvironmentsPage />} />
          <Route path="agents" element={<AdminAgentGovernancePage />} />
          <Route path="mcp" element={<AdminAgentGovernancePage />} />
          <Route path="skills" element={<AdminAgentGovernancePage />} />
          <Route path="tools" element={<AdminAgentGovernancePage />} />
        </Route>

        <Route
          path="/console"
          element={
            // ConsoleScopeProvider 只提供“当前组织/项目”选择态，不做鉴权。
            <RequireAuth>
              <ConsoleScopeProvider>
                <ConsoleLayout />
              </ConsoleScopeProvider>
            </RequireAuth>
          }
        >
          <Route index element={<ConsoleWorkbenchPage />} />
          <Route path="projects" element={<ConsoleProjectsPage />} />
          <Route path="projects/:id" element={<ConsoleProjectDetailPage />} />
          <Route path="defects" element={<ConsoleDefectsPage />} />
          <Route path="api-catalog" element={<ConsoleApiCatalogPage />} />
          <Route path="business-management" element={<ConsoleBusinessManagementPage />} />
          <Route path="test-asset" element={<ConsoleTestAssetPage />} />
          <Route path="test-suites" element={<ConsoleTestSuitesPage />} />
          <Route path="test-plans" element={<ConsoleTestPlansPage />} />
          <Route path="execution-center" element={<ConsoleExecutionCenterPage />} />
          <Route path="execution-history" element={<ConsoleExecutionHistoryPage />} />
          <Route path="test-reports" element={<ConsoleReportListPage />} />
          <Route path="test-reports/:reportId" element={<ConsoleReportDetailPage />} />
          <Route path="notification-channels" element={<ConsoleNotificationChannelsPage />} />
          <Route path="test-data" element={<ConsoleTestDataPage />} />
          <Route path="mock-management" element={<ConsoleMockManagementPage />} />
          <Route path="mock-management/services/:serviceId" element={<ConsoleMockServiceDetailPage />} />
          <Route path="mock-management/endpoints/:endpointId" element={<ConsoleMockEndpointPage />} />
          <Route path="mock-management/executions" element={<ConsoleMockExecutionListPage />} />
          <Route path="web-ui" element={<ConsoleWebUIPage />} />
          <Route path="web-ui-agent" element={<ConsoleWebUIAgentPage />} />
          <Route path="security-testing" element={<ConsoleSecurityTestingPage />} />
          <Route path="asr/audio" element={<AsrAudioPage />} />
          {/* 兼容旧书签；模型中心现在仅由管理后台提供。 */}
          <Route path="model-center" element={<LegacyModelEntry />} />
          <Route path="asr/connections" element={<LegacyModelEntry />} />
          <Route path="asr/jobs" element={<AsrJobsPage />} />
          <Route path="asr/jobs/:jobId" element={<AsrJobDetailPage />} />
          <Route path="asr/runs/:runId" element={<AsrRunWorkbenchPage />} />
          <Route path="asr/comparisons" element={<AsrComparisonsPage />} />
          <Route path="asr/comparisons/:comparisonId" element={<AsrComparisonDetailPage />} />
          <Route path="asr/experiments" element={<AsrExperimentsPage />} />
          <Route path="tasks" element={<ConsoleTasksPage />} />
          <Route path="tasks/inbox" element={<ConsoleTaskInboxPage />} />
          <Route path="tasks/templates" element={<ConsoleTaskTemplatesPage />} />
          <Route path="tasks/:taskId" element={<ConsoleTaskDetailPage />} />
          <Route path="agent" element={<ConsoleAgentPage />} />
          <Route path="notifications" element={<ConsoleNotificationsPage />} />
          <Route path="profile" element={<ConsoleProfilePage />} />
        </Route>

        <Route path="/403" element={<ForbiddenPage />} />
        <Route path="/404" element={<NotFoundPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </Suspense>
  );
}

/**
 * 应用根组件：挂载浏览器路由，并渲染认证外壳。
 *
 * 不发请求；仅做 <BrowserRouter> 与 <AuthShell> 的组合，
 * Provider 层级由 AuthShell / AppProviders 负责。
 */
export function App() {
  return (
    <BrowserRouter>
      <AuthShell />
    </BrowserRouter>
  );
}
