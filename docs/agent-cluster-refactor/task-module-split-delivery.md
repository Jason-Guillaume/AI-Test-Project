# 任务模块拆分交付记录

日期：2026-10-28。实施范围：T0–T3；后续按用户要求开始统一任务前端首轮拆分。T4–T6 不在本轮范围。

## 交付状态

任务查询、纯响应转换、项目访问检查、消息处理、资源引用及报告/审阅处理已迁入职责模块；`TaskService` 和 `TaskWorker` 继续作为兼容入口和运行协调器。没有修改接口/schema、数据库结构或依赖版本，也没有重做 core、Agent 或执行器。

开始时工作区有大量已有未提交改动，任务文件本身已包含 Agent 组装和 core 导入迁移。实施前读取并保留这些改动，只在其上完成任务拆分和必要调用接线，没有重置工作区。

## 统一任务前端：首轮页面拆分

列表与详情从单个 `frontend/src/pages/console/Tasks/index.tsx` 拆为职责模块；路由改为直接懒加载页面组件。详情编排页从约 550 行缩减为 286 行，持有 URL、React Query 轮询、缓存刷新、命令确认和消息 mutation；运行面板只接收已加载数据和显式回调，不自行请求数据或改变控制边界。

| 原职责 | 拆分路径 | 说明 |
|---|---|---|
| 任务列表和创建入口 | `frontend/src/pages/console/Tasks/TaskListPage.tsx` | 保留项目作用域、分页、5 秒刷新、URL 预填创建语义和既有创建弹窗。 |
| 运行详情查询与命令编排 | `frontend/src/pages/console/Tasks/TaskDetailPage.tsx` | 保留 `['tasks']`、`['task-run']`、消息/事件/资源 queryKey，续读游标与终态刷新；暂停、继续、取消、批准、重试及人工高风险确认仍走原调用。 |
| 参与者、会话、方案、调度和产物面板 | `frontend/src/pages/console/Tasks/TaskRunPanels.tsx` | 仅接收详情数据与消息/运行命令回调，视图按职责集中。 |
| 消息、事件与资源链接展示 | `frontend/src/pages/console/Tasks/TaskDetailActivity.tsx` | 复用既有会话、事件与业务产物地址。 |
| 状态文案和视图快照字段 | `frontend/src/pages/console/Tasks/taskLabels.ts`、`taskTypes.ts` | 提取列表/详情共用映射及后端输入快照的局部视图类型，不改 wire schema。 |
| 页面路由 | `frontend/src/App.tsx` | 直接懒加载 `TaskListPage.tsx` / `TaskDetailPage.tsx`；纯 re-export 的 `Tasks/index.tsx` 已删除。 |

本轮只拆统一任务页面，不声称治理、测试资产或其他前端页面已拆分；未做浏览器端交互/E2E 或视觉回归。

## T0：基线与失败复核

| 检查 | 实测结果 |
|---|---|
| 拆分前任务相关回归：`tests/test_35_tasks.py tests/test_task_notifications.py tests/test_36_agent_governance_details.py` | `22 passed, 13 warnings`，24.08 秒。使用本地 PostgreSQL 上唯一命名的隔离测试库；未连接或修改 `testplatform_dev`。 |
| 拆分前定向 Langfuse 回归：`tests/test_27_langfuse_tracing.py` | `7 errors`；autouse fixture 调用 `app.agents.providers.langfuse_tracer._build_client.cache_clear()`，规范实现未提供 `_build_client`，错误均在用例执行前发生。归类为已有测试替身与现有 Langfuse 实现不匹配，本轮不为 tasks 拆分改写 Agent 追踪行为。 |
| 拆分前独立 Agent 运行变量预览用例 | `1 passed`。 |
| 拆分前任务、通知与治理用例收集 | `22 tests collected`，无收集错误。 |
| 既有全量后端记录 | [core 归并交付记录](core-consolidation-delivery.md)记载 `947 passed, 69 failed, 13 errors`；其中包括 Agent 节点误收集、Langfuse setup 错误及 ZAP/Web 相关失败。该历史数值不作为本轮实测，本轮全量结果见下文。 |

拆分过程中新增的审阅事实用例首次发现“安全评估缺失时只追加发现、未否决模型批准”的回归；已在审阅事实核验中恢复确定性否决，并通过定向用例。报告 API/Web 链路首次验证发现资源引用适配器遗漏 `version=None`；已修复并通过任务链路回归。

## T1：访问、查询和响应转换

| 原入口 | 唯一实现 | 兼容方式 |
|---|---|---|
| `TaskService._get_project_for_read/write`、`_get_task_for_read`、`_get_run_for_read/write` | `backend/app/features/tasks/services/access.py` | 原方法保留并转发；读写门槛、404 隐藏、run 行锁不变 |
| `list_tasks`、`get_task`、`get_run_detail`、`list_messages`、`list_events`、`_latest_runs` | `backend/app/features/tasks/services/query_service.py` | `TaskService` 原公开/私有方法保留并转发；分页、排序、游标和最新运行行为保留 |
| `_task_response`、`_run_response` | `backend/app/features/tasks/services/serializers.py` | 原方法保留并转发；字段名与 Agent 快照脱敏保留 |

查询服务只读，不提交事务；访问校验仍在 service 层。`get_run_detail` 保留 Planner 提交期间的最后一次运行状态刷新。

## T2：消息和资源引用

| 原入口 | 唯一实现 | 保留行为 |
|---|---|---|
| `TaskService.send_message` | `backend/app/features/tasks/services/message_service.py` | 客户端消息键冲突检查、接收者校验、运行行锁、消息/事件/工作项原子提交、目标更新新建运行；运行创建与工作入队通过明确窄回调协调 |
| `TaskService.list_resources/find_tasks_for_resource` 与响应/名称转换 | `backend/app/features/tasks/services/resource_service.py` | 项目可见性过滤、来源反查排序/上限、按类型批量加载名称，避免 N+1 |
| `TaskService._add_resource_ref`、`TaskWorker._add_resource_ref` | `TaskResourceService.add_resource_ref/add_worker_resource_ref` | 两类既有元数据语义分别保留；唯一键命中复用；不单独提交，归属调用方事务 |

消息的 `db.commit()` 仍在消息、事件、工作项和可能的新运行写完之后执行。用户消息重复提交复用原 `created_run_id`，不重复创建运行；人工方案确认与控制命令未迁移。

## T3：报告与审阅处理器

| 原处理入口 | 当前实现 | Worker 保留职责 |
|---|---|---|
| `TaskWorker._handle_report` | `backend/app/features/tasks/runtime/handlers/reporting.py` | 保留薄兼容转发；报告处理真实调用既有 `build_test_report` |
| `TaskWorker._handle_review` | `backend/app/features/tasks/runtime/handlers/reviewing.py` | 保留薄兼容转发；外层继续负责完成/失败、租约和工作项控制 |
| 可信输入与运行能力 | `backend/app/features/tasks/runtime/contracts.py` | Worker 装配 task/run/work/attempt/agent/actor；只传模型 provider、入队、资源、事件和控制边界等窄能力 |

报告仍先以 `report:<test_run_id>` 写入 `STARTED` 回执并提交，再调用正式报告服务；之后写成功回执、报告资源引用、消息、审阅工作项依赖和事件。没有新增回执 key 或改变正式业务产物归属。

审阅使用 TestRun、正式报告、已批准方案、批准用例范围和安全发现作为事实。只有模型结论、执行覆盖、报告计数及安全执行事实全部满足时才允许通过；模型调用后仍刷新运行并检查暂停/取消边界，之后才创建 finalize 工作项。高风险人工确认仍由既有 `APPROVE_PLAN` 命令负责。

## 兼容入口与依赖方向

- `services/__init__.py` 继续导出 `TaskService`，并增加 access/query/serializer/message/resource 专用服务导出。
- Router、公开 schema、端点、错误信封及返回字段均未改；原 `TaskService` 方法保留转发，Worker 的 `_handle_report/_handle_review` 保留薄转发。
- handler 不导入 TaskService 或 TaskWorker；通过 `TaskHandlerContext` 和 `TaskHandlerServices` 取得可信上下文及少量显式能力。
- 任务运行领取、续租、暂停/取消、完成/失败、方案批准和其他处理器仍留在原文件；没有提前建设 T4–T6 空壳。
- 无 Alembic 迁移、数据库结构变化或新依赖。

## 验证结果

所有涉及数据库的用例都通过 fixture 使用本机 PostgreSQL 上带唯一后缀的 `testplatform_task_split_*` 测试库；全量库在创建前经只读查询确认不存在，fixture 只创建并清理本次全量测试库。未使用 `testplatform_dev`。

| 命令/检查 | 结果 |
|---|---|
| `python -m compileall -q app/features/tasks` | 通过。 |
| tasks 服务/handler/Worker 导入与 Worker 窄协作合同实例化检查 | 通过。 |
| `TEST_POSTGRES_PASSWORD=not-used python -m pytest tests/test_task_module_split.py -q` | `4 passed, 1 warning`；不请求数据库 fixture。 |
| 拆分后任务、通知、Agent 治理与新增事实测试：`python -m pytest tests/test_35_tasks.py tests/test_task_notifications.py tests/test_36_agent_governance_details.py tests/test_task_module_split.py -q` | `26 passed, 13 warnings, 23.76s`；覆盖项目越权 404、目标更新重复提交、暂停/恢复、真实 TestRun/报告/审阅与资源回链。 |
| 后端全量回归：`python -m pytest -q` | `952 passed, 68 failed, 13 errors, 92 warnings`，310.69 秒；全量未通过。 |
| `git diff --check`（任务代码与测试） | 通过。 |

### 前端首轮验证

| 命令 | 结果 |
|---|---|
| `npm test` | `6 passed, 0 failed`。 |
| `npm run typecheck` | 通过。 |
| `npm run lint` | 通过。 |
| `npm run build` | 通过；Vite 转换 3302 个模块并完成生产构建。 |
| `git diff --check -- frontend/src/pages/console/Tasks` | 通过。 |

## 后续旧路径转发文件清理（2026-10-29）

根据后续要求，移除了仅用于兼容旧导入路径的源文件，并将活跃调用点迁到规范实现：`app.shared`/`app.models`、旧 `features.agent` 与治理转发文件、已迁移的脱敏/子 Agent 路径、Feature 访问服务旧转发文件，以及 Agent、MockManagement、Reports、Tasks、TestManagement 的前端 re-export 页面入口。前端路由现在直接懒加载实际页面组件。

保留真正有业务逻辑的治理 HTTP 路由、ZAP 访问服务和规范实现；`TaskService`/`TaskWorker` 的方法级委托继续作为原接口的一部分。旧路径文件清理不改变 API、权限、事务、报告回执、人工确认或暂停/取消语义。历史 core 和 T 阶段记录中的兼容入口表描述的是清理前状态，当前状态见[core 归并交付记录](core-consolidation-delivery.md)本次清理一节。

| 清理后验证 | 结果 |
|---|---|
| 后端编译及核心/任务导入测试：`compileall -q app alembic/env.py scripts tests`；`pytest tests/test_core_consolidation.py tests/test_task_module_split.py -q` | 编译通过；`7 passed, 1 warning`。 |
| 两个旧目录断言迁移后的定向测试 | 初次发现旧断言还读取 `app/models/__init__.py`；已改为检查旧 Python 源文件已清理且 Feature 模型不进入 core 注册表，复跑 `2 passed, 1 warning`。 |
| Agent 契约导入路径收口：`pytest tests/test_16_agent.py tests/test_20_test_data_lifecycle.py -q` | 移除 `app.agents.schemas` 的通配转发，将节点与测试改为直接导入工具契约；`41 passed, 13 warnings`。 |
| 前端 `npm run typecheck`、`npm run lint`、`npm test`、`npm run build` | 均通过；`npm test` 为 `6 passed`，Vite 构建成功。 |
| 清理后的后端全量回归：`python -m pytest -q --tb=no` | `958 passed, 68 failed, 3 errors, 79 warnings`，450.40 秒；未通过。全量运行使用单独数据库 `testplatform_compat_final_20261028_2f0b`，创建前只读确认不存在，未使用 `testplatform_dev`。此全量结果在最后一处 Agent schema 通配导入收口之前取得；收口后重新运行了受影响的 Agent 和造数模块，41 项通过，未再次跑全量。 |
| 全量失败归类 | 3 个 errors 是 pytest 将 3 个 Agent node 函数当作测试收集，缺少 `ctx` fixture。68 个 failures 主要集中在 ZAP 路由/API（创建目标接口返回 404）、ZAP/Agent 审批、Web UI 流程及一个治理 Skill 用例；失败均需独立复核，未据此宣称全通过。 |
| `git diff --check` | 仅报告 4 个服务聚合文件末尾空行，均为本轮前已有未提交改动，本轮未修改。 |

### T0–T3 阶段全量失败分类（兼容文件清理前）

当时 13 个 errors 中，6 个来自 Agent node 源文件被 pytest 当测试收集并请求不存在的 `ctx` fixture，7 个来自 Langfuse fixture 调用不存在的 `_build_client`；这两类均在拆分前已分别由定向复现确认。68 个 failed 主要集中在已有 ZAP 路由/Agent 审批与 Web 流程；代表性失败是 `tests/test_29_zap_scan.py::TestScanTarget::test_create_read_patch_delete` 预期 201、实际 404。那次没有在拆分前复跑全量，因此未把 68 项逐一断言为基线失败。拆分后任务/通知/治理及事实核验定向组 26 项通过；报告和资源接线中途发现的两处新增问题均已修复并由该组复验通过。

### 失败与未测项归类

- **本轮已修复的失败：** 报告资源写入口漏传默认版本、审阅安全事实缺失未否决模型批准；修复后相关定向组全绿。
- **已复现基线失败：** Langfuse 7 个 setup errors 在拆分前与全量回归中均复现；Agent node `ctx` fixture 错误在本次全量中复现，前轮全量记录也报告了同类收集问题。
- **全量仍失败但未逐项确认新旧：** 68 个 failed，主要来自 ZAP 路由/API 与相邻 Agent 审批、Web 用例；当前可核实示例为扫描目标创建返回 404。由于本轮没有在拆分前重跑全量，逐条新增/基线归属未测。
- **未覆盖的高风险边界：** 未模拟报告服务外部写入结果不明后的重试；未在模型调用期间制造暂停/取消竞争并直接断言 finalize 不入队；未对生产模型或真实 ZAP 服务做外部集成验证。代码保留原回执和 Worker 控制边界，但这些行为仍待专门故障注入用例验证。

## 后续与回退

- 后续阶段：T4 运行创建/方案批准/控制命令服务；T5 其他角色处理器；T6 租约/恢复/完成协调；继续评估并拆分治理、测试资产等前端大页面。
- 数据升级、全量回归基线中 Langfuse/ZAP/Web 的失败处理，以及前轮 core 交付记录中的既有库升级与数据保留验证，均独立跟踪，不由本次拆分宣称完成。
- 回退只恢复 `TaskService`/`TaskWorker` 对应委托及实现映射，不删除业务运行数据和正式报告，不改回执 key；本轮无 schema 变化，不做数据库 downgrade。回退前需保留工作区原先已有的其他改动。


后续入口（2026-10-29）：[后端综合职责拆分 B0–B9](backend-comprehensive-delivery.md)。本文历史范围、结果与限制保持原事实。
