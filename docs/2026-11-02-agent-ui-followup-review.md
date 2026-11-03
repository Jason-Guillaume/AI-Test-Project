# Agent 工作台优化后复审

日期：2026-11-02。依据当前工作区实现，复核上一版方案与交付说明。

## 结论

导航、选择校验、任务模板、收件箱和运行对比已有实际实现，但仍有执行配置丢失、待办漏报、项目上下文残留、重试幂等及 UI 要求未落实的问题。现有 A–D 全部完成的标记需要按下述缺口重新核验。

本次仅新增复审报告，没有修改产品代码。执行了前端现有测试与类型检查，以及两个不连接业务数据库的最小复现。5173/8001 未发现监听服务，未进行本次登录态浏览器验收；没有重新执行数据库集成测试，不把历史验收结果当成本次通过。

## 1. [P1] 模板/再次执行预设的 Agent 会在折叠状态提交时丢失

位置：`frontend/src/widgets/task-assistant/TaskCreateModal.tsx:652–660`；相关预填在 265 行起，模板更新在 689 行附近。

触发：首次打开创建弹窗，套用配置了 `agent_definition_id` 的模板，或对指定 Agent 的任务再次执行；不展开“高级设置”，直接创建或更新模板。

原因：预填使用 `form.setFieldsValue` 将 Agent ID 放入 store，但该字段位于默认关闭、未设置 forceRender 的 Collapse 中，首次没有挂载注册。当前 rc-field-form 的 `validateFields()` / submit 默认只返回注册字段。`onFinish` 和更新模板分支直接使用这些值。

影响：新任务无声地改用默认编排；更新模板还可能把原 Agent 配置保存为空。用户仅仅展开一次高级设置就会改变提交结果。

验证：使用项目当前安装的 `rc-field-form/lib/useForm` FormStore，注册 goal 字段，预填 goal 与 agent_definition_id=42，调用 validateFields：

```json
{"stored":{"goal":"模板目标","agent_definition_id":42},"submitted":{"goal":"模板目标"}}
```

同时检查当前 rc-collapse/PanelContent，关闭且未 forceRender 时确实返回 null。这是依赖行为的最小复现，不是完整浏览器操作录像。

建议：确保需要提交的字段始终注册，或验证后从完整 store 按明确 DTO 白名单构建请求，保留类型切换的清理语义。新增“未展开高级设置也保持模板/重跑 Agent”和“更新模板不丢 Agent”组件行为测试。

## 2. [P1] 模型配置阻塞不会进入待我处理

位置：`backend/app/orchestration/tasks/services/inbox_service.py:17–22`。

触发：任务主模型和备用模型多次失败，达到重试上限。

真实写入：`runtime/completion_service.py:152–156` 写入 `status='PAUSED'`、`stage='WAITING_MODEL'`。收件箱 CATEGORY 却比较 `TaskRun.status == 'WAITING_MODEL'`，因此真实任务被 CATEGORY.isnot(None) 排除，模型阻塞计数也为 0。列表正文的分类分支同样需要修正。任务详情 nextStep 也有相同 status/stage 混用。

验证：直接导入当前 CATEGORY，编译成 SQLite SQL，在独立内存库放入上述真实状态组合，输出：

```text
runtime_status=PAUSED, runtime_stage=WAITING_MODEL, inbox_category=None
```

已有测试 `backend/tests/test_35_tasks.py:173–182` 直接制造 `status='WAITING_MODEL', stage='PLAN_REVIEW'`，与运行时不一致，因此无法发现问题。

建议：按真实 status/stage 组合统一分类，并由模型失败路径产生状态后验证待办、计数与恢复入口；不要只修改测试里的期望值。

## 3. [P1] 创建任务/新缺陷的失败重试会绕过幂等保护

位置：`frontend/src/widgets/task-assistant/TaskCreateModal.tsx:225–230`；`frontend/src/pages/console/TestManagement/ExecutionHistory.tsx:108–117`。

触发：服务端已经提交创建，但响应超时/断网，用户在保留的表单中再次点击提交。

原因：每次 mutationFn 都用当前时间和/或随机数生成新 request_key，第二次请求不会命中第一次的幂等记录。后端按 request_key 去重；缺陷的新建分支也没有按同一来源自动复用旧缺陷。

影响：一次用户意图可能变成两个独立任务或两条缺陷。按钮 loading 只能减少同时点击，不能解决“已落库、响应未知”的重试。

建议：在一次提交意图建立时生成并保存键，未知结果的同内容重试复用原键；内容变化、新建意图或确认成功后再更换。补“服务端提交成功但客户端没有收到响应”的回归，不能只测两次手工传相同键。

## 4. [P2] 运行对比切换项目后保留旧项目结果

位置：`frontend/src/pages/console/TestManagement/ExecutionHistory.tsx:91–101`。

触发：在项目 A 打开运行对比，然后使用顶栏切换到项目 B。

原因：baselineRunId、candidateRunId、comparisonDefaultsSet 和缺陷处理状态未随项目变化清理；对比 queryKey 不包含项目，enabled 也不要求当前项目与结果项目一致。布局 Outlet 不随项目重挂载。

影响：B 的执行历史旁边仍显示 A 的对比；证据链接却使用 currentProjectId=B，创建缺陷也把 B 与 A 的失败执行混合，触发错误或误导。后端项目校验仍在，这不是已证实的权限绕过。

建议：项目切换同步隔离对比、分页和缺陷弹窗状态，对返回的 project_id 再做一致性检查；只有当前项目的两次运行可提交。补 A→B、清空项目及请求中切换项目场景。

## 5. [P2] 停用模板的“套用或编辑”入口进入空表单

位置：`frontend/src/pages/console/Tasks/TaskTemplatesPage.tsx:53`；`frontend/src/widgets/task-assistant/TaskCreateModal.tsx:146–150,364–370`。

触发：模板列表展示停用模板，点击其“套用或编辑”。

原因：列表使用 include_inactive=true；弹窗为预填读取的模板列表不包含停用模板，找不到 initialTemplateId 后直接 return，没有错误提示。

影响：用户进入没有预填的创建表单，不能通过这个入口编辑停用模板，还可能误以为配置已丢失。当前模板编辑也没有改名和修改说明的 UI，更新请求始终取 selectedTemplate 的旧名称与说明。

建议：区分套用与编辑，停用模板不可套用但可以读取并编辑；按 ID 读取模板且明确处理不存在/无权限，提供名称与说明编辑。启停操作避免以列表旧快照整体覆盖配置。

## 6. [P2] 结构化结果与中等宽度布局仍未按方案完成

位置：`frontend/src/pages/console/Agent/AgentWorkspacePanel.tsx:85–91`，及其分析/执行分支；`frontend/src/pages/console/Agent/AgentPanels.tsx`；`frontend/src/styles/workspace.css:8,21`。

Agent 计划、分析和执行结果仍默认直接 JSON.stringify；没有方案要求的目标/范围/环境/失败证据摘要与折叠原始数据。对话消息同样仍输出原始结构。因此主要功能增加了，但用户感受到的阅读负担没有完全解决。

布局仍是 220px 会话 + 对话 + 320px 工作区，容器 ≤1100px 直接变为三选一面板；没有落实中等宽度的对话加可收起结果栏。审核动作已经移到工作区，这部分已改善。

建议：补结构化业务摘要，原始数据仅放详情；实现可收起会话与结果区域，实际验收 1440/1024/768/390px。这里是源码确认的设计缺口，不声称已经目测到具体像素溢出。

## 其他已定位但次于上述问题的缺口

- `TaskInboxPage.tsx` 项目变化不重置 page：在 A 的后续页切到任务较少的 B，可能显示空列表但顶部计数非零。
- `task_service.py:303–310` 验证任务的 request_key 命中分支只核对项目与来源，不比较 environment_id；同键换环境会返回旧环境任务。前端 BugVerificationPanel 失败后保留键，改变环境却不重置，正好可以触发该情况。应对请求体变化返回冲突或建立新意图，不能静默复用不同环境。
- 模板 update 用读取 version 后 `+=1`，没有并发版本条件或行锁；两位成员同时更新可能丢失修改并得到相同版本。共享模板应增加乐观锁或等效串行化，并提示冲突。
- 已有交付文档没有保存在仓库的浏览器截图；自动化用例也未覆盖此次发现的折叠表单、真实模型阻塞、跨项目对比和未知响应重试。当前测试通过不等于完整验收。

## 本次验证与建议顺序

| 检查 | 本次结果 |
| --- | --- |
| frontend / npm test | 14 passed，0 failed |
| frontend / npm run typecheck | 通过 |
| 未注册折叠字段提交实验 | 复现预填 Agent ID 被漏掉 |
| 收件箱 CATEGORY 内存 SQL 实验 | 复现真实模型阻塞状态被漏掉 |
| 产品浏览器、数据库集成、外部模型 | 本次未运行 |

先修 1–4，补行为回归，再完成模板管理和结构化 UI。完成后更新 A–D 交付状态，并重新做关键浏览器流程验收。暂不建议继续扩展新的业务模块。
