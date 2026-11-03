# Agent 工作台优化交付说明

日期：2026-10-30。实现根据开发需求、详细方案及问题审查完成，实施记录见 [进度文档](agent-ui-optimization-progress.md)，可复核结果见 [验收记录](agent-ui-optimization-validation/verification.md)。

## 完成内容

### A · 交互正确性

- Agent 工作区显式空选与已失效/越界 ID 会被拒绝；后端只接受当前会话快照中的用例或测试点。
- 项目、会话切换会隔离响应缓存和草稿；发送失败保留输入并提供重试，历史/工作区读取有明确失败态。
- 对话滚动定位到末尾，支持新消息提示；执行结果 Tab 仅在存在执行结果时显示。
- Agent 范围全选只作用于当前工作区，所选数、确认操作和全局任务摘要与服务端范围一致。

### B · 导航与工作流

- 控制台侧栏按工作台、任务、资产、结果、项目设置、管理组织；原路由和管理权限边界保持有效。
- 工作台提供任务创建与收件箱入口；任务列表和详情突出目标、状态、下一步，高级信息可展开，终端轮询在离开页面后停止。
- 任务创建选择器改为服务端搜索/分页；高级 Agent 查询按需加载；模板和再次执行预填现有配置。修复弹窗在环境请求期间卸载表单导致的渲染循环。
- 待办、模板、对比和缺陷验证能力进入既有任务、执行历史与缺陷页。

### C · 待办与模板

- 新增 Alembic `0030_task_templates` 与 `TaskTemplate` 持久模型。
- 项目模板支持列表、创建、版本化更新和停用；校验项目访问，敏感的浏览器登录态和 Web 会话引用不写入模板。
- 用模板创建任务会校验模板仍有效、版本匹配并保存模板版本与实际输入快照；再次执行保留原配置语义并使用新的幂等键。
- 新增 `/tasks/inbox` 最新运行分页聚合及分类计数、`/tasks/summary` 完整可见范围统计；详情 API 以一致数据库快照返回运行与工作项状态。

### D · 比对和失败闭环

- 新增 `/test-runs/compare`，对齐同项目两次 TestRun 的稳定 `test_case_id`，分类恢复、新增失败、持续失败、通过、范围增删及未解决状态，并返回证据 ID 和环境变化信息。
- 比对拒绝同一运行、跨项目、缺少执行记录和不兼容执行类型；前端按服务端分页展示结果与全量计数。
- 执行历史可将新失败幂等创建并关联缺陷。新增 `/bugs/{bug_id}/verification-tasks`，验证请求固定来源缺陷/失败执行/用例，复用普通任务审批与调度；不满足安全前置条件时拒绝创建，初始运行快照原子写入来源引用，不自动关闭缺陷。

## 新增与扩展接口

- `GET/POST /projects/{project_id}/task-templates`
- `PUT/DELETE /task-templates/{template_id}`（DELETE 停用模板）
- `GET /tasks/inbox`、`GET /tasks/summary`
- `GET /test-runs/compare?baseline_run_id=…&candidate_run_id=…`
- `POST /bugs/{bug_id}/verification-tasks`
- Web 用例列表支持 `keyword` 与 `confirmed_only`；安全策略列表支持服务端 `keyword`。原有任务、执行、审批、权限和路由继续复用。

## 验证状态

| 验证 | 结果 |
|---|---|
| 前端 ESLint | 通过：`npm run lint` |
| TypeScript | 通过：`npm run typecheck` |
| 前端测试 | 通过：14/14，包含原路由回归 |
| 前端生产构建 | 通过：`npm run build` |
| 任务后端集成测试 | 通过：`tests/test_35_tasks.py` 15/15 |
| Agent 选择与 Web 搜索集成测试 | 通过：6/6 |
| Python 编译和 Alembic heads | 通过：`compileall`；当前 head 为 `0030` |
| Alembic 数据迁移 | 通过：完整迁移及 0029→0030 既有项目记录保留检查 |
| 浏览器验收 | 通过：1440/1024/768/390 视口；任务创建、详情、审批、API 执行和报告完成。详细步骤见验收记录 |
| Git 差异空白检查 | 通过：`git diff --check` |

浏览器与集成测试使用一次性本地数据库、确定性模型替身及本地目标端点。它们验证应用接口与 UI 工作流，不代表外部模型质量、生产网络或扫描器验收。相关后端测试包含已有 Starlette/AnyIO 弃用告警和 Pydantic `schema_json` 字段告警；没有测试失败。

本次实施未触碰既有未跟踪 `.idea/`。没有运行全仓库全部后端测试；本次定向覆盖如上。

第二轮整改（R1–R9）另见 [`agent-ui-followup-delivery.md`](agent-ui-followup-delivery.md)，本轮结果与历史记录分开维护。
