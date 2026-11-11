// P6 真实后端与本地 LLM 桩：异步响应、刷新恢复、并行和协作取消。
import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test';

const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8101/api/v1';
const ADMIN = process.env.E2E_ADMIN_USERNAME ?? 'e2e-admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';
let api: APIRequestContext;
let project = 0;
let agent = 0;

/** 登录真实浏览器、恢复项目并打开已有生成工作台。 */
async function openWorkbench(page: Page, batchId: number) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(ADMIN);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'));
  await page.evaluate(({ project, batchId }) => {
    const user = JSON.parse(localStorage.getItem('user') ?? '{}');
    localStorage.setItem('console.current_project_id', String(project));
    localStorage.setItem('console.scope_user_id', String(user.id));
    localStorage.setItem(`generation-task:${user.id}:${project}:API`, String(batchId));
  }, { project, batchId });
  await page.goto('/console/test-cases');
  await page.getByText('P6范围').first().click();
  await page.getByRole('button', { name: '生成草稿' }).click();
  await expect(page.getByTestId('gen-task-progress')).toContainText(`任务 #`, { timeout: 20_000 });
}

/** 使用真实状态接口等待最终态，不假定固定模型执行时间。 */
async function waitStatus(batchId: number, status: string) {
  await expect.poll(async () => (await (await api.get(`case-generation-batches/${batchId}/task`)).json()).status,
    { timeout: 60_000, intervals: [100, 300, 500] }).toBe(status);
}

test.beforeAll(async () => {
  const login = await request.newContext();
  const response = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  const token = (await response.json()).access_token;
  await login.dispose();
  api = await request.newContext({ baseURL: `${API}/`, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  project = (await (await api.post('projects', { data: { name: `P6异步-${Date.now()}` } })).json()).id;
  expect((await api.post(`projects/${project}/test-scopes`, { data: { direction: 'API', node_type: 'FOLDER', name: 'P6范围' } })).ok()).toBeTruthy();
  agent = (await (await api.get(`projects/${project}/case-generation-agents`)).json())[0].id;
});

test.afterAll(async () => { await api?.dispose(); });

test('P6 HTTP立即返回、并发幂等、刷新恢复与模块并行', async ({ page }) => {
  const body = { agent_id: agent, direction: 'API', requirements: 'P6 [stub-delay-api-5] [stub-delay-security-5]',
    include_security: true, cases_per_module: 1, request_key: crypto.randomUUID() };
  const started = Date.now();
  const response = await api.post(`projects/${project}/case-generation-tasks`, { data: body });
  expect(response.status()).toBe(202);
  expect(Date.now() - started).toBeLessThan(2000);
  const batch = await response.json();
  expect(batch.task_id).toBeGreaterThan(0);
  const duplicate = await api.post(`projects/${project}/case-generation-tasks`, { data: body });
  expect((await duplicate.json()).id).toBe(batch.id);
  await openWorkbench(page, batch.id);
  await page.reload();
  await page.getByText('P6范围').first().click();
  await page.getByRole('button', { name: '生成草稿' }).click();
  await expect(page.getByTestId('gen-task-progress')).toBeVisible();
  await waitStatus(batch.id, 'COMPLETED');
  await expect(page.getByTestId('gen-task-module-review')).toContainText('SUCCEEDED', { timeout: 20_000 });
  const status = await (await api.get(`case-generation-batches/${batch.id}/task`)).json();
  const modules = status.modules.filter((item: { module: string }) => item.module !== 'review');
  expect(modules).toHaveLength(2);
  expect(Math.max(...modules.map((item: { started_at: string }) => Date.parse(item.started_at))))
    .toBeLessThan(Math.min(...modules.map((item: { finished_at: string }) => Date.parse(item.finished_at))));
  const result = await (await api.get(`case-generation-batches/${batch.id}`)).json();
  expect(result.drafts).toHaveLength(2);
  expect((await api.post(`case-drafts/${result.drafts[0].id}/accept`)).ok()).toBeTruthy();
  expect(status.events.some((item: { type: string }) => item.type === 'generation.finished')).toBeTruthy();
});

test('P6 运行中取消保留已完成草稿，刷新后取消状态可恢复', async ({ page }) => {
  const response = await api.post(`projects/${project}/case-generation-tasks`, { data: {
    agent_id: agent, direction: 'API', requirements: 'P6 取消 [stub-delay-security-8]', include_security: true,
    cases_per_module: 1, request_key: crypto.randomUUID(),
  } });
  expect(response.status()).toBe(202);
  const batch = await response.json();
  await expect.poll(async () => (await (await api.get(`case-generation-batches/${batch.id}`)).json()).drafts.length).toBe(1);
  await openWorkbench(page, batch.id);
  await page.getByTestId('gen-cancel').click();
  await waitStatus(batch.id, 'CANCELLED');
  const result = await (await api.get(`case-generation-batches/${batch.id}`)).json();
  expect(result.drafts.length).toBeGreaterThanOrEqual(1);
  await page.reload();
  await page.getByText('P6范围').first().click();
  await page.getByRole('button', { name: '生成草稿' }).click();
  await expect(page.getByText('已取消', { exact: true })).toBeVisible({ timeout: 20_000 });
});
