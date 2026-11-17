// 缺陷飞书分享闭环。
// 飞书 Webhook 指向本机桩，不代表真实飞书租户已经联调通过。
import { expect, request, test, type Page } from '@playwright/test';
import { createServer } from 'node:http';
import type { AddressInfo } from 'node:net';

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

test('tester pushes a defect and a developer resolves it without logging in', async ({ page, browser }) => {
  test.skip(!PASSWORD, '需要 E2E_ADMIN_PASSWORD 才能登录隔离环境');
  const received: string[] = [];
  const hook = createServer((req, response) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
    req.on('end', () => {
      received.push(Buffer.concat(chunks).toString('utf8'));
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ code: 0, msg: 'success' }));
    });
  });
  await new Promise<void>((resolve) => hook.listen(0, '127.0.0.1', resolve));
  const port = (hook.address() as AddressInfo).port;
  try {
    const api = await request.newContext();
    const login = await api.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
    expect(login.ok()).toBeTruthy();
    const token = (await login.json()).access_token as string;
    const authenticated = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
    const suffix = Date.now();
    const project = await authenticated.post(`${API}/projects`, { data: { name: `分享项目 ${suffix}` } });
    expect(project.status()).toBe(201);
    const projectId = (await project.json()).id as number;
    const channel = await authenticated.post(`${API}/projects/${projectId}/notification-channels`, {
      data: { name: '研发缺陷群', webhook_url: `http://127.0.0.1:${port}/hook`, enabled: true },
    });
    expect(channel.status()).toBe(201);
    const bug = await authenticated.post(`${API}/bugs`, {
      data: {
        project_id: projectId, title: `登录接口 500 ${suffix}`, description: '登录接口返回 500',
        severity: 4, status: '待确认', steps_to_reproduce: '调用登录接口', environment: 'test',
      },
    });
    expect(bug.status()).toBe(201);
    const bugId = (await bug.json()).id as number;
    await loginThroughUi(page);
    await page.goto(`/console/defects?bugId=${bugId}`);
    await page.getByRole('dialog').getByRole('button', { name: '推送到飞书', exact: true }).click();
    await page.getByText('研发缺陷群').click();
    await page.getByRole('button', { name: '确认推送' }).click();
    await expect(page.getByText('已推送到')).toBeVisible();
    const shareUrl = await page.locator('.ant-typography').filter({ hasText: '/public/defects/share/' }).first().innerText();
    const guest = await browser.newContext();
    const guestPage = await guest.newPage();
    await guestPage.goto(shareUrl);
    await expect(guestPage.getByText(`登录接口 500 ${suffix}`)).toBeVisible();
    await guestPage.getByPlaceholder('请填写修复说明').fill('已经修复登录接口异常处理逻辑，修复版本 v1.2.3。');
    await guestPage.getByRole('button', { name: '已解决' }).click();
    await guestPage.getByRole('button', { name: '确认已解决' }).click();
    await expect(guestPage.locator('header').getByText('当前状态：已修复')).toBeVisible();
    await guest.close();
    await page.reload();
    await expect(page.getByText('已经修复登录接口异常处理逻辑')).toBeVisible();
    await page.getByRole('button', { name: '验证通过，关闭缺陷' }).click();
    await expect(page.getByText('缺陷已更新')).toBeVisible();
    expect(received.length).toBeGreaterThan(0);
    expect(received.join('')).toContain('/public/defects/share/');
  } finally {
    await new Promise<void>((resolve, reject) => hook.close((error) => error ? reject(error) : resolve()));
  }
});
