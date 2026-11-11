// Playwright E2E 配置：用例生成审核闭环。
// 由 scripts/e2e_case_generation.sh 编排启动（隔离库 + LLM 桩 + 真实前后端）。
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // 单工作进程串行：所有用例共享同一个隔离库，避免相互污染。
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  outputDir: 'e2e/artifacts',
  reporter: [['list'], ['html', { open: 'never', outputFolder: 'e2e/report' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5174',
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
    actionTimeout: 15_000,
  },
});
