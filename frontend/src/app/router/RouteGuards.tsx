// 路由守卫：登录校验与平台管理员校验。
import { Navigate, useLocation } from 'react-router-dom';
import { Spin } from 'antd';
import { useAuth } from '@/app/providers/AuthProvider';
import { safeInternalPath } from '@/shared/lib/safeRedirect';

/**
 * 登录守卫：需要登录才能进入的路由统一包一层。
 *
 * 不发请求，只读 useAuth 提供的登录态。三种出口：
 * 1. 登录态还没拉完 -> 全屏转圈，避免闪跳；
 * 2. 未登录 -> 跳 /login 并带 redirect 回跳地址（做了开放重定向防护）；
 * 3. 已登录 -> 正常渲染 children。
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const { ready, user } = useAuth();
  const location = useLocation(); // 记录当前路径，登录后回跳用
  if (!ready) {
    return (
      <div style={{ padding: 64, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }
  // 未登录分支：拼 redirect 参数，失败一律回落到 /console。
  if (!user) {
    // 使用同一站内路径校验器，避免反斜杠与编码路径绕过开放重定向检查。
    const redirect = safeInternalPath(`${location.pathname}${location.search}`);
    return <Navigate to={`/login?redirect=${encodeURIComponent(redirect)}`} replace />;
  }
  return <>{children}</>;
}

/**
 * 平台管理员守卫：只有平台管理员可进入的路由（如用户管理、模型配置）。
 *
 * 不发请求，只读登录态与 isPlatformAdmin。三种出口：
 * 1. 登录态未就绪 -> 转圈；
 * 2. 未登录 -> 跳 /login；
 * 3. 已登录但不是平台管理员 -> 跳 /403 无权限页。
 */
export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const { ready, user, isPlatformAdmin } = useAuth();
  if (!ready) {
    return (
      <div style={{ padding: 64, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }
  // 未登录先补齐登录态，不直接报 403。
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  // 权限不足：明确跳 403 页而不是渲染受保护内容，避免越权访问。
  if (!isPlatformAdmin) {
    return <Navigate to="/403" replace />;
  }
  return <>{children}</>;
}

/**
 * 游客守卫：只允许未登录访问的路由（如登录页本身）。
 *
 * 不发请求，只读登录态。已登录用户统一回到用户工作台，防止登录后仍停在登录页。
 */
export function GuestOnly({ children }: { children: React.ReactNode }) {
  const { ready, user } = useAuth();
  if (!ready) {
    return (
      <div style={{ padding: 64, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }
  if (user) {
    return <Navigate to="/console" replace />;
  }
  return <>{children}</>;
}
