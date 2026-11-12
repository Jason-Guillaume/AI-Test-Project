// P6 真实后端与本地 LLM 桩：异步响应、刷新恢复、并行和协作取消。
import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test';

const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8101/api/v1';
const ADMIN = process.env.E2E_ADMIN_USERNAME ?? 'e2e-admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';
let api: APIRequestContext;
let project = 0;
let agent = 0;
let completedTaskId = 0;
let completedRunId = 0;

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
  completedTaskId = batch.task_id;
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
  completedRunId = status.run_id ?? batch.task_run_id;
  const modules = status.modules.filter((item: { module: string }) => item.module !== 'review');
  expect(modules).toHaveLength(2);
  expect(Math.max(...modules.map((item: { started_at: string }) => Date.parse(item.started_at))))
    .toBeLessThan(Math.min(...modules.map((item: { finished_at: string }) => Date.parse(item.finished_at))));
  const result = await (await api.get(`case-generation-batches/${batch.id}`)).json();
  expect(result.drafts).toHaveLength(2);
  expect((await api.post(`case-drafts/${result.drafts[0].id}/accept`)).ok()).toBeTruthy();
  expect(status.events.some((item: { type: string }) => item.type === 'generation.finished')).toBeTruthy();
});

test('Agent 会话刷新恢复、任务 Trace 与运行质量页面可查看', async ({ page }) => {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(ADMIN);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'));
  await page.evaluate(({ project }) => {
    const user = JSON.parse(localStorage.getItem('user') ?? '{}');
    localStorage.setItem('console.current_project_id', String(project));
    localStorage.setItem('console.scope_user_id', String(user.id));
  }, { project });

  await page.goto('/console/agent');
  await page.getByRole('button', { name: '显示会话' }).click();
  await page.getByRole('button', { name: '新建 Agent 会话' }).click();
  const input = page.getByPlaceholder('输入测试需求，例如：生成 /api/orders 接口的测试点');
  await input.fill('帮我设计测试');
  await page.getByRole('button', { name: '发送' }).click();
  await expect(page.getByText('请指定接口或业务流程目标。', { exact: true })).toBeVisible({ timeout: 30_000 });
  await input.fill('补充订单接口上下文');
  await page.getByRole('button', { name: '发送' }).click();
  const chat = page.locator('#agent-workspace-chat');
  await expect(chat.getByText('补充订单接口上下文', { exact: true })).toBeVisible();
  await page.reload();
  const restoredChat = page.locator('#agent-workspace-chat');
  await expect(restoredChat.getByText('帮我设计测试', { exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(restoredChat.getByText('补充订单接口上下文', { exact: true })).toBeVisible();
  await expect(restoredChat.getByText('请指定接口或业务流程目标。', { exact: true })).toHaveCount(2);
  await expect(restoredChat.getByText('请指定接口或业务流程目标。', { exact: true }).first()).toBeVisible();

  expect(completedTaskId).toBeGreaterThan(0);
  expect(completedRunId).toBeGreaterThan(0);
  await page.goto(`/console/tasks/${completedTaskId}?runId=${completedRunId}`);
  await page.getByRole('tab', { name: '运行记录' }).click();
  await expect(page.getByText(/Agent Trace ·/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/投影 (PENDING|SUCCEEDED|FAILED|RETRYING)/).first()).toBeVisible();

  await page.goto('/admin/agent-runtime');
  await expect(page.getByRole('heading', { name: 'Agent 运行质量' })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('模型 P50 / P95')).toBeVisible();
  await expect(page.getByText('统计口径与数据来源')).toBeVisible();
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
