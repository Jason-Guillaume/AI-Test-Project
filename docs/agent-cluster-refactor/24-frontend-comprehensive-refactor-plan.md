# 前端全量重构与后端收尾整单计划

日期：2026-10-30。项目：`/Users/a1/Desktop/ai-test-project`。

审查依据：[23 全量审查](23-frontend-full-audit.md)、[源码证据](frontend-full-audit-evidence.json)、[逐文件映射](frontend-file-migration-map.json)、[后端最近交付](backend-capability-refactor-delivery.md)。执行入口：[25 总需求提示词](25-frontend-comprehensive-agent-prompt.md)。

## 1. 交付目标与整单范围

本单一次覆盖当前前端全部模块的合理拆分、基础行为修复、后端必要收尾和整体验证。U0–U12 是同一委托内的内部工作包，执行者完成检查点后自行推进，不能每拆完一个页面便要求用户重新下单。

最终目标：

1. 全部 174 个现有源码文件有明确归属；业务 API、DTO、查询和表单不再集中在根级大文件里。
2. 当前 15 个超过 500 行的文件完成职责拆分；同时处理下一档职责混杂文件，保留已经清晰的小模块。
3. 统一会话过期、退出、换账号、组织/项目切换、查询失效和轮询生命周期，修复本次发现的状态缺口。
4. 页面 URL、关键交互、字段、权限、确认/审批、任务控制和后端事务语义保持。
5. 现有前后端回归保留，并增加足以支撑本次迁移的行为测试、浏览器验收和逐文件交付证据。
6. 后端 C05 统计查询完成归位；其他有意保留边界形成最终决策记录，结束无收益的目录搬迁。

本单不包含从零建设尚未存在的知识库、向量检索或业务草稿产品，不包含更换 UI 框架、状态库、Router、测试框架、数据库设计或重新设计整站视觉。实施时若已有相关能力合入当前源码，现有能力自动纳入迁移和回归范围，不能按本审查时点将它漏掉。

## 2. 目标结构

路径相对 `/Users/a1/Desktop/ai-test-project/frontend/`。仅建立有实际实现的目录，不预生成空模块。

```text
src/
  main.tsx                         # 薄启动入口
  app/
    App.tsx
    providers/                     # UI、Query、会话、控制台范围的真实装配
    router/                        # 路由目录、守卫、懒加载与异常边界
    layouts/                       # 管理端/控制台壳层与导航
    styles/                        # 壳层样式
  pages/
    auth/                          # 登录/注册路由容器
    admin/                         # 各管理路由容器
    console/                       # 各业务路由容器
    errors/                        # 403/404 等
  widgets/
    execution-detail/              # 执行、缺陷、附件等跨领域展示组合
    task-assistant/                # 全局任务入口/抽屉等跨页组合
  features/
    identity/                      # 登录 API、用户契约、个人资料/密码表单
    users/                         # 管理端用户管理
    organizations/
    projects/
    environments/
    model-configuration/
    agent-governance/              # agents / skills / mcp / tools 子域
    notifications/                 # inbox / channels 子域
    dashboard/                     # 管理看板、用户工作台统计
    api-catalog/
    business/
    test-management/
    test-data/
    mocking/
    security-testing/              # 普通安全测试与 zap 子域
    web-testing/                   # 正式资产、确认、执行、附件读取
    browser-authoring/             # Web 探索编写，含任务绑定模式
    agent/                         # 通用 Agent 会话和资产工作区
    tasks/                         # Task / TaskRun 与控制命令
    reports/
    defects/
  shared/
    api/                           # HTTP 客户端、错误、分页及通用信封
    query/                         # 与具体领域无关的 Query 基础配置/辅助
    session/                       # 会话 Context/事件契约；不请求具体领域 API
    scope/                         # 范围 Context/值契约；不组装业务页面
    ui/                            # 无领域请求的通用组件
    lib/                           # 格式化、安全跳转、健壮存储等通用函数
    theme/                         # 唯一主题构造
    styles/                        # reset、基础 token、确有复用的工具样式
  vite-env.d.ts
tests/                             # 现有 Node 测试及新增纯行为测试
```

典型业务模块按实际需要采用以下结构，不要求每个领域凑齐所有层级：

```text
features/test-management/
  api/{cases,suites,plans,executions}.ts
  contracts/{cases,plans,executions}.ts
  queries/{keys,cases,plans,executions}.ts
  mutations/                       # 复杂变更及其明确失效契约
  model/                           # 编辑状态、表单转换、合法状态派生
  components/{case-editor,suites,plans}/
  lib/
  styles/
```

简单领域可只用 `api.ts`、`contracts.ts`、`queries.ts` 和少量组件，不为风格一致拆出十几个单函数文件。

### 2.1 依赖方向与公共入口

允许方向：`app → pages → widgets → features → shared`，各层也可直接依赖更低层。`shared` 不能导入任何业务领域；`features` 不能导入 `pages`、`widgets` 或 `app`；`widgets` 不能依赖页面。

页面保留真实的路由参数处理、跨域组合或容器职责。不要为了保留旧路径产生只 re-export 的页面包装。小而完整的路由页可直接留在 pages，领域操作和合同仍归 feature。

同一领域内部可以直接相对导入。确有业务关系的跨 feature 调用只经对方显式公共入口，例如 `contracts.ts`、`public.ts` 或有实质定义的专用查询接口；必须记录有向依赖且无环。禁止导入对方组件内部状态或 ORM 式私有数据模型。若两个 feature 需要互相调用，应把组合提升到 page/widget，不能把领域逻辑丢进 shared 消除循环。

公共入口只导出实际使用的稳定合同，不建立巨型全量 barrel。类型依赖和运行依赖分开记录；规则检查识别 `import type` 和动态导入。

### 2.2 会话与作用域装配

`shared/session`、`shared/scope` 定义 Context、读取 Hook、轻量值类型和事件合同。`app/providers` 负责调用身份、项目和组织的公开查询，组合真实 Provider，并注入失效回调；具体 HTTP 层不直接导航，不导入 app。

这样业务查询可读取共享范围合同，不反向导入应用装配。角色能力与项目契约归 `features/projects`；用户角色合同归 identity，不能把所有平台实体移进 shared。

### 2.3 与后端的对应关系

前端按交互和数据所有权分域，不机械复制 Python 层级。身份/组织/项目等对应 `backend/app/platform/`；tasks 对应 `orchestration/tasks/`；Web 正式测试对应 `features/web_testing/`；探索编写对应 `agents/browser_authoring/`；Mock 对应 `features/mocking/`。治理 UI 四个面板可属于一个前端 agent-governance 模块，后端分别落在 agents/skills/mcp/tools 也不构成冲突。

知识库未来对应 `backend/app/knowledge/` 和 `frontend/src/features/knowledge/`，业务组装 UI 对应 business-assembly。当前没有实现时只记录接入约定，不新增空目录、假 API、假菜单或假页面。知识库提供项目事实，Skill 提供操作方法，两者不合并。

## 3. 全量迁移规则

精确到当前文件的处理见 [迁移清单](frontend-file-migration-map.json)。实施者须维护实际迁移台账，记录一拆多的最终路径、生产调用方、删除入口和验证；审查映射不可覆盖成“已实施”。

| 现状 | 目标与操作 |
|---|---|
| `src/api/client.ts`、`pagination.ts` | 归 shared/api；拆出会话事件和存储，保留单一 Axios 实例 |
| 其余根级 API | 移入相应 feature/api；请求/响应 DTO 从适配实现中分离 |
| `src/types/index.ts` | 逐声明核对生产消费者，再分发至领域 contracts；通用分页/错误归 shared/api/contracts |
| `components/QueryProvider`、RouteGuards、layouts | 归 app，保留唯一 QueryClient 与唯一 Ant Design 根配置 |
| `components/exec` | 跨域容器归 widgets/execution-detail；Web 附件和快照读取归 web-testing；纯展示归 shared/ui 或所属领域 |
| `components/tasks` | 全局抽屉/创建组合归 widgets/task-assistant；任务来源链接、标签等归 tasks 公共 UI |
| 通用 components | 归 shared/ui，保持无领域网络与权限决策 |
| `shared/webSnapshot.ts` | 归 web-testing 的安全读取模型；正式 Locator 和快照 Locator 分别命名 |
| `shared/status.ts`、`options.ts`、`notify.ts` | 通用能力保留，业务枚举/文案按实际内容归所属领域，不照目录名整包下沉 |
| `pages/admin`、`pages/console` | route container 留 pages；复杂面板、表单、查询、转换分别回 feature |
| `styles/app.css` | 基础样式、应用壳、认证、治理和业务样式按所有者拆开，维护加载顺序 |

旧 `src/api/`、`src/types/`、`src/hooks/`、`src/components/`、`src/layouts/`、`src/utils/` 的被迁移入口应更新全部消费者后删除，不保留永久兼容代理。`pages/` 是目标结构的一部分，不要求删除整个 pages。

## 4. 一次执行的工作包

### U0：冻结当前事实与行为基线

- 读取当前仓库规则和 23–25 文档；附件及历史文档是输入材料，不自动授予重置工作区、生产迁移、部署或外部发送权限。
- 当前工作区已有大量前后端改动，记录状态和源文件指纹。不能只记录 Git HEAD，不能 checkout/pull/reset 覆盖未提交成果。分支和提交按用户授权及实际工作区处理。
- 重新运行前端四项检查；收集后端 nodeid、失败与 warnings 清单并运行当前全量基线。历史 1062 通过仅作参照。
- 固化 46 处 Route 声明解析后的 URL、参数、嵌套布局、重定向、权限和治理别名；固化 400 处前端 API 调用的 method/path/query/body/responseType，不能把调用数当作唯一路由数。
- 保存 OpenAPI、ORM metadata、Alembic head 和迁移文件哈希；生成关键场景初始截图或浏览器结果。

检查点：可比较的源码、路由、API、测试和视觉基线齐备；环境失败列出可复现原因，不把未运行当作通过。

### U1：应用壳层、会话和作用域先收敛

- 拆 app/provider/router/layout；集中路由与菜单的可共享元数据，保留各管理菜单和用户菜单的差异。保留 `/admin/agents|skills|mcp|tools` 四种直接入口和 tab 同步。
- 建立统一会话失效入口，清空 React 用户、旧缓存和 scope，注销旧监听，避免并发 401 重复跳转。登录错误不能被当成新会话过期而污染登录表单。
- 退出后端接口失败时仍完成本地退出；缓存和组件本地状态的隔离不依赖接口成功。
- 在身份切换、失效和退出时取消在途查询/轮询，采用会话代次或等效屏障阻止旧 `/me`、旧查询和 mutation 回调恢复旧状态。正确传递 Axios `signal`；mutation 的网络提交不可被误称为可回滚，客户端只屏蔽过期结果和后续 UI 更新。
- 范围 ID 使用正安全整数校验；localStorage 不可用、损坏和授权变化均有安全回退；重新校验组织与项目所属关系。
- 补 ErrorBoundary、懒加载失败兜底与有限重试；不统一吞掉 API 错误。

检查点：失效回登录且不反跳；A→退出→B 无旧数据闪现；并发失效只触发一次会话转换；非法 scope 不向 API 发送 NaN/0；普通 403 保持原页面语义。

### U2：领域 API、类型、查询和失效合同全量归位

- 迁移全部 23 个 API 文件和集中类型；保留请求路径、动词、snake_case、空值/缺省值、分页、blob 和错误信封。
- 同时处理 API 文件自带 DTO，避免只拆 `types/index.ts` 留下第二套合同。移除真实重复 MemberGrant；保留正式 Locator 与宽松快照投影的区别。
- 每个 feature 拥有 query key 工厂与实际使用的查询/变更入口。键明确 session、org/project、resource、filters/page 的必要维度；维度按可见范围选取，不要求所有查询无差别携带每个 ID。
- 项目 scoped 查询显式 `enabled`，参数是新 key 的一部分；跨项目不使用旧项目 `placeholderData`。明确删除、编辑、执行、通知、生成、审批后的失效范围，不遍历全局缓存模糊匹配字段。
- 修正粗粒度跨项目失效；允许保留仍有权访问项目的缓存，但在身份转换时清理，且切换时不会展示前项目结果。
- 数据获取逻辑与表单脏状态分离，后台 refetch 不覆盖未保存编辑。各 query/mutation 模块大小受控，不形成新的千行 Hook。
- 深链报告/任务/执行页面按资源所属范围取数；用户顶栏项目变化不能篡改正在操作资源的项目 ID。

检查点：400 个调用位置逐项承接；所有生产导入指向新归属；mutation 失效关系可查；分页和下载行为保持；无巨型集中类型兼容入口。

### U3：治理与平台管理页面

- `AgentGovernance.tsx` 拆 Agent、Skill、MCP、Tool 四个面板和各自表单/详情/版本记录。Skill 文件编辑器独立，保留文件树、脏状态、保存/恢复、路径限制和长内容编辑。
- MCP 配置、发现和工具开关保持原授权与脱敏；工具参数和风险展示完整。
- Users、Organizations、Projects、ModelConfigs、Environments 的列表查询、编辑表单、成员/模型授权和出站目标编辑按职责分离。
- 表单转换区分创建/修改，保留“未修改密钥不覆盖”“空值清除”的既有接口语义；不把已脱敏密钥当真实值回传。
- 登录、注册、个人资料和密码修改归 identity；验证码与安全回跳用例保留。

检查点：各角色路由入口、成员授权、模型授权、Skill 版本、MCP/Tool 开关真实可用；无密码或密钥进入审计截图。

### U4：测试资产、套件、计划与执行

- `TestAsset.tsx` 拆资产树、基础编辑、前置条件、数据、Fixture、步骤、断言，以及工作区状态控制。保持 project key 切换时重建编辑状态的既有保护。
- revision 乐观锁、确认/撤销、启停、生成草稿/保存正式资产和错误提示不变；选择/切换未保存编辑时不静默丢失。
- 套件、计划、执行中心、执行历史的选择、排序、分页和变更统一到对应领域数据层。
- 执行详情调用统一 widget，保持 CaseExecution、TestRun、TaskRun 的标识和状态区分。

检查点：创建→编辑→确认→套件/计划执行→历史/报告链路及并发修订冲突通过；执行变更失效对应查询。

### U5：通用 Agent 与 Web 探索编写

- 通用助手分离会话、消息气泡、输入区、工作区、生成选择、报告简报和会话控制 Hook；保持当前响应式三栏切换。
- WebUIAgent 分离配置、历史会话、观察、聊天、步骤提案、提升和控制器。
- 明确独立会话与 `taskId/runId` 绑定模式，缺任一参数、跨项目、过期 run、暂停、取消均不能降级到不受任务控制的执行。
- 逐步确认/驳回、提升草稿、正式人工确认保持；不因 UI 拆分自动执行未批准动作。
- 管理定时器、请求、截图 blob、事件和滚动副作用的卸载清理。失败、重复点击和页面返回不能发出重复动作。

检查点：独立会话、任务绑定、批准/驳回、暂停/取消、恢复查看、提升后人工确认各有真实回归；无模型/浏览器失控调用。

### U6：安全测试与 ZAP 全子域

- 安全策略、规则、设置、用例、执行预览、变异详情和执行历史拆分。
- ZAP 分 targets、auth-profiles、profiles、jobs、events、alerts、coverage、findings、reports，API/合同与 UI 对应归属；不新建独立顶层通用 scanner 框架。
- `policies.tsx` 四个列表/抽屉独立；`jobPanels.tsx` 五类面板独立；执行/计划预览与普通用例编辑分离。
- 命令行为保留目标授权、认证状态、主动/被动模式、超时、停止、事件游标、终态停止轮询和结果来源。

检查点：用受控测试替身验证主要分支，明确真实 ZAP 验证状态。自动测试通过不能宣称真实生产扫描已验收；不得向未授权外部目标发起扫描。

### U7：Mock 与业务管理

- Mock 服务列表/编辑、从 API 创建、Token、endpoint、场景匹配、响应、上下文、测试运行和执行详情按子域拆分。
- 保留匹配优先级、分页、场景测试与运行接口差异、Token 一次展示、失效和脱敏行为。
- 业务管理保留已有组件；进一步拆流程控制、绑定编辑、映射规则、前置条件、输入输出、变量引用和执行查询。
- 领域之间通过公开 API/合同组合，业务编辑器不能导入 API 目录页面内部实现。

检查点：业务流程执行和 Mock 场景/上下文正反路径通过；不更改运行面 Token 和平台权限边界。

### U8：报告与跨域执行详情组合

- ReportDetail 拆报告查询与操作、概览、安全摘要、结果筛选、AI 总结、通知面板。
- `Reports → TestManagement/constants` 改依赖 test-management 公共领域状态合同。
- `widgets/execution-detail` 整合请求响应、断言、时间线、缺陷来源和领域面板；实际 Web 附件读取、快照解释归 web-testing 公共接口。
- 提取两种 JsonView 的共用能力但保留树/原文和截断/空态差异。复制内容是否完整必须有明确 UI 和行为，不把截断文本静默当完整证据复制。
- 下载仍经认证 API，blob URL 随卸载/替换回收；Trace 保持脱敏事件展示，不恢复已移除的 DOM 回放。

检查点：筛选/翻页、删除报告、AI 重生成、发送通知与审计、来源跳转、截图/Trace、空快照和未知字段均有承接。

### U9：其余全部模块完成归位

- API 目录：17 个现有文件逐一处理，保留合理拆分；导入、树、请求参数、响应/Schema、关系、调试、变更记录分别归位。
- 测试数据：23 个现有文件完整迁移，Fixture、资产、Provider、Pool、Connection、Policy、执行详情与加密配置分别保留行为；不为优化目录引入新的全局数据仓库。
- Tasks：延用已拆 TaskDetailActivity、TaskRunPanels 等成果；统一查询和命令，事件游标/去重/暂停/取消/重试/终态保留。
- 正式 Web：与 browser-authoring 区分，资产编辑、确认指纹、调试执行、历史和附件保持。
- 缺陷、通知收件箱/渠道、项目、个人资料、工作台和管理看板全部纳入领域合同、查询和页面迁移。
- 任何小模块选择保留文件形态，仍要在台账记录理由，不能以“大文件都拆完”为由漏掉它。

检查点：174 文件台账全部完成/合并/删除/合理保留，无“未看”“后续再做”；所有路由映射有浏览器访问结果。

### U10：样式、体验、依赖与体量防反弹

- 拆全局 CSS，维护当前设计和已修布局；只修影响可用性的溢出、滚动、焦点、表单和窄屏问题，不重新设计全站。
- 核心页面实测 1440、1024、768、390 px：输入区、长文件名、长 JSON、表格横向滚动、抽屉操作、表单错误、键盘关闭/焦点和 aria 标签。390 px 允许表格容器横向滚动，不允许整页操作区不可达。
- 核实并显式声明直接依赖；复用既有 React Query 和 Node/Python Playwright，不默认引入 Redux、Zustand、Monaco、Vitest 或新 UI 库。不执行批量 upgrade/audit fix。
- 保持路由懒加载，记录构建清单和主要路由加载；相同环境下比较初始资源与页面请求，只有测量证明有回归再调整分块。
- 增加轻量结构检查：依赖方向、跨域私有导入、循环、旧路径、体量。扫描排除 dist/node_modules/生成代码，不用 ESLint suppression 掩盖问题。

体量标准：路由容器目标不超过 300 行；普通组件目标不超过 350 行；单 Hook/控制器目标不超过 250 行；API/contract 模块目标不超过 400 行。**手写业务源码超过 500 行必须拆分或给出明确审核理由与实际职责证明**；现有 15 个大文件全部按职责处理，不用简单例外批量放行。函数复杂度、参数数目、重复状态也要复核，不能只看行数。

### U11：后端收尾和契约闭环

以下是一份确定的收尾清单，不重新执行已完成的 B0–B9 或 C01–C12 全量迁移。

| 项目 | 本单动作 | 完成标准 |
|---|---|---|
| C05 Skill 使用统计 | 将 `agents/services/reference_service.py::skill_usage` 的治理统计用例迁入 `platform/agent_governance/services/usage_query_service.py`，Router 调用治理查询。仅迁真实统计实现，删除原纯代理；其他 Skill 引用保护仍留原领域服务 | Agent 引用服务不再因统计导入 Task/TaskRun；返回结构、计数去重、最近十条排序、404、管理员权限不变；只读且不 commit |
| C05 查询边界 | 治理统计属于跨域 read model，可使用现有公开任务只读查询，或明确记录治理查询层的只读联表例外；不把 ORM 统计转移进通用 core，也不为十条数据新造事件总线 | 消除运行 Agent 对任务模型的反向依赖；例外有唯一归属和测试 |
| 已完成 C01–C07 主要边界 | 复核项目权限、治理决策、工具写入归域、报告投递、浏览器运行时及事务提交，修正本单引入的漂移 | 生产调用真实承接，无旧包恢复、重复实体或执行链 |
| C08 执行注册分派 | 按当前无扩展需求的决策保留延迟导入；补/确认分派优先级、普通回退、结果生命周期回归 | 决策记为“保留”，不冒充已实现注册器 |
| C09 TestCaseMock | 保留声明服务在 Mocking，复核项目/场景/service/endpoint/scope 校验与 runtime commit/flush-only 边界 | 明确所有者与测试；不为目录整齐迁动事务 |
| C10 readiness | 保留现有只读 readiness 与 URL，明确未来运维归属；不建空 operations | 真实响应与登录要求保持 |
| C11 密文包装 | 保留包装差异；补/确认 strip、空值、原文、解密失败策略的边界测试与注释 | 不改变已有密文可读性，不重加密现有数据 |
| C12 平台公开查询 | 保留 HTTP/LLM 经公开平台配置查询的实际依赖，文档列出契约 | 不增加纯转发层，不把授权与配置快照混淆 |
| warning 与测试环境 | 保存 47 项历史 warning 的分类清单，修复可安全处理的误收集、测试配置/fixture 问题；依赖弃用等保留明确来源和处置理由 | 新增 warning 有解释或修复；不全局 filter、skip、xfail 降门槛，不为“清零”升级依赖 |
| 前后端契约 | 对照迁移前后 method/path/字段/分页/错误/下载/权限和前端 400 处调用承接；OpenAPI 差异逐项解释 | 运行接口语义不漂移；若修复 operationId 重复等文档元数据，单独列出影响，不冒充零差异 |
| 文档事实 | 更新主 README、开发指引、coding-conventions 和架构索引中仍在指导新开发的过期路径 | 正式指引按当前 core/platform/orchestration/features 与新前端结构；历史报告不伪改为新验证结果 |

此处 C08–C12 的保留是本单明确边界决策，交付时记录“核验后保留”和证据，不继续列成无限期未处理的目录任务。若核验发现真实缺陷，修复缺陷并追加证据，不擅自扩展成新基础框架。

### U12：统一验收、清理与交付

- 每个工作包先跑实际影响面检查；最终在全部源码完成后统一运行前端四项、后端全量和新增浏览器套件。
- 保留原有测试有效语义，后端以 U0 收集 nodeid 为当次基线，新增用例单独列清单。移动测试必须有 nodeid 映射；不能以通过数接近为由忽略删除/漏收集。
- 历史六项前端测试必须保留/等价承接；对分页、安全跳转、主题的路径更新不降低断言。
- 旧目录无生产引用后删除，删除无用 re-export、重复实现、死样式和临时调试代码；复核 lockfile 与依赖。
- 输出实际迁移、检查结果、保留边界、环境限制、风险与回退方案，并更新文档索引。

## 5. 必须新增或复核的行为验收

| 验收族 | 最低场景 |
|---|---|
| 会话与身份 | 401、账户禁用、普通 403、并发失效、注销监听、失败登出、A→B、延迟 `/me`/查询/变更回调、StrictMode |
| 范围与缓存 | 组织/项目切换、损坏/无权限存储、撤销成员、过滤/翻页、mutation 失效、旧项目响应晚到、资源深链所属范围 |
| 路由与导航 | 当前全部路由可达、四治理别名、嵌套参数、刷新深链、403/404、登录回跳保护、懒加载失败与异常边界 |
| 编辑与确认 | 脏表单、切换选中、revision 冲突、创建/修改缺省字段、密钥不覆盖、确认/撤销和保存错误 |
| 任务与 Agent | 消息、事件游标/去重、暂停/取消/重试、终态停止轮询、避免重复提交和过期回调 |
| Web | 独立/绑定模式、参数不完整/越权、逐步审批、暂停后禁止动作、草稿提升后确认、附件认证与 URL 回收 |
| 安全/ZAP | 策略/认证、预览/执行/停止、作业事件与终态、漏洞/覆盖/报告；真实扫描与替身结果分开 |
| Mock/业务 | 场景匹配、上下文、Token、从 API 创建、流程/绑定/映射和执行详情 |
| 报告/缺陷/通知 | 来源跳转、筛选分页、AI、通知审计、删除不误删运行、未知/脱敏快照 |
| 数据/API/管理 | 接口导入调试、Fixture、Pool/Connection/Provider/Policy、组织成员/模型/出站权限 |
| UI/资源 | 四视口、长文本、键盘、截图/Trace/下载、弹窗关闭、定时器卸载、主题实际 CSS |

优先用 Node 内置 runner 测可独立运行的状态/键/转换行为，用当前 React Query 实例验证缓存与取消；复杂会话/路由/交互复用现有 Python Playwright 设施。不得只断言源码包含某字符串。所有路由做访问冒烟，关键写入链路做真实交互；不要求重复跑每个静态文案的截图。

## 6. 环境与验证纪律

前端命令工作目录：`/Users/a1/Desktop/ai-test-project/frontend`：

```bash
npm test
npm run lint
npm run typecheck
npm run build
```

后端命令工作目录：`/Users/a1/Desktop/ai-test-project/backend`，按当前环境确认专用测试连接后：

```bash
.venv/bin/python -m pytest tests/ --collect-only -q
.venv/bin/python -m pytest tests/ -q
```

测试必须使用隔离测试库。最近交付使用 127.0.0.1:55439，实施时重新确认容器与端口，不把它当永远有效配置。连接信息从安全配置读取，不将密码、Cookie、Webhook、模型密钥写进报告/日志/截图；不重置开发/生产库。浏览器测试起临时服务和临时端口，使用受控外部目标与测试替身。

最终比较所有构建 JS 资源总量、入口依赖和主要路由实测加载。资源增长超过同环境基线 10% 或出现新的大块/首屏加载异常，需要解释和定位；不得把该比例当脱离功能变化的绝对硬指标。

若环境阻塞，继续独立可做项，记录命令、错误、影响和复测入口。最终把“已改但未测”“保留边界”“产品另立项”明确分开，不能用专项通过替代全量验收。

## 7. 完成判定

- [ ] 174 个基线文件全部有最终映射，后续新增/合入文件也有归属；一拆多列出真实路径与调用方。
- [ ] 旧集中 DTO、API 及兼容入口已清理；无新增循环、禁止反向依赖和跨页借用内部实现。
- [ ] 15 个现有大文件和其他混合职责完成处理；没有用巨型 Hook、barrel 或高参数组件替代巨型页面。
- [ ] FE-01/02 会话状态与缓存隔离得到修复，并有行为/浏览器证据；范围与查询失效迁移完整。
- [ ] 原公开路由、关键交互、审批、权限、下载和 API 合同承接完整；关键链路与所有路由冒烟通过。
- [ ] 后端 C05 统计归位；C08–C12 的保留决策和事务/密文边界核验完成，无新增无收益框架。
- [ ] 最终前端四项检查通过；后端原测试逐项承接且全量通过，新增测试清单明确；任何失败/未测均公开，不能标记整单全绿。
- [ ] 四视口核心页面、错误/空态/加载态、键盘和长内容验证完成；构建与加载对比无未解释回归。
- [ ] 文档、正式开发指引、验证资产、变更范围和可执行回退方式更新完成。

## 8. 工作量与执行方式

这是覆盖约 4.16 万行现有前端和后端收尾的综合任务。以下是熟悉项目工程师的粗估，包含测试和联调，**不是 Agent 运行时长承诺**。

| 工作包 | 工程人日 |
|---|---:|
| U0 基线 | 1–2 |
| U1 壳层/会话/范围 | 3–4 |
| U2 全量合同/API/查询 | 3–4 |
| U3 治理与平台 | 2–3 |
| U4 测试管理 | 2–3 |
| U5 Agent/Web 编写 | 2–3 |
| U6 安全/ZAP | 2–3 |
| U7 Mock/业务 | 2–3 |
| U8 报告/执行组合 | 2–3 |
| U9 其余全模块 | 2–3 |
| U10 样式/依赖/性能 | 1–2 |
| U11 后端收尾 | 1–2 |
| U12 统一验证交付 | 3–5 |
| **合计** | **26–40** |

可按依赖分内部批次：U0 → U1/U2 → U3–U9 → U10/U11 → U12。批次不是用户确认关卡；关键行为测试在相关工作包内完成，不拖到最后才发现问题。执行者维护检查点和当前进度，上下文切换后从检查点继续，不把用户的“一次委托”误解为一个巨大不可审查提交。

## 9. 实施交付文件

统一写入 `/Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/`：

- `frontend-comprehensive-progress.md`：U0–U12 状态、当前阻塞和下一内部工作项。
- `frontend-comprehensive-delivery.md`：最终目录、真实迁移映射、行为修复、后端收尾、保留决策、风险和回退。
- `frontend-refactor-validation/`：基线/最终文件清单、路由与 API 差异、测试 nodeid/结果、warning 分类、构建对比、浏览器场景与脱敏截图。

本计划与 23 的审查证据保留审查时点，执行者另外记录实际结果，不能把计划勾选完成后当作测试证据。
