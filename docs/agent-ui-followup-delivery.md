# Agent 工作台第二轮整改交付

日期：2026-11-02。执行范围：`docs/2026-11-02-agent-ui-followup-development-prompt.md` 中 R1–R9。基线分支 `codex/code-optimization`。本次只开发、验证并记录；没有提交或推送。

## 交付结论

R1–R9 对应代码和本轮定向回归已完成。前端测试、lint、typecheck、生产构建、隔离数据库后端回归、迁移头检查和 `git diff --check` 均通过。浏览器已验收关键数据行为、模板并发冲突以及四个 CSS 视口的布局与输入保留。

两项证据范围如实受限：浏览器截图已在验收会话中捕获并显示，但导出为仓库文件时被安全策略拒绝；没有用其它途径绕过。另未在四种 viewport 各自完整重复生成、人工审核、执行和报告流程。详细逐项结果见[进度表](agent-ui-followup-progress.md)、[浏览器验收记录](agent-ui-followup-validation/browser-acceptance.md)及[测试结果](agent-ui-followup-validation/test-results.md)。

## 实际改动

- **配置提交与重放（R1）**：在 [TaskCreateModal.tsx](../frontend/src/widgets/task-assistant/TaskCreateModal.tsx) 从表单完整 store 按后端 DTO 字段构造请求，折叠/已展开后收起都保留隐藏的 Agent 配置；主动清空、类型或项目切换时重置相关选择。旧运行的 Agent 摘要缺少定义 ID 时，重放回退到 `submitted_input.agent_definition_id`。停用或不可访问预设 Agent 不会静默降级。
- **模型阻塞待办（R2）**：新增 [inbox_service.py](../backend/app/orchestration/tasks/services/inbox_service.py)，仅将真实 `PAUSED + WAITING_MODEL` 纳入模型阻塞分类，计数和条目使用同一条件；恢复或新运行后从待办移除。任务详情显示修复路由等下一步。
- **创建幂等与未知结果（R3–R4）**：任务创建请求携带稳定 `request_key`，后端按规范化有效输入计算摘要并处理并发唯一键冲突。相同键换内容返回 409。缺陷验证摘要还绑定环境、来源缺陷与失败运行。前端只在 `sessionStorage` 记录不含表单内容的未知请求标识，避免把新内容伪装成旧请求重试。
- **数据库兼容（R3）**：新增 Alembic `0031_task_request_digest.py`，为旧任务保留兼容路径并存储新请求摘要；数据库迁移 head 为 `0031`。`0030_task_templates.py` 和模板域文件在当前工作区中也包含在既有未提交实现里。
- **项目隔离（R5）**：运行对比和收件箱在项目切换时清空旧选择/分页，迟到的异项目响应不进入当前视图；查询和操作按当前项目限定。
- **模板编辑与并发（R6–R7）**：新增按 ID 读取编辑模板和专用启停接口；停用模板可改名称、说明、配置并保持停用。更新、启停请求携带 `expected_version`，数据库以版本条件更新，旧表单冲突返回明确错误；前端保留草稿，不自动覆盖。
- **Agent 工作区（R8–R9）**：新增 [AgentSummaries.tsx](../frontend/src/pages/console/Agent/AgentSummaries.tsx)，将计划、执行和分析按实际字段渲染为业务摘要，原始 JSON 收起。工作区使用容器宽度响应式布局，中屏优先收起会话历史，小屏改用面板切换。

受影响的主要后端 API/契约：

- `POST /projects/{project_id}/tasks` 接受 `request_key`；相同键相同输入返回原任务，同键不同输入冲突。
- `GET /task-templates/{template_id}` 支持直接读取编辑目标；`GET /projects/{project_id}/task-templates?include_inactive=true` 用于编辑列表读取停用项。
- `PUT /task-templates/{template_id}` 必须携带 `expected_version`、名称、说明、配置；省略 `is_active` 时保持当前状态。
- `PATCH /task-templates/{template_id}/status` 仅改启停状态，且同样需要 `expected_version` 并推进版本号。旧表单/调用方必须按版本更新契约传参。
- 缺陷验证请求幂等标识校验环境与缺陷来源；相同键换环境返回冲突，使用新提交意图才可在新环境创建任务。

既有路由、项目权限、任务审批与人工确认边界保留。工作区原有未提交改动没有被重置；`.idea/` 与用户提供的三份需求文档均保留。

## 实际验证结果

- 前端 `npm test`：14/14 通过；`npm run lint`、`npm run typecheck`、`npm run build` 通过，构建转换 3335 个模块。
- 后端任务与缺陷来源集成回归：隔离数据库 **20 passed，13 warnings**。并发模板由两个独立数据库 session 验证。
- 后端 `compileall` 通过；Alembic 唯一 head 为 `0031`；`git diff --check` 通过。
- 响应丢失语义：本地 API 首次提交成功但丢弃响应体，同 key 重试返回原任务且只创建一次；同 key 不同内容冲突；确认完成后新意图创建新任务。
- 浏览器：创建/再次执行/模板更新的折叠 Agent 配置保留；R2 阻塞待办；A→B 对比清理和第 3 页→第 1 页回落；停用无环境模板编辑；双会话版本冲突并保留草稿；视口 1440×900、1024×900、768×900、390×844 无页面级横向溢出，390→1024 调整后输入仍保留。

**未验证**：浏览器代理主动断开第一次创建连接后的客户端超时交互；缺陷面板切换缺陷与迟到响应的完整浏览器流程；异项目慢响应的定时竞态；四种 viewport 各自的全链路 Agent 生成→人工审核→执行→报告；所有未知/极长分析字段组合；外部模型服务质量及完整全仓库后端测试。相关后端与 UI 常规分支已有定向测试或构建覆盖，不将这些未执行的情况宣称为通过。

## 截图与运行环境限制

四种尺寸的浏览器截图曾在验收会话中捕获并显示。浏览器拒绝将截图导出为工作区文件，并明确禁止换用间接方式、其它浏览器表面或原始浏览器命令绕过。因此 `docs/agent-ui-followup-validation/` 保存的是脱敏行为和尺寸记录，没有截图文件。仓库截图归档是本轮唯一明确的交付阻塞；不能把浏览器工具中的临时显示当作项目截图文件。

验收使用的开发服务进程已停止。唯一命名的隔离浏览器数据库 `testplatform_round2_browser_e8e4597b` 仍保留，其中包含本轮合成验收数据；没有清理或改动现有开发/生产数据库。
