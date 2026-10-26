# 阶段交付记录

更新日期：2026-10-26。当前交付：P0–P3 首个 API 任务闭环。P4–P6 尚未交付。

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
1004 passed, 46 warnings in 275.09s
```

任务定向集 `.venv/bin/python -m pytest tests/test_35_tasks.py -q`：`3 passed`。全量回归期间曾捕获任务详情在多个 READ COMMITTED 查询间跨过 Planner 提交时可能返回混合状态；已调整详情组装并复跑全量通过。

`tests/test_35_tasks.py` 的真实 API 闭环使用本地受控 HTTP StubServer，但任务 API、PostgreSQL 迁移与调度、项目出站白名单、既有 RunService / TestRun 执行链和 ReportService 都是真实实现；它验证了 TestPlan、TestSuite、TestRun、TestReport 资产和管理页反向关联。测试只替代外部 LLM HTTP 边界以提供确定性输出；未验证生产模型连接、回答质量或真实供应商兼容性。该文件还覆盖目标更新产生新运行、人工方案批准、暂停/恢复、Planner 失败重试、取消、请求/消息/命令幂等和组织授权撤销。

前端验证：`npm run typecheck` 通过；`npm run build` 通过。构建报告 Vite 主包分块超过 500 KB 的警告，未阻断构建。新增后端代码及集成测试 `compileall` 通过。后端和前端测试产生的 Starlette / Pydantic 警告与既有组件有关。

## 未完成与限制

- **P4 未完成**：没有 UI Worker、浏览器任务资源归属/恢复适配、安全测试 Worker 或 ZAP 任务适配器；审阅目前只做证据与计数校验，没有有限预算返工、重审和依赖结果汇总。旧 Web 与安全入口保留且上述回归通过，但不能据此宣称任务集群已接入它们。
- **P5 未完成**：没有 Agent / Skill / Tool 配置中心、草稿/发布版本、任务模板选择、文件上传和解析；当前角色 Skills 为空，同一运行各角色使用任务创建时绑定的一个授权模型，不提供按职责配置不同模型。
- **P6 未完成**：没有任务功能开关、灰度/停止新派发、旧 AgentSession 适配、并发压测或部署/回滚演练。
- 本轮没有用进程强杀来验证租约过期恢复，也没有并发多调度器压力测试。API 工具在外部副作用回执不明时会停止自动重试并要求到执行中心核对；当前未提供一个在任务界面登记该人工核对结论的专用恢复命令。
- 页面目前没有浏览器端到端自动化验收。真实 LLM 服务、文件解析以及生产目标的外部访问均未在本次验证范围内。

## 后续步骤

按计划先补 P1 中断/租约恢复与多调度器并发验证和人工回执核对入口；然后实施 P4 的 UI 与 ZAP 适配、有限返工协议及对应真实业务服务测试，再实现 P5 配置版本与受控文件解析，最后完成 P6 灰度、兼容、压力和回滚演练。每阶段更新本记录并列出相应迁移、契约、测试和限制。
