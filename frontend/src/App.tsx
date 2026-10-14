// 应用路由表：
// - /admin/*  平台管理端（仅平台管理员，RequireAdmin + AdminLayout）
// - /console/* 用户控制台（登录用户，RequireAuth + ConsoleLayout + 作用域上下文）
// 两个入口共用登录、请求客户端、基础组件与类型定义。
import { useCallback } from 'react';
import {
  BrowserRouter,
  Navigate,
  Route,
  Routes,
  useNavigate,
} from 'react-router-dom';
import { Spin } from 'antd';
import { AuthProvider, useAuth } from '@/hooks/useAuth';
import { ConsoleScopeProvider } from '@/hooks/useConsoleScope';
import { AdminLayout } from '@/layouts/AdminLayout';
import { ConsoleLayout } from '@/layouts/ConsoleLayout';
import { GuestOnly, RequireAdmin, RequireAuth } from '@/components/RouteGuards';
import { ForbiddenPage, NotFoundPage } from '@/components/ResultPages';
import { LoginPage } from '@/pages/auth/Login';
import { RegisterPage } from '@/pages/auth/Register';
import { AdminDashboardPage } from '@/pages/admin/Dashboard';
import { AdminUsersPage } from '@/pages/admin/Users';
import { AdminOrganizationsPage } from '@/pages/admin/Organizations';
import { AdminProjectsPage } from '@/pages/admin/Projects';
import { AdminModelConfigsPage } from '@/pages/admin/ModelConfigs';
import { AdminEnvironmentsPage } from '@/pages/admin/Environments';
import { ConsoleWorkbenchPage } from '@/pages/console/Workbench';
import { ConsoleProjectsPage } from '@/pages/console/Projects';
import { ConsoleProjectDetailPage } from '@/pages/console/ProjectDetail';
import { ConsoleNotificationsPage } from '@/pages/console/Notifications';
import { ConsoleProfilePage } from '@/pages/console/Profile';
import { ConsoleDefectsPage } from '@/pages/console/Defects';
import { ConsoleApiCatalogPage } from '@/pages/console/ApiCatalog';
import { ConsoleBusinessManagementPage } from '@/pages/console/BusinessManagement';
import {
  ConsoleTestAssetPage,
  ConsoleTestSuitesPage,
  ConsoleTestPlansPage,
  ConsoleExecutionCenterPage,
  ConsoleExecutionHistoryPage,
} from '@/pages/console/TestManagement';

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
    <AuthProvider onAuthExpired={onAuthExpired}>
      <AppRoutes />
    </AuthProvider>
  );
}

/**
 * 根路径跳转：按当前登录态与角色决定落地页。
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
        // 平台管理员进管理端首页；其余登录用户进控制台；未登录回登录页。
        user ? (user.role === 'admin' ? '/admin/dashboard' : '/console') : '/login'
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
        <Route path="notifications" element={<ConsoleNotificationsPage />} />
        <Route path="profile" element={<ConsoleProfilePage />} />
      </Route>

      <Route path="/403" element={<ForbiddenPage />} />
      <Route path="/404" element={<NotFoundPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
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
