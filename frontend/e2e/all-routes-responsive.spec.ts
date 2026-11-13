import { mkdirSync } from 'node:fs';
import { expect, request, test, type Page } from '@playwright/test';

const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8101/api/v1';
const ADMIN = process.env.E2E_ADMIN_USERNAME ?? 'e2e-admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';

async function loginThroughUi(page: Page) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(ADMIN);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'));
}

const ROUTES = [
  '/admin/dashboard', '/admin/users', '/admin/organizations', '/admin/projects',
  '/admin/knowledge', '/admin/model-configs', '/admin/environments', '/admin/agents',
  '/admin/agent-runtime', '/admin/mcp', '/admin/skills', '/admin/tools', '/admin/recycle-bin',
  '/console', '/console/projects', '/console/projects/1', '/console/defects',
  '/console/api-catalog', '/console/business-management', '/console/test-asset',
  '/console/test-cases', '/console/test-suites', '/console/test-plans',
  '/console/execution-center', '/console/execution-history', '/console/test-reports',
  '/console/test-reports/1', '/console/automation-projects', '/console/automation-runs',
  '/console/automation-history', '/console/automation-reports/1', '/console/automation-integration',
  '/console/notification-channels', '/console/test-data', '/console/mock-management',
  '/console/mock-management/services/1', '/console/mock-management/endpoints/1',
  '/console/mock-management/executions', '/console/web-ui', '/console/web-ui-agent',
  '/console/security-testing', '/console/asr/audio', '/console/asr/jobs', '/console/asr/jobs/1',
  '/console/asr/runs/1', '/console/asr/runs/1/listen', '/console/asr/comparisons',
  '/console/asr/comparisons/1', '/console/asr/experiments', '/console/asr/funasr',
  '/console/tasks', '/console/tasks/inbox', '/console/tasks/templates', '/console/tasks/1',
  '/console/agent', '/console/notifications', '/console/profile', '/console/recycle-bin',
  '/console/knowledge', '/console/model-center', '/console/asr/connections', '/403', '/404',
];
const routeLimit = process.env.E2E_ROUTE_UNTIL ? ROUTES.indexOf(process.env.E2E_ROUTE_UNTIL) : -1;
const ROUTES_TO_CHECK = process.env.E2E_ROUTE_ONLY
  ? [process.env.E2E_ROUTE_ONLY]
  : routeLimit >= 0 ? ROUTES.slice(0, routeLimit + 1) : ROUTES;
const VIEWPORTS_TO_CHECK = process.env.E2E_VIEWPORT_ONLY
  ? [{ width: 390, height: 844, label: '390×844' }]
  : [
    { width: 1440, height: 900, label: '1440×900' },
    { width: 1024, height: 768, label: '1024×768' },
    { width: 768, height: 1024, label: '768×1024' },
    { width: 390, height: 844, label: '390×844' },
  ];

test('all registered business routes render without page-level horizontal overflow', async ({ page }) => {
  test.setTimeout(120_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginThroughUi(page);
  for (const viewport of VIEWPORTS_TO_CHECK) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(ROUTES_TO_CHECK[0]);
    await expect(page.locator('.app-content')).toBeVisible();
    for (const route of ROUTES_TO_CHECK.slice(1)) {
      await page.evaluate(`window.history.pushState({}, '', ${JSON.stringify(route)}); window.dispatchEvent(new PopStateEvent('popstate'))`);
      await expect(page.locator('.app-content, .auth-page, .result-page, .ant-result').first()).toBeVisible({ timeout: 3000 });
      // Allow lazy route chunks and the layout breakpoint transition to settle before measuring.
      await page.waitForTimeout(250);
      const dimensions = await page.evaluate('({ documentWidth: document.documentElement.scrollWidth, viewportWidth: window.innerWidth })') as { documentWidth: number; viewportWidth: number };
      const overflowElements = dimensions.documentWidth > dimensions.viewportWidth + 1
        ? await page.evaluate(`Array.from(document.querySelectorAll('body *'))
          .map((element) => {
            const rect = element.getBoundingClientRect();
            const parent = element.parentElement;
            const parentRect = parent?.getBoundingClientRect();
            return { tag: element.tagName, className: typeof element.className === 'string' ? element.className : '', id: element.id, text: (element.textContent ?? '').trim().slice(0, 60), right: Math.round(rect.right), width: Math.round(rect.width), scrollWidth: element.scrollWidth, clientWidth: element.clientWidth, parent: parent ? { tag: parent.tagName, className: typeof parent.className === 'string' ? parent.className : '', right: Math.round(parentRect?.right ?? 0), width: Math.round(parentRect?.width ?? 0) } : undefined };
          })
          .filter((element) => element.right > window.innerWidth + 1)
          .sort((left, right) => right.right - left.right)
          .slice(0, 12)`)
        : [];
      expect(dimensions.documentWidth, `${route} 在 ${viewport.label} 出现横向溢出：${JSON.stringify(overflowElements)}`).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
    }
  }
});

test('representative business pages render and save four-viewport screenshots', async ({ page }) => {
  test.setTimeout(120_000);
  const screenshots = `/tmp/ai-test-project-ux-core-${Date.now()}`;
  mkdirSync(screenshots, { recursive: true });
  const api = await request.newContext();
  const login = await api.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token as string;
  const authenticatedApi = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const projectResponse = await authenticatedApi.post(`${API}/projects`, {
    data: { name: `E2E 截图项目 ${Date.now()}`, description: '通过项目 API 创建的真实验收项目。' },
  });
  expect(projectResponse.status()).toBe(201);
  const projectId = (await projectResponse.json()).id as number;
  const pages = [
    { path: '/console', name: 'console-home' },
    { path: '/console/projects', name: 'projects' },
    { path: '/console/api-catalog', name: 'api-catalog' },
    { path: '/console/business-management', name: 'business-management' },
    { path: '/console/test-asset', name: 'test-assets' },
    { path: '/console/test-data', name: 'test-data' },
    { path: '/console/execution-center', name: 'execution-center' },
    { path: '/console/security-testing', name: 'security-testing' },
    { path: '/console/test-reports', name: 'test-reports' },
    { path: '/admin/dashboard', name: 'admin-dashboard' },
    { path: '/admin/users', name: 'admin-users' },
  ];
  const viewports = [
    { width: 1440, height: 900, label: '1440x900' },
    { width: 1024, height: 768, label: '1024x768' },
    { width: 768, height: 1024, label: '768x1024' },
    { width: 390, height: 844, label: '390x844' },
  ];
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginThroughUi(page);
  await page.evaluate((pid) => {
    const user = JSON.parse(localStorage.getItem('user') ?? '{}');
    localStorage.setItem('console.current_project_id', String(pid));
    localStorage.setItem('console.scope_user_id', String(user.id ?? ''));
  }, projectId);
  for (const item of pages) {
    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(item.path);
      await expect(page.locator('.app-content')).toBeVisible();
      await page.waitForTimeout(150);
      const dimensions = await page.evaluate('({ documentWidth: document.documentElement.scrollWidth, viewportWidth: window.innerWidth })') as { documentWidth: number; viewportWidth: number };
      expect(dimensions.documentWidth, `${item.path} 在 ${viewport.label} 出现横向溢出`).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
      await page.screenshot({ path: `${screenshots}/${item.name}-${viewport.label}.png`, fullPage: true });
    }
  }
  await authenticatedApi.dispose();
  await api.dispose();
});
