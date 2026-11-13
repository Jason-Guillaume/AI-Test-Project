import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
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
const ROUTE_TITLES: Record<string, string> = {
  '/admin/dashboard': '平台总览', '/admin/users': '用户管理', '/admin/organizations': '组织管理',
  '/admin/projects': '项目管理', '/admin/knowledge': '项目知识库', '/admin/model-configs': '统一模型中心',
  '/admin/environments': '环境配置', '/admin/agents': 'Agent 管理', '/admin/agent-runtime': 'Agent 运行质量',
  '/admin/mcp': 'MCP 管理', '/admin/skills': 'Skill 管理', '/admin/tools': '工具管理', '/admin/recycle-bin': '回收站',
  '/console': '工作台', '/console/projects': '项目管理', '/console/projects/1': '项目详情',
  '/console/defects': '缺陷管理', '/console/api-catalog': '接口管理', '/console/business-management': '业务管理',
  '/console/test-asset': '测试资产', '/console/test-cases': '测试用例', '/console/test-suites': '测试套件',
  '/console/test-plans': '测试计划', '/console/execution-center': '执行中心', '/console/execution-history': '执行历史',
  '/console/test-reports': '测试报告', '/console/test-reports/1': '报告详情',
  '/console/automation-projects': '自动化项目', '/console/automation-runs': '执行任务',
  '/console/automation-history': '执行历史', '/console/automation-reports/1': 'Allure 报告',
  '/console/automation-integration': '集成配置', '/console/notification-channels': '通知渠道',
  '/console/test-data': '测试数据', '/console/mock-management': '接口 Mock',
  '/console/mock-management/services/1': '服务详情', '/console/mock-management/endpoints/1': '端点详情',
  '/console/mock-management/executions': '接口 Mock 执行', '/console/web-ui': 'Web UI 工作区',
  '/console/web-ui-agent': '浏览器智能编写', '/console/security-testing': '安全测试工作区',
  '/console/asr/audio': '音频资产', '/console/asr/jobs': '评测任务', '/console/asr/jobs/1': '任务详情',
  '/console/asr/runs/1': '单模型音频工作台', '/console/asr/runs/1/listen': '单模型音频工作台',
  '/console/asr/comparisons': '识别结果对比', '/console/asr/comparisons/1': '识别结果对比',
  '/console/asr/experiments': '参数实验', '/console/asr/funasr': 'AI 分析与调优',
  '/console/tasks': '统一任务', '/console/tasks/inbox': '待我处理', '/console/tasks/templates': '任务模板',
  '/console/tasks/1': '任务执行台', '/console/agent': 'AI 助手', '/console/notifications': '消息中心',
  '/console/profile': '个人中心', '/console/recycle-bin': '回收站', '/console/knowledge': '项目知识库',
  '/console/model-center': '统一模型中心', '/console/asr/connections': '统一模型中心', '/403': '403', '/404': '404',
};
const ROUTE_CORE_SELECTOR = [
  '.page-container .ant-table-wrapper', '.page-container .ant-card', '.page-container .ant-tabs',
  '.page-container .ant-empty', '.page-container .ant-alert', '.page-container .ant-result',
  '.page-container .ant-spin', '.page-container button', '.page-container input', '.page-container .ant-select',
].join(', ');

async function assertRouteContract(page: Page, route: string) {
  const title = ROUTE_TITLES[route];
  expect(title, `缺少 ${route} 的页面标题契约`).toBeTruthy();
  if (route === '/403' || route === '/404') {
    await expect(page.locator('.ant-result-title')).toHaveText(title);
    await expect(page.locator('.ant-result')).toBeVisible();
    return;
  }
  const redirectedToAdmin = ['/console/knowledge', '/console/model-center', '/console/asr/connections'].includes(route);
  if (route.startsWith('/admin/') || redirectedToAdmin) {
    await expect(page.locator('.page-container .page-header').getByRole('heading', { name: title, exact: true }).first()).toBeVisible();
  } else {
    await expect(page.locator('.app-breadcrumb')).toContainText(title);
  }
  await expect(page.locator('.app-content')).toBeVisible();
  await expect(page.locator('.page-container').first()).toBeVisible();
  await expect(page.locator(ROUTE_CORE_SELECTOR).first()).toBeVisible();
  const primaryAction = page.locator('.page-container button.ant-btn-primary:visible').first();
  if (await primaryAction.count()) {
    await primaryAction.scrollIntoViewIfNeeded();
    const actionable = await page.evaluate(`(() => {
      const element = Array.from(document.querySelectorAll('.page-container button.ant-btn-primary'))
        .find((button) => button.getBoundingClientRect().width > 0 && button.getBoundingClientRect().height > 0);
      if (!element) return false;
      const rect = element.getBoundingClientRect();
      const hit = document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2);
      return Boolean(hit && (hit === element || element.contains(hit)) && rect.left >= 0 && rect.right <= window.innerWidth + 1);
    })()`);
    expect(actionable, `${route} 的主要操作按钮被遮挡或超出视口`).toBeTruthy();
  }
}
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
  test.setTimeout(300_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginThroughUi(page);
  for (const viewport of VIEWPORTS_TO_CHECK) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    for (const route of ROUTES_TO_CHECK) {
      const pageErrors: string[] = [];
      const consoleErrors: string[] = [];
      const systemApiErrors: string[] = [];
      const apiNetworkErrors: string[] = [];
      const expectedBusinessErrors: string[] = [];
      const onPageError = (error: Error) => pageErrors.push(`${error.name}: ${error.message}`);
      const onConsole = (message: import('@playwright/test').ConsoleMessage) => {
        if (message.type() === 'error') consoleErrors.push(message.text());
      };
      const onResponse = (response: import('@playwright/test').Response) => {
        if (!new URL(response.url()).pathname.includes('/api/v1/')) return;
        if (response.status() < 400) return;
        const description = `${response.status()} ${response.request().method()} ${new URL(response.url()).pathname}`;
        if ([403, 404].includes(response.status())) expectedBusinessErrors.push(description);
        else systemApiErrors.push(description);
      };
      const onRequestFailed = (requestEvent: import('@playwright/test').Request) => {
        if (!new URL(requestEvent.url()).pathname.includes('/api/v1/')) return;
        const failure = requestEvent.failure();
        const reason = typeof failure === 'string' ? failure : failure?.errorText || 'unknown network error';
        if (!/aborted|cancelled/i.test(reason)) apiNetworkErrors.push(`${requestEvent.method()} ${requestEvent.url()} · ${reason}`);
      };
      page.on('pageerror', onPageError);
      page.on('console', onConsole);
      page.on('response', onResponse);
      page.on('requestfailed', onRequestFailed);
      await test.step(`${route} · ${viewport.label}`, async () => {
        if (new URL(page.url()).pathname === route) await page.reload();
        else await page.evaluate(`window.history.pushState({}, '', ${JSON.stringify(route)}); window.dispatchEvent(new PopStateEvent('popstate'))`);
        await assertRouteContract(page, route);
        const dimensions = await page.evaluate('({ documentWidth: document.documentElement.scrollWidth, viewportWidth: window.innerWidth })') as { documentWidth: number; viewportWidth: number };
        expect(dimensions.documentWidth, `${route} 在 ${viewport.label} 出现横向溢出`).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
        expect(pageErrors, `${route} 出现未处理页面异常`).toEqual([]);
        expect(consoleErrors, `${route} 出现浏览器控制台异常`).toEqual([]);
        expect(systemApiErrors, `${route} 出现系统级 API 错误；业务拒绝记录：${expectedBusinessErrors.join('; ')}`).toEqual([]);
        expect(apiNetworkErrors, `${route} 出现 API 网络错误`).toEqual([]);
        if (expectedBusinessErrors.length) {
          await test.info().attach(`${route.replaceAll('/', '_')}-${viewport.width}-business-api-errors.txt`, {
            body: expectedBusinessErrors.join('\n'), contentType: 'text/plain',
          });
        }
      });
      page.off('pageerror', onPageError);
      page.off('console', onConsole);
      page.off('response', onResponse);
      page.off('requestfailed', onRequestFailed);
    }
  }
});

test('representative business pages render and save four-viewport screenshots', async ({ page }) => {
  test.setTimeout(120_000);
  const screenshots = resolve(process.cwd(), '../docs/second-round-quality-fix/screenshots', `responsive-${Date.now()}`);
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
      await assertRouteContract(page, item.path);
      const dimensions = await page.evaluate('({ documentWidth: document.documentElement.scrollWidth, viewportWidth: window.innerWidth })') as { documentWidth: number; viewportWidth: number };
      expect(dimensions.documentWidth, `${item.path} 在 ${viewport.label} 出现横向溢出`).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
      await page.screenshot({ path: `${screenshots}/${item.name}-${viewport.label}.png`, fullPage: true });
    }
  }
  await authenticatedApi.dispose();
  await api.dispose();
});
