import { expect, test, type Page } from '@playwright/test';

async function mockConsoleApi(page: Page, responses: Record<string, unknown>) {
  await page.addInitScript(() => {
    localStorage.setItem('console.scope_user_id', '1');
    localStorage.setItem('console.current_project_id', '1');
  });
  const project = { id: 1, name: '排版验证项目', my_role: 'owner' };
  const fixtures: Record<string, unknown> = {
    '/api/v1/me': { id: 1, username: 'admin', role: 'admin', is_active: true },
    '/api/v1/projects': { items: [project], total: 1 },
    '/api/v1/projects/1': project,
    ...responses,
  };
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    await route.fulfill({ json: fixtures[path] ?? { items: [], total: 0 } });
  });
}

test('展开侧栏后，计划名称仍在自己的列内，操作列可滚动到达', async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  const name = '支付流程回归计划';
  await mockConsoleApi(page, {
    '/api/v1/projects/1/test-plans': [{
      id: 12, project_id: 1, name, description: '支付结果校验', status: 'ACTIVE',
      execution_mode: 'MANUAL', environment_id: null, created_at: '2025-01-02T08:00:00Z',
    }],
  });
  await page.goto('/console/test-plans');
  const cell = page.getByRole('cell', { name, exact: true });
  await expect(cell).toBeAttached();
  const fits = await cell.evaluate((element) => {
    const range = element.ownerDocument.createRange();
    range.selectNodeContents(element);
    const lines = [...range.getClientRects()];
    const bounds = element.getBoundingClientRect();
    return lines.length === 1 && lines[0].left >= bounds.left && lines[0].right <= bounds.right;
  });
  expect(fits).toBe(true);
  const edit = page.getByRole('row').filter({ has: cell }).getByRole('button', { name: '编辑' });
  await edit.scrollIntoViewIfNeeded();
  await expect(edit).toBeInViewport();
  await edit.click();
  await expect(page.getByRole('dialog').getByLabel('计划名称')).toHaveValue(name);
  await page.getByRole('button', { name: /取\s*消/ }).click();
  await page.getByRole('button', { name: '更多操作' }).click();
  await expect(page.getByRole('menuitem', { name: '管理套件' })).toBeVisible();
  await page.getByRole('menuitem', { name: '删除' }).click();
  await expect(page.getByRole('dialog')).toContainText(name);
  await page.getByRole('dialog').getByRole('button', { name: /取\s*消/ }).click();
  await expect(cell).toBeAttached();
  expect(await page.locator('html').evaluate((root) => root.scrollWidth)).toBeLessThanOrEqual(1024);
});

test('工作台趋势图的刻度等距，缩放窗口后仍能读出日期', async ({ page }) => {
  const days = Array.from({ length: 7 }, (_, i) => ({
    date: `2025-01-0${i + 1}`, total: i + 3, passed: i + 2, failed: 1, count: i + 3,
  }));
  await mockConsoleApi(page, {
    '/api/v1/dashboard/overview': { stats: [] },
    '/api/v1/dashboard/charts': { execution_trend: days, case_generation: days, defect_severity: [] },
  });
  await page.goto('/console');
  const charts = page.getByRole('img', { name: /折线图|柱状图/ });
  for (const width of [1200, 1440, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(charts).toHaveCount(2);
    for (const chart of await charts.all()) {
      const dates = chart.locator('text').filter({ hasText: /01\// });
      await expect(dates.first()).toHaveText('01/01');
      await expect(dates.last()).toHaveText('01/07');
      await expect.poll(() => dates.first().evaluate((tick) => tick.getBoundingClientRect().height)).toBeGreaterThanOrEqual(12);
      await expect.poll(() => dates.evaluateAll((labels) => {
        const boxes = labels.map((label) => label.getBoundingClientRect());
        return boxes.every((box, i) => i === 0 || box.left >= boxes[i - 1].right + 1);
      })).toBe(true);
      const ticks = (await chart.locator('text').allTextContents()).filter((s) => /^\d+$/.test(s)).map(Number);
      const steps = ticks.slice(1).map((tick, index) => ticks[index] - tick);
      expect(steps.length).toBeGreaterThan(1);
      expect(new Set(steps).size).toBe(1);
    }
  }
});

test('手机上的批次分享能在卡片内读完长缺陷标题', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const title = '移动端重复提交付款后，订单详情仍显示待支付，刷新页面后才显示最新支付状态';
  const item = { share_id: 'issue', bug_no: 'BUG-1042', title, live_status: '处理中' };
  await page.route('**/api/v1/public/defect-shares/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({ json: path.endsWith('/batches/demo') ? { items: [item] }
      : path.endsWith('/views') ? {} : { content: { ...item, attachments: [] } } });
  });
  await page.goto('/public/defects/share/batch/demo#token=sample');
  const selector = page.getByRole('button', { name: new RegExp(title) });
  await expect(selector).toBeVisible();
  expect(await selector.evaluate((button) => {
    const range = button.ownerDocument.createRange();
    range.selectNodeContents(button);
    const card = button.closest('header')!.getBoundingClientRect();
    return [...range.getClientRects()].every((line) => line.left >= card.left && line.right <= card.right);
  })).toBe(true);
  expect(await page.locator('html').evaluate((root) => root.scrollWidth)).toBeLessThanOrEqual(390);
});

test('手机开启减少动态效果后，仍能从用户菜单进入管理后台', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await mockConsoleApi(page, {
    '/api/v1/projects/1/test-plans': [],
    '/api/v1/dashboard/platform': { stats: [] },
    '/api/v1/dashboard/ready': { checks: [] },
  });
  await page.goto('/console/test-plans');
  await page.locator('.app-scope-select').click();
  const project = page.locator('.ant-select-dropdown').getByText('排版验证项目', { exact: true });
  await expect(project).toBeInViewport();
  await project.click();
  await page.getByRole('button', { name: /用户菜单/ }).click();
  const admin = page.getByRole('menuitem', { name: '管理后台' });
  await expect(admin).toBeInViewport();
  await admin.click();
  await expect(page).toHaveURL(/\/admin\/dashboard$/);
});
