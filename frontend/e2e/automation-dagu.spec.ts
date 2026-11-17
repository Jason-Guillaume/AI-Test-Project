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

test('Dagu trigger, run identity and asynchronous cancellation are rendered', async ({ page }) => {
  test.setTimeout(90_000);
  const api = await request.newContext();
  const login = await api.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token as string;
  const authenticatedApi = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const suffix = Date.now();
  const projectResponse = await authenticatedApi.post(`${API}/projects`, {
    data: { name: `Dagu UI ${suffix}` },
  });
  expect(projectResponse.status()).toBe(201);
  const projectId = (await projectResponse.json()).id as number;
  const integrationResponse = await authenticatedApi.post(`${API}/projects/${projectId}/automation-integrations`, {
    data: {
      provider_type: 'DAGU', name: `Dagu integration ${suffix}`,
      dagu_base_url: 'https://dagu.example.com', dagu_api_key: 'e2e-dagu-api-key',
      callback_secret: 'e2e-callback-secret', default_timeout_seconds: 3600,
    },
  });
  expect(integrationResponse.status()).toBe(201);
  const integrationId = (await integrationResponse.json()).id as number;
  const automationResponse = await authenticatedApi.post(`${API}/projects/${projectId}/automation-projects`, {
    data: {
      integration_config_id: integrationId, name: `Dagu pytest ${suffix}`,
      repository_url: 'https://codeup.aliyun.com/66cc480801205f48f8ba4715/testing/site-genius-test-backed.git',
      pipeline_id: 'automation-pytest-allure', default_branch: 'main', timeout_seconds: 3600,
    },
  });
  expect(automationResponse.status()).toBe(201);
  const automationProjectId = (await automationResponse.json()).id as number;

  let execution: { id: number; stop_requested: boolean; stop_reason: string | null; external_status: string; [key: string]: unknown } = {
    id: 990001, project_id: projectId, automation_project_id: automationProjectId,
    automation_project_name: `Dagu pytest ${suffix}`, pipeline_id: 'automation-pytest-allure',
    pipeline_run_id: 'automation-990001', provider_type: 'DAGU', external_run_url: '',
    trigger_source: 'MANUAL', status: 'PENDING', stop_requested: false, stop_reason: null,
    branch: 'main', environment_name: 'qa', pytest_args: '-q', test_tags: '', test_scope: '',
    git_commit: '', external_status: 'queued', log_excerpt: '', error_message: '',
    started_at: null, finished_at: null, duration_ms: null, notify_status: 'WAITING',
    report_id: null, created_at: new Date().toISOString(),
  };
  let triggerCount = 0;
  await page.route(`**/api/v1/automation-projects/${automationProjectId}/executions`, async (route) => {
    triggerCount += 1;
    await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(execution) });
  });
  await page.route(`**/api/v1/automation-executions/${execution.id}`, async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(execution) });
  });
  await page.route(`**/api/v1/automation-executions/${execution.id}/cancel`, async (route) => {
    execution = { ...execution, stop_requested: true, stop_reason: 'CANCELLED', external_status: 'STOP_REQUESTED' };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(execution) });
  });

  await loginThroughUi(page);
  const me = await authenticatedApi.get(`${API}/me`);
  expect(me.ok()).toBeTruthy();
  const userId = (await me.json()).id as number;
  await page.evaluate(({ currentProjectId, ownerId }) => {
    localStorage.setItem('console.current_project_id', String(currentProjectId));
    localStorage.setItem('console.scope_user_id', String(ownerId));
  }, { currentProjectId: projectId, ownerId: userId });
  await page.goto('/console/automation-runs');
  const projectSelect = page.getByRole('combobox', { name: '自动化项目' });
  await expect(projectSelect).toBeVisible();
  await projectSelect.click();
  await page.getByText(`Dagu pytest ${suffix} / automation-pytest-allure`, { exact: true }).click();
  const runButton = page.getByRole('button', { name: '执行自动化测试', exact: true });
  await expect(runButton).toBeEnabled();
  await runButton.click();
  await expect(page.getByText('Dagu', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('automation-990001', { exact: true })).toBeVisible();
  expect(triggerCount).toBe(1);

  const cancelButton = page.getByRole('button', { name: '取消执行', exact: true });
  await cancelButton.click();
  await expect(page.getByText('已请求取消')).toBeVisible();
  await expect(cancelButton).toBeDisabled();
  await authenticatedApi.dispose();
  await api.dispose();
});
