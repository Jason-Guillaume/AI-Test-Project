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

test('Jenkins Queue trigger and asynchronous cancellation state are rendered from API responses', async ({ page }) => {
  test.setTimeout(90_000);
  const api = await request.newContext();
  const login = await api.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token as string;
  const authenticatedApi = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const suffix = Date.now();
  const projectResponse = await authenticatedApi.post(`${API}/projects`, {
    data: { name: `Jenkins Queue UI ${suffix}` },
  });
  expect(projectResponse.status()).toBe(201);
  const projectId = (await projectResponse.json()).id as number;
  const integrationResponse = await authenticatedApi.post(`${API}/projects/${projectId}/automation-integrations`, {
    data: {
      provider_type: 'JENKINS', name: `Jenkins UI ${suffix}`, jenkins_base_url: 'https://1.1.1.1/jenkins',
      jenkins_username: 'e2e-user', jenkins_api_token: 'e2e-token-value',
      callback_secret: 'e2e-callback-secret', default_timeout_seconds: 3600,
    },
  });
  expect(integrationResponse.status()).toBe(201);
  const integrationId = (await integrationResponse.json()).id as number;
  const automationResponse = await authenticatedApi.post(`${API}/projects/${projectId}/automation-projects`, {
    data: {
      integration_config_id: integrationId, name: `Jenkins suite ${suffix}`,
      repository_url: 'https://codeup.aliyun.com/e2e/repo.git', pipeline_id: 'folder/automation',
      default_branch: 'main', timeout_seconds: 3600, pipeline_params: { TEST_SUITE: 'smoke' },
    },
  });
  expect(automationResponse.status()).toBe(201);
  const automationProjectId = (await automationResponse.json()).id as number;

  let execution: {
    id: number; project_id: number; automation_project_id: number; automation_project_name: string;
    pipeline_id: string; pipeline_run_id: string | null; provider_type: string; queue_id: string | null;
    build_number: number | null; external_run_url: string; trigger_source: string; status: string;
    stop_requested: boolean; stop_reason: string | null; branch: string; environment_name: string;
    pytest_args: string; test_tags: string; test_scope: string; git_commit: string; external_status: string;
    log_excerpt: string; error_message: string; started_at: string | null; finished_at: string | null;
    duration_ms: number | null; notify_status: string; report_id: number | null; created_at: string;
  } = {
    id: 990001, project_id: projectId, automation_project_id: automationProjectId,
    automation_project_name: `Jenkins suite ${suffix}`, pipeline_id: 'folder/automation',
    pipeline_run_id: null, provider_type: 'JENKINS', queue_id: '735', build_number: null,
    external_run_url: '', trigger_source: 'MANUAL', status: 'PENDING', stop_requested: false,
    stop_reason: null, branch: 'main', environment_name: 'qa', pytest_args: '-q',
    test_tags: '', test_scope: '', git_commit: '', external_status: 'QUEUED',
    log_excerpt: '', error_message: '', started_at: null, finished_at: null, duration_ms: null,
    notify_status: 'WAITING', report_id: null, created_at: new Date().toISOString(),
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
  const user = await page.evaluate(() => JSON.parse(localStorage.getItem('user') ?? '{}')) as { id: number };
  await page.evaluate(({ currentProjectId, userId }) => {
    localStorage.setItem('console.current_project_id', String(currentProjectId));
    localStorage.setItem('console.scope_user_id', String(userId));
  }, { currentProjectId: projectId, userId: user.id });
  await page.goto('/console/automation-runs');
  await page.getByLabel('自动化项目').click();
  await page.getByText(`Jenkins suite ${suffix} / folder/automation`).click();
  await page.getByRole('button', { name: '执行' }).click();
  await expect(page.getByText('Jenkins', { exact: true }).first()).toBeVisible();
  await expect(page.getByText('735', { exact: true })).toBeVisible();
  expect(triggerCount).toBe(1);

  await page.getByRole('button', { name: '取消' }).click();
  await expect(page.getByText('已提交，等待 Jenkins 确认')).toBeVisible();
  await expect(page.getByRole('button', { name: '取消' })).toBeDisabled();
  await authenticatedApi.dispose();
  await api.dispose();
});
