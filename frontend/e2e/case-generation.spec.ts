// 用例生成审核闭环 E2E：真实前后端 + 独立隔离库 + OpenAI 兼容 LLM 桩。
// 由 scripts/e2e_case_generation.sh 编排运行；数据库事实一律通过后端 API 复核。
import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test';
import { mkdirSync } from 'node:fs';

const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8101/api/v1';
const ADMIN = process.env.E2E_ADMIN_USERNAME ?? 'e2e-admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';
const SHOTS = 'e2e/artifacts/screenshots';

// 主场景需求：含失败注入标记，安全模块首次生成失败、重新生成成功。
const REQUIREMENTS = 'E2E 登录功能：账号密码登录、错误密码锁定 [stub-fail-security]';

let token = '';
let projectId = 0;
let agentId = 0;
let batchId = 0;
let firstDraftId = 0;
let secondDraftId = 0;

async function apiLogin(username: string, password: string): Promise<string> {
  const ctx = await request.newContext({ baseURL: `${API}/` });
  // 注意：baseURL 含路径时，请求 URL 不能以 / 开头，否则会丢弃 /api/v1 前缀。
  const response = await ctx.post('login', { data: { username, password } });
  expect(response.ok(), `登录失败：${response.status()}`).toBeTruthy();
  const body = await response.json();
  await ctx.dispose();
  return body.access_token as string;
}

async function apiAs(authToken: string): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: `${API}/`, extraHTTPHeaders: { Authorization: `Bearer ${authToken}` } });
  const strip = (url: string) => url.replace(/^\/+/, '');
  return {
    get: (url: string, options?: object) => ctx.get(strip(url), options),
    post: (url: string, options?: object) => ctx.post(strip(url), options),
    dispose: () => ctx.dispose(),
  } as APIRequestContext;
}

/** 浏览器登录并选中项目作用域后进入用例中心。 */
async function enterCaseCenter(page: Page) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(ADMIN);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登\s*录|登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'), { timeout: 20_000 });
  // 直接写入项目作用域（与布局选择器等价，减少脆弱点击）。
  await page.evaluate(({ pid }) => {
    const user = JSON.parse(localStorage.getItem('user') ?? '{}');
    localStorage.setItem('console.current_project_id', String(pid));
    localStorage.setItem('console.scope_user_id', String(user.id ?? ''));
  }, { pid: projectId });
  await page.goto('/console/test-cases');
  await expect(page.getByText('E2E范围').first()).toBeVisible({ timeout: 20_000 });
}

/** 选择范围节点并打开生成抽屉。 */
async function openGenerationDrawer(page: Page) {
  await page.getByText('E2E范围').first().click();
  await page.getByRole('button', { name: '生成草稿' }).click();
  await expect(page.getByTestId('gen-submit')).toBeVisible();
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  mkdirSync(SHOTS, { recursive: true });
  token = await apiLogin(ADMIN, PASSWORD);
  const api = await apiAs(token);
  const project = await api.post('/projects', { data: { name: `E2E闭环项目-${Date.now()}`, description: 'e2e' } });
  expect(project.status()).toBe(201);
  projectId = (await project.json()).id;
  const scope = await api.post(`/projects/${projectId}/test-scopes`, {
    data: { direction: 'API', node_type: 'FOLDER', name: 'E2E范围' },
  });
  expect(scope.status()).toBe(201);
  const agents = await api.get(`/projects/${projectId}/case-generation-agents`);
  expect(agents.ok()).toBeTruthy();
  const options = await agents.json();
  expect(options.length).toBeGreaterThan(0);
  agentId = options[0].id;
  await api.dispose();
});

test('01 创建生成批次：失败模块保留成功草稿并真实持久化', async ({ page }) => {
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.getByTestId('gen-agent-select').click();
  await page.locator('.ant-select-item').first().click();
  await page.getByTestId('gen-include-security').check();
  await page.getByTestId('gen-requirements').fill(REQUIREMENTS);
  await page.getByTestId('gen-submit').click();
  // 安全模块首次被桩注入失败；接口模块草稿正常生成。
  await expect(page.getByTestId('gen-module-error-security')).toBeVisible({ timeout: 60_000 });
  const api = await apiAs(token);
  const list = await api.get(`/projects/${projectId}/case-generation-batches`);
  const listBody = await list.json();
  expect(listBody.total).toBe(1);
  await expect.poll(async () => (await (await api.get(`/case-generation-batches/${listBody.items[0].id}`)).json()).status).toBe('PARTIAL_FAILED');
  batchId = listBody.items[0].id;
  const detail = await (await api.get(`/case-generation-batches/${batchId}`)).json();
  expect(detail.status).toBe('PARTIAL_FAILED');
  expect(detail.drafts.length).toBe(2);
  expect(detail.drafts.every((d: { module: string }) => d.module === 'api')).toBeTruthy();
  expect(detail.module_errors.some((e: { module: string; status: string }) => e.module === 'security' && e.status === 'FAILED')).toBeTruthy();
  expect(detail.review_summary).toContain('E2E 审阅');
  firstDraftId = detail.drafts[0].id;
  secondDraftId = detail.drafts[1].id;
  await page.screenshot({ path: `${SHOTS}/01-batch-partial-failed.png`, fullPage: true });
  await api.dispose();
});

test('02 刷新后历史批次与草稿恢复', async ({ page }) => {
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.reload();
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await expect(page.getByTestId(`gen-batch-open-${batchId}`)).toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: `${SHOTS}/02-batch-history.png`, fullPage: true });
  await page.getByTestId(`gen-batch-open-${batchId}`).click();
  await expect(page.getByTestId(`gen-draft-${firstDraftId}`)).toBeVisible({ timeout: 20_000 });
});

test('03 编辑草稿并同步到数据库', async ({ page }) => {
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batchId}`).click();
  await page.getByTestId(`gen-draft-edit-${firstDraftId}`).click();
  const modal = page.locator('.ant-modal:has-text("编辑草稿")');
  const newTitle = `E2E 编辑后的标题 ${Date.now()}`;
  await modal.locator('input').first().fill(newTitle);
  await page.getByTestId('gen-edit-save').click();
  await expect(page.getByTestId(`gen-draft-${firstDraftId}`)).toContainText(newTitle, { timeout: 20_000 });
  const api = await apiAs(token);
  const detail = await (await api.get(`/case-generation-batches/${batchId}`)).json();
  const draft = detail.drafts.find((d: { id: number }) => d.id === firstDraftId);
  expect(draft.title).toBe(newTitle);
  expect(draft.payload.title).toBe(newTitle);
  // 原始 AI 内容不随编辑变化。
  expect(draft.original_payload.title).not.toBe(newTitle);
  await api.dispose();
});

test('04 单条接受入库：TestCase 为 DRAFT 且重复接受幂等', async ({ page }) => {
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batchId}`).click();
  await page.getByTestId(`gen-draft-accept-${firstDraftId}`).click();
  await page.locator('.ant-popconfirm .ant-btn-primary').click();
  await expect(page.getByTestId(`gen-draft-status-${firstDraftId}`)).toHaveText('已入库', { timeout: 20_000 });
  const api = await apiAs(token);
  const detail = await (await api.get(`/case-generation-batches/${batchId}`)).json();
  const draft = detail.drafts.find((d: { id: number }) => d.id === firstDraftId);
  expect(draft.status).toBe('ACCEPTED');
  expect(draft.test_case_id).toBeGreaterThan(0);
  const caseDetail = await (await api.get(`/test-cases/${draft.test_case_id}`)).json();
  expect(caseDetail.status).toBe('DRAFT');
  expect(caseDetail.source_type).toBe('AI');
  // 重复接受返回同一用例，不产生重复资产。
  const again = await api.post(`/case-drafts/${firstDraftId}/accept`);
  expect(again.ok()).toBeTruthy();
  expect((await again.json()).test_case_id).toBe(draft.test_case_id);
  await page.screenshot({ path: `${SHOTS}/04-draft-accepted.png`, fullPage: true });
  await api.dispose();
});

test('05 项目内重名入库返回 409 并标明原因', async ({ page }) => {
  const api = await apiAs(token);
  const detail = await (await api.get(`/case-generation-batches/${batchId}`)).json();
  const draft = detail.drafts.find((d: { id: number }) => d.id === secondDraftId);
  const created = await api.post(`/projects/${projectId}/test-cases`, { data: { name: draft.title } });
  expect(created.status()).toBe(201);
  const conflicted = await api.post(`/case-drafts/${secondDraftId}/accept`);
  expect(conflicted.status()).toBe(409);
  expect(JSON.stringify(await conflicted.json())).toContain('同名');
  // 页面可见入库失败原因，草稿仍为待审核。
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batchId}`).click();
  await expect(page.getByTestId(`gen-import-error-${secondDraftId}`)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByTestId(`gen-draft-status-${secondDraftId}`)).toHaveText('待审核');
  await page.screenshot({ path: `${SHOTS}/05-import-conflict.png`, fullPage: true });
  await api.dispose();
});

test('06 拒绝附原因并可恢复待审核', async ({ page }) => {
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batchId}`).click();
  await page.getByTestId(`gen-draft-reject-${secondDraftId}`).click();
  await page.locator('.ant-modal-confirm textarea').fill('边界覆盖不足');
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
  await expect(page.getByTestId(`gen-draft-status-${secondDraftId}`)).toHaveText('已拒绝', { timeout: 20_000 });
  await expect(page.getByTestId(`gen-draft-${secondDraftId}`)).toContainText('边界覆盖不足');
  // 已拒绝不能再接受。
  const api = await apiAs(token);
  const acceptRejected = await api.post(`/case-drafts/${secondDraftId}/accept`);
  expect(acceptRejected.status()).toBe(400);
  await page.getByTestId(`gen-draft-reopen-${secondDraftId}`).click();
  await expect(page.getByTestId(`gen-draft-status-${secondDraftId}`)).toHaveText('待审核', { timeout: 20_000 });
  await api.dispose();
});

test('07 批量审核：二次确认、部分失败可见、重复执行不产生重复资产', async ({ page }) => {
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batchId}`).click();
  await page.getByTestId('gen-review-all-accept').click();
  await expect(page.locator('.ant-modal-confirm')).toContainText('将对 1 条待审核草稿', { timeout: 10_000 });
  await page.getByTestId('gen-batch-review-confirm').click();
  // 第二条草稿与 05 创建的手工用例重名，单条失败；批量操作不整体失败。
  await expect(page.locator('.ant-message')).toContainText('1 条失败', { timeout: 30_000 });
  const api = await apiAs(token);
  // 再次批量接受：无待审核草稿，受影响 0。
  const again = await api.post(`/case-generation-batches/${batchId}/review`, {
    data: { action: 'accept', scope: 'all', confirm: true },
  });
  expect((await again.json()).affected).toBe(0);
  // 无 confirm 直接拒绝。
  const denied = await api.post(`/case-generation-batches/${batchId}/review`, {
    data: { action: 'accept', scope: 'all' },
  });
  expect(denied.status()).toBe(400);
  await page.screenshot({ path: `${SHOTS}/07-batch-review.png`, fullPage: true });
  await api.dispose();
});

test('08 仅失败模块重新生成且不覆盖已审核草稿', async ({ page }) => {
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batchId}`).click();
  await page.getByTestId('gen-regenerate').click();
  await page.locator('.ant-popconfirm .ant-btn-primary').click();
  await expect(page.locator('.ant-message')).toContainText('失败模块已排队重试', { timeout: 20_000 });
  const waitApi = await apiAs(token);
  await expect.poll(async () => (await (await waitApi.get(`/case-generation-batches/${batchId}`)).json()).status, { timeout: 60_000 }).toBe('COMPLETED');
  await waitApi.dispose();
  await expect(page.getByTestId('gen-module-error-security')).toHaveCount(0, { timeout: 20_000 });
  const api = await apiAs(token);
  const detail = await (await api.get(`/case-generation-batches/${batchId}`)).json();
  expect(detail.status).toBe('COMPLETED');
  expect(detail.module_errors).toHaveLength(0);
  const securityDrafts = detail.drafts.filter((d: { module: string }) => d.module === 'security');
  expect(securityDrafts.length).toBe(2);
  // 已入库草稿保持 ACCEPTED 且 test_case_id 不变。
  const first = detail.drafts.find((d: { id: number }) => d.id === firstDraftId);
  expect(first.status).toBe('ACCEPTED');
  expect(first.test_case_id).toBeGreaterThan(0);
  await page.screenshot({ path: `${SHOTS}/08-regenerated.png`, fullPage: true });
  await api.dispose();
});

test('09 批次审计时间线完整', async ({ page }) => {
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batchId}`).click();
  await page.getByTestId('gen-audits').click();
  const panel = page.locator('.ant-collapse-content-active');
  await expect(panel).toContainText('创建批次', { timeout: 20_000 });
  await expect(panel).toContainText('编辑草稿');
  await expect(panel).toContainText('接受入库');
  await expect(panel).toContainText('拒绝');
  await expect(panel).toContainText('恢复待审核');
  await expect(panel).toContainText('批量审核');
  await expect(panel).toContainText('重新生成失败模块');
  await page.screenshot({ path: `${SHOTS}/09-audit-timeline.png`, fullPage: true });
});

test('10 并发接受同一草稿只入库一次', async () => {
  const api = await apiAs(token);
  const created = await api.post(`/projects/${projectId}/case-generation-batches`, {
    data: { agent_id: agentId, direction: 'API', requirements: 'E2E 并发接受场景', include_security: false, cases_per_module: 1 },
  });
  expect(created.ok()).toBeTruthy();
  const batch = await created.json();
  const draftId = batch.drafts[0].id;
  const [first, second] = await Promise.all([
    api.post(`/case-drafts/${draftId}/accept`),
    api.post(`/case-drafts/${draftId}/accept`),
  ]);
  expect(first.ok()).toBeTruthy();
  expect(second.ok()).toBeTruthy();
  const [firstBody, secondBody] = await Promise.all([first.json(), second.json()]);
  expect(firstBody.test_case_id).toBe(secondBody.test_case_id);
  // 项目内该标题的正式用例只有一条。
  const cases = await (await api.get(`/projects/${projectId}/test-scope-cases`, { params: { direction: 'API', keyword: batch.drafts[0].title, page_size: 50 } })).json();
  expect(cases.items.filter((item: { name: string }) => item.name === batch.drafts[0].title).length).toBe(1);
  await api.dispose();
});

test('11 入库请求中断不产生残留，恢复后可重试', async ({ page }) => {
  const api = await apiAs(token);
  const created = await api.post(`/projects/${projectId}/case-generation-batches`, {
    data: { agent_id: agentId, direction: 'API', requirements: 'E2E 网络中断场景', include_security: false, cases_per_module: 1 },
  });
  const batch = await created.json();
  const draftId = batch.drafts[0].id;
  await api.dispose();
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batch.id}`).click();
  // 中断入库请求：前端报错，草稿保持待审核。
  await page.route('**/case-drafts/*/accept', (route) => route.abort());
  await page.getByTestId(`gen-draft-accept-${draftId}`).click();
  await page.locator('.ant-popconfirm .ant-btn-primary').click();
  await expect(page.locator('.ant-message')).toContainText('入库失败', { timeout: 20_000 });
  await expect(page.getByTestId(`gen-draft-status-${draftId}`)).toHaveText('待审核');
  await page.unroute('**/case-drafts/*/accept');
  await page.getByTestId(`gen-draft-accept-${draftId}`).click();
  await page.locator('.ant-popconfirm .ant-btn-primary').click();
  await expect(page.getByTestId(`gen-draft-status-${draftId}`)).toHaveText('已入库', { timeout: 20_000 });
});

test('12 跨项目隔离与非法资源访问', async () => {
  const outsider = `e2e-outsider-${Date.now()}`;
  const api = await apiAs(token);
  const registered = await api.post('/register', { data: { username: outsider, password: 'e2e-pass-123456' } });
  expect(registered.status()).toBe(201);
  const outsiderToken = await apiLogin(outsider, 'e2e-pass-123456');
  const outside = await apiAs(outsiderToken);
  expect((await outside.get(`/case-generation-batches/${batchId}`)).status()).toBe(404);
  expect((await outside.get(`/case-generation-batches/${batchId}/audits`)).status()).toBe(404);
  const accepted = await outside.post(`/case-drafts/${firstDraftId}/accept`);
  expect([403, 404]).toContain(accepted.status());
  expect((await api.get('/case-generation-batches/99999999')).status()).toBe(404);
  const denied = await outside.post(`/case-generation-batches/${batchId}/review`, {
    data: { action: 'accept', scope: 'all', confirm: true },
  });
  expect([403, 404]).toContain(denied.status());
  await api.dispose();
  await outside.dispose();
});

test('13 与正式用例重名的草稿给出疑似重复质量提示', async ({ page }) => {
  // 与 01 相同的需求：桩生成相同标题，而已入库用例占用这些标题。
  const api = await apiAs(token);
  const created = await api.post(`/projects/${projectId}/case-generation-batches`, {
    data: { agent_id: agentId, direction: 'API', requirements: REQUIREMENTS, include_security: false, cases_per_module: 1 },
  });
  expect(created.ok()).toBeTruthy();
  const batch = await created.json();
  const flagged = batch.drafts.filter((d: { quality: { rule: string }[] }) =>
    d.quality.some((issue) => issue.rule === 'TITLE_SIMILAR_TO_EXISTING'));
  expect(flagged.length).toBeGreaterThan(0);
  await api.dispose();
  await enterCaseCenter(page);
  await openGenerationDrawer(page);
  await page.locator('.ant-tabs-tab:has-text("历史批次")').click();
  await page.getByTestId(`gen-batch-open-${batch.id}`).click();
  await expect(page.getByText('疑似重复').first()).toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: `${SHOTS}/13-quality-flags.png`, fullPage: true });
});
