# Agent 工作台优化验收记录

验收日期：2026-10-30。所有数据库测试使用独立临时 PostgreSQL 和按进程生成的测试库；浏览器任务使用隔离种子数据、本地健康检查端点与确定性 LLM 替身。未连接项目开发数据库或外部模型服务。

## 自动验证

| 命令/检查 | 结果 |
|---|---|
| `frontend/npm run lint` | 退出码 0 |
| `frontend/npm run typecheck` | 退出码 0 |
| `frontend/npm test` | 14 passed，0 failed；含路由注册回归、选择边界、分页/API 客户端和样式检查 |
| `frontend/npm run build` | 退出码 0；Vite 生成生产 bundle |
| `backend/tests/test_35_tasks.py` | 15 passed，13 warnings；覆盖迁移、模板隐私/版本、收件箱分页/精确聚合、运行对比、缺陷验证回链、模型降级、任务调度和 Web/API 执行 |
| `backend/tests/test_16_agent.py::TestAgentState` + `backend/tests/test_30_web_ui.py::test_web_case_listing_supports_server_search_and_confirmed_filter` | 6 passed，11 warnings |
| `backend/.venv/bin/python -m compileall -q backend/app backend/tests` | 退出码 0 |
| `backend/.venv/bin/alembic -c backend/alembic.ini heads` | `0030 (head)` |
| `git diff --check` | 退出码 0 |
| Alembic 迁移数据保留检查 | 新库完整升级成功；从 `0029` 插入既有项目后升级到 `0030`，原项目记录保留且 `task_template` 表存在 |

后端通过输出含 13 条现存弃用/Schema 警告：Starlette/AnyIO BlockingPortal、Pydantic `schema_json` 字段名和 Starlette 422 常量。所列测试均以成功退出。未运行全仓库全部后端测试。

## 浏览器流程

1. 打开本地 Vite 与 FastAPI 服务，登录隔离验收账号并选择已种入的验收项目。
2. `/console/tasks` 上打开创建任务窗体；选本地执行环境和已确认 API 用例，填写名称/目标并创建。列表出现“排队中 / PLANNING”任务与详情入口。
3. 打开任务详情，首次进入显示 `PLAN_REVIEW` 和“确认方案并执行”操作；确认后状态进入 API 执行。
4. 任务完成后详情显示 `COMPLETED`；方案/调度记录中 `test-run.create` 与 `report.generate` 均成功，Planner、API Worker、报告 Agent、审阅 Agent 和任务主 Agent 均完成。
5. 在 1440、1024、768、390 CSS 像素视口检查创建窗体、统一任务、待我处理、模板和任务详情。创建窗体在 390 宽度内收缩；浏览器 DOM 的页面宽度未超过可视宽度，页面无横向溢出或 React 错误页。390 宽度下目视检查表单输入、执行环境/用例选择、高级设置和固定操作按钮可见。

创建窗体初次浏览器验收曾发现项目环境加载时表单卸载导致的 `Maximum update depth exceeded`；修复后在上述视口和完整任务流程复测通过。

浏览器截图在本次桌面验收会话中目视检查，没有保存为仓库图片文件；本文记录所查路由、屏宽和关键状态。
