import { expect, request, test, type Page } from '@playwright/test';

const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8101/api/v1';
const ADMIN = process.env.E2E_ADMIN_USERNAME ?? 'e2e-admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';

let token = '';
let projectId = 0;
let scopeName = '';
let caseNames: string[] = [];

async function loginThroughUi(page: Page) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(ADMIN);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'));
  await page.evaluate(({ pid }) => {
    const user = JSON.parse(localStorage.getItem('user') ?? '{}');
    localStorage.setItem('console.current_project_id', String(pid));
    localStorage.setItem('console.scope_user_id', String(user.id ?? ''));
  }, { pid: projectId });
}

async function selectAgentTableView(page: Page) {
  const view = page.getByRole('main').locator('.ant-select').filter({ hasText: '主子关系' });
  await view.locator('.ant-select-selector').click();
  const input = view.getByRole('combobox');
  await input.press('ArrowDown');
  await input.press('ArrowDown');
  await input.press('Enter');
  await expect(page.getByRole('button', { name: /批量删除/ })).toBeVisible();
  await expect(page.getByRole('table')).toBeVisible();
}

test('用例列表多选删除 → 项目回收站批量恢复 → 原用例列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  token = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const projectResponse = await api.post(`${API}/projects`, { data: { name: `E2E 生命周期项目 ${Date.now()}` } });
  expect(projectResponse.status()).toBe(201);
  projectId = (await projectResponse.json()).id as number;

  scopeName = `E2E 回收站范围 ${Date.now()}`;
  const scopeResponse = await api.post(`${API}/projects/${projectId}/test-scopes`, {
    data: { direction: 'API', node_type: 'FOLDER', name: scopeName },
  });
  expect(scopeResponse.status()).toBe(201);
  const scopeId = (await scopeResponse.json()).id as number;

  caseNames = [`E2E 生命周期用例 A ${Date.now()}`, `E2E 生命周期用例 B ${Date.now()}`];
  for (const name of caseNames) {
    const created = await api.post(`${API}/projects/${projectId}/test-cases`, { data: { name } });
    expect(created.status()).toBe(201);
    const caseId = (await created.json()).id as number;
    const linked = await api.put(`${API}/test-cases/${caseId}/scope-links`, { data: { scope_node_ids: [scopeId] } });
    expect(linked.ok()).toBeTruthy();
  }
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/console/test-cases');
  await page.getByText(scopeName).first().click();
  for (const name of caseNames) {
    await expect(page.getByRole('row').filter({ hasText: name })).toBeVisible();
    await page.getByRole('row').filter({ hasText: name }).getByRole('checkbox').check();
  }

  await page.getByRole('button', { name: '批量删除' }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('删除选中的 2 条测试用例');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  for (const name of caseNames) {
    await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);
  }

  await page.goto('/console/recycle-bin');
  for (const name of caseNames) {
    const row = page.getByRole('row').filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 2 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  for (const name of caseNames) {
    await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);
  }

  await page.goto('/console/test-cases');
  await page.getByText(scopeName).first().click();
  for (const name of caseNames) {
    await expect(page.getByRole('row').filter({ hasText: name })).toBeVisible();
  }
});

test('Agent 管理多选删除 → 管理回收站恢复 → 原 Agent 列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  const agentToken = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${agentToken}` } });
  const project = await api.post(`${API}/projects`, { data: { name: `E2E Agent 回收站项目 ${Date.now()}` } });
  expect(project.status()).toBe(201);
  projectId = (await project.json()).id as number;
  const agentName = `E2E 可恢复 Agent ${Date.now()}`;
  const created = await api.post(`${API}/agent-governance/agents`, {
    data: {
      name: agentName,
      description: 'lifecycle e2e',
      workflow_template: 'api_test',
      instruction: '只用于回收站流程验收。',
      skill_keys: [],
      tool_keys: [],
      child_agent_ids: [],
      is_enabled: false,
    },
  });
  expect(created.status()).toBe(201);
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/admin/agents');
  await selectAgentTableView(page);
  const row = page.getByRole('row').filter({ hasText: agentName });
  await expect(row).toBeVisible();
  await row.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量删除/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('将 1 个 Agent 移入回收站');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(row).toHaveCount(0);

  await page.goto('/admin/recycle-bin');
  const recycled = page.getByRole('row').filter({ hasText: agentName });
  await expect(recycled).toBeVisible();
  await recycled.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 1 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(recycled).toHaveCount(0);

  await page.goto('/admin/agents');
  await selectAgentTableView(page);
  await expect(page.getByRole('row').filter({ hasText: agentName })).toBeVisible();
});

test('Skill 管理多选删除 → 管理回收站恢复 → 原 Skill 列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  const skillToken = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${skillToken}` } });
  const skillName = `E2E 可恢复 Skill ${Date.now()}`;
  const created = await api.post(`${API}/agent-governance/skills`, {
    data: { name: skillName, content: '# E2E Skill\nOnly for lifecycle verification.', is_enabled: false },
  });
  expect(created.status()).toBe(201);
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/admin/skills');
  await expect(page.getByText(skillName, { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: `选择 Skill ${skillName}` }).check();
  await page.getByRole('button', { name: /批量删除/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('将 1 个 Skill 移入回收站');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(page.getByText(skillName, { exact: true })).toHaveCount(0);

  await page.goto('/admin/recycle-bin');
  const recycled = page.getByRole('row').filter({ hasText: skillName });
  await expect(recycled).toBeVisible();
  await recycled.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 1 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(recycled).toHaveCount(0);

  await page.goto('/admin/skills');
  await expect(page.getByText(skillName, { exact: true })).toBeVisible();
});

test('MCP 管理多选删除 → 管理回收站恢复 → 原 MCP 列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  const mcpToken = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${mcpToken}` } });
  const serverName = `E2E 可恢复 MCP ${Date.now()}`;
  const created = await api.post(`${API}/agent-governance/mcp-servers`, {
    data: {
      name: serverName,
      endpoint: 'https://mcp.example.test/mcp',
      auth_type: 'none',
      is_enabled: false,
    },
  });
  expect(created.status(), await created.text()).toBe(201);
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/admin/mcp');
  await expect(page.getByText(serverName, { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: `选择 MCP 服务 ${serverName}` }).check();
  await page.getByRole('button', { name: /批量删除/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('将 1 个 MCP 服务移入回收站');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(page.getByText(serverName, { exact: true })).toHaveCount(0);

  await page.goto('/admin/recycle-bin');
  const recycled = page.getByRole('row').filter({ hasText: serverName });
  await expect(recycled).toBeVisible();
  await recycled.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 1 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(recycled).toHaveCount(0);

  await page.goto('/admin/mcp');
  await expect(page.getByText(serverName, { exact: true })).toBeVisible();
});

test('业务流程列表多选删除 → 回收站批量恢复 → 原流程树', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  token = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const projectResponse = await api.post(`${API}/projects`, { data: { name: `E2E 业务回收站项目 ${Date.now()}` } });
  expect(projectResponse.status()).toBe(201);
  projectId = (await projectResponse.json()).id as number;
  const stamp = Date.now();
  const domainName = `E2E 业务域 ${stamp}`;
  const domainResponse = await api.post(`${API}/projects/${projectId}/business-domains`, {
    data: { name: domainName, status: 'ACTIVE', sort: 0 },
  });
  expect(domainResponse.status()).toBe(201);
  const domainId = (await domainResponse.json()).id as number;
  const flowNames = [`E2E 流程 A ${stamp}`, `E2E 流程 B ${stamp}`];
  for (const name of flowNames) {
    const flowResponse = await api.post(`${API}/projects/${projectId}/business-flows`, {
      data: { name, domain_id: domainId, status: 'DRAFT' },
    });
    expect(flowResponse.status()).toBe(201);
  }
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/console/business-management');
  await page.getByText(domainName, { exact: true }).click();
  for (const name of flowNames) {
    const flowName = page.getByText(name, { exact: true });
    await expect(flowName).toBeVisible();
    await flowName.locator('..').getByRole('checkbox').check();
  }

  await page.getByRole('button', { name: /批量删除流程/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('删除选中的 2 个业务流程');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  for (const name of flowNames) await expect(page.getByText(name, { exact: true })).toHaveCount(0);

  await page.goto('/console/recycle-bin');
  for (const name of flowNames) {
    const row = page.getByRole('row').filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 2 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  for (const name of flowNames) await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);

  await page.goto('/console/business-management');
  await page.getByText(domainName, { exact: true }).click();
  for (const name of flowNames) await expect(page.getByText(name, { exact: true })).toBeVisible();
});

test('缺陷列表多选删除 → 项目回收站批量恢复 → 原缺陷列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  token = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const projectName = `E2E 缺陷回收站项目 ${Date.now()}`;
  const projectResponse = await api.post(`${API}/projects`, { data: { name: projectName } });
  expect(projectResponse.status()).toBe(201);
  projectId = (await projectResponse.json()).id as number;
  const bugTitles = [`E2E 缺陷 A ${Date.now()}`, `E2E 缺陷 B ${Date.now()}`];
  for (const title of bugTitles) {
    const bug = await api.post(`${API}/bugs`, {
      data: { project_id: projectId, title, severity: 2, status: '待确认' },
    });
    expect(bug.status()).toBe(201);
  }
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/console/defects');
  await page.getByRole('main').locator('.ant-select').first().click();
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: projectName }).first().click();
  for (const title of bugTitles) {
    const row = page.getByRole('row').filter({ hasText: title });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }

  await page.getByRole('button', { name: /批量删除/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('删除选中的 2 个缺陷');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  for (const title of bugTitles) await expect(page.getByRole('row').filter({ hasText: title })).toHaveCount(0);

  await page.goto('/console/recycle-bin');
  for (const title of bugTitles) {
    const row = page.getByRole('row').filter({ hasText: title });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 2 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();

  await page.goto('/console/defects');
  await page.getByRole('main').locator('.ant-select').first().click();
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: projectName }).first().click();
  for (const title of bugTitles) await expect(page.getByRole('row').filter({ hasText: title })).toBeVisible();
});

test('Web 页面对象多选删除 → 回收站批量恢复 → 原页面对象列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  token = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const projectResponse = await api.post(`${API}/projects`, { data: { name: `E2E Web 对象回收站项目 ${Date.now()}` } });
  expect(projectResponse.status()).toBe(201);
  projectId = (await projectResponse.json()).id as number;
  const pageNames = [`E2E 页面 A ${Date.now()}`, `E2E 页面 B ${Date.now()}`];
  for (const name of pageNames) {
    const result = await api.post(`${API}/projects/${projectId}/web-pages`, { data: { name, path: '/', elements: [] } });
    expect(result.status()).toBe(201);
  }
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/console/web-ui');
  await page.getByRole('tab', { name: '页面对象' }).click();
  for (const name of pageNames) {
    const row = page.getByRole('row').filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('button', { name: /批量删除已选/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('删除选中的 2 个页面对象');
  await page.getByRole('button', { name: '删除并移入回收站' }).click();
  for (const name of pageNames) await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);

  await page.goto('/console/recycle-bin');
  for (const name of pageNames) {
    const row = page.getByRole('row').filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 2 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();

  await page.goto('/console/web-ui');
  await page.getByRole('tab', { name: '页面对象' }).click();
  for (const name of pageNames) await expect(page.getByRole('row').filter({ hasText: name })).toBeVisible();
});

test('测试策略多选删除 → 回收站批量恢复 → 原策略列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  token = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const projectResponse = await api.post(`${API}/projects`, { data: { name: `E2E 策略回收站项目 ${Date.now()}` } });
  expect(projectResponse.status()).toBe(201);
  projectId = (await projectResponse.json()).id as number;
  const strategyNames = [`E2E 策略 A ${Date.now()}`, `E2E 策略 B ${Date.now()}`];
  for (const name of strategyNames) {
    const result = await api.post(`${API}/projects/${projectId}/test-strategies`, { data: { name, category: 'FUNCTIONAL', enabled: true } });
    expect(result.status()).toBe(201);
  }
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/console/test-asset');
  await page.getByRole('tab', { name: /测试策略/ }).click();
  for (const name of strategyNames) {
    const row = page.getByRole('row').filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('button', { name: /批量删除已选/ }).click();
  await expect(page.getByRole('dialog')).toContainText('删除选中的 2 个测试策略');
  await page.getByRole('dialog').getByRole('button', { name: '删除并移入回收站' }).click();
  for (const name of strategyNames) await expect(page.getByRole('row').filter({ hasText: name })).toHaveCount(0);

  await page.goto('/console/recycle-bin');
  for (const name of strategyNames) {
    const row = page.getByRole('row').filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 2 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();

  await page.goto('/console/test-asset');
  await page.getByRole('tab', { name: /测试策略/ }).click();
  for (const name of strategyNames) await expect(page.getByRole('row').filter({ hasText: name })).toBeVisible();
});

test('测试数据资产与 Data Provider 多选删除 → 回收站批量恢复', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  token = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const stamp = Date.now();
  const projectResponse = await api.post(`${API}/projects`, { data: { name: `E2E 数据工厂回收站项目 ${stamp}` } });
  expect(projectResponse.status()).toBe(201);
  projectId = (await projectResponse.json()).id as number;
  const assetName = `E2E 测试数据资产 ${stamp}`;
  const assetResponse = await api.post(`${API}/projects/${projectId}/test-data-assets`, {
    data: { name: assetName, entity_type: 'USER', value_json: { email: `e2e-${stamp}@example.test` } },
  });
  expect(assetResponse.status()).toBe(201);
  const providerName = `E2E Data Provider ${stamp}`;
  const providerResponse = await api.post(`${API}/projects/${projectId}/data-providers`, {
    data: { name: providerName, provider_type: 'STATIC', config_json: { values: { source: 'e2e' } } },
  });
  expect(providerResponse.status()).toBe(201);
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/console/test-data');
  const assetRow = page.getByRole('row').filter({ hasText: assetName });
  await expect(assetRow).toBeVisible();
  await assetRow.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量删除已选/ }).click();
  await expect(page.getByRole('dialog')).toContainText('删除选中的 1 个测试数据资产');
  await page.getByRole('dialog').getByRole('button', { name: '删除并移入回收站' }).click();
  await expect(page.getByRole('row').filter({ hasText: assetName })).toHaveCount(0);
  await page.getByRole('dialog').getByRole('button', { name: '查看回收站' }).click();

  await page.goto('/console/test-data');
  await page.getByRole('tab', { name: '数据工厂' }).click();
  const providerRow = page.getByRole('row').filter({ hasText: providerName });
  await expect(providerRow).toBeVisible();
  await providerRow.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量删除已选/ }).click();
  await expect(page.getByRole('dialog')).toContainText('删除选中的 1 个 Data Provider');
  await page.getByRole('dialog').getByRole('button', { name: '删除并移入回收站' }).click();
  const providerReceipt = page.getByRole('dialog', { name: /批量删除完成：成功 1 个，失败 0 个/ });
  await expect(providerReceipt).toBeVisible();
  await providerReceipt.getByRole('button', { name: '查看回收站' }).click();
  for (const name of [assetName, providerName]) {
    const row = page.getByRole('row').filter({ hasText: name });
    await expect(row).toBeVisible();
    await row.getByRole('checkbox').check();
  }
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 2 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();

  await page.goto('/console/test-data');
  await expect(page.getByRole('row').filter({ hasText: assetName })).toBeVisible();
  await page.getByRole('tab', { name: '数据工厂' }).click();
  await expect(page.getByRole('row').filter({ hasText: providerName })).toBeVisible();
});

test('项目根资源批量删除 → 管理回收站恢复 → 原项目列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  const projectToken = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${projectToken}` } });
  const projectName = `E2E 可恢复项目 ${Date.now()}`;
  const created = await api.post(`${API}/projects`, { data: { name: projectName } });
  expect(created.status()).toBe(201);
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/admin/projects');
  await page.getByPlaceholder('按项目名搜索').fill(projectName);
  await page.getByPlaceholder('按项目名搜索').press('Enter');
  const projectRow = page.getByRole('row').filter({ hasText: projectName });
  await expect(projectRow).toBeVisible();
  await projectRow.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量删除/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('将 1 个项目移入回收站');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(projectRow).toHaveCount(0);

  await page.goto('/admin/recycle-bin');
  const recycled = page.getByRole('row').filter({ hasText: projectName });
  await expect(recycled).toBeVisible();
  await recycled.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 1 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(recycled).toHaveCount(0);

  await page.goto('/admin/projects');
  await page.getByPlaceholder('按项目名搜索').fill(projectName);
  await page.getByPlaceholder('按项目名搜索').press('Enter');
  await expect(page.getByRole('row').filter({ hasText: projectName })).toBeVisible();
});

test('MCP 服务批量删除 → 管理回收站恢复 → 原 MCP 列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  const mcpToken = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${mcpToken}` } });
  const name = `E2E 可恢复 MCP 服务 ${Date.now()}`;
  const created = await api.post(`${API}/agent-governance/mcp-servers`, {
    data: { name, endpoint: 'https://mcp.example.test/mcp', auth_type: 'none', is_enabled: false },
  });
  expect(created.status()).toBe(201);
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/admin/mcp');
  await expect(page.getByText(name, { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: `选择 MCP 服务 ${name}` }).check();
  await page.getByRole('button', { name: /批量删除/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('将 1 个 MCP 服务移入回收站');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(page.getByText(name, { exact: true })).toHaveCount(0);

  await page.goto('/admin/recycle-bin');
  const recycled = page.getByRole('row').filter({ hasText: name });
  await expect(recycled).toBeVisible();
  await recycled.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 1 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(recycled).toHaveCount(0);

  await page.goto('/admin/mcp');
  await expect(page.getByText(name, { exact: true })).toBeVisible();
});

test('用户管理批量删除 → 管理回收站恢复 → 原用户列表', async ({ page }) => {
  const login = await request.newContext();
  const loginResponse = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginResponse.ok()).toBeTruthy();
  const userToken = (await loginResponse.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${userToken}` } });
  const username = `E2E 可恢复用户 ${Date.now()}`;
  const created = await api.post(`${API}/users`, {
    data: { username, password: 'e2e-user-password', role: 'test', is_active: true },
  });
  expect(created.status(), await created.text()).toBe(201);
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/admin/users');
  const row = page.getByRole('row').filter({ hasText: username });
  await expect(row).toBeVisible();
  await row.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量删除/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('将选中的 1 个用户账号移入回收站');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(row).toHaveCount(0);

  await page.goto('/admin/recycle-bin');
  const recycled = page.getByRole('row').filter({ hasText: username });
  await expect(recycled).toBeVisible();
  await recycled.getByRole('checkbox').check();
  await page.getByRole('button', { name: /批量恢复/ }).click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('恢复选中的 1 条数据');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(recycled).toHaveCount(0);

  await page.goto('/admin/users');
  await expect(page.getByRole('row').filter({ hasText: username })).toBeVisible();
});
