// 管理页面模块多选删除全链路浏览器验收（隔离测试项目）。
//
// 覆盖：
// 1. 测试用例（API / UI / AI 三个方向）：连续勾选、全选可见/筛选结果、清空、系统目录禁选、
//    父子同选、混合提交部分失败（保留失败项勾选并展示原因）、删除当前目录后回退父目录/根视图、
//    切换方向与项目清空勾选、窄屏勾选操作、回收站批量恢复。
// 2. 接口管理：连续勾选计数递增、全选普通模块（排除未分类）与半选/清空、父子同选影响数去重、
//    取消预览保留勾选、右侧表头与「选择本页未分类接口」、回收站恢复与切换项目清空勾选。
// 3. 业务管理：业务域与流程连续勾选、全选、部分失败保留勾选并显示名称、切换项目清空勾选、恢复。
// 4. 测试数据 Fixture 树：按实体分组勾选、确认框明确显示 Fixture 数量、批删与回收站恢复、切换项目。
import { expect, test, type Page } from '@playwright/test';

const ADMIN = process.env.E2E_ADMIN_USERNAME ?? 'admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';
const RUN_ID = `${Date.now().toString(36)}${Math.floor(Math.random() * 1000)}`;
const ORIGIN = process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5174';

type ApiEnvelope<T> = { data?: T } & T;

/** 通过登录页完成认证，后续浏览器与 page.request 复用 Cookie 会话。 */
async function loginThroughUi(page: Page) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(ADMIN);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'));
}

/** 调用后端接口并统一解包；失败时直接输出响应文本方便排错。 */
async function api<T = unknown>(page: Page, method: string, path: string, body?: unknown): Promise<T> {
  const response = await page.request.fetch(`/api/v1${path}`, {
    method,
    data: body as object | undefined,
    headers: { origin: ORIGIN },
  });
  const payload = (await response.json().catch(() => ({}))) as ApiEnvelope<T>;
  expect(response.ok(), `${method} ${path} 失败：${response.status()} ${JSON.stringify(payload)}`).toBeTruthy();
  return (payload.data ?? payload) as T;
}

/** 写入当前控制台项目并跳转到目标控制台页面。 */
async function openProjectPage(page: Page, projectId: number, route: string) {
  await page.goto('/console');
  await page.evaluate((id) => {
    const rawUser = localStorage.getItem('user');
    const userId = rawUser ? (JSON.parse(rawUser) as { id?: number }).id : undefined;
    localStorage.setItem('console.current_project_id', String(id));
    if (userId) localStorage.setItem('console.scope_user_id', String(userId));
  }, projectId);
  await page.goto(route);
}

/** 通过顶部项目选择器切换项目，验证页面内选择态被清空。 */
async function switchProjectViaTopbar(page: Page, targetProjectName: string) {
  const selector = page.locator('.app-scope-select');
  await selector.click();
  const option = page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: targetProjectName }).first();
  await expect(option).toBeVisible();
  await option.click();
}

/** 返回测试范围树中指定名称节点对应的勾选框元素。 */
function scopeTreeCheckbox(page: Page, name: string) {
  return page.locator('.scope-tree .ant-tree-treenode').filter({ hasText: name }).first().locator('.ant-tree-checkbox');
}

/** 在测试范围树中展开所有折叠节点，确保子目录可见。 */
async function expandAllScopeNodes(page: Page) {
  for (let round = 0; round < 4; round += 1) {
    const collapsed = page.locator('.scope-tree .ant-tree-switcher_close');
    const count = await collapsed.count();
    if (count === 0) break;
    for (let index = 0; index < count; index += 1) {
      await collapsed.first().click();
    }
  }
}

test('管理页面模块多选删除全链路验收（隔离项目）', async ({ page }) => {
  test.setTimeout(300_000);
  expect(PASSWORD, '需要 E2E_ADMIN_PASSWORD 才能执行浏览器验收').toBeTruthy();
  await loginThroughUi(page);

  const projectAName = `模块多选验收A-${RUN_ID}`;
  const projectBName = `模块多选验收B-${RUN_ID}`;
  const projectA = await api<{ id: number }>(page, 'POST', '/projects', {
    name: projectAName,
    description: '模块多选删除主隔离项目',
  });
  const projectB = await api<{ id: number }>(page, 'POST', '/projects', {
    name: projectBName,
    description: '模块多选删除切换项目验证',
  });
  const projectAId = projectA.id;
  const projectBId = projectB.id;

  try {
    // =========================================================================
    // 1. 测试用例（API / UI / AI 三个方向）目录多选删除与恢复
    // =========================================================================
    for (const direction of ['API', 'UI', 'AI'] as const) {
      const targetType = direction === 'UI' ? 'WEB' : direction;
      const emptyA = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/test-scopes`, {
        direction, node_type: 'FOLDER', name: `${direction}-空目录A-${RUN_ID}`,
      });
      const emptyB = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/test-scopes`, {
        direction, node_type: 'FOLDER', name: `${direction}-空目录B-${RUN_ID}`,
      });
      const occupied = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/test-scopes`, {
        direction, node_type: 'FOLDER', name: `${direction}-含用例目录-${RUN_ID}`,
      });
      const testCase = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/test-cases`, {
        name: `${direction}-保留用例-${RUN_ID}`,
        target_type: targetType,
      });
      await api(page, 'PUT', `/test-cases/${testCase.id}/scope-links`, {
        scope_node_ids: [occupied.id],
      });
      const parent = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/test-scopes`, {
        direction, node_type: 'FOLDER', name: `${direction}-父目录-${RUN_ID}`,
      });
      await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/test-scopes`, {
        direction, node_type: 'FOLDER', parent_id: parent.id, name: `${direction}-子目录-${RUN_ID}`,
      });
      expect(emptyA.id && emptyB.id).toBeTruthy();
    }
    // 给项目 B 建一个目录，用于切换项目验证
    await api<{ id: number }>(page, 'POST', `/projects/${projectBId}/test-scopes`, {
      direction: 'API', node_type: 'FOLDER', name: `项目B目录-${RUN_ID}`,
    });

    await openProjectPage(page, projectAId, `/console/test-cases?projectId=${projectAId}&direction=API`);
    await expect(page.locator('.scope-tree')).toBeVisible();

    for (const direction of ['API', 'UI', 'AI'] as const) {
      const directionLabel = direction === 'API' ? 'API 接口测试' : direction === 'UI' ? 'UI 界面测试' : 'AI 专项测试';
      await page.locator('.ant-segmented-item').filter({ hasText: directionLabel }).click();
      const emptyAName = `${direction}-空目录A-${RUN_ID}`;
      const emptyBName = `${direction}-空目录B-${RUN_ID}`;
      const occupiedName = `${direction}-含用例目录-${RUN_ID}`;
      const parentName = `${direction}-父目录-${RUN_ID}`;
      const childName = `${direction}-子目录-${RUN_ID}`;
      const caseName = `${direction}-保留用例-${RUN_ID}`;

      await expect(page.locator('.scope-tree').getByText(emptyAName)).toBeVisible();
      await expandAllScopeNodes(page);

      // 系统「待整理」节点禁选复选框
      const inboxCheckbox = scopeTreeCheckbox(page, '待整理');
      await expect(inboxCheckbox).toHaveClass(/ant-tree-checkbox-disabled/);

      // 连续勾选两个空目录，再勾选含用例目录 -> 计数递增 1 -> 2 -> 3
      await scopeTreeCheckbox(page, emptyAName).click();
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 1 个');
      await scopeTreeCheckbox(page, emptyBName).click();
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 2 个');
      await scopeTreeCheckbox(page, occupiedName).click();
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 3 个');

      // 点击目录名称浏览右侧用例，勾选状态不受影响
      await page.locator('.scope-tree').getByText(emptyAName, { exact: true }).click();
      await expect(page.locator('.scope-detail-head h4')).toContainText(emptyAName);
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 3 个');

      // 取消确认应保留勾选
      await page.locator('.scope-tree-bulk-bar').getByRole('button', { name: '删除目录' }).click();
      await expect(page.locator('.ant-modal-confirm-title')).toContainText('删除选中的 3 个测试目录？');
      await page.locator('.ant-modal-confirm').getByRole('button', { name: '取消' }).click();
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 3 个');

      // 混合提交 2 空目录 + 1 含用例目录 -> 成功 2 个，失败 1 个，当前浏览的空目录被删后回到根视图
      await page.locator('.scope-tree-bulk-bar').getByRole('button', { name: '删除目录' }).click();
      await page.locator('.ant-modal-confirm').getByRole('button', { name: '删除 3 个目录' }).click();
      const partialModal = page.locator('.ant-modal-confirm').filter({ hasText: '批量删除目录完成：成功 2 个，失败 1 个' });
      await expect(partialModal).toBeVisible();
      await expect(partialModal).toContainText(occupiedName);
      await expect(partialModal).toContainText('测试用例');
      await partialModal.getByRole('button', { name: '关闭' }).click();

      // 空目录已消失，失败项保留勾选且含用例目录和用例仍可查看，当前浏览视图已回到「全部用例」
      await expect(page.locator('.scope-tree').getByText(emptyAName)).toHaveCount(0);
      await expect(page.locator('.scope-tree').getByText(emptyBName)).toHaveCount(0);
      await expect(page.locator('.scope-detail-head h4')).toContainText('全部用例');
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 1 个');
      await expect(scopeTreeCheckbox(page, occupiedName)).toHaveClass(/ant-tree-checkbox-checked/);
      await page.locator('.scope-tree').getByText(occupiedName, { exact: true }).click();
      await expect(page.getByRole('row').filter({ hasText: caseName })).toBeVisible();

      // 清空后测试筛选范围全选（搜索「目录-」）与父子同选批删
      await page.locator('.scope-tree-bulk-bar').getByRole('button', { name: '清空' }).click();
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 0 个');

      const searchInput = page.getByPlaceholder('搜索范围');
      await searchInput.fill(`${direction}-子目录`);
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('全选筛选结果（2）');
      await page.locator('.scope-tree-bulk-bar .ant-checkbox-input').check();
      await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 2 个');
      await searchInput.fill('');
      await expandAllScopeNodes(page);

      // 当前浏览子目录，父子同选一起删除 -> 子先父后全部成功，浏览视图回退根视图
      await page.locator('.scope-tree').getByText(childName, { exact: true }).click();
      await expect(page.locator('.scope-detail-head h4')).toContainText(childName);
      await page.locator('.scope-tree-bulk-bar').getByRole('button', { name: '删除目录' }).click();
      await page.locator('.ant-modal-confirm').getByRole('button', { name: '删除 2 个目录' }).click();
      const successModal = page.locator('.ant-modal-confirm').filter({ hasText: '已将 2 个目录移入回收站' });
      await expect(successModal).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(successModal).toBeHidden();
      await expect(page.locator('.scope-tree').getByText(parentName)).toHaveCount(0);
      await expect(page.locator('.scope-tree').getByText(childName)).toHaveCount(0);
      await expect(page.locator('.scope-detail-head h4')).toContainText('全部用例');
    }

    // 切换方向与切换项目应清空目录勾选
    await scopeTreeCheckbox(page, `AI-含用例目录-${RUN_ID}`).click();
    await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 1 个');
    await page.locator('.ant-segmented-item').filter({ hasText: 'API 接口测试' }).click();
    await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 0 个');

    await scopeTreeCheckbox(page, `API-含用例目录-${RUN_ID}`).click();
    await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 1 个');
    await switchProjectViaTopbar(page, projectBName);
    await expect(page.locator('.scope-tree').getByText(`项目B目录-${RUN_ID}`)).toBeVisible();
    await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 0 个');

    // 窄屏勾选目录操作（在项目 B 上验证）
    await page.setViewportSize({ width: 800, height: 900 });
    await scopeTreeCheckbox(page, `项目B目录-${RUN_ID}`).click();
    await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 1 个');
    await page.locator('.scope-tree-bulk-bar').getByRole('button', { name: '清空' }).click();
    await expect(page.locator('.scope-tree-bulk-bar')).toContainText('已选 0 个');
    await page.setViewportSize({ width: 1440, height: 900 });

    // 回收站批量恢复 API 方向的父子目录（子先删、父先恢复）
    await openProjectPage(page, projectAId, '/console/recycle-bin');
    const apiParentName = `API-父目录-${RUN_ID}`;
    const apiChildName = `API-子目录-${RUN_ID}`;
    await expect(page.getByRole('row').filter({ hasText: apiParentName })).toBeVisible();
    await expect(page.getByRole('row').filter({ hasText: apiChildName })).toBeVisible();
    await page.getByRole('row').filter({ hasText: apiChildName }).getByRole('checkbox').check();
    await page.getByRole('row').filter({ hasText: apiParentName }).getByRole('checkbox').check();
    await page.getByRole('button', { name: /批量恢复/ }).click();
    await page.locator('.ant-modal-confirm .ant-btn-primary').click();
    await expect(page.getByRole('row').filter({ hasText: apiParentName })).toHaveCount(0);
    await expect(page.getByRole('row').filter({ hasText: apiChildName })).toHaveCount(0);

    await page.goto(`/console/test-cases?projectId=${projectAId}&direction=API`);
    await expect(page.locator('.scope-tree').getByText(apiParentName)).toBeVisible();
    await expandAllScopeNodes(page);
    await expect(page.locator('.scope-tree').getByText(apiChildName)).toBeVisible();

    // =========================================================================
    // 2. 接口管理：全选普通模块（排除未分类）、连续勾选、父子去重、右侧未分类列表选择
    // =========================================================================
    const modParent = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/api-modules`, {
      name: `接口父模块-${RUN_ID}`,
    });
    const modChild = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/api-modules`, {
      name: `接口子模块-${RUN_ID}`,
      parent_id: modParent.id,
    });
    const modSibling = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/api-modules`, {
      name: `接口平级模块-${RUN_ID}`,
    });
    await api(page, 'POST', `/projects/${projectAId}/apis`, {
      module_id: modChild.id, name: `子模块接口-${RUN_ID}`, method: 'GET', path: `/bulk/${RUN_ID}/child`, status: 'ACTIVE',
    });
    await api(page, 'POST', `/projects/${projectAId}/apis`, {
      module_id: null, name: `未分类接口-${RUN_ID}`, method: 'GET', path: `/bulk/${RUN_ID}/unclassified`, status: 'ACTIVE',
    });
    await api<{ id: number }>(page, 'POST', `/projects/${projectBId}/api-modules`, {
      name: `项目B模块-${RUN_ID}`,
    });
    expect(modSibling.id).toBeTruthy();

    await openProjectPage(page, projectAId, '/console/api-catalog');
    await expect(page.locator('.api-catalog-page')).toBeVisible();

    // 有数据的「未分类」文件夹可见且可勾选，并纳入「全选模块」
    await expect(page.getByRole('checkbox', { name: '选择模块 未分类' })).toBeEnabled();

    // 连续勾选两个普通模块：计数从 1 增至 2，全选模块为半选状态
    await page.getByRole('checkbox', { name: `选择模块 接口父模块-${RUN_ID}` }).check();
    await expect(page.getByText('已选 1 个模块')).toBeVisible();
    await page.getByRole('checkbox', { name: `选择模块 接口平级模块-${RUN_ID}` }).check();
    await expect(page.getByText('已选 2 个模块')).toBeVisible();

    // 全选模块（4）：包含有数据的「未分类」及全部 3 个普通模块
    const selectAllModules = page.locator('.api-module-toolbar').getByRole('checkbox');
    await selectAllModules.check();
    await expect(page.getByText('已选 4 个模块')).toBeVisible();
    await expect(page.getByRole('checkbox', { name: '选择模块 未分类' })).toBeChecked();

    // 清空后验证父子同选预览影响数不重复（2 个模块，1 个接口），取消保留勾选，确认移入回收站
    await page.locator('.api-module-toolbar').getByRole('button', { name: '清空' }).click();
    await expect(page.getByText('已选 0 个模块')).toBeVisible();

    await page.getByRole('button', { name: `展开模块 接口父模块-${RUN_ID}` }).click();
    await page.getByRole('checkbox', { name: `选择模块 接口父模块-${RUN_ID}` }).check();
    await page.getByRole('checkbox', { name: `选择模块 接口子模块-${RUN_ID}` }).check();
    await expect(page.getByText('已选 2 个模块')).toBeVisible();
    await page.getByRole('button', { name: '删除模块' }).click();
    await expect(page.locator('.ant-modal-confirm-content')).toContainText('2 个模块，1 个接口');
    await page.locator('.ant-modal-confirm').getByRole('button', { name: '取消' }).click();
    await expect(page.getByText('已选 2 个模块')).toBeVisible();

    await page.getByRole('button', { name: '删除模块' }).click();
    await page.locator('.ant-modal-confirm').getByRole('button', { name: '移入回收站' }).click();
    await expect(page.getByText('已将 2 个模块和 1 个接口移入回收站')).toBeVisible();

    // 右侧点击单行复选框不会误跳转接口详情，表头与「选择本页未分类接口」均可正常切换
    await page.locator('button.api-module-open[title="未分类"]').click();
    await expect(page.locator('.api-module-interfaces h4')).toContainText('未分类');
    await page.locator('.api-module-interfaces .ant-table-tbody tr.ant-table-row').first().getByRole('checkbox').check();
    await expect(page.locator('.api-module-interfaces h4')).toContainText('未分类');
    await expect(page.getByText('已选 1 个接口')).toBeVisible();
    await page.locator('.api-module-interfaces').getByRole('checkbox', { name: '选择本页未分类接口' }).uncheck();
    await expect(page.getByText('已选 1 个接口')).toHaveCount(0);

    // 左侧直接勾选「未分类」删除：清空未分类下全部接口后，「未分类」文件夹自动隐藏
    await page.getByRole('checkbox', { name: '选择模块 未分类' }).check();
    await expect(page.getByText('已选 1 个模块')).toBeVisible();
    await page.getByRole('button', { name: '删除模块' }).click();
    await expect(page.locator('.ant-modal-confirm-content')).toContainText('1 个接口');
    await page.locator('.ant-modal-confirm').getByRole('button', { name: '移入回收站' }).click();
    await expect(page.getByText('已将 1 个未分类接口移入回收站')).toBeVisible();
    await expect(page.locator('button.api-module-open[title="未分类"]')).toHaveCount(0);

    // 切换项目清空接口模块勾选，且无未分类数据的项目 B 不显示「未分类」文件夹
    await page.getByRole('checkbox', { name: `选择模块 接口平级模块-${RUN_ID}` }).check();
    await expect(page.getByText('已选 1 个模块')).toBeVisible();
    await switchProjectViaTopbar(page, projectBName);
    await expect(page.getByRole('checkbox', { name: `选择模块 项目B模块-${RUN_ID}` })).toBeVisible();
    await expect(page.locator('button.api-module-open[title="未分类"]')).toHaveCount(0);
    await expect(page.getByText('已选 0 个模块')).toBeVisible();

    // =========================================================================
    // 3. 业务管理：连续勾选、全选、部分失败保留失败项并显示名称、切换项目与恢复
    // =========================================================================
    const emptyDomain = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/business-domains`, {
      name: `空业务域-${RUN_ID}`, status: 'ACTIVE', sort: 0,
    });
    const occupiedDomain = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/business-domains`, {
      name: `含流程业务域-${RUN_ID}`, status: 'ACTIVE', sort: 1,
    });
    const flowA = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/business-flows`, {
      name: `流程甲-${RUN_ID}`, domain_id: occupiedDomain.id, status: 'DRAFT',
    });
    await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/business-flows`, {
      name: `流程乙-${RUN_ID}`, domain_id: occupiedDomain.id, status: 'DRAFT',
    });
    expect(emptyDomain.id && flowA.id).toBeTruthy();

    await openProjectPage(page, projectAId, '/console/business-management');
    await expect(page.getByText(`空业务域-${RUN_ID}`, { exact: true })).toBeVisible();
    await page.getByRole('checkbox', { name: /全选当前搜索结果/ }).check();
    await page.getByRole('button', { name: /批量删除域（2）/ }).click();
    await page.locator('.ant-modal-confirm .ant-btn-primary').click();
    const domainPartial = page.locator('.ant-modal-confirm').filter({ hasText: '成功 1 条，失败 1 条' });
    await expect(domainPartial).toBeVisible();
    await expect(domainPartial).toContainText(`含流程业务域-${RUN_ID}`);
    await domainPartial.getByRole('button', { name: /知道了|确定|OK/ }).click();
    await expect(domainPartial).toBeHidden();
    const businessSidebar = page.locator('.resource-split__sidebar');
    await expect(businessSidebar.getByText(`空业务域-${RUN_ID}`, { exact: true })).toHaveCount(0);
    await expect(businessSidebar.getByRole('button', { name: /批量删除域（1）/ })).toBeVisible();

    // 进入含流程业务域，批量删除两条流程
    await businessSidebar.getByText(`含流程业务域-${RUN_ID}`, { exact: true }).click();
    await expect(businessSidebar.getByText(`流程甲-${RUN_ID}`, { exact: true })).toBeVisible();
    await businessSidebar.getByRole('checkbox', { name: /全选当前流程列表/ }).check();
    await businessSidebar.getByRole('button', { name: /批量删除流程（2）/ }).click();
    await page.locator('.ant-modal-confirm .ant-btn-primary').click();
    await expect(businessSidebar.getByText(`流程甲-${RUN_ID}`, { exact: true })).toHaveCount(0);
    await expect(businessSidebar.getByText(`流程乙-${RUN_ID}`, { exact: true })).toHaveCount(0);

    // 切换项目清空业务域勾选
    await switchProjectViaTopbar(page, projectBName);
    await expect(businessSidebar.getByRole('button', { name: /批量删除域（0）/ })).toBeVisible();

    // =========================================================================
    // 4. 测试数据 Fixture 树：分组勾选、确认框明确显示 Fixture 数量、批删与切换项目
    // =========================================================================
    await api(page, 'POST', `/projects/${projectAId}/fixtures`, {
      name: `用户夹具1-${RUN_ID}`, fixture_key: `USER_FIX_1_${RUN_ID.toUpperCase()}`, entity_type: 'user', scope: 'PROJECT', status: 'DRAFT',
    });
    await api(page, 'POST', `/projects/${projectAId}/fixtures`, {
      name: `用户夹具2-${RUN_ID}`, fixture_key: `USER_FIX_2_${RUN_ID.toUpperCase()}`, entity_type: 'user', scope: 'PROJECT', status: 'DRAFT',
    });

    await openProjectPage(page, projectAId, '/console/test-data');
    await page.getByRole('tab', { name: 'Fixture' }).click();
    await expect(page.getByText(`用户夹具1-${RUN_ID}`)).toBeVisible();
    const userGroupCheckbox = page.locator('.ant-tree-treenode').filter({ hasText: 'user（2）' }).first().locator('.ant-tree-checkbox');
    await userGroupCheckbox.click();
    await expect(page.getByRole('button', { name: '批量删除（2）' })).toBeVisible();

    // 切换项目应清空 Fixture 勾选
    await switchProjectViaTopbar(page, projectBName);
    await expect(page.getByRole('button', { name: '批量删除（0）' })).toBeVisible();
    await switchProjectViaTopbar(page, projectAName);
    await expect(page.getByText(`用户夹具1-${RUN_ID}`)).toBeVisible();

    await page.locator('.ant-tree-treenode').filter({ hasText: 'user（2）' }).first().locator('.ant-tree-checkbox').click();
    await page.getByRole('button', { name: '批量删除（2）' }).click();
    await expect(page.locator('.ant-modal-confirm-title')).toContainText('将选中的 2 个 Fixture 移入回收站？');
    await page.locator('.ant-modal-confirm').getByRole('button', { name: '删除 2 个 Fixture' }).click();
    const fixtureDone = page.locator('.ant-modal-confirm').filter({ hasText: '删除完成：成功 2 个，失败 0 个' });
    await expect(fixtureDone).toBeVisible();
    await fixtureDone.getByRole('button', { name: '查看回收站' }).click();
    await expect(page).toHaveURL(/\/console\/recycle-bin/);

    // 在回收站批量恢复 Fixture、空业务域和接口父子模块，确认恢复能力正常
    await expect(page.getByRole('row').filter({ hasText: `用户夹具1-${RUN_ID}` })).toBeVisible();
    await page.getByRole('row').filter({ hasText: `用户夹具1-${RUN_ID}` }).getByRole('checkbox').check();
    await page.getByRole('row').filter({ hasText: `空业务域-${RUN_ID}` }).getByRole('checkbox').check();
    await page.getByRole('row').filter({ hasText: `接口父模块-${RUN_ID}` }).getByRole('checkbox').check();
    await page.getByRole('row').filter({ hasText: `接口子模块-${RUN_ID}` }).getByRole('checkbox').check();
    await page.getByRole('row').filter({ hasText: `未分类接口-${RUN_ID}` }).getByRole('checkbox').check();
    await page.getByRole('button', { name: /批量恢复/ }).click();
    await page.locator('.ant-modal-confirm .ant-btn-primary').click();
    await expect(page.getByRole('row').filter({ hasText: `用户夹具1-${RUN_ID}` })).toHaveCount(0);
    await expect(page.getByRole('row').filter({ hasText: `空业务域-${RUN_ID}` })).toHaveCount(0);
    await expect(page.getByRole('row').filter({ hasText: `接口父模块-${RUN_ID}` })).toHaveCount(0);
    await expect(page.getByRole('row').filter({ hasText: `接口子模块-${RUN_ID}` })).toHaveCount(0);
    await expect(page.getByRole('row').filter({ hasText: `未分类接口-${RUN_ID}` })).toHaveCount(0);

    // 切回接口管理验证已恢复的模块及未分类文件夹重新出现
    await page.goto('/console/api-catalog');
    await expect(page.getByRole('checkbox', { name: `选择模块 接口父模块-${RUN_ID}` })).toBeVisible();
    await expect(page.locator('button.api-module-open[title="未分类"]')).toBeVisible();

    // =========================================================================
    // 5. 项目知识库（/admin/knowledge）：持久化知识库目录多选删除与部分失败保留勾选
    // =========================================================================
    const kbEmpty = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/knowledge-bases`, {
      name: `空知识库-${RUN_ID}`,
    });
    const kbOccupied = await api<{ id: number }>(page, 'POST', `/projects/${projectAId}/knowledge-bases`, {
      name: `含文档知识库-${RUN_ID}`,
    });
    const docUpload = await page.request.post(`/api/v1/projects/${projectAId}/knowledge-bases/${kbOccupied.id}/documents`, {
      headers: { origin: ORIGIN },
      multipart: {
        category: '项目情况',
        file: { name: `doc-${RUN_ID}.txt`, mimeType: 'text/plain', buffer: Buffer.from('隔离知识库文档内容') },
      },
    });
    expect(docUpload.ok(), `上传测试知识文档失败：${docUpload.status()} ${await docUpload.text()}`).toBeTruthy();
    expect(kbEmpty.id).toBeTruthy();

    await page.goto('/admin/knowledge');
    await page.locator('.ant-select[aria-label="项目"]').click();
    await page.locator('.ant-select-dropdown:visible .ant-select-item-option').filter({ hasText: projectAName }).first().click();
    await expect(page.getByRole('row').filter({ hasText: `空知识库-${RUN_ID}` })).toBeVisible();
    await page.getByRole('row').filter({ hasText: `空知识库-${RUN_ID}` }).getByRole('checkbox').check();
    await page.getByRole('row').filter({ hasText: `含文档知识库-${RUN_ID}` }).getByRole('checkbox').check();
    await page.getByRole('button', { name: '批量删除知识库（2）' }).click();
    await page.locator('.ant-modal-confirm').getByRole('button', { name: '移入回收站' }).click();
    await expect(page.getByRole('row').filter({ hasText: `空知识库-${RUN_ID}` })).toHaveCount(0);
    await expect(page.getByRole('row').filter({ hasText: `含文档知识库-${RUN_ID}` })).toBeVisible();
    await expect(page.getByRole('button', { name: '批量删除知识库（1）' })).toBeVisible();
  } finally {
    // 清理隔离测试项目，避免残留测试数据。
    for (const id of [projectAId, projectBId]) {
      await page.request.delete(`/api/v1/projects/${id}`, { headers: { origin: ORIGIN } }).catch(() => undefined);
    }
  }
});
