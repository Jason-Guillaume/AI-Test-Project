// 接口管理选择、批量删除与全项目序号验收场景。
//
// 通过真实登录与 API 在隔离项目内构造父子模块、跨页接口、筛选接口和带业务关联的
// 未分类接口，再用浏览器核对勾选尺寸、跨页编号、末页删空回退、部分失败回执和窄屏抽屉。
import { expect, test, type Page } from '@playwright/test';

const ADMIN = process.env.E2E_ADMIN_USERNAME ?? 'admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';
const RUN_ID = `${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;

type ApiEnvelope<T> = { data?: T } & T;

/** 通过登录页获取 HttpOnly Cookie，后续 page.request 与页面请求共享登录态。 */
async function loginThroughUi(page: Page) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(ADMIN);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'));
}

/** 调用后端接口并断言成功；统一解包 {code,message,data} 信封。 */
async function api<T = unknown>(page: Page, method: string, path: string, body?: unknown): Promise<T> {
  const response = await page.request.fetch(`/api/v1${path}`, {
    method,
    data: body as object | undefined,
    // Cookie 写请求必须携带受信任 Origin，与浏览器 axios 行为一致。
    headers: { origin: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5174' },
  });
  const payload = (await response.json().catch(() => ({}))) as ApiEnvelope<T>;
  expect(response.ok(), `${method} ${path} 失败：${response.status()} ${JSON.stringify(payload)}`).toBeTruthy();
  return (payload.data ?? payload) as T;
}

/** 把新建的隔离项目写入控制台作用域，刷新后接口管理直接进入该项目。 */
async function selectProject(page: Page, projectId: number) {
  await page.goto('/console');
  await page.evaluate((id) => {
    const rawUser = localStorage.getItem('user');
    const userId = rawUser ? (JSON.parse(rawUser) as { id?: number }).id : undefined;
    localStorage.setItem('console.current_project_id', String(id));
    if (userId) localStorage.setItem('console.scope_user_id', String(userId));
  }, projectId);
  await page.goto('/console/api-catalog');
}

/** 读取当前接口表序号列（第二列，第一列是行选择）。 */
async function readSequences(page: Page): Promise<string[]> {
  const cells = page.locator('.api-module-interfaces .ant-table-tbody tr.ant-table-row td:nth-child(2)');
  await expect(cells.first()).toBeVisible();
  return (await cells.allTextContents()).map((text) => text.trim());
}

/** 点击分页页码并等待目标页序号列首项变化。 */
async function gotoPage(page: Page, target: number) {
  await page.locator('.api-module-interfaces .ant-pagination-item').filter({ hasText: new RegExp(`^${target}$`) }).click();
  await expect(page.locator('.api-module-interfaces .ant-pagination-item-active')).toHaveText(String(target));
}

test('接口目录选择、批量删除与序号跨页验收', async ({ page }) => {
  test.setTimeout(240_000);
  expect(PASSWORD, '需要 E2E_ADMIN_PASSWORD 才能执行浏览器验收').toBeTruthy();
  await loginThroughUi(page);

  // ---- 隔离数据：项目、模块与接口 ----
  const project = await api<{ id: number }>(page, 'POST', '/projects', {
    name: `序号验收-${RUN_ID}`,
    description: '接口管理选择与序号验收隔离项目',
  });
  const projectId = project.id;

  const pageParent = await api<{ id: number }>(page, 'POST', `/projects/${projectId}/api-modules`, {
    name: '分页父模块',
  });
  const pageModule = await api<{ id: number }>(page, 'POST', `/projects/${projectId}/api-modules`, {
    name: '分页序号模块',
    parent_id: pageParent.id,
  });
  const relationModule = await api<{ id: number }>(page, 'POST', `/projects/${projectId}/api-modules`, {
    name: '关联目标模块',
  });
  const deleteParent = await api<{ id: number }>(page, 'POST', `/projects/${projectId}/api-modules`, {
    name: '模块删除父',
  });
  const deleteChild = await api<{ id: number }>(page, 'POST', `/projects/${projectId}/api-modules`, {
    name: '模块删除子',
    parent_id: deleteParent.id,
  });

  const createApi = (name: string, path: string, moduleId?: number) =>
    api<{ id: number }>(page, 'POST', `/projects/${projectId}/apis`, {
      module_id: moduleId ?? null,
      name,
      method: 'GET',
      path,
      status: 'ACTIVE',
    });

  const pagedApis: { id: number }[] = [];
  for (let index = 1; index <= 19; index += 1) {
    const suffix = String(index).padStart(2, '0');
    const path = index === 19
      ? `/seq/${RUN_ID}/very/long/${'segment/'.repeat(12)}${index}`
      : `/seq/${RUN_ID}/${index}`;
    pagedApis.push(await createApi(`分页序号 ${suffix}`, path, pageModule.id));
  }
  for (const label of ['甲', '乙', '丙', '丁']) {
    await createApi(`筛选组${label}`, `/filter/${RUN_ID}/${label}`, pageModule.id);
  }
  const relatedTarget = await createApi('关联目标接口', `/relation/${RUN_ID}/target`, relationModule.id);
  const partialFail = await createApi('部分失败甲', `/partial/${RUN_ID}/fail`);
  await createApi('部分失败乙', `/partial/${RUN_ID}/success`);
  await createApi('模块删除接口1', `/delete-module/${RUN_ID}/1`, deleteChild.id);
  await createApi('模块删除接口2', `/delete-module/${RUN_ID}/2`, deleteChild.id);
  await api(page, 'POST', `/apis/${partialFail.id}/relations`, {
    source_api_id: partialFail.id,
    target_api_id: relatedTarget.id,
    relation_type: 'OUTPUT_INPUT',
  });

  await selectProject(page, projectId);
  await expect(page.locator('.api-catalog-page')).toBeVisible();

  // ---- 选择列固定在树最左，框体与点击区达到设计尺寸 ----
  const moduleCheckbox = page.getByRole('checkbox', { name: '选择模块 分页父模块' });
  await expect(moduleCheckbox).toBeVisible();
  const checkboxBox = await moduleCheckbox.boundingBox();
  const hitBox = await page.locator('.api-module-select-cell').filter({ has: page.getByRole('checkbox', { name: '选择模块 分页父模块' }) }).boundingBox();
  expect(checkboxBox?.width ?? 0).toBeGreaterThanOrEqual(20);
  expect(checkboxBox?.height ?? 0).toBeGreaterThanOrEqual(20);
  expect(hitBox?.width ?? 0).toBeGreaterThanOrEqual(36);
  expect(hitBox?.height ?? 0).toBeGreaterThanOrEqual(36);

  // 键盘可单独勾选模块，不影响展开与打开列表。
  await moduleCheckbox.focus();
  await page.keyboard.press('Space');
  await expect(moduleCheckbox).toBeChecked();
  await page.keyboard.press('Space');
  await expect(moduleCheckbox).not.toBeChecked();

  // ---- 跨页序号：默认每页 20 条，23 条数据分两页 ----
  await page.getByRole('button', { name: '展开模块 分页父模块' }).click();
  await page.locator('button.api-module-open[title="分页序号模块"]').click();
  await expect(page.locator('.api-module-interfaces h4')).toContainText('分页序号模块');
  expect(await readSequences(page)).toEqual(Array.from({ length: 20 }, (_, index) => String(index + 1)));

  // 长路径保留全文提示与复制入口。
  const longPath = page.locator('.api-module-interfaces .ant-table-tbody code').filter({ hasText: `/seq/${RUN_ID}/very/long/` });
  await expect(longPath).toHaveCount(1);
  await expect(longPath).toContainText(`/seq/${RUN_ID}/very/long/`);
  await expect(
    page.locator('.api-module-interfaces .ant-table-tbody tr.ant-table-row').filter({ hasText: '分页序号 19' }).locator('.ant-typography-copy'),
  ).toHaveCount(1);

  await gotoPage(page, 2);
  expect(await readSequences(page)).toEqual(['21', '22', '23']);

  // 筛选后序号重新从 1 开始。
  await page.getByPlaceholder('按接口名或路径搜索').fill('筛选组');
  await page.getByPlaceholder('按接口名或路径搜索').press('Enter');
  expect(await readSequences(page)).toEqual(['1', '2', '3', '4']);
  await page.getByRole('button', { name: '重置' }).click();
  await expect(page.locator('.api-module-interfaces .ant-pagination-item-active')).toHaveText('1');
  await expect(page.locator('.api-module-interfaces .ant-table-tbody tr.ant-table-row')).toHaveCount(20);
  await gotoPage(page, 2);
  await expect(page.locator('.api-module-interfaces .ant-table-tbody tr.ant-table-row')).toHaveCount(3);

  // ---- 删空末页回到有效页并重排序号 ----
  await page.locator('.api-module-interfaces .ant-table-thead .ant-checkbox-input').check();
  await expect(page.getByText('已选 3 个接口')).toBeVisible();
  await page.getByRole('button', { name: '删除选中' }).click();
  await page.getByRole('button', { name: '删除 3 个' }).click();
  await expect(page.locator('.ant-modal-confirm-title').filter({ hasText: '已将 3 个接口移入回收站' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.ant-modal-confirm-success')).toBeHidden();
  await expect(page.locator('.api-module-interfaces .ant-pagination-item-active')).toHaveText('1');
  expect(await readSequences(page)).toEqual(Array.from({ length: 20 }, (_, index) => String(index + 1)));

  // 改变每页容量后序号按新页容量连续。
  await page.locator('.api-module-interfaces .ant-pagination-options .ant-select-selector').click();
  await page.locator('.ant-select-item-option').filter({ hasText: /^10 条\/页$/ }).click();
  expect(await readSequences(page)).toEqual(Array.from({ length: 10 }, (_, index) => String(index + 1)));
  await gotoPage(page, 2);
  expect(await readSequences(page)).toEqual(Array.from({ length: 10 }, (_, index) => String(index + 11)));

  // ---- 未分类在左树禁选，选择本页未分类接口明确放在右侧列表；部分失败保留失败项勾选 ----
  await expect(page.getByRole('checkbox', { name: '未分类模块不可删除' })).toBeDisabled();
  await page.locator('button.api-module-open[title="未分类"]').click();
  await expect(page.locator('.api-module-interfaces h4')).toContainText('未分类');
  await expect(page.locator('.api-module-interfaces .ant-table-tbody tr.ant-table-row')).toHaveCount(2);
  await page.locator('.api-module-interfaces').getByRole('checkbox', { name: '选择本页未分类接口' }).check();
  await expect(page.getByText('已选 2 个接口')).toBeVisible();
  await page.getByRole('button', { name: '删除选中' }).click();
  await page.getByRole('button', { name: '删除 2 个' }).click();
  await expect(page.locator('.ant-modal-confirm-title').filter({ hasText: '批量删除完成：成功 1 条，失败 1 条' })).toBeVisible();
  const receipt = page.locator('.ant-modal-confirm').filter({ hasText: '批量删除完成：成功 1 条，失败 1 条' });
  await expect(receipt.locator('.ant-modal-confirm-content')).toContainText('部分失败甲');
  await expect(receipt.locator('.ant-modal-confirm-content')).toContainText('业务关联');
  await page.screenshot({ path: 'e2e/artifacts/api-catalog-partial-failure.png', fullPage: true });
  await page.getByRole('button', { name: '关闭' }).click();
  const remainingPartial = page.locator('.api-module-interfaces .ant-table-tbody tr.ant-table-row');
  await expect(remainingPartial).toHaveCount(1);
  await expect(remainingPartial).toContainText('部分失败甲');
  await expect(remainingPartial.locator('.ant-checkbox-input')).toBeChecked();
  expect(await readSequences(page)).toEqual(['1']);

  // ---- 父子模块同时勾选：预览去重；取消后数据完整；再次删除生效 ----
  await page.getByRole('button', { name: '展开模块 模块删除父' }).click();
  const parentModuleCheckbox = page.getByRole('checkbox', { name: '选择模块 模块删除父' });
  await parentModuleCheckbox.click();
  // 上个场景保留了失败接口勾选，切到模块选择需显式确认互斥切换。
  await expect(page.locator('.ant-modal-confirm-title').filter({ hasText: '切换为选择模块？' })).toBeVisible();
  await page.getByRole('button', { name: '继续' }).click();
  await expect(parentModuleCheckbox).toBeChecked();
  await page.getByRole('checkbox', { name: '选择模块 模块删除子' }).check();
  await expect(page.getByText(/已选 2 个模块/).first()).toBeVisible();
  await page.getByRole('button', { name: '删除模块' }).click();
  await expect(page.locator('.ant-modal-confirm-content')).toContainText('2 个模块，2 个接口');
  await page.getByRole('button', { name: '取消' }).click();
  await expect(page.getByRole('checkbox', { name: '选择模块 模块删除父' })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: '选择模块 模块删除子' })).toBeChecked();

  await page.getByRole('button', { name: '删除模块' }).click();
  await page.getByRole('button', { name: '移入回收站' }).click();
  await expect(page.getByText('已将 2 个模块和 2 个接口移入回收站').first()).toBeVisible();
  await expect(page.getByRole('button', { name: /模块删除父/ })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /模块删除子/ })).toHaveCount(0);

  // ---- 桌面布局截图 ----
  await page.locator('button.api-module-open[title="分页序号模块"]').click();
  await page.screenshot({ path: 'e2e/artifacts/api-catalog-desktop.png', fullPage: true });

  // ---- 窄屏：目录收进抽屉，选择列与数量仍可见 ----
  await page.setViewportSize({ width: 800, height: 900 });
  await page.reload();
  await page.getByRole('button', { name: /切换目录/ }).click();
  const drawer = page.locator('.api-catalog-drawer');
  await expect(drawer).toBeVisible();
  // 等待抽屉滑入完成，避免截到动画中间态。
  await expect(page.locator('.ant-drawer-content-wrapper').filter({ has: page.locator('.api-catalog-drawer') })).toHaveCSS('width', '320px');
  await page.waitForTimeout(400);
  await expect(drawer.getByRole('checkbox', { name: '选择模块 分页父模块' })).toBeVisible();
  const narrowCheckbox = await drawer.getByRole('checkbox', { name: '选择模块 分页父模块' }).boundingBox();
  expect(narrowCheckbox?.width ?? 0).toBeGreaterThanOrEqual(20);
  await drawer.getByRole('checkbox', { name: '选择模块 分页父模块' }).check();
  await expect(drawer.getByText('已选 1 个模块')).toBeVisible();
  await page.screenshot({ path: 'e2e/artifacts/api-catalog-narrow-drawer.png', fullPage: true });

  // 选中模块后抽屉关闭，窄屏仍能看到模块路径与序号列表。
  await drawer.getByRole('button', { name: '展开模块 分页父模块' }).click();
  await drawer.locator('button.api-module-open[title="分页序号模块"]').click();
  await expect(page.locator('.api-module-interfaces h4')).toContainText('分页序号模块');
  await page.screenshot({ path: 'e2e/artifacts/api-catalog-narrow-list.png', fullPage: true });

  // 清理隔离项目；失败不影响已完成的验收结论。
  await page.request.delete(`/api/v1/projects/${projectId}`, {
    headers: { origin: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5174' },
  }).catch(() => undefined);
});