import { mkdirSync } from 'node:fs';
import { expect, request, test, type Page } from '@playwright/test';

const API = process.env.E2E_API_URL ?? 'http://127.0.0.1:8101/api/v1';
const ADMIN = process.env.E2E_ADMIN_USERNAME ?? 'e2e-admin';
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? '';
const RUN_ID = Date.now();
const SCREENSHOTS = `/tmp/ai-test-project-ux-${RUN_ID}`;

async function loginThroughUi(page: Page) {
  await page.goto('/login');
  await page.getByPlaceholder('请输入用户名').fill(ADMIN);
  await page.getByPlaceholder('请输入密码').fill(PASSWORD);
  await page.getByRole('button', { name: /登录/ }).click();
  await page.waitForURL((url) => !url.pathname.includes('/login'));
}

test('Skill 文件工作区编辑、版本恢复与四种视口布局', async ({ page }) => {
  mkdirSync(SCREENSHOTS, { recursive: true });
  const api = await request.newContext();
  const login = await api.post(`${API}/login`, { data: { username: ADMIN, password: PASSWORD } });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token as string;
  const adminApi = await request.newContext({ extraHTTPHeaders: { Authorization: `Bearer ${token}` } });
  const skillName = `E2E Skill Workspace ${RUN_ID}`;
  const created = await adminApi.post(`${API}/agent-governance/skills`, {
    data: {
      name: skillName,
      description: '用于验证 Skill 文件工作区、真实版本写入和恢复。',
      content: '# 使用说明\n初始说明。',
      files_json: { 'SKILL.md': '# 使用说明\n初始说明。', 'references/checklist.md': '初始检查清单。' },
      mcp_tool_keys_json: [],
      is_enabled: false,
    },
  });
  expect(created.status()).toBe(201);
  const initialSkill = await created.json() as { id: number; version: number };

  try {
    await page.setViewportSize({ width: 1440, height: 900 });
    await loginThroughUi(page);
    await page.goto('/admin/skills');
    const tree = page.locator('.skill-workspace__tree-wrap');
    await tree.getByText(skillName, { exact: true }).click();
    await expect(page.getByText('Skill 概览')).toBeVisible();

    for (const viewport of [
      { width: 1440, height: 900, name: '1440x900' },
      { width: 1024, height: 768, name: '1024x768' },
      { width: 768, height: 1024, name: '768x1024' },
      { width: 390, height: 844, name: '390x844' },
    ]) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await expect(page.getByText('Skill 概览')).toBeVisible();
      const dimensions = await page.evaluate('({ documentWidth: document.documentElement.scrollWidth, viewportWidth: window.innerWidth })') as { documentWidth: number; viewportWidth: number };
      expect(dimensions.documentWidth, `页面在 ${viewport.name} 出现横向溢出`).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
      await page.screenshot({ path: `${SCREENSHOTS}/skill-workspace-${viewport.name}.png`, fullPage: true });
    }

    await expect(page.getByRole('button', { name: '展开导航' })).toBeVisible();
    await page.getByRole('button', { name: '展开导航' }).click();
    await expect(page.locator('.app-sidebar--mobile-open')).toBeVisible();
    await page.locator('.app-nav-scrim').click({ position: { x: 350, y: 500 } });
    await page.setViewportSize({ width: 1440, height: 900 });

    await tree.getByText('SKILL.md', { exact: true }).click();
    const editor = page.locator('.skill-workspace__editor');
    await expect(editor).toBeVisible();
    await editor.fill('# 更新后的使用说明\n请按顺序检查每一项。');
    await page.getByRole('tab', { name: '预览' }).click();
    await expect(page.locator('.skill-workspace__markdown-preview')).toContainText('更新后的使用说明');
    await page.getByRole('tab', { name: '编辑' }).click();
    await page.getByRole('button', { name: '保存新版本' }).click();

    await expect.poll(async () => {
      const response = await adminApi.get(`${API}/agent-governance/skills`);
      const skills = await response.json() as Array<{ id: number; version: number; files_json: Record<string, string> }>;
      const saved = skills.find((skill) => skill.id === initialSkill.id);
      return saved?.version;
    }).toBe(initialSkill.version + 1);

    await page.getByPlaceholder('references/guide.md').fill('references/new-guide.md');
    await page.getByRole('button', { name: '新建 Skill 文件' }).click();
    await expect(tree.getByText('new-guide.md', { exact: true })).toBeVisible();
    await tree.getByText('new-guide.md', { exact: true }).click();
    await page.locator('.skill-workspace__editor').fill('编辑器应切换到新文件内容。');
    await page.getByRole('button', { name: '保存新版本' }).click();

    await expect.poll(async () => {
      const response = await adminApi.get(`${API}/agent-governance/skills`);
      const skills = await response.json() as Array<{ id: number; version: number; files_json: Record<string, string> }>;
      const saved = skills.find((skill) => skill.id === initialSkill.id);
      return saved?.files_json['references/new-guide.md'];
    }).toBe('编辑器应切换到新文件内容。');

    await page.getByPlaceholder('references/guide.md').fill('assets/diagram.bin');
    await page.getByRole('button', { name: '新建 Skill 文件' }).click();
    await page.getByRole('button', { name: '保存新版本' }).click();
    await tree.getByText('diagram.bin', { exact: true }).click();
    await expect(page.getByText('暂不支持在线预览此文件类型')).toBeVisible();
    await expect(page.locator('.skill-workspace__editor')).toHaveCount(0);

    await page.getByRole('button', { name: '版本历史' }).click();
    const history = page.getByRole('dialog').filter({ hasText: `${skillName} · 版本历史` });
    await expect(history).toBeVisible();
    await history.getByRole('row').filter({ hasText: 'v1' }).click();
    await history.getByRole('button', { name: '恢复为新版本' }).click();
    await page.locator('.ant-modal-confirm .ant-btn-primary').click();
    await expect(history).toBeHidden();

    const verify = await adminApi.get(`${API}/agent-governance/skills`);
    expect(verify.ok()).toBeTruthy();
    const skills = await verify.json() as Array<{ id: number; version: number; files_json: Record<string, string> }>;
    const restored = skills.find((skill) => skill.id === initialSkill.id);
    expect(restored?.version).toBe(initialSkill.version + 4);
    expect(restored?.files_json['references/checklist.md']).toBe('初始检查清单。');
    expect(restored?.files_json['references/new-guide.md']).toBeUndefined();
  } finally {
    await adminApi.dispose();
    await api.dispose();
  }
});

test('五类 Agent 生态资源页在四种视口下无横向溢出并留存验收截图', async ({ page }) => {
  const viewports = [
    { width: 1440, height: 900, name: '1440x900' },
    { width: 1024, height: 768, name: '1024x768' },
    { width: 768, height: 1024, name: '768x1024' },
    { width: 390, height: 844, name: '390x844' },
  ];
  const resourcePages = [
    { path: '/admin/model-configs', title: '统一模型中心', file: 'llm' },
    { path: '/admin/agents', title: 'Agent 管理', file: 'agent' },
    { path: '/admin/mcp', title: 'MCP 管理', file: 'mcp' },
    { path: '/admin/skills', title: 'Skill 管理', file: 'skill' },
    { path: '/admin/tools', title: '工具管理', file: 'tool' },
  ];
  const screenshotDirectory = `/tmp/ai-test-project-ux-resources-${Date.now()}`;
  mkdirSync(screenshotDirectory, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await loginThroughUi(page);

  for (const resource of resourcePages) {
    for (const viewport of viewports) {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await page.goto(resource.path);
      await expect(page.getByRole('heading', { name: resource.title, exact: true })).toBeVisible();
      await page.waitForTimeout(150);
      const dimensions = await page.evaluate('({ documentWidth: document.documentElement.scrollWidth, viewportWidth: window.innerWidth })') as { documentWidth: number; viewportWidth: number };
      expect(dimensions.documentWidth, `${resource.path} 在 ${viewport.name} 出现横向溢出`).toBeLessThanOrEqual(dimensions.viewportWidth + 1);
      await page.screenshot({ path: `${screenshotDirectory}/${resource.file}-${viewport.name}.png`, fullPage: true });
    }
  }

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/admin/model-configs');
  await page.locator('.resource-card-actions button').first().click();
  await expect(page.getByRole('tab', { name: '连接配置' })).toBeVisible();
  await expect(page.getByText('凭据仅显示是否已配置；明文不会从服务端回读。')).toBeVisible();
  await page.locator('.ant-drawer-close').click();

  await page.goto('/admin/agents');
  await page.getByRole('button', { name: '查看详情 / 编辑配置' }).first().click();
  await expect(page.getByText('模型选择优先级')).toBeVisible();
  await page.getByLabel('Agent 名称').fill(`Unsaved ${Date.now()}`);
  await page.locator('.ant-drawer-close').click();
  await expect(page.locator('.ant-modal-confirm')).toBeVisible();
  await page.locator('.ant-modal-confirm .ant-btn-default').click();
  await page.locator('.ant-drawer-close').click();
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();

  await page.goto('/admin/mcp');
  await page.getByRole('button', { name: '新增 MCP 服务' }).click();
  await expect(page.getByRole('tab', { name: '连接状态' })).toBeVisible();
  await page.getByLabel('服务名称').fill(`Unsaved MCP ${Date.now()}`);
  await page.locator('.ant-drawer-close').click();
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();

  await page.goto('/admin/tools');
  const toolCards = page.locator('.ant-card[role="button"]');
  const toolStatusFilter = page.getByRole('combobox', { name: '工具状态筛选' });
  await toolStatusFilter.click();
  await page.locator('.ant-select-dropdown .ant-select-item-option-content').filter({ hasText: '执行器未接入' }).click();
  await expect(toolCards).not.toHaveCount(0);
  for (const cardText of await toolCards.allTextContents()) {
    expect(cardText).toContain('执行器 未接入');
  }
  await page.goto('/admin/tools');
  await expect(page.getByRole('heading', { name: '工具管理', exact: true })).toBeVisible();
  await toolStatusFilter.click();
  await page.locator('.ant-select-dropdown .ant-select-item-option-content').filter({ hasText: '执行器已接入' }).click();
  await expect(toolCards).not.toHaveCount(0);
  for (const cardText of await toolCards.allTextContents()) {
    expect(cardText).toMatch(/执行器 (可运行|已接入)/);
  }
  await page.locator('.ant-card[role="button"]').first().click();
  await expect(page.getByRole('tab', { name: '运行详情' })).toBeVisible();
  await page.locator('.ant-drawer textarea').first().fill('未保存的工具说明草稿');
  await page.locator('.ant-drawer-close').click();
  await page.locator('.ant-modal-confirm .ant-btn-default').click();
  await page.locator('.ant-drawer-close').click();
  await page.locator('.ant-modal-confirm .ant-btn-primary').click();
});
