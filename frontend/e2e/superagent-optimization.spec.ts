import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test';

const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8101/api/v1';
const USER = process.env.E2E_ADMIN_USERNAME ?? 'e2e-admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';
const STUB = process.env.E2E_STUB_URL ?? 'http://127.0.0.1:8799';
const VIEWPORTS = [{ width: 1440, height: 900 }, { width: 390, height: 844 }];
const API_TOOLS = ['test_asset.get_existing_cases', 'execution.get_test_run', 'execution.create_test_run', 'report.generate', 'report.review', 'api_catalog.search_api'];
type Named = { id: number; name: string };
type Version = { id: number; document_id: number; status: string };

async function login(page: Page, path: string) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(USER);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'));
  await page.goto(path);
}

async function adminApi() {
  const auth = await request.newContext({ baseURL: `${API}/` });
  const response = await auth.post('login', { data: { username: USER, password: PASSWORD } });
  expect(response.ok()).toBeTruthy();
  const { access_token: token } = await response.json();
  await auth.dispose();
  return request.newContext({ baseURL: `${API}/`, extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
}

async function json<T>(response: Pick<Awaited<ReturnType<APIRequestContext['get']>>, 'ok' | 'status' | 'url' | 'json' | 'text'>): Promise<T> {
  if (!response.ok()) throw new Error(`${response.status()} ${new URL(response.url()).pathname} ${(await response.text()).slice(0, 500)}`);
  return response.json() as Promise<T>;
}

async function select(page: Page, label: string, option: string) {
  await page.getByRole('combobox', { name: label, exact: true })
    .locator('xpath=ancestor::div[contains(@class, "ant-select-selector")][1]').click();
  await page.locator('.ant-select-dropdown:visible').getByText(option, { exact: true }).click();
}

async function screenshot(page: Page, name: string) {
  const directory = process.env.E2E_SUPERAGENT_SCREENSHOTS ?? test.info().outputPath('screenshots');
  mkdirSync(directory, { recursive: true });
  const viewport = page.viewportSize()!;
  await page.screenshot({ path: join(directory, `${name}-${viewport.width}x${viewport.height}.png`), animations: 'disabled' });
}

async function createAgent(api: APIRequestContext, name: string, options: Record<string, unknown> = {}) {
  return json<Named>(await api.post('agent-governance/agents', { data: {
    name, workflow_template: 'api_test', is_enabled: true, instruction: '在项目授权范围内分析。', ...options,
  } }));
}

async function seedKnowledge(api: APIRequestContext, name: string) {
  const project = await json<Named>(await api.post('projects', { data: { name } }));
  const root = `projects/${project.id}`;
  const base = await json<Named>(await api.post(`${root}/knowledge-bases`, { data: { name: '隔离退款资料' } }));
  const upload = async (name: string, text: string, documentId?: number) => json<Version>(await api.post(
    `${root}/knowledge-bases/${base.id}/documents`,
    { multipart: { file: { name, mimeType: 'text/plain', buffer: Buffer.from(text) },
      ...(documentId ? { document_id: String(documentId) } : {}) } },
  ));
  const old = await upload('退款渠道 A.txt', '退款 SLA 旧版为七天。');
  const current = await upload('退款渠道 A.txt', '退款 SLA 新版为两天。', old.document_id);
  const other = await upload('退款渠道 B.txt', '退款 SLA 由渠道 B 单独审批。');
  await expect.poll(async () => {
    const versions = await json<{ items: Version[] }>(await api.get(`${root}/knowledge-documents/${old.document_id}/versions`));
    return versions.items.find((version) => version.id === current.id)?.status;
  }).toBe('READY');
  return { project, current, other };
}

for (const viewport of VIEWPORTS) {
  test(`知识范围、试搜和文档版本 ${viewport.width}×${viewport.height}`, async ({ page }) => {
    const api = await adminApi();
    const { project, current, other } = await seedKnowledge(api, `SuperAgent 隔离退款 ${viewport.width}`);
    const agents = await json<Named[]>(await api.get(`projects/${project.id}/knowledge-agent-options`));
    const agent = agents[0];
    await page.setViewportSize(viewport);
    await login(page, '/admin/knowledge');
    await select(page, '项目', project.name);
    await select(page, '配置 Agent', agent.name);
    await page.getByText('限定 Agent 范围', { exact: true }).click();
    await select(page, '授权知识库', '隔离退款资料');
    await page.getByRole('checkbox', { name: '退款渠道 A.txt' }).check();
    const saved = page.waitForResponse((response) => response.url().endsWith(`/agents/${agent.id}/knowledge-binding`)
      && response.request().method() === 'PUT');
    await page.getByRole('button', { name: '保存 Agent 范围' }).click();
    const binding = await json<{ access_mode: string; scopes: { document_ids: number[] }[] }>(await saved);
    expect(binding.access_mode).toBe('AGENT_SCOPED');
    expect(binding.scopes[0].document_ids).toEqual([current.document_id]);
    await expect(page.getByRole('checkbox', { name: '退款渠道 A.txt' })).toBeChecked();
    await screenshot(page, '01-agent-scope');

    await page.getByText('指定 Agent', { exact: true }).click();
    const query = page.getByRole('textbox', { name: '检索问题' });
    await query.fill('退款 SLA');
    await page.getByRole('button', { name: '检索', exact: true }).click();
    await expect(page.getByText(`版本 ID ${current.id}`, { exact: false })).toBeVisible();
    await expect(page.getByText('退款 SLA 新版为两天。', { exact: true })).toBeVisible();
    await expect(page.getByText('退款 SLA 由渠道 B 单独审批。')).toHaveCount(0);
    await page.getByText('退款 SLA 新版为两天。', { exact: true }).evaluate((el) => el.scrollIntoView({ block: 'center' }));
    await screenshot(page, '02-agent-search');
    await page.getByRole('button', { name: '查看来源', exact: true }).click();
    const detail = page.getByRole('dialog', { name: '片段来源' });
    await expect(detail.getByText(`退款渠道 A.txt · v2 · 版本 ID ${current.id}`, { exact: true })).toBeVisible();
    await expect(detail.getByText('退款 SLA 新版为两天。', { exact: true })).toBeVisible();
    await screenshot(page, '03-document-source');
    await detail.getByRole('button', { name: '关闭' }).click();

    await page.getByText('项目范围', { exact: true }).click();
    await page.getByRole('button', { name: '检索', exact: true }).click();
    await expect(page.getByText(`版本 ID ${other.id}`, { exact: false })).toBeVisible();
    await expect(page.getByText('退款 SLA 由渠道 B 单独审批。')).toBeVisible();
    await page.getByText('退款 SLA 由渠道 B 单独审批。').evaluate((el) => el.scrollIntoView({ block: 'center' }));
    await screenshot(page, '04-project-search');

    await query.fill('???');
    await query.press('Enter');
    await expect(page.getByText('当前范围未找到匹配片段')).toBeVisible();
    await page.route('**/knowledge-search', (route) => route.abort('failed'), { times: 1 });
    await query.fill('退款 SLA');
    await query.press('Enter');
    await expect(page.getByText('检索失败，请重试')).toBeVisible();
    await query.press('Enter');
    await expect(page.getByText('退款 SLA 由渠道 B 单独审批。')).toBeVisible();
    await page.getByRole('row').filter({ hasText: '退款渠道 A.txt' }).getByRole('button', { name: '查看版本 / 更新' }).click();
    await expect(page.getByText('fixed-window-1200-200-v2').first()).toBeVisible();
    await expect(page.getByText('解析队列 0 项', { exact: true })).toBeVisible();
    expect(await page.evaluate<number>('document.documentElement.scrollWidth')).toBeLessThanOrEqual(viewport.width + 1);
    await api.dispose();
  });
}

test('迟到的项目、Agent 和查询响应无法覆盖当前试搜', async ({ page }) => {
  const api = await adminApi();
  const { project } = await seedKnowledge(api, 'SuperAgent 迟到响应项目');
  const newProject = await json<Named>(await api.post('projects', { data: { name: 'SuperAgent 空项目' } }));
  const [firstAgent, secondAgent] = await json<Named[]>(await api.get(`projects/${project.id}/knowledge-agent-options`));
  await login(page, '/admin/knowledge');
  await select(page, '项目', project.name);
  const query = page.getByRole('textbox', { name: '检索问题' });
  const oldQuery = '退款 SLA';

  async function delayedSearch(change: () => Promise<void>) {
    let release!: () => void;
    let received!: () => void;
    let finished!: () => void;
    const delay = new Promise<void>((resolve) => { release = resolve; });
    const inFlight = new Promise<void>((resolve) => { received = resolve; });
    const returned = new Promise<void>((resolve) => { finished = resolve; });
    await page.route('**/knowledge-search', async (route) => {
      const response = await route.fetch();
      received();
      await delay;
      try { await route.fulfill({ response }); } catch { /* request cancelled by the page */ }
      finally { finished(); }
    }, { times: 1 });
    try {
      await query.fill(oldQuery);
      await query.press('Enter');
      await inFlight;
      await expect(page.getByText('检索中…')).toBeVisible();
      await change();
    } finally {
      release();
    }
    await returned;
    await expect(page.getByText('退款 SLA 新版为两天。', { exact: true })).toHaveCount(0);
  }

  await delayedSearch(() => select(page, '项目', newProject.name));
  await select(page, '项目', project.name);
  await select(page, '配置 Agent', firstAgent.name);
  await page.getByText('指定 Agent', { exact: true }).click();
  await delayedSearch(() => select(page, '配置 Agent', secondAgent.name));
  await delayedSearch(async () => {
    await query.fill('没有这个答案');
    await query.press('Enter');
    await expect(page.getByText('当前范围未找到匹配片段')).toBeVisible();
  });
  await expect(page.getByText('本次问题：没有这个答案')).toBeVisible();
  await api.dispose();
});

for (const viewport of VIEWPORTS) {
  test(`质量页刷新和子 Agent 事件定位 ${viewport.width}×${viewport.height}`, async ({ page }) => {
    const api = await adminApi();
    const { project, current } = await seedKnowledge(api, `SuperAgent 质量隔离 ${viewport.width}`);
    const emptyProject = await json<Named>(await api.post('projects', { data: { name: `SuperAgent 质量空项目 ${viewport.width}` } }));
    const root = `projects/${project.id}`;
    const child = await createAgent(api, `退款分析子 Agent ${viewport.width}`);
    const parent = await createAgent(api, `退款规划主 Agent ${viewport.width}`, { child_agent_ids: [child.id], tool_keys: API_TOOLS });
    const env = await json<{ id: number; environment_id?: number }>(await api.post(`${root}/environments`, { data: {
      name: `superagent-fixture-${viewport.width}`, display_name: '隔离目标服务', base_url: STUB,
    } }));
    const endpoint = await json<{ id: number }>(await api.post(`${root}/apis`, { data: {
      name: '隔离退款接口', path: '/fixture/refund', method: 'GET', status: 'ACTIVE',
    } }));
    const asset = await json<{ id: number }>(await api.post(`${root}/test-cases`, { data: {
      name: '隔离退款计划用例', api_id: endpoint.id, target_type: 'API', status: 'ACTIVE',
    } }));
    await page.setViewportSize(viewport);
    await page.clock.setFixedTime(new Date(Date.now() - 300_000));
    await login(page, '/admin/agent-runtime');
    await select(page, '统计窗口', '最近 7 天');
    await select(page, '运行项目', project.name);
    await expect(page.getByText(`统计范围 · ${project.name}`)).toBeVisible();
    await expect(page.getByText('当前范围暂无异常运行')).toBeVisible();
    const initialCutoff = await page.getByText(/^统计截止 /).innerText();
    const title = `回归测试异常 ${viewport.width}`;
    const task = await json<{ id: number; latest_run: { id: number } }>(await api.post(`${root}/tasks`, { data: {
      title, goal: '核对退款原路返回 SLA [stub-fail-subagent]', agent_definition_id: parent.id,
      environment_id: env.environment_id ?? env.id, case_ids: [asset.id],
    } }));
    const runId = task.latest_run.id;
    await expect.poll(async () => {
      const detail = await json<{ run: { stage: string; error_code: string | null } }>(await api.get(`task-runs/${runId}`));
      return [detail.run.stage, detail.run.error_code];
    }, { timeout: 30_000 }).toEqual(['MODEL_RETRY', 'LLM_FALLBACK_EXHAUSTED']);
    await expect(page.getByText(title, { exact: true })).toHaveCount(0);
    await page.clock.setFixedTime(new Date(Date.now() + 2_000));
    const refreshed = page.waitForResponse((response) => response.url().includes('/agent-governance/runtime/overview'));
    await page.getByRole('button', { name: '刷新统计' }).click();
    const parameters = new URL((await refreshed).url()).searchParams;
    expect(parameters.get('project_id')).toBe(String(project.id));
    expect(Date.parse(parameters.get('to_at')!) - Date.parse(parameters.get('from_at')!)).toBe(7 * 24 * 3600 * 1000);
    await expect(page.getByText(/^统计截止 /)).not.toHaveText(initialCutoff);
    const failure = page.getByText(title, { exact: true });
    await expect(failure).toBeVisible();
    await select(page, '运行项目', emptyProject.name);
    await expect(page.getByText(`统计范围 · ${emptyProject.name}`)).toBeVisible();
    await expect(page.getByText('当前范围暂无异常运行')).toBeVisible();
    await expect(failure).toHaveCount(0);
    await select(page, '运行项目', project.name);
    await expect(failure).toBeVisible();
    await failure.scrollIntoViewIfNeeded();
    await screenshot(page, '05-quality-failure');
    const locator = page.getByRole('link', { name: new RegExp(`定位事件.*${child.name}`) });
    await expect(locator).toBeVisible();
    await locator.click();
    await expect(page).toHaveURL(new RegExp(`/console/tasks/${task.id}\\?runId=${runId}.*eventId=`));
    const event = page.locator('.ant-card').filter({ has: page.getByText('已定位的运行事件', { exact: true }) }).last();
    await expect(event.getByText('子 Agent 执行', { exact: true })).toBeVisible();
    await expect(event.getByText(`${child.name} · SUB_AGENT`, { exact: true })).toBeVisible();
    await screenshot(page, '06-focused-subagent');
    const retrieval = page.locator('.ant-list-item').filter({ hasText: '知识检索' }).filter({
      has: page.getByText(new RegExp(`版本.*\\b${current.id}\\b`)),
    }).first();
    await expect(retrieval).toBeVisible();
    await retrieval.scrollIntoViewIfNeeded();
    await screenshot(page, '07-run-retrieval');
    expect(await page.evaluate<number>('document.documentElement.scrollWidth')).toBeLessThanOrEqual(viewport.width + 1);
    await api.dispose();
  });

  test(`MCP 直接和经 Skill 依赖及有效配置 ${viewport.width}×${viewport.height}`, async ({ page }) => {
    const api = await adminApi();
    const project = await json<Named>(await api.post('projects', { data: { name: `SuperAgent 依赖隔离 ${viewport.width}` } }));
    const server = await json<Named>(await api.post('agent-governance/mcp-servers', { data: {
      name: `隔离只读 MCP ${viewport.width}`, endpoint: `${STUB}/mcp`, is_enabled: true,
    } }));
    const root = `agent-governance/mcp-servers/${server.id}`;
    const toolKey = `mcp:${server.id}:read_policy`;
    await page.setViewportSize(viewport);
    await login(page, '/admin/mcp');
    const serverCard = page.locator('.ant-card').filter({ has: page.getByText(server.name, { exact: true }) }).first();
    await serverCard.getByRole('button', { name: '连接并发现' }).click();
    const dialog = page.getByRole('dialog', { name: `${server.name} · MCP 详情` });
    await dialog.getByText('read_policy', { exact: true }).click();
    await expect(dialog.getByRole('checkbox', { name: 'read_policy' })).toBeChecked();
    const approval = page.waitForResponse((response) => response.url().endsWith('/approved-tools') && response.request().method() === 'PUT');
    await dialog.getByRole('button', { name: '保存审批清单' }).click();
    expect((await approval).ok()).toBeTruthy();
    await dialog.getByRole('button', { name: '关闭', exact: true }).last().click();
    const skill = await json<Named & { key: string }>(await api.post('agent-governance/skills', { data: {
      name: `退款规则 Skill ${viewport.width}`, content: '退款规则', files_json: { 'SKILL.md': '退款规则', 'notes.md': '合成附件' },
      mcp_tool_keys_json: [toolKey], is_enabled: true,
    } }));
    const agent = await createAgent(api, `隔离规则 Agent ${viewport.width}`, { skill_keys: [skill.key], tool_keys: API_TOOLS });
    async function openDependencies() {
      await page.goto('/admin/mcp');
      await serverCard.getByRole('button', { name: '工具清单' }).click();
      await dialog.getByRole('tab', { name: 'Agent 关联（1）' }).click();
      await expect(dialog.getByText(agent.name, { exact: true })).toBeVisible();
      await expect(dialog.getByText(`经 Skill ${skill.name} · v1`, { exact: true })).toBeVisible();
    }
    await openDependencies();
    await expect(dialog.getByText('当前可用', { exact: true })).toBeVisible();
    await expect(dialog.getByText('直接绑定', { exact: true })).toHaveCount(0);
    await json(await api.patch(`agent-governance/agents/${agent.id}`, { data: { tool_keys: [...API_TOOLS, toolKey] } }));
    await openDependencies();
    await expect(dialog.getByText('直接绑定', { exact: true })).toHaveCount(1);
    await screenshot(page, '08-mcp-dependencies');

    await page.goto('/admin/agents');
    await expect(page.getByText('主子关系', { exact: true })).toBeVisible();
    const node = page.getByText(agent.name, { exact: true }).locator('xpath=ancestor::span[contains(@class,"ant-tree-title")][1]');
    await node.getByRole('button', { name: '有效配置' }).click();
    const config = page.getByRole('dialog', { name: `${agent.name} · 有效配置` });
    await select(page, '有效配置项目', project.name);
    await expect(config.getByText('notes.md', { exact: true })).toBeVisible();
    await expect(config.getByText('E2E 桩模型 · e2e-stub-model', { exact: true })).toBeVisible();
    await expect(config.getByText('知识范围', { exact: true })).toBeVisible();
    await screenshot(page, '09-agent-effective-config');
    await json(await api.patch(root, { data: { is_enabled: false } }));
    await openDependencies();
    await expect(dialog.getByText('已配置 · 当前不可用', { exact: true })).toBeVisible();

    const child = await createAgent(api, `共享叶节点 ${viewport.width}`, { skill_keys: [skill.key] });
    const firstParent = await createAgent(api, `退款主节点甲 ${viewport.width}`, { tool_keys: API_TOOLS, child_agent_ids: [child.id] });
    const otherModel = await json<Named>(await api.post('model-configs', { data: {
      label: `隔离继承模型 ${viewport.width}`, provider: 'openai-compatible', api_base: `${STUB}/v1`,
      model_name: 'parent-path-model', api_key: 'e2e-dummy', is_enabled: true,
    } }));
    const secondParent = await createAgent(api, `退款主节点乙 ${viewport.width}`, {
      tool_keys: API_TOOLS, child_agent_ids: [child.id], model_config_id: otherModel.id,
      settings_json: { model_binding: 'agent' },
    });
    await json(await api.patch(root, { data: { is_enabled: true } }));
    await page.goto('/admin/mcp');
    await serverCard.getByRole('button', { name: '工具清单' }).click();
    await dialog.getByRole('tab', { name: 'Agent 关联（2）' }).click();
    for (const parent of [firstParent, secondParent]) {
      await expect(dialog.getByText(`经 ${parent.name} · 当前不可用`, { exact: true })).toBeVisible();
    }
    await page.goto('/admin/agents');
    await page.getByRole('searchbox', { name: '搜索 Agent' }).fill(child.name);
    await expect(page.getByText(child.name, { exact: true })).toHaveCount(2);
    await select(page, 'Agent 视图', '全部卡片');
    const secondPath = page.locator('.ant-space').filter({ has: page.getByText(`主 Agent · ${secondParent.name}`, { exact: true }) })
      .filter({ has: page.getByRole('button', { name: '有效配置', exact: true }) }).last();
    await secondPath.getByRole('button', { name: '有效配置', exact: true }).click();
    const childConfig = page.getByRole('dialog', { name: `${child.name} · 有效配置` });
    await select(page, '有效配置项目', project.name);
    await expect(childConfig.getByText(`${secondParent.name} → ${child.name}`, { exact: true })).toBeVisible();
    await expect(childConfig.getByText(`隔离继承模型 ${viewport.width} · parent-path-model`, { exact: true })).toBeVisible();
    await expect(childConfig.getByText('已配置 · 当前不可用', { exact: true })).toBeVisible();
    await api.dispose();
  });

  test(`环境目录可查看和编辑第 201 条 ${viewport.width}×${viewport.height}`, async ({ page }) => {
    const api = await adminApi();
    const url = 'environments?include_inactive=true';
    const listed = await json<{ total: number }>(await api.get(`${url}&page_size=1`));
    for (let start = listed.total; start < 201; start += 12) {
      await Promise.all(Array.from({ length: Math.min(12, 201 - start) }, async (_, offset) => {
        const number = start + offset + 1;
        await json(await api.post('environments', { data: { name: `superagent-catalog-${number}`, display_name: `隔离环境 ${number}` } }));
      }));
    }
    const boundary = await json<{ items: Named[]; total: number }>(await api.get(`${url}&page=2&page_size=200`));
    const target = boundary.items[0];
    await page.setViewportSize(viewport);
    await login(page, '/admin/environments');
    await page.getByRole('tab', { name: '平台环境类型' }).click();
    const catalog = page.getByRole('tabpanel', { name: '平台环境类型' });
    await expect(catalog.getByText(`共 ${boundary.total} 项`, { exact: true })).toBeVisible();
    await select(page, '环境每页条数', '200 条/页');
    await catalog.getByRole('row').nth(2).getByRole('checkbox').check();
    await expect(page.getByRole('button', { name: '批量删除（1）' })).toBeEnabled();
    await catalog.locator('.ant-pagination-item-2').click();
    await expect(page.getByRole('button', { name: '批量删除（0）' })).toBeDisabled();
    const row = catalog.getByRole('row').filter({ hasText: target.name });
    await row.getByRole('button', { name: '编辑', exact: true }).click();
    const modal = page.getByRole('dialog', { name: `编辑平台环境类型：${target.name}` });
    const label = `隔离第 201 条 · ${viewport.width}`;
    await modal.getByLabel('展示名称').fill(label);
    await modal.getByRole('button', { name: /确\s*定/ }).click();
    await expect(row.getByText(label, { exact: true })).toBeVisible();
    const edited = row.getByText(label, { exact: true });
    await edited.evaluate((el) => el.scrollIntoView({ block: 'nearest', inline: 'center' }));
    await expect(edited).toBeInViewport();
    await screenshot(page, '10-environment-page-201');
    await api.dispose();
  });
}
