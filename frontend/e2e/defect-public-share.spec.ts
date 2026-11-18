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

test('batch share sends one card and previews only its authorized attachments', async ({ browser }) => {
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
  const api = await request.newContext();
  let authenticated: Awaited<ReturnType<typeof request.newContext>> | undefined;
  let uiContext: Awaited<ReturnType<typeof browser.newContext>> | undefined;
  let guest: Awaited<ReturnType<typeof browser.newContext>> | undefined;
  try {
    const login = await api.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
    expect(login.ok()).toBeTruthy();
    const token = (await login.json()).access_token as string;
    authenticated = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
    const suffix = Date.now();
    const projectName = `批次分享项目 ${suffix}`;
    const project = await authenticated.post(`${API}/projects`, { data: { name: projectName } });
    expect(project.status()).toBe(201);
    const projectId = (await project.json()).id as number;
    const channel = await authenticated.post(`${API}/projects/${projectId}/notification-channels`, {
      data: { name: '批次研发群', webhook_url: `http://127.0.0.1:${port}/hook`, enabled: true },
    });
    expect(channel.status()).toBe(201);
    for (let index = 0; index < 11; index += 1) {
      const created = await authenticated.post(`${API}/bugs`, { data: {
        project_id: projectId,
        title: index === 10 ? `支付响应异常 ${suffix}` : `库存接口问题 ${suffix}-${index}`,
        category: '接口', severity: 4,
        expected_result: index === 10 ? '应返回 200\n并包含订单状态' : undefined,
        actual_result: index === 10 ? '实际返回 500' : undefined,
      } });
      expect(created.status()).toBe(201);
    }
    const firstPage = await authenticated.get(`${API}/bugs`, { params: { project_id: projectId, page: 1, page_size: 10 } });
    const secondPage = await authenticated.get(`${API}/bugs`, { params: { project_id: projectId, page: 2, page_size: 10 } });
    expect(firstPage.ok()).toBeTruthy();
    expect(secondPage.ok()).toBeTruthy();
    const firstItems = (await firstPage.json()).items as Array<{ id: number; title: string }>;
    const firstVisible = firstItems.find((item) => item.title.startsWith('支付响应异常'))!;
    const secondVisible = ((await secondPage.json()).items as Array<{ id: number; title: string }>)[0];
    expect(firstVisible).toBeTruthy();
    expect(secondVisible).toBeTruthy();
    const firstId = firstVisible.id;
    const uploaded = await authenticated.post(`${API}/bugs/${firstId}/attachments`, {
      multipart: { file: { name: 'evidence.txt', mimeType: 'text/plain', buffer: Buffer.from('safe evidence\nsecond line') } },
    });
    expect(uploaded.status()).toBe(201);

    uiContext = await browser.newContext();
    const uiPage = await uiContext.newPage();
    await loginThroughUi(uiPage);
    await uiPage.goto('/console/defects');
    await uiPage.locator('.console-toolbar .ant-select').first().click();
    await uiPage.getByText(projectName, { exact: true }).last().click();
    const firstRow = uiPage.getByRole('row').filter({ hasText: firstVisible.title });
    await expect(firstRow).toBeVisible();
    await firstRow.getByRole('checkbox').check();
    await uiPage.locator('.ant-pagination-next').click();
    const secondRow = uiPage.getByRole('row').filter({ hasText: secondVisible.title });
    await expect(secondRow).toBeVisible();
    await secondRow.getByRole('checkbox').check();
    await uiPage.getByRole('button', { name: '批量推送到飞书（2）' }).click();
    await uiPage.getByRole('dialog').getByRole('radio', { name: /批次研发群/ }).click();
    await uiPage.getByRole('button', { name: '确认推送' }).click();
    const shareUrl = await uiPage.getByLabel('批次分享链接').inputValue();
    expect(shareUrl).toContain('/public/defects/share/batch/');
    expect(received).toHaveLength(1);
    const card = JSON.parse(received[0]) as { card: { elements: Array<{ tag: string; actions?: unknown[] }> } };
    const actionRows = card.card.elements.filter((element) => element.tag === 'action');
    expect(actionRows).toHaveLength(1);
    expect(actionRows[0].actions).toHaveLength(1);

    await uiContext.close();
    guest = await browser.newContext();
    const guestPage = await guest.newPage();
    await guestPage.goto(shareUrl);
    await expect(guestPage.getByRole('heading', { name: new RegExp(firstVisible.title) })).toBeVisible();
    await expect(guestPage.getByText('应返回 200')).toBeVisible();
    await expect(guestPage.getByText('实际返回 500')).toBeVisible();
    await expect(guestPage.getByText('safe evidence')).toBeVisible();
    await guestPage.getByRole('button', { name: new RegExp(`^BUG-${secondVisible.id} `) }).click();
    await expect(guestPage.getByRole('heading', { name: new RegExp(secondVisible.title) })).toBeVisible();
    expect(await guestPage.locator('body').innerText()).not.toContain('safe evidence');
  } finally {
    await guest?.close();
    await uiContext?.close();
    await authenticated?.dispose();
    await api.dispose();
    await new Promise<void>((resolve, reject) => hook.close((error) => error ? reject(error) : resolve()));
  }
});
