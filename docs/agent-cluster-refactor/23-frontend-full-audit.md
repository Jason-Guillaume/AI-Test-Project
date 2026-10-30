# 前端全量结构审查与后端收尾审查

日期：2026-10-30。审查根目录：`/Users/a1/Desktop/ai-test-project`。

本文是实施前审查，配套 [24 整单优化计划](24-frontend-comprehensive-refactor-plan.md) 与 [25 执行提示词](25-frontend-comprehensive-agent-prompt.md)。本次只生成方案与证据，没有实施业务重构。

## 1. 结论与审查边界

前端需要一次覆盖目录、领域数据层、大文件、会话隔离和回归保障的综合整理。已有按路由懒加载、统一 Axios 客户端和部分页面组件拆分，不需要重建前端，也不需要更换框架。后端已完成主体拆分，本单以边界复核、契约联调和验证收尾为主。

本次读取并统计 `frontend/src/` 全部 174 个文件，对其中 171 个 TS/TSX 文件进行 TypeScript AST 分析，覆盖导入、类型声明、函数体量、Hooks、查询键、失效操作、API 调用、存储访问和路由。同时审查前端配置、全部三个测试文件、关键页面实现，以及后端最近交付与相关边界。超大文件的职责拆分依据实际函数和数据流，而非只按行数切段。

这属于**全量静态扫描与重点语义审查**，并非逐页面浏览器验收。本轮没有操作全部业务页面，没有运行后端全量测试，也没有验证真实外部模型、ZAP 或通知投递。过去的 UI 审查报告是历史材料，其中主题和助手布局已有修改，不能直接当作当前缺陷清单。

证据文件：

- [全量静态证据](frontend-full-audit-evidence.json)：每个源码文件的 SHA-256、行数、导入、函数、查询、API 调用等；还包含测试与配置文件指纹。
- [逐文件迁移建议](frontend-file-migration-map.json)：174 个源码文件逐一对应工作包和目标归属；混合文件标注一拆多，目标为建议而非已存在文件。
- [本轮验证记录](frontend-audit-validation.json)：本次实测与引用历史结果分开记录。

统计的导入循环只覆盖可静态解析的源码模块依赖；不证明运行时副作用、接口契约或跨页面状态完全正确。API 调用计数不等于去重后的后端端点数量。

## 2. 规模与实测基线

| 项目 | 结果 | 含义 |
|---|---:|---|
| 源码文件 | 174 | `frontend/src/` 全部文件 |
| 源码行数 | 41,582 | 包含注释、类型、CSS |
| TS/TSX 文件 | 171 | 含声明文件 |
| 超过 500 行 | 15 | 包含类型与 API 文件 |
| 超过 800 行 | 7 | 不宜只迁移路径后继续保留 |
| 集中类型文件 | 3,072 行 | 被 104 个源码文件导入 |
| API 适配文件 | 23 个，3,132 行 | 其中也包含传输与分页基础设施 |
| `useQuery` / `useMutation` 调用 | 187 / 183 | 是 AST 调用计数 |
| `queryKey` 属性 | 346 | 含失效配置，不能解读为 346 个查询 |
| `api.*` 调用位置 | 400 | 同一路径的不同方法/调用仍分别计数 |
| `<Route>` 声明 | 46 | 含布局、索引、重定向和兜底 |
| 动态导入入口 | 38 | 含布局，不能直接当作独立业务页数 |
| 静态导入循环 / TS 语法诊断 | 0 / 0 | 类型正确性另由 typecheck 验证 |

本轮在当前工作区实测：

| 命令，工作目录 `frontend/` | 结果 |
|---|---|
| `npm test` | 6 passed，0 failed |
| `npm run lint` | 退出码 0 |
| `npm run typecheck` | 退出码 0 |
| `npm run build` | 退出码 0；Vite 5.91 秒，3,297 个转换模块 |

构建最大单个 JS 文件约 335.55 kB，gzip 110.30 kB；没有看到超过默认阈值的大块告警。已有大量路由和组件分块，不能把“大源码文件”等同于“首屏加载过大”。后续需测实际路由加载和请求瀑布，不盲目增加手工分包。

后端参照 [最近交付记录](backend-capability-refactor-delivery.md)：1062 passed、47 warnings、352.95 秒，专用测试 PostgreSQL 端口 55439。这是此前实施者的实测记录，**不是本轮重新运行的结果**。早先 963 passed / 69 failed / 3 errors 已不是最新验收基线。

## 3. 当前问题与优先级

### FE-01：会话失效未同步 React 用户状态（P1，源码确认）

`frontend/src/api/client.ts` 的拦截器收到 401 或账户禁用响应时执行 `tokenStore.clear()` 和失效回调。`hooks/useAuth.tsx` 注册的是外部 `onAuthExpired`，该回调在 `App.tsx` 里仅导航登录页，没有调用 `setUser(null)`。

而 `components/RouteGuards.tsx` 的 `GuestOnly` 与 `RequireAuth` 都读取 React Context 中的 `user`。因此存在存储已清除、守卫仍判定已登录的确定状态缺口；可能发生登录页被送回控制台等表现。本轮未用浏览器复现具体跳转次数。

整改：应用级会话协调器统一处理用户清空、请求取消、缓存清理、作用域重置和一次性跳转；拦截器只发布失效通知，并支持注销监听。处理并发 401、登录接口失败、StrictMode 重挂载及旧请求晚返回。

### FE-02：退出和换账号缺少查询缓存生命周期（P1，源码确认的风险）

`components/QueryProvider.tsx` 的 QueryClient 贯穿整个应用生命周期；`useAuth.logout()` 清除本地用户但不清空 React Query 缓存。登录和注册同样没有建立新的缓存身份边界。查询默认 30 秒新鲜期。

这意味着同一 SPA 内换账号可能复用此前身份的缓存；本轮未验证实际敏感数据曝光。必须补充双账号浏览器用例和延迟响应测试，而不能以服务端鉴权存在为由忽略客户端缓存隔离。

整改要覆盖 query 与 mutation 的回调、旧 `/me` 响应、轮询、页面本地选中项。仅在 logout 加一行 `clear()` 不足以覆盖所有竞态。

### FE-03：作用域与查询键维护分散（P1/P2，源码确认，影响需逐项核对）

`hooks/useConsoleScope.tsx` 声称项目查询统一使用 `['project', id, ...]`，实际同时有 `test-*`、`security-*`、`zap-*`、`mock-*`、`task-*`、`agent` 等命名。当前切项目广泛失效多个前缀，无法从一处判断依赖是否完整。

多数查询已经带项目 ID，不能据此直接宣称所有页面跨项目串数据。需要为每个领域统一键工厂、范围输入、`enabled`、失效范围和轮询生命周期，保留报告/任务深链根据资源所属项目取数据的正确行为。

此外，本地项目 ID 只做 `Number(raw)`，组织 ID 的清理只检查 NaN；需要统一校验正安全整数并重新核验授权，覆盖项目被删除、组织切换、撤销成员和损坏存储。

### FE-04：路由、导航、权限与异常兜底分散（P2，源码确认）

`App.tsx` 管路由，两个 Layout 还维护菜单、标题、选中态和作用域请求。当前使用 `Suspense`，未发现 React ErrorBoundary。需要建立可核对的路由目录和菜单元数据，但保留已有 `BrowserRouter` 和公开 URL，不为合并配置强制更换 Router 模式。

新增应用/路由异常兜底，区分 API 加载失败、权限拒绝、资源不存在和懒加载模块失败；不能让统一兜底吞掉错误或无限刷新。

### FE-05：类型、API 与页面横向耦合（P2，源码确认）

- `types/index.ts` 3,072 行，被 104 个文件导入；业务 DTO、统计、浏览器步骤等混杂。
- `api/securityTesting.ts` 731 行，同时拥有普通安全测试、ZAP 合同与适配。
- `Reports/ReportDetail.tsx:71` 直接导入 `TestManagement/constants.ts`，页面目录成为跨域依赖入口。
- `MemberGrant` 在组织 API 和集中类型中重复，字段语义相同，可归一。
- 两个 `WebLocator` 并不等价：正式写入 Locator 严格必填；快照读取 Locator 宽松可选。应明确命名为正式契约和快照投影，不能为了“去重”降低写入校验。
- 两个 `Option` 的同名不等于重复领域契约，按泛型用途判断。

整改以领域所有权和显式公共入口为准，不把 3,072 行文件搬成另一个集中大文件，也不保留长期全量重导出旧入口。

### FE-06：业务组合组件混在通用组件中（P2，源码确认）

`components/tasks/` 依赖任务、Agent 与项目行为；`components/exec/` 组合执行、缺陷、Web 附件等领域。它们不应整体下沉到 `shared/ui/`。

两个 `JsonView` 有不同能力：全局版本提供截断、空态和复制；API 目录版本提供树/原文切换。建议共用序列化和基本展示，保留两种明确变体，覆盖树视图、复制完整性与截断提示，不能直接删掉其中一份替换调用。

### FE-07：回归覆盖不足以支撑全站搬迁（P1，测试资产确认）

前端三个 Node 测试文件共六项，覆盖分页、跳转保护和主题 CSS；没有覆盖会话切换、页面交互、表单和轮询。后端已有真实 Playwright 验收 `backend/tests/test_31_web_ui_console.py`，覆盖 Web 测试链路，不能代表整个前端均有浏览器保障。

应复用现有 Node 测试与 Python Playwright 能力补行为回归。结构守卫仅用于防止反向依赖、遗漏迁移和体量反弹，不得替代行为测试，也不增加大量只断言文件名的测试。

### FE-08：依赖、样式与注释需随迁移整理（P2/P3）

源码使用 `@ant-design/icons`，但 `package.json` 没有直接声明；当前由传递依赖提供且构建通过。应核实后显式声明实际直接使用的依赖，维护 lockfile，不借机升级整个工具链。

全局 `styles/app.css` 456 行包含壳层、认证和各业务规则；应保留全局 reset/token，其他规则按所有者迁移，并验证加载顺序。当前主题已通过“实际解析 token”的测试，助手已使用响应式 class，不能照搬 10 月 28 日的旧缺陷描述。多处固定尺寸、长文本和复杂抽屉仍需本次在真实视口确认。

## 4. 全模块审查结论与拆分范围

以下数量均来自同一份静态清单。全部路径相对 `frontend/src/`；表格覆盖所有源码分组。

| 当前范围 | 文件 / 行数 | 本次处理 |
|---|---:|---|
| `App.tsx`、`main.tsx`、`layouts/` | 4 / 808 | 路由装配、Layout、导航与 providers 归 app，保留薄启动入口 |
| `hooks/` | 3 / 388 | 会话与作用域契约归 shared，真实协调归 app；角色能力按项目领域归属 |
| `api/` | 23 / 3,132 | client/pagination 归 shared/api；业务 API 和 DTO 回到领域 |
| `types/` | 1 / 3,072 | 按领域分割；共享仅保留分页、错误等通用信封 |
| `components/` | 23 / 3,113 | 通用 UI、业务组件、跨域组合分开；exec/tasks 重点整理 |
| `shared/`、`utils/` | 6 / 431 | 纯函数保留 shared；Web 快照、领域状态和通知语义归原领域 |
| `styles/`、`theme/`、`vite-env.d.ts` | 3 / 675 | 样式按所有者拆开；保留主题唯一入口和全局声明 |
| `pages/auth/` | 3 / 294 | 登录注册路由页与认证展示拆分，保留验证码与安全回跳 |
| `pages/admin/` | 7 / 3,282 | 管理 CRUD、表单、成员授权分离；治理四子域重点拆分 |
| `console/Agent/` | 1 / 870 | 会话、消息、工作区、资产生成选择和提交动作分离 |
| `console/ApiCatalog/` | 17 / 3,416 | 已有组件保留，归域；请求参数/树/导入/调试模型明确 |
| `console/BusinessManagement/` | 12 / 2,867 | 域/流程/绑定/映射/执行子域，编辑状态和表单转换提取 |
| `console/Defects/` | 1 / 484 | 查询筛选、来源引用、编辑器与列表分离 |
| `console/MockManagement/` | 6 / 2,606 | service/endpoint/scenario/runtime/contexts 子域，保护 Token 和留痕 |
| `console/NotificationChannels/` | 1 / 461 | 渠道编辑与校验、发送测试、列表查询归通知领域 |
| `console/Notifications/` | 1 / 192 | 迁移并收敛已读/删除失效，不为凑拆分增加空组件 |
| `console/Profile/` | 1 / 275 | 用户资料和密码修改归身份领域，明确刷新登录态 |
| `console/Projects/` | 2 / 258 | 组织/项目范围、详情和权限契约一致 |
| `console/Reports/` | 3 / 1,231 | 详情拆概览、结果、AI、通知；跨域执行详情归 widget |
| `console/SecurityTesting/` | 14 / 5,382 | security 与 zap 子域；计划预览、规则、认证/策略、作业面板独立 |
| `console/Tasks/` | 6 / 847 | 已拆分成果保留；收敛查询、事件游标、命令与运行状态 |
| `console/TestData/` | 23 / 3,098 | 已拆组件按 fixture/assets/providers/pools/connections/policies 归域 |
| `console/TestManagement/` | 6 / 2,695 | 用例编辑重点；套件/计划/执行页面数据层统一 |
| `console/WebUI/` | 4 / 360 | 正式 Web 测试资产归 web-testing，确认/执行保持 |
| `console/WebUIAgent/` | 1 / 840 | 探索编写归 browser-authoring，保护独立与任务绑定两种模式 |
| `console/Workbench/` | 2 / 505 | 工作台与管理看板共享统计合同和图表组件，保留各自范围 |

## 5. 大文件的具体拆分点

| 当前文件 | 行数 | 建议职责单元 |
|---|---:|---|
| `types/index.ts` | 3,072 | 各 feature/contracts；通用错误/分页信封；区分写入与快照 DTO |
| `TestManagement/TestAsset.tsx` | 1,256 | 编辑工作区、资产树、详情表单、前置条件、数据、Fixture、步骤、断言；编辑控制 Hook |
| `admin/AgentGovernance.tsx` | 997 | Agent/Skill/MCP/Tool 四面板、各自表单、版本历史、Skill 文件编辑、工具详情 |
| `Reports/ReportDetail.tsx` | 986 | 详情查询、报告头、概览/安全摘要、结果筛选、AI 总结、通知、执行详情 |
| `Agent/AgentPage.tsx` | 870 | 会话列表、消息气泡、输入、工作区、报告简报、生成选择、会话控制 |
| `SecurityTesting/zap/policies.tsx` | 855 | 策略列表/抽屉、认证配置列表/抽屉、各自表单转换 |
| `WebUIAgent/index.tsx` | 840 | 启动配置、会话选择、聊天、观察/截图、提案、人工确认、任务绑定控制 |
| `api/securityTesting.ts` | 731 | security API；zap targets/auth/profiles/jobs/findings/reports API；分域 contracts |
| `SecurityTesting/StrategyTab.tsx` | 719 | 策略列表/表单、规则列表/表单、项目设置、查询与提交 |
| `SecurityTesting/zap/jobPanels.tsx` | 706 | events/alerts/coverage/findings/report 五面板，cursor/polling 共用控制 |
| `SecurityTesting/CasesTab.tsx` | 700 | 用例列表、计划预览、执行确认、变异详情和执行状态 |
| `MockManagement/ServiceList.tsx` | 611 | 列表、编辑、从 API 创建、Token 一次展示与重置 |
| `MockManagement/ExecutionList.tsx` | 595 | 执行筛选、详情、上下文面板，保留分页和项目隔离 |
| `components/exec/CaseExecutionDetail.tsx` | 584 | widget 容器、请求/响应、断言、步骤、缺陷、附件面板和视图模型 |
| `MockManagement/ScenarioEditor.tsx` | 525 | 匹配器、响应规则、上下文读写、场景编辑和测试抽屉 |

下一档如 `BindingEditor.tsx`（496）、`Defects/index.tsx`（484）、ZAP wizard（483）、通知渠道（461）、Mock 详情（456）、各管理 CRUD 和业务流程详情，也纳入本单职责审查，不等它们达到 800 行才处理。

体量目标是预警与复核依据，不能靠删注释、压行、复制状态或转发文件达标。已有较小且职责清晰的文件只迁移与适配，不强行继续切碎。

## 6. 必须保护的现有正确行为

- 统一 `/api/v1`、HttpOnly Cookie、内存 Bearer 兼容、安全站内回跳；禁止重新持久化 token。
- 列表分页聚合失败不静默截断；请求/响应、乐观锁 revision 和服务端 404/403 保持原义。
- 报告、任务和执行深链按资源真实项目取数；不要强制改成顶栏项目。
- Web 步骤须逐步批准，正式用例需人工确认；探索草稿提升不是自动批准。
- Web 附件受认证保护，现有 blob 下载与 URL 回收需要继续有效；脱敏快照不能被前端“补全”敏感值。
- Mock Token 与平台登录凭据分离，重置和一次展示行为不变。
- 任务暂停、取消、重试和事件顺序、游标、去重、终态轮询停止；不要混淆 TaskRun 与 TestRun。
- 现有响应式样式、主题修复及其他未提交修改均作为当前基线保留。

## 7. 后端收尾与知识库事实

当前后端主体目录为 `core / platform / orchestration / features / agents / execution / llm / tools / skills / mcp`。不要重启早先 models/shared 或 features 整体迁移，也不要恢复已删除的纯兼容包。

后端本单必须完成：复核前端实际使用的接口和权限合同；核对新旧命名与导入；保存逐项测试基线与新增用例；整理实际 warning；确认构建和联调；更新正式开发文档中已过期的路径。当前 `.claude/skills/develop-this-project/SKILL.md` 仍含旧 `app/shared`、`app/models`、旧 feature 清单等说明，应在实际实施交付时同步事实，不能按旧指引恢复目录。

有意保留项必须保持诚实：C05 的 Skill 使用统计只读联查 TaskRun 尚在 Agent 服务；C08 执行注册分派、C10 readiness 独立运维包、C11 密文包装统一未实施；C09 TestCaseMock 服务暂留 Mocking；C12 基础执行层经公开平台查询契约取配置被明确保留。下一份计划给出逐项处置，不把这些重新描述成必须全部改完的缺陷。

**知识库差距：** 本次当前源码树未发现 `backend/app/knowledge/`，前端未发现独立知识库页面/API；既有 [知识库与业务组装计划](../project-knowledge-business-assembly-plan.md) 也标记为拟新增。不能将历史“已新增知识库”的产品描述当作当前工作区实现证据。本次为其明确未来归属和接入规则；从零实现上传、解析、检索、索引、作业和业务草稿属于产品开发，不暗中混入本次结构整理。若实施时其他分支的知识库代码已合入，则必须一并迁移现有实现并回归，不允许遗漏已有能力。

## 8. 下一步

按 [24](24-frontend-comprehensive-refactor-plan.md) 在同一份委托内连续完成所有工作包。内部检查点用于控制风险，无需用户每完成一个页面再补一条需求。最终以行为保持、问题修复、逐文件归属和前后端实测收尾为完成条件。
