# 前端全量重构与后端收尾交付

日期：2026-10-30。交付依据为 24 号计划、25 号执行提示词及本次工作区源码。原工作区在实施前已有大量未提交文件；没有执行 reset/checkout、没有提交，也没有覆盖整个工作区的自动回退。

## 实际迁移清单

174 个 U0 基线源码文件均已在 [逐文件实际迁移账本](frontend-refactor-validation/frontend-actual-migration-ledger.json) 中有目标：102 个保留原路径，54 个移动，18 个拆分。当前源码清单、行数和 SHA-256 在 [当前文件清单](frontend-refactor-validation/frontend-current-file-inventory.json)；可用 `build_actual_ledger.py` 重建。当前清单记录 245 个 TS/TSX/CSS/MJS 源文件、41,997 行；没有手写 TS/TSX 文件超过 500 行。

主要拆分与归属如下：

| 原职责 | 实际模块 |
|---|---|
| 应用与会话 | `src/app/App.tsx`、`src/app/providers/*`、`src/app/router/*`、`src/shared/session/sessionLifecycle.mjs`、`src/shared/api/client.ts` |
| API 与 DTO | `src/features/*/api/`、`src/features/*/contracts.ts`；身份、Mock、报告、通知、任务、Web 测试等均按领域归位；公共 API 合同在 `src/shared/api/contracts.ts` |
| 治理与测试资产 | `src/pages/admin/AgentGovernance/*`；`src/pages/console/TestManagement/TestAsset{Workspace,Dialogs,EditTabs,ExecutionTabs}.tsx` |
| Agent / Web UI Agent | `src/pages/console/Agent/AgentPanels.tsx`、`AgentWorkspacePanel.tsx`；`src/pages/console/WebUIAgent/webAgentPanels.tsx` |
| 报告 / 执行详情 | `src/pages/console/Reports/Report{Overview,Workspace,SummaryPanels,FailureClusterGrid}.tsx`；`src/widgets/execution-detail/ExecutionDetailPanel.tsx` |
| 安全 / ZAP | `src/features/security-testing/zap/{api,contracts}.ts`；安全用例 `PlanPreviewModal.tsx`、策略 `StrategyFormModals.tsx`/`SecuritySettingModal.tsx`；ZAP `ScanProfiles.tsx`、`AuthProfiles.tsx`、`panels/*` |
| Mock | `src/pages/console/MockManagement/components/*`、`ScenarioTestDrawer.tsx`、`scenarioFormUtils.ts` |
| 公共层与样式 | `src/shared/lib/*`、`src/shared/ui/*`、身份状态 Tag、feature 专属状态映射；`src/styles/{base,workspace,admin,authentication,responsive}.css` |

关键行为改动包括：会话身份代次变化时屏蔽过期请求响应，重复 401 过期通知去重，登录接口 401 保留给登录表单。对应行为测试在 `frontend/tests/sessionLifecycle.test.mjs`、`staleSessionRequest.test.mjs`。另增加所有原路由声明承接检查 `frontend/tests/frontendRoutes.test.mjs`。

### 后端 C05

新增 `backend/app/platform/agent_governance/services/usage_query_service.py`。治理 Router 从该只读查询读取 Skill 使用统计；保留统计计数、distinct TaskRun 数、最新时间、最近十条和不存在 Skill 的 404。`agents/services/reference_service.py` 中纯代理移除，引用保护逻辑留在 Agent 域。新增统计集成测试 `backend/tests/test_36_agent_governance_details.py::test_skill_usage_read_model_counts_distinct_runs_and_limits_recent_tasks`。

C08–C12 按已有边界决定核验并保留：延迟导入执行分派；TestCaseMock 声明仍归 Mock；readiness 保持只读；密文包装差异保留；HTTP/LLM 继续通过公开平台配置查询契约。没有为目录整齐增加注册器、operations 空包、通用密文服务或纯转发层。没有变更 DB schema、Alembic 迁移或真实数据。

## 验证结果

| 验证 | 结果 |
|---|---|
| `cd frontend && npm test` | 12 passed，0 failed。覆盖原路由声明、分页失败行为、安全同站跳转、会话代次、迟到响应和 CSS 主题。 |
| `cd frontend && npm run lint` | 通过，`--max-warnings=0`。 |
| `cd frontend && npm run typecheck` | 通过。 |
| `cd frontend && npm run build` | 通过；Vite 转换 3330 modules。产物明细见 `frontend-refactor-validation/frontend-assets-current.json`。 |
| `cd frontend && npm ls --depth=0` | 通过；`@ant-design/icons@5.6.1` 为直接依赖。 |
| 结构扫描 | 236 个 TS/TSX/MJS 输入、919 条本地导入边、0 个循环、0 个 shared 反向依赖、0 个 feature→page 依赖。脚本和结果见 `check_frontend_structure.py`、`frontend-structure-current.txt`。 |
| 路由承接 | 基线与当前各 46 个 `<Route>` 声明，测试确认原路由路径全部仍注册；这是静态承接检查，不等同于所有受保护页面的登录态浏览器链路。 |
| 浏览器 | 本地 Vite 登录页 `/login` 打开并检查了可访问树/布局；没有可用的项目账号、测试数据库或受支持的视口控制，因此没有声称保护页和 1440/1024/768/390 px 完成验收。 |
| 后端 Python | 修改模块 `compileall` 通过；pytest collection 从 1062 增至 1063，新增集成测试已发现。结果见 `backend-collection-current.txt`。 |
| OpenAPI | 基线与当前均为 269 paths / 418 method operations；path/method、参数、请求体、响应与安全声明没有变化。7 个 Mock runtime methods 的 `operationId` 因同一路由多方法定义从旧的 `..._get` 变为 `..._head`，仍有 FastAPI duplicate-operation-id warning；这是文档元数据差异，不是 HTTP 路径/方法契约变化。当前和基线 JSON 均在验证目录。 |

### 未能完成的验收

- 没有执行完整后端 pytest，也没有运行新增数据库集成测试：本地隔离测试 PostgreSQL 端口不可用。一次连接尝试在 sandbox 层因 `Operation not permitted` 被阻止；没有连通 5432，也没有触碰开发/生产库。需在隔离 DB 可用时重跑：`cd backend && .venv/bin/python -m pytest tests/ -q`。
- 浏览器只有登录页可用。所有需会话、项目数据、后端响应的核心路由、审批、下载和真实交互没有端到端验收；四个指定视口也没有实际测量。当前静态路由检查不能替代这些检查。
- 有构建后的当前资源清单，没有 U0 同环境的 `dist` 构建产物，无法据此计算资源增幅或路由加载前后差异。当前 JS 资源为 137 个、2,221,697 bytes（未压缩）；当前清单只作为后续对比基线。
- 未执行真实 ZAP 扫描；未对外部目标发起请求。

## 回退说明

本次没有提交或自动执行回退；实施开始时工作区已存在大量未提交成果。不能用 `git reset --hard`、全局 `git checkout` 或整份 `git apply --reverse` 回退，否则会覆盖用户之前的变更。当前 U0 证据包含文件哈希与路径，不包含所有原始文件内容；工作区没有完整的实施前副本，因此不能安全生成一个会自动还原所有变更的全局回退补丁。

若需要回退，请先另存当前工作区差异与未跟踪文件，再仅按实际迁移账本处理本次文件：从独立的实施前备份恢复被拆分的入口文件，只删除账本中确认由本次新增且没有其他引用的目标文件；后端只恢复本次 C05 涉及的 Router、reference service、Agent service facade、usage query service 与新增测试。若没有独立实施前副本，应保留当前状态并按模块逐项人工回退，不能从仓库 HEAD 覆盖已存在的用户成果。
