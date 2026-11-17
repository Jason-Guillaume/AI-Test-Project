// 缺陷管理前后端划分与结构化批量创建端到端验收。
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

test('缺陷管理支持前后端划分筛选与结构化批量创建', async ({ page }) => {
  test.skip(!PASSWORD, '需要 E2E_ADMIN_PASSWORD 才能登录隔离环境');

  const suffix = Date.now();
  const projectName = `E2E 缺陷前后端项目 ${suffix}`;
  const legacyTitle = `E2E 历史未划分 ${suffix}`;
  const singleFeTitle = `E2E 前端单条 ${suffix}`;
  const batchBeTitle = `E2E 后端批建 ${suffix}`;
  const batchFeTitle = `E2E 前端批建 ${suffix}`;
  const batchBothTitle = `E2E 前后端批建 ${suffix}`;

  const login = await request.newContext();
  const loginRes = await login.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(loginRes.ok()).toBeTruthy();
  const token = (await loginRes.json()).access_token as string;
  await login.dispose();

  const api = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const projRes = await api.post(`${API}/projects`, { data: { name: projectName } });
  expect(projRes.status()).toBe(201);
  const projectId = (await projRes.json()).id as number;

  // 预置一条未传 category 的历史存量缺陷，验证列表展示为「未划分」且可切到未划分页签查看。
  const legacyRes = await api.post(`${API}/bugs`, {
    data: { project_id: projectId, title: legacyTitle, severity: 2, status: '待确认' },
  });
  expect(legacyRes.status()).toBe(201);
  await api.dispose();

  await loginThroughUi(page);
  await page.goto('/console/defects');

  // 按项目过滤，确认历史缺陷显示「未划分」。
  await page.getByRole('main').locator('.ant-select').first().click();
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: projectName }).first().click();
  const legacyRow = page.getByRole('row').filter({ hasText: legacyTitle });
  await expect(legacyRow).toBeVisible();
  await expect(legacyRow).toContainText('未划分');

  // 1. 新建单条缺陷时强制选择前端/后端/前后端。
  await page.getByRole('button', { name: '新建缺陷' }).click();
  const createDialog = page.getByRole('dialog', { name: '新建缺陷' });
  await expect(createDialog).toBeVisible();
  await createDialog.getByPlaceholder('一句话描述问题').fill(singleFeTitle);
  await createDialog.getByRole('button', { name: /保\s*存/ }).click();
  await expect(createDialog).toContainText('请选择前后端划分');
  await createDialog.locator('.ant-radio-button-wrapper', { hasText: /^前端$/ }).click();
  await createDialog.getByRole('button', { name: /保\s*存/ }).click();
  await expect(createDialog).toBeHidden();
  await expect(page.getByRole('row').filter({ hasText: singleFeTitle })).toContainText('前端');

  // 2. 打开批量创建弹窗，验证多行文本拆分 + 表格逐字段编辑 + 整批原子拦截。
  await page.getByRole('button', { name: '批量创建' }).click();
  const batchDialog = page.getByRole('dialog', { name: '批量创建缺陷' });
  await expect(batchDialog).toBeVisible();

  await batchDialog.getByText(/粘贴多行文本快速拆分/).click();
  await batchDialog.getByLabel('多行文本快速拆分输入').fill(
    `${batchBeTitle} | 后端 | 严重 | 接口返回 500 | 1. 发起提交\\n2. 观察报错 | staging\n${batchFeTitle}\n${batchBothTitle} | 前后端 | 高 | 接口协议联调不一致 | 1. 提交保存 | test`,
  );
  await batchDialog.getByRole('button', { name: '拆分为下方表格行' }).click();

  await expect(batchDialog.getByLabel('第 1 行标题')).toHaveValue(batchBeTitle);
  await expect(batchDialog.getByLabel('第 2 行标题')).toHaveValue(batchFeTitle);
  await expect(batchDialog.getByLabel('第 3 行标题')).toHaveValue(batchBothTitle);

  // 为第 2 行在结构化表格中补充前后端划分与描述。
  await batchDialog.getByRole('combobox', { name: '第 2 行前后端划分' }).click();
  await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: /^前端$/ }).first().click();
  await batchDialog.getByLabel('第 2 行缺陷描述').fill('页面弹窗按钮对齐异常');

  // 添加一行空行直接提交，验证拦截第 4 行且不丢失前面行数据。
  await batchDialog.getByRole('button', { name: /添加一行/ }).click();
  await batchDialog.getByRole('button', { name: /确认批量创建/ }).click();
  await expect(batchDialog).toContainText('第 4 行：缺陷标题不能为空');
  await expect(batchDialog.getByLabel('第 1 行标题')).toHaveValue(batchBeTitle);

  // 删除第 4 行空行后再次确认提交，验证三条结构化缺陷成功入库。
  await batchDialog.getByRole('button', { name: '删除第 4 行' }).click();
  await batchDialog.getByRole('button', { name: /确认批量创建（3 条）/ }).click();
  await expect(batchDialog).toBeHidden();

  // 3. 验证前后端划分标签页筛选准确性。
  await page.getByRole('tab', { name: '后端缺陷', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: batchBeTitle })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: singleFeTitle })).toHaveCount(0);

  await page.getByRole('tab', { name: '前端缺陷', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: singleFeTitle })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: batchFeTitle })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: batchBeTitle })).toHaveCount(0);

  await page.getByRole('tab', { name: '前后端缺陷', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: batchBothTitle })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: batchBeTitle })).toHaveCount(0);
  await expect(page.getByRole('row').filter({ hasText: singleFeTitle })).toHaveCount(0);

  await page.getByRole('tab', { name: '未划分', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: legacyTitle })).toBeVisible();
  await expect(page.getByRole('row').filter({ hasText: batchBeTitle })).toHaveCount(0);
});
