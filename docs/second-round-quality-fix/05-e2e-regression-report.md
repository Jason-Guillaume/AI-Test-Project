# Playwright 与响应式回归报告

## 测试契约

`frontend/e2e/all-routes-responsive.spec.ts` 现为每个登记路由绑定预期标题，断言真实页面标题、`.page-container` 内的业务组件、主要操作按钮尺寸/遮挡和横向溢出。测试监听 `pageerror`、`console.error`、API 请求失败与 API 响应；401、5xx、429、网络错误等失败会阻断用例，403/404 会作为权限拒绝或动态资源不存在记录。失败时 Playwright 配置保留截图与 trace。

四个检查视口：1440×900、1024×768、768×1024、390×844。路由和截图测试使用 Playwright 自动等待断言，没有固定 `waitForTimeout`。

`frontend/e2e/model-center.spec.ts` 使用真实后端 API 创建带随机名称的项目及合成模型，依次操作详情、连接修订、参数方案和默认策略；诊断用例确认无项目时不能提交，选择项目并勾选计费确认后仍不发送请求。该用例不会对外部模型发起真实请求。

已有 `skill-workspace.spec.ts` 覆盖 Skill 文件编辑、版本恢复和四视口布局；`data-lifecycle.spec.ts` 覆盖 Agent、Skill、MCP 等回收站恢复流程。

## 实际执行结果

- `npx playwright test --list`：33 个用例载入成功。
- `bash scripts/e2e_case_generation.sh`：隔离 PostgreSQL scratch 库创建成功；在 Alembic `upgrade head` 阶段因 MultipleHeads 退出，脚本确认并删除了 scratch 库。
- 浏览器 E2E 实际执行：**0 个**。页面标题、核心容器、异常监听和四视口行为没有获得运行时结果。
- 截图：本轮未生成。实际浏览器阶段没有启动；截图目录中的 README 说明了后续生成入口。

该结果不是 E2E 通过。修复已发布 migration graph 冲突后，应重新运行完整脚本，再核对路由合同是否与真实空态、权限态及动态详情页一致。
