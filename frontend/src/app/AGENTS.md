# 路由、布局与访问控制

- 在 `App.tsx` 的 React Router 路由树中找到同类入口，确认页面属于公开访问、登录后控制台还是管理后台。沿用该分支的布局和 `router/RouteGuards.tsx` 中的访问控制。
- 调整 URL 时，同时核对 `layouts/` 中的菜单、页面链接、登录后回跳和旧链接行为。验证直接打开、刷新和无权限访问；公开分享入口还要覆盖未登录访问。
- 会话及控制台范围沿用 `providers/AuthProvider.tsx` 和 `providers/ConsoleScopeProvider.tsx`。切换组织或项目时检查页面数据是否随范围更新。前端守卫负责页面访问反馈，资源授权由后端执行。
- 修改布局时检查桌面及手机宽度下的导航展开、当前项高亮和内容可达性。路由或跳转改动可先在 frontend 目录运行 `node --test tests/frontendRoutes.test.mjs tests/safeRedirect.test.mjs`，再验证受影响的浏览器流程。
