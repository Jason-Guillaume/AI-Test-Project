import { mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
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

test('模型详情随修订、参数方案与默认策略刷新；诊断保留项目和计费确认', async ({ page }) => {
  test.setTimeout(90_000);
  const api = await request.newContext();
  const login = await api.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token as string;
  const adminApi = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const runId = Date.now();
  const projectName = `E2E 模型诊断项目 ${runId}`;
  const modelName = `E2E 模型详情 ${runId}`;
  const projectResponse = await adminApi.post(`${API}/projects`, { data: { name: projectName } });
  expect(projectResponse.status()).toBe(201);
  const modelResponse = await adminApi.post(`${API}/model-center/resources`, {
    data: {
      category: 'TEXT_GENERATION', visibility: 'PLATFORM', display_name: modelName,
      provider: 'synthetic-vendor', adapter_key: 'openai-compatible-chat', model_name: `synthetic-${runId}`,
      endpoint: 'https://models.example.invalid/v1/chat/completions', config: { timeout: 3 },
      capabilities: ['text_generation'], parameter_schema: [], enabled: true,
      initial_profile: { name: '初始方案', values: { temperature: 0 }, definitions: [] }, grant_project_ids: [],
    },
  });
  expect(modelResponse.status(), await modelResponse.text()).toBe(201);
  const resourceId = (await modelResponse.json()).id as number;
  const diagnosticRequests: string[] = [];
  page.on('request', (requestEvent) => {
    if (requestEvent.method() === 'POST' && requestEvent.url().includes(`/model-center/resources/${resourceId}/diagnostics`)) {
      diagnosticRequests.push(requestEvent.url());
    }
  });

  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginThroughUi(page);
    await page.evaluate(() => {
      localStorage.removeItem('console.current_project_id');
    });
    await page.goto('/admin/model-configs');
    const modelCard = page.locator('.ant-card').filter({ has: page.getByText(modelName, { exact: true }) }).last();
    const detailsButton = modelCard.getByRole('button', { name: '详情' });
    await detailsButton.focus();
    await page.keyboard.press('Enter');
    const drawer = page.locator('.ant-drawer').filter({ hasText: `模型详情：${modelName}` });
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText('修订 v1');

    await drawer.getByRole('button', { name: '新增连接修订' }).click();
    const revisionDialog = page.getByRole('dialog').filter({ hasText: `为「${modelName}」新增连接修订` });
    await revisionDialog.getByLabel('厂商模型 ID').fill(`synthetic-${runId}-v2`);
    await revisionDialog.getByLabel('服务地址').fill('https://models.example.invalid/v2/chat/completions');
    await revisionDialog.getByRole('button', { name: '保存配置' }).click();
    await expect(revisionDialog).toBeHidden();
    await expect(drawer).toContainText('修订 v2');
    const screenshot = resolve(process.cwd(), '../docs/second-round-quality-fix/screenshots/model-center-detail.png');
    mkdirSync(dirname(screenshot), { recursive: true });
    await page.screenshot({ path: screenshot, fullPage: true });

    await drawer.getByRole('button', { name: '参数方案' }).click();
    const profileDialog = page.getByRole('dialog').filter({ hasText: `为「${modelName}」新增参数方案版本` });
    const profileName = `E2E 调优方案 ${runId}`;
    await profileDialog.getByLabel('方案名称').fill(profileName);
    await profileDialog.getByRole('button', { name: '创建参数版本' }).click();
    await expect(profileDialog).toBeHidden();
    await drawer.getByRole('tab', { name: '参数方案' }).click();
    await expect(drawer.getByText(profileName, { exact: false })).toBeVisible();

    await drawer.getByRole('button', { name: '默认策略' }).click();
    const defaultDialog = page.getByRole('dialog').filter({ hasText: '设置用途默认策略' });
    await defaultDialog.getByRole('button', { name: '保存默认策略' }).click();
    await expect(defaultDialog).toBeHidden();
    await drawer.getByRole('tab', { name: '默认策略' }).click();
    await expect(drawer.getByText('TEXT_INFERENCE')).toBeVisible();

    await drawer.getByRole('button', { name: '连接诊断' }).click();
    const diagnosticDialog = page.getByRole('dialog').filter({ hasText: `诊断「${modelName}」` });
    await expect(diagnosticDialog).toBeVisible();
    await expect(diagnosticDialog).toContainText('诊断会真实调用所选模型，可能产生费用');
    await expect(diagnosticDialog.getByText(projectName)).toHaveCount(0);
    await diagnosticDialog.getByRole('button', { name: '开始后台诊断' }).click();
    await expect(diagnosticDialog.getByText('请选择诊断项目')).toBeVisible();
    await expect(diagnosticRequests).toHaveLength(0);

    const projectSelect = diagnosticDialog.getByRole('combobox').first();
    await projectSelect.click();
    await page.getByText(projectName, { exact: false }).last().click();
    await diagnosticDialog.getByRole('checkbox', { name: /我确认发起一次真实模型调用/ }).check();
    await expect(diagnosticDialog.getByRole('button', { name: '开始后台诊断' })).toBeEnabled();
    await expect(diagnosticRequests).toHaveLength(0);
    await page.keyboard.press('Escape');
    await expect(diagnosticDialog).toBeHidden();
    await expect(diagnosticRequests).toHaveLength(0);
  } finally {
    await adminApi.dispose();
    await api.dispose();
  }
});
