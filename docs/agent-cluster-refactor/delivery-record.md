# 阶段交付记录

更新日期：2026-10-26。已合并交付：P0–P3 首个 API 任务闭环。当前分支新增 P4 的 Web 正式用例和 ZAP 队列适配部分；P4 其余协作能力及 P5–P6 尚未交付。

[返回设计文档索引](README.md)

## P0–P3 已实现

| 阶段 | 实际交付 |
|---|---|
| P0 契约与边界 | 新增统一任务、运行、计划、工作项、依赖、参与者、尝试、消息、命令、事件、资源引用、工具回执与调度控制模型；约束任务目标更新、计划人工批准、消息接收和工具权限。新任务在创建时绑定当前授权模型；后台每轮模型调用及 API 副作用前复查用户、项目角色、组织智能体开关、模型白名单与模型启用态。 |
| P1 运行底座 | Alembic `0015_unified_tasks`；PostgreSQL 持久队列、行锁领取、数据库并发额度、租约心跳、事件游标、暂停/恢复/取消、失败重试、幂等键与不确定 API 回执转待核对。应用生命周期启动/停止调度线程。 |
| P2 任务内团队与 API | 每个运行创建独立 MAIN、PLANNER、API_WORKER、REPORT_AGENT、REVIEWER 实例，会话消息、模型 ID、配置快照、Skills 列表和工具白名单分开保存。Planner 生成版本化方案，必须由用户显式批准后才执行；API Worker 仅能选取批准的 API 用例，并调用原有执行服务创建 TestPlan、TestSuite、TestRun；Report Agent 通过原 ReportService 创建或复用 TestReport；审阅者核对报告与 TestRun 的覆盖和统计。 |
| P3 产品界面 | 增加任务列表/详情页、左侧参与者和右侧会话布局、目标调整、指定 API Worker 补充要求、方案确认、任务命令、产物与事件、Console 全局调度抽屉；现有测试资产页可发起任务，执行记录和报告可反查任务来源。原有管理路由及业务表保留。 |

交付代码入口：`backend/app/features/tasks/`、`backend/alembic/versions/0015_unified_tasks.py`、`frontend/src/pages/console/Tasks/`、`frontend/src/components/tasks/`、`frontend/src/api/tasks.ts`。

## 实际验证

在后端隔离测试数据库中运行：

```text
.venv/bin/python -m pytest tests/ -q
P0–P3 合并前：1004 passed, 46 warnings in 275.09s
P4 当前分支：1007 passed, 46 warnings in 290.81s
```

任务定向集 `.venv/bin/python -m pytest tests/test_35_tasks.py -q`：`3 passed`。全量回归期间曾捕获任务详情在多个 READ COMMITTED 查询间跨过 Planner 提交时可能返回混合状态；已调整详情组装并复跑全量通过。

`tests/test_35_tasks.py` 的 API 闭环使用本地受控 HTTP StubServer，但任务 API、PostgreSQL 迁移与调度、项目出站白名单、既有 RunService / TestRun 执行链和 ReportService 都是真实实现；它验证了 TestPlan、TestSuite、TestRun、TestReport 资产和管理页反向关联。测试只替代外部 LLM HTTP 边界以提供确定性输出；未验证生产模型连接、回答质量或真实供应商兼容性。该文件还覆盖目标更新产生新运行、人工方案批准、暂停/恢复、Planner 失败重试、取消、请求/消息/命令幂等和组织授权撤销。

前端验证：`npm run typecheck` 通过；`npm run build` 通过。构建报告 Vite 主包分块超过 500 KB 的警告，未阻断构建。新增后端代码及集成测试 `compileall` 通过。后端和前端测试产生的 Starlette / Pydantic 警告与既有组件有关。

## P4 部分实现：Web 正式用例与 ZAP 队列

本分支增加 Alembic `0016_task_security_polling`：任务保存可选安全扫描范围，工作项支持持久化下次领取时间，ZAP Job 增加任务调用方幂等键。任务创建可选择单一类型的已确认 API 或 Web 用例；Web 用例复核既有 Web 确认指纹，由 UI Worker 调用原 Web TestRun / Playwright 执行路径和报告服务。任务可绑定同项目、同环境且类型/扫描模式兼容的现有 ZAP 目标与策略。计划确认时明确记录安全扫描人工确认；主动扫描另要求既有项目编辑权限及批准说明。安全 Worker 通过原 job_service 创建关联真实 TestRun 的 ZAP Job，再对现有 ScanWorker Job 做持久轮询；报告等待扫描终态，任务取消向原 ZAP 服务发取消请求。新增任务详情与安全扫描详情的双向链接。

这是真实业务服务和数据库 Job 的适配，不是直接在任务调度线程中模拟 ZAP 扫描。集成测试断言真实 ZAP Job 保持 PENDING 时，报告工作项仍被依赖阻塞；本次没有启用真实 ZAP 服务或对目标发出扫描请求。Web 集成测试覆盖已确认 Web 用例经过现有 TestRun / Playwright 适配器的任务路径。

当前分支实际验证：

```text
cd backend && .venv/bin/python -m pytest tests/test_35_tasks.py -q
6 passed, 11 warnings in 14.83s

cd frontend && npm run typecheck && npm run build
通过；Vite 提示一个压缩后大于 500 KB 的 bundle

cd backend && .venv/bin/python -m compileall -q app tests
通过
```

```text
cd backend && .venv/bin/python -m pytest tests/test_29_zap_scan.py tests/test_30_web_ui.py tests/test_32_web_agent_runtime.py -q
124 passed, 13 warnings in 54.06s
```

该组测试和 `test_35_tasks.py` 均会先应用完整迁移。测试设置 `ZAP_ENABLED=false`，只在任务集成测试中于应用启动后开启 Job 创建服务，原 ScanWorker 仍关闭，故不会产生外部扫描流量。

## 未完成与限制

- **P4 部分完成**：当前只支持正式 API 或 Web 用例的单类型任务，不支持 API 与 UI 并行、共享账号/Fixture 资源锁或按职责并发配额。没有接入交互式 Web 编写会话的 owner/资源上限与会话恢复；浏览器句柄恢复仍未验证。审阅仍是证据/计数核验，没有有限预算返工、重审和依赖结果汇总。安全扫描必须经过人工方案确认；本轮未对真实 ZAP 部署或目标做外部验证。
- **P5 未完成**：没有 Agent / Skill / Tool 配置中心、草稿/发布版本、任务模板选择、文件上传和 PDF/DOCX/XLSX/图片解析；当前角色 Skills 为空，同一运行各角色使用任务创建时绑定的一个授权模型，不提供按职责配置不同模型。
- **P6 未完成**：没有任务功能开关、灰度/停止新派发、旧 AgentSession 适配、历史数据回填、并发压测或部署/回滚演练。
- 本轮没有用进程强杀来验证租约过期恢复，也没有并发多调度器压力测试。API 工具在外部副作用回执不明时会停止自动重试并要求到执行中心核对；当前未提供一个在任务界面登记该人工核对结论的专用恢复命令。
- 页面目前没有浏览器端到端自动化验收。真实 LLM 服务、文件解析以及生产目标的外部访问均未在本次验证范围内。

## 后续步骤

按计划继续 P4：增加交互式 Web 会话的资源 owner 与配额、API/UI 并行但资源隔离、审阅有限返工及多 Worker 依赖汇总，并对这些边界补真实业务服务测试。之后实现 P5 配置版本与受控文件解析，最后完成 P6 灰度、兼容、压力和回滚演练；再补 P1 中断/租约恢复与多调度器并发验证及人工回执核对入口。每阶段更新本记录并列出相应迁移、契约、测试和限制。
