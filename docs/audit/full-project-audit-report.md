# 全项目代码质量、功能完整性与 UI/UX 审计报告

审计日期：2026-10-28（Asia/Shanghai）
审计对象：当前工作区，包括审计开始前已有的未提交改动
审计方式：首次审计包含全仓文件/路由/依赖清点、静态检索与 AST 检查、前端类型检查和构建、可执行的隔离测试；首次审计未修改业务代码。用户随后授权整改，本报告末尾附分支复核与验证记录。

## 1. 执行摘要

项目是基于 FastAPI、SQLAlchemy、Alembic 与 React/TypeScript 的测试开发平台。当前工作树包含 19 个受版本控制的后端业务域、22 个前端 API 模块、46 个 React Router 路由元素、408 个常规 HTTP 操作声明（包括本次新增的 3 个 Cookie 会话端点），以及一个 Mock 运行时 catch-all 路由的 7 种 HTTP 方法。数据库模型源码有 112 个唯一 `__tablename__`，迁移目录有 29 个版本文件；这些是源码计数，未连接数据库核实实际库表。

首次审计记录 7 项问题（P1 1 项、P2 4 项、P3 2 项）。整改复核另发现 1 项依赖漏洞簇 DEP-001；当前报告共记录 **8 项问题**（P1 1 项、P2 5 项、P3 2 项），类型涉及安全/依赖 4 项、性能/架构 2 项、测试门禁 1 项、文档 1 项。没有发现可确认的 P0 或 P1 业务逻辑/越权缺陷。后端认证依赖、项目/组织隔离、Alembic 迁移及分域结构在静态实现中可见；因数据库、后端依赖和浏览器不可用，认证 Cookie 与权限路径未能通过集成请求验证。

首次审计时前端 `typecheck` 和生产构建通过，但构建输出一个 588.51 kB 的 JavaScript chunk 警告；整改后重新构建通过，最大 chunk 降至 335.45 kB。整改后 `npm test` 4 项通过、严格 ESLint 通过。后端 40 个测试文件及新增认证测试均未能运行：当前没有 `backend/.venv`，系统 Python 缺少 `psycopg`，pytest 在加载测试夹具时停止；PostgreSQL 5432 和 API 8001 当时均未监听。Compose 配置静态解析通过，但未启动容器。CUA 没有可用浏览器，因此未完成逐页浏览器操作或截图。

**整体评价：** 当前源码与测试开发文档描述的阶段已明显不同。整改已收紧开发数据库暴露面、拒绝弱密钥、采用 HttpOnly Cookie、为批量分页设置硬上限、补上前端 test/lint 命令、更新历史架构文档并拆分大构建块。浏览器回归和服务端分页尚未完成；npm 依赖审计仍发现需经 major 升级流程处理的漏洞。功能是否端到端可用尚不能由本次构建结果推断。

## 2. 项目概况与覆盖边界

### 2.1 技术架构

```mermaid
flowchart LR
  UI[React 18 / TypeScript / Vite / antd] --> API[前端 api 模块 / Axios]
  API --> HTTP[/api/v1 FastAPI 路由]
  HTTP --> SVC[feature services / executors]
  SVC --> ORM[SQLAlchemy 模型]
  ORM --> DB[(PostgreSQL)]
  SVC --> EXT[LLM / MCP / ZAP / Playwright / Webhook]
  MIG[Alembic 迁移] --> DB
```

| 范围 | 源码盘点 | 审计覆盖说明 |
|---|---:|---|
| 仓库 | 681 个已跟踪文件 | 包括当前工作树内已有的未提交修改；不将其归因于本审计 |
| 后端 | 367 个 Python 源文件，约 72,277 行 | AST 解析全部 Python 源文件，0 个语法错误；路由、认证、配置、ORM 与迁移做静态映射 |
| 后端业务域 | 19 个已跟踪 feature 目录 | 按 feature 逐域映射到前端入口和 API 模块，见 §3.3 |
| 数据层 | 112 个唯一 ORM 表名；29 个 Alembic 迁移文件 | 未访问运行数据库，未验证迁移能否在当前数据库升级 |
| 后端 API | 22 个由 `main.py` 装配的 Router；23 个含路由声明的源文件 | 静态计数 408 个标准 HTTP 操作 + Mock Runtime 7 个方法 + 3 个系统端点，共 418 个操作/方法组合；未请求每个端点 |
| 前端 | `frontend/src/pages` 下 96 个 TSX 文件；22 个业务 API 模块 | 组件/页面、路由表、API 调用与错误态做全仓静态扫描和抽样代码审查 |
| 页面路由 | 44 个显式 `path` 路由 + 2 个 index 路由，共 46 个 Route 元素 | 路径均列在 §3.2；受保护页面未登录、登录后与各数据状态未做浏览器验证 |
| 自动化测试 | 后端 40 个 `test_*.py` 文件；整改后前端 2 个 Node 测试文件 | 首次审计时前端测试未注册 npm 脚本；整改后已提供 `npm test` 和 `npm run lint`。后端测试因驱动缺失未执行 |

API 数是从路由装饰器和 `api_route(methods=...)` 做的源码计数，不等同于运行时 OpenAPI 中去重后的 URL 数。系统端点为 `/healthz`、`/health`、`/api/v1/meta`。`backend/app/features/captcha` 当前只有被忽略的缓存字节码，没有受版本控制的 Python 源码或装配路由，未按业务域计数。

### 2.2 代码与依赖

- 后端依赖定义在 [backend/requirements.txt](../../backend/requirements.txt)，主要是 FastAPI、SQLAlchemy、Alembic、psycopg、PyJWT、Pydantic、Playwright 与 pytest。当前机器没有项目 `.venv`，也没有安装完整后端运行依赖，因此未确认锁定版本实际可安装或运行。
- 前端依赖定义在 [frontend/package.json](../../frontend/package.json) 和 `package-lock.json`。本次前端构建实测 Vite 5.4.21；配置是 React 18、TypeScript 5.6、antd 5、React Query 5、React Router 6、Axios。
- API 客户端以 `frontend/src/api/client.ts` 为单例，前缀 `/api/v1`；后端在 [backend/app/main.py](../../backend/app/main.py) 挂载 22 个 Router。功能域内部可见 router/service/schema、ORM model、Alembic migration 分层。
- 审计期间的一次 `git status` 快照显示已有 45 个已跟踪文件修改及 4 个未跟踪路径（含此前已有的审计草稿、分页辅助代码和测试）；报告在该快照之后新增，因此当前未跟踪数会多 1。工作区可能被并行编辑，具体列表以实时 `git status` 为准。审计过程中没有修改业务源码；生产构建生成物位于忽略目录。

### 2.3 安全检查范围

- 后端 `.env` 在本地存在但未跟踪；版本控制中仅有 `.env.example`。前端已构建产物未发现本地敏感环境变量的精确值，且没有 source map。报告不包含任何密钥、令牌或密码原值。
- 全仓对 `dangerouslySetInnerHTML`、`innerHTML`、`eval`、`new Function` 的源码检索没有命中。
- 静态认证依赖扫描发现常规业务路由采用当前用户或平台管理员依赖；未认证的 `/model-configs/providers` 和 `/notifications/events` 仅返回供应商/事件类型枚举。该启发式扫描不能替代逐端点权限矩阵测试。
- 对模型 API Key 的响应类型与页面路径可见掩码字段，提交明文由后端加密存储的实现约定也见于项目文档；本次没有实际发送请求验证响应体。

## 3. 页面、API 与业务域映射

### 3.1 前端路由清单

下面列出全部显式路径。两个 index 路由分别是 `/admin` 的仪表盘跳转和 `/console` 的工作台；`/` 为首页跳转，`*` 为兜底 404。

| 路由组 | 显式页面路径 | 动态覆盖 |
|---|---|---|
| 公共 | `/`、`/login`、`/register`、`/403`、`/404`、`*` | 路由与守卫静态检查；未在浏览器中操作登录/注册或错误页 |
| 管理端 | `/admin`、`/admin/dashboard`、`/admin/users`、`/admin/organizations`、`/admin/projects`、`/admin/model-configs`、`/admin/environments`、`/admin/agents`、`/admin/mcp`、`/admin/skills`、`/admin/tools` | 源码映射到 AdminLayout 与对应管理页；管理员/非管理员登录场景未执行 |
| 控制台 | `/console`、`/console/projects`、`/console/projects/:id`、`/console/defects`、`/console/api-catalog`、`/console/business-management`、`/console/test-asset`、`/console/test-suites`、`/console/test-plans`、`/console/execution-center`、`/console/execution-history`、`/console/test-reports`、`/console/test-reports/:reportId`、`/console/notification-channels`、`/console/test-data`、`/console/mock-management`、`/console/mock-management/services/:serviceId`、`/console/mock-management/endpoints/:endpointId`、`/console/mock-management/executions`、`/console/web-ui`、`/console/web-ui-agent`、`/console/security-testing`、`/console/tasks`、`/console/tasks/:taskId`、`/console/agent`、`/console/notifications`、`/console/profile` | 逐条对应 ConsoleLayout/子页与 API 模块；未以登录账号逐页验证 |

管理端 Agent/MCP/Skill/工具路径复用一个治理页，组件按 URL 选择对应标签。移动端断点在布局 CSS/antd Sider 中可见，但没有真实视口测试。由于没有可用浏览器，页面溢出、遮挡、键盘操作、空态、加载态、截图证据均未能动态确认；本次不把静态推测写成已确认 UI 缺陷。

### 3.2 API Router 与操作数量清单

| 后端路由源文件 | 操作声明数 | 主要职责 | 对应前端 API 模块/入口 |
|---|---:|---|---|
| `features/users/auth.py` + `admin.py` | 14 | 注册、登录、Cookie 会话、当前用户、管理员用户管理 | `auth.ts`、`users.ts`；登录/注册/个人资料/管理用户 |
| `features/organizations/router.py` | 9 | 组织、成员、模型授权 | `organizations.ts`；管理组织、个人资料 |
| `features/projects/router.py` | 19 | 项目、成员、出站目标、环境绑定 | `projects.ts`；管理项目、控制台项目与详情 |
| `features/defects/router.py` | 9 | 缺陷与执行来源关联 | `defects.ts`；`/console/defects` |
| `features/api_catalog/router.py` | 23 | 接口导入、目录、请求/响应、关系、历史、调试 | `apiCatalog.ts`；`/console/api-catalog` |
| `features/business/router.py` | 47 | 业务域、流程、动作、规则、绑定与执行 | `business.ts`；`/console/business-management` |
| `features/test_management/router.py` | 54 | 测试资产、套件、计划、执行与断言 | `testManagement.ts`；资产、套件、计划、执行中心/历史 |
| `features/tasks/router.py` | 16 | 异步任务、状态、调度与控制 | `tasks.ts`；`/console/tasks` |
| `features/reports/router.py` | 5 | 报告列表、详情、生成与删除 | `reports.ts`；`/console/test-reports` |
| `features/agent/router.py` | 6 | Agent 会话及任务对话 | `agent.ts`；`/console/agent` |
| `features/agent_governance/router.py` | 24 | Agent、工作流、技能、工具、MCP 治理 | `agentGovernance.ts`；管理端治理页 |
| `features/notifications/router.py` + `channel_router.py` | 15 | 通知、渠道、发送和审计记录 | `notifications.ts`、`notificationChannels.ts`；通知/渠道/报告详情 |
| `features/model_configuration/router.py` | 7 | 模型供应商与连接配置 | `modelConfigs.ts`；`/admin/model-configs`、Agent 治理 |
| `features/environment_configuration/router.py` | 6 | 被测环境配置 | `environments.ts`；`/admin/environments` |
| `features/dashboard/router.py` | 5 | 平台/项目看板与就绪检查 | `dashboard.ts`；`/admin/dashboard`、`/console` |
| `features/test_data/router.py` | 44 | Provider、Fixture、数据资产与执行 | `testData.ts`；`/console/test-data` |
| `features/web_ui/router.py` | 27 | 页面对象、Web 用例、运行记录、Agent 会话 | `webUI.ts`；`/console/web-ui`、`/console/web-ui-agent` |
| `features/security_testing/router.py` + `security_testing/zap/router.py` | 50 | 安全用例、策略、问题、ZAP 扫描任务 | `securityTesting.ts`；`/console/security-testing` |
| `features/mock_management/router.py` | 28 | Mock 服务、接口、场景、令牌和执行记录 | `mockManagement.ts`；`/console/mock-management` |
| `features/mock_management/runtime_router.py` | 7 方法 | Mock 运行时 catch-all，GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS | 由被测请求访问；不作为常规管理页面 API |
| 系统端点（`app/main.py`） | 3 | 存活、健康、应用元信息 | 无专用业务模块 |
| **合计** | **418** | 408 个标准装饰器操作 + 7 个运行时方法 + 3 个系统端点 | 静态映射；未逐端点 HTTP 调用 |

动态执行的 API 覆盖数为 0：数据库未运行且后端依赖不齐。每个模块的接口路径、请求/响应字段是否与实际后端 OpenAPI 契约一致，尚未通过当前运行服务验证；前端 TypeScript 检查只证明前端本地类型一致。

### 3.3 业务模块覆盖结论

| 后端 feature | 前端 API/页面入口 | 静态审计结论 |
|---|---|---|
| `agent` | `agent.ts` / `/console/agent` | 有对应 API、页面和服务端路由；LLM/工具执行未联调 |
| `agent_governance` | `agentGovernance.ts` / `/admin/agents`、`mcp`、`skills`、`tools` | 路由标签映射一致；MCP 外部连接、审批和凭据运行时未验证 |
| `api_catalog` | `apiCatalog.ts` / `/console/api-catalog` | 导入、编辑、关系、调试等页面入口存在；数据库流程未运行 |
| `business` | `business.ts` / `/console/business-management` | 业务模型与页面入口成对；API 动作执行和目标系统未实测 |
| `dashboard` | `dashboard.ts` / `/admin/dashboard`、`/console` | 有管理端及控制台看板；统计数据未访问数据库验证 |
| `defects` | `defects.ts` / `/console/defects` | CRUD 与来源关联有对应前端模块；权限/持久化未动态测 |
| `environment_configuration` | `environments.ts` / `/admin/environments` | 有配置页面和 API；环境连接与目标限制未实测 |
| `mock_management` | `mockManagement.ts` / `/console/mock-management*` | 管理面与执行面路由均装配；真实运行匹配未测 |
| `model_configuration` | `modelConfigs.ts` / `/admin/model-configs` | 有管理页面；密钥遮罩/加密路径仅静态审查 |
| `notifications` | `notifications.ts`、`notificationChannels.ts` / 通知、渠道及报告页 | 两类 Router 均已挂载；外部 Webhook 未发送 |
| `organizations` | `organizations.ts` / 管理组织、资料页 | 有 API 和页面；跨组织矩阵未在本次运行 |
| `projects` | `projects.ts` / 管理项目、控制台项目及详情 | 有 API 和页面；成员权限与数据隔离未运行 |
| `reports` | `reports.ts` / `/console/test-reports*` | 列表/详情入口存在；报告生成、下载未验证 |
| `security_testing` | `securityTesting.ts` / `/console/security-testing` | 安全用例、ZAP 页面/接口均有映射；ZAP 未启动 |
| `tasks` | `tasks.ts` / `/console/tasks*` | 任务创建与查看入口存在；后台 Worker 未运行 |
| `test_data` | `testData.ts` / `/console/test-data` | 页面及 API 模块存在；目标数据库连接和清理未测 |
| `test_management` | `testManagement.ts` / 资产、套件、计划、执行相关路由 | 入口与后端域对应；执行链路未运行 |
| `users` | `auth.ts`、`users.ts` / 登录、注册、资料、管理用户 | JWT 与用户路由映射存在；登录/角色矩阵未动态测 |
| `web_ui` | `webUI.ts` / `/console/web-ui`、`web-ui-agent` | 页面对象、Agent、执行相关映射存在；Playwright 浏览器未运行 |

未发现“前端整个业务域存在而后端完全没有对应 feature/API”的明确断层。上表只证明源码入口有对应关系，不证明所有按钮都能成功完成完整业务流程。

## 4. 问题总览

| 编号 | 分类 | 严重程度 | 优先级 | 验证状态 | 主题 |
|---|---|---|---|---|---|
| SEC-001 | 安全/部署配置 | 高（暴露条件触发） | P1 | 配置已确认，网络可达性待验证 | PostgreSQL 默认凭据与宿主机端口发布 |
| SEC-002 | 安全/认证 | 中 | P2 | 静态确认 | Bearer JWT 存在 localStorage，脚本可读取 |
| SEC-003 | 安全/配置 | 中 | P2 | 静态确认，部署影响待验证 | 示例 JWT 密钥会被启动接受 |
| ARCH-001 | 性能/架构 | 中 | P2 | 静态确认，数据规模影响未实测 | 分页辅助函数无界拉取所有记录 |
| QUAL-001 | 测试与质量门禁 | 中 | P2 | 清单确认 | 缺少统一前端测试/浏览器回归与 lint 门禁 |
| DOC-001 | 架构文档 | 低 | P3 | 静态确认 | 目标架构文档与现有迁移/模块数量不一致 |
| PERF-001 | 性能 | 低 | P3 | 构建实测 | 一个生产 JS chunk 超过 500 kB |
| DEP-001 | 依赖安全 | 中（开发工具高危项） | P2 | npm audit 实测；利用条件待验证 | Vite/esbuild 与 React Router 依赖存在已知漏洞 |

> 本节 SEC-001 至 PERF-001 的原始描述反映首次审计时的整改前状态；当前复核结果与残余风险见 §9。

### SEC-001 — 开发数据库凭据默认且端口对所有宿主接口发布

- **模块/分类：** 部署配置 / 数据库安全。
- **严重程度/优先级：** 高，P1（若该 Compose 配置运行在可被其他设备访问的主机上）；当前未确认存在外部暴露。
- **问题与影响：** `compose.yaml` 为开发 PostgreSQL 使用固定默认凭据，并将容器端口映射为 `5432:5432`。Docker 未指定宿主机环回地址时通常会在宿主机各网络接口发布端口。若开发 Compose 被放在共享网络或云主机上，且防火墙允许访问，攻击者可尝试使用仓库内可见的默认凭据直接访问数据库，造成数据读取、篡改或删除。测试夹具与启动文档也保留了本地默认连接设置。
- **位置：** [compose.yaml:12-15](../../compose.yaml)；`backend/tests/conftest.py:26-49`；`docs/getting-started.md` 和 `local-startup-guide.md` 的本地数据库配置段。默认口令在本报告中已脱敏。
- **证据与复现：** Compose 明确绑定 5432 主机端口，配置中存在固定凭据。确认真实暴露面需在运行 Compose 的主机上从另一台设备连接 5432 并检查防火墙；本次未启动数据库，也未尝试远程连接。
- **验证状态：** 静态确认默认配置；运行时网络可达性待验证。
- **建议：** 本地开发绑定 `127.0.0.1:5432:5432`；将数据库口令改为本地 `.env` 注入且随机生成；对非本机部署禁止默认口令启动，并确保生产数据库不复用 Compose/test fixture 凭据。

### SEC-002 — 访问令牌存储于 JavaScript 可读的 localStorage

- **模块/分类：** 认证 / 浏览器端令牌保护。
- **严重程度/优先级：** 中，P2；本次未确认有可利用 XSS。
- **问题与影响：** 登录和注册后，Bearer JWT 写入 `localStorage`。同源脚本均可读取该令牌；若未来任一页面引入 XSS、被攻陷的依赖或恶意注入脚本，令牌可被复制用于调用 API，直到过期或版本吊销。
- **位置：** [frontend/src/api/client.ts:14-40](../../frontend/src/api/client.ts)；`frontend/src/hooks/useAuth.tsx:102-123`。
- **证据与复现：** 源码中 `tokenStore.set()` 直接调用 `localStorage.setItem()`，请求拦截器再把值设为 `Authorization: Bearer ...`。未进行真实登录，也未发现本次静态检索覆盖范围内的危险 HTML 注入点。
- **验证状态：** 存储方式静态确认；令牌被窃取的攻击路径未验证。
- **建议：** 结合部署架构评估 HttpOnly、Secure、SameSite Cookie/BFF；若继续使用 Bearer localStorage，至少缩短令牌时效、落实严格 CSP 与依赖/输入安全检查，并保持服务端吊销机制。

### SEC-003 — 示例 JWT 密钥虽为占位值仍可通过启动校验

- **模块/分类：** 密钥管理 / 配置安全。
- **严重程度/优先级：** 中，P2；是否影响当前部署取决于运维是否原样复制示例。
- **问题与影响：** `.env.example` 明确给出占位字符串作为 `SECRET_KEY`。`config.py` 仅检查密钥是否为空，没有拒绝该示例值或检查最小熵/长度。若部署时复制后未替换，JWT 的签名密钥将可预测；同一密钥还可能作为模型配置加密密钥的派生来源，风险不限于令牌签名。
- **位置：** [backend/.env.example:7-10](../../backend/.env.example)；[backend/app/shared/config.py:220-222](../../backend/app/shared/config.py)。
- **证据与复现：** 静态读取配置可见占位值非空且启动门禁仅为 `if not SECRET_KEY`。当前本机 `.env` 的值已脱敏且不纳入报告；本次未启动后端验证真实部署配置。
- **验证状态：** 校验逻辑静态确认；实际环境是否使用占位值未知。
- **建议：** 拒绝已知占位值，并对非测试环境强制最小长度/熵；明确区分测试密钥与运行密钥，启动日志只记录校验结果、不记录密钥。

### ARCH-001 — 前端分页辅助函数把分页接口逐页全部拉入内存

- **模块/分类：** 前端数据加载 / 性能与扩展性。
- **严重程度/优先级：** 中，P2；实际影响取决于项目数据量和网络延迟。
- **问题与影响：** `collectPages` 与 `collectArrayPages` 以串行循环一直请求到总数结束，然后把所有行合并成一个数组。该模式被测试资产、业务域/流程、安全策略/用例、模型选项、Mock/Provider 等多个列表和选择器使用。数据大时，页面首屏等待时间与浏览器内存随总记录数增长；多个查询同时触发时会产生大量串行 API 请求。它解决了只显示首页的问题，但没有限制读取规模或提供服务器端搜索/分页交互。
- **位置：** [frontend/src/api/pagination.ts:1-23](../../frontend/src/api/pagination.ts)；例如 `frontend/src/pages/console/ApiCatalog/ModuleTree.tsx:63-70` 会并发请求树所需的全部接口页；`TestAsset.tsx`、`SecurityTesting/*`、`MockManagement/*` 也调用全量收集器。
- **证据与复现：** 静态循环条件为 `items.length < total` 且无最大页数/取消条件。可在隔离项目中写入数万条记录，观察 API 请求数、首屏时间与浏览器内存；本次没有可用数据库/浏览器，未做规模测试。
- **验证状态：** 无界分页行为静态确认；性能退化未动态量测。
- **建议：** 主要表格用服务端分页；选择器采用远程搜索、游标分页或按需加载；确需树形全量数据时设置硬上限、取消信号、缓存和超限提示，并给辅助函数补总量/页数保护。

### QUAL-001 — 前端缺少统一的测试、Lint 与浏览器回归门禁

- **模块/分类：** 自动化测试 / 代码质量。
- **严重程度/优先级：** 中，P2。
- **问题与影响：** 首次审计时 npm 脚本只有 `dev`、`build`、`preview`、`typecheck`；没有 `test` 或 `lint`。当时有一个 `frontend/tests/pagination.test.mjs`，但未注册到 package script，也没有 Playwright/Cypress 配置或可运行的逐页交互套件；后端依赖清单未包含统一 lint/formatter 工具配置。页面下有 96 个 TSX 文件、当前后端静态计数 418 个 HTTP 操作，类型检查无法覆盖点击、权限跳转、后端契约、空态和错误态。
- **位置：** [frontend/package.json:6-10](../../frontend/package.json)；`frontend/tests/pagination.test.mjs`；`backend/requirements.txt`；项目未发现 ESLint/Vitest/Playwright 配置文件或后端 lint/formatter 配置。
- **证据与复现：** `npm run` 清单无测试或 lint 命令；但直接执行 `node --test tests/pagination.test.mjs` 可运行 2 项测试并通过。后端有 40 个测试文件，但本次由于依赖缺失未能执行。
- **验证状态：** 脚本和配置清单已确认；自动化覆盖缺口客观存在。
- **建议：** 将现有前端测试纳入 `npm test`；增加可运行的浏览器关键路径覆盖（登录/角色、项目切换、分页、表单重复提交、错误与空态）；在 CI 配置 lint、前端单测和类型检查。

### DOC-001 — 目标架构文档仍将现状描述为第一阶段基线

- **模块/分类：** 架构文档 / 可维护性。
- **严重程度/优先级：** 低，P3。
- **问题与影响：** `docs/target-architecture.md` 称现有 Alembic 只有 `0001_initial_schema.py`、测试仅 test_01 到 test_07，并把 Agent、API 执行、UI 自动化、数据工厂等标为未接入；当前仓库已有 29 个迁移文件、19 个 feature 域及相应页面/API。根 README 已提示自身记录阶段一历史基线，但架构文档仍称关键事实来自当前代码。新维护者可能遗漏现有实现、重复建表或误判功能边界。
- **位置：** [docs/target-architecture.md:3-10](../target-architecture.md)；`docs/target-architecture.md:77-105`；根 README 的历史基线说明位于 `README.md:1-10`。
- **证据与复现：** 文档所称单迁移与源码迁移目录 29 个版本文件不符；文档模块列表与 19 个受版本控制 feature 目录不符。数据库实际物理表数未连接验证，112 仅为 ORM 声明计数。
- **验证状态：** 静态对照确认文档与当前源码存在漂移。
- **建议：** 将该文档明确标注为历史快照，或更新目标架构、模块清单、迁移数量、测试入口和未接入能力；将 README 中的旧基线数值标明版本/日期。

### PERF-001 — 生产构建包含超过 Vite 默认阈值的 JavaScript chunk

- **模块/分类：** 前端加载性能。
- **严重程度/优先级：** 低，P3；本次未测真实网络或首屏加载时间。
- **问题与影响：** 生产构建生成一个 588.51 kB 的 JavaScript chunk（gzip 约 194.53 kB），触发 Vite 的 500 kB 提示。低带宽设备或首次访问可能增加下载/解析耗时。
- **位置：** 构建产物 `frontend/dist/assets/index-B7bz_Gaz.js`（文件名由本次构建生成，哈希会变化）；构建配置在 `frontend/vite.config.ts`。
- **证据与复现：** 本次 `npm run build` 输出 `(!) Some chunks are larger than 500 kB after minification`，最大 chunk 588.51 kB / gzip 194.53 kB。
- **验证状态：** 构建实测；运行时性能未测。
- **建议：** 对初始依赖做 Rollup bundle 分析，按路由/重依赖拆包，检查图标、编辑器和组件导入方式；以真实首屏关键资源指标决定拆包优先级。

### DEP-001 — Vite/esbuild 与 React Router 依赖存在已知安全公告

- **模块/分类：** 前端依赖 / 开发服务与路由安全。
- **严重程度/优先级：** 中，P2。Vite/esbuild 问题主要影响正在运行的开发服务器；React Router 公告影响站内跳转处理，需结合实际路径判断可利用性。
- **问题与影响：** 整改期间执行 `npm audit --json`，发现 4 个漏洞公告（3 个中危、1 个高危）：Vite 5.4.21 所依赖的 esbuild/`launch-editor` 落在公告影响范围；react-router-dom 6.26.2 依赖的 React Router 版本低于修复版本，包含反斜杠开放重定向公告。应用只使用客户端路由，未发现 SSR hydration 使用路径；登录回跳是直接相关的输入点，现已补充站内路径校验。
- **位置：** `frontend/package.json`、`frontend/package-lock.json`；开发服务器绑定见 `frontend/vite.config.ts`；登录回跳见 `frontend/src/pages/auth/Login.tsx` 与 `frontend/src/utils/safeRedirect.ts`。
- **证据与复现：** `cd frontend && npm audit --json` 返回 4 个受影响依赖公告；[Vite/esbuild GHSA-67mh-4wv8-2f99](https://github.com/advisories/GHSA-67mh-4wv8-2f99)、[React Router GHSA-wrjc-x8rr-h8h6](https://github.com/advisories/GHSA-wrjc-x8rr-h8h6)、[React Router GHSA-337j-9hxr-rhxg](https://github.com/advisories/GHSA-337j-9hxr-rhxg)。
- **验证状态：** 依赖版本与 npm 公告已动态核对；攻击可利用性未做浏览器验证。登录回跳防护有 Node 单测覆盖。
- **建议：** 已将 Vite 开发服务器限定到 `127.0.0.1` 并拒绝登录跳转中的反斜杠。依赖公告的完整清除需要 Vite 8 与 React Router 7 major 升级；按 `docs/coding-conventions.md` §4.3，需先制定迁移计划并跑完整回归，不在本分支直接越过该流程。

## 5. 未计入问题统计的观察项

### OBS-001 — 接口结构指纹对列表顺序敏感，需确认顺序语义

`backend/app/features/api_catalog/services/hash.py:27-33` 对 JSON 对象键排序，但 `parameters`、`responses` 等列表仍按输入顺序参与 SHA-256。相同参数集合换序会产生不同指纹；导入分类由该指纹驱动。参数顺序是否属于接口结构/产品展示语义尚未由规范明确，因此本项不计为已确认缺陷。建议产品确认后统一排序规范或明确顺序差异必须产生版本变更，并加回归测试。本次无法导入 Pydantic 模块做实际函数验证。

## 6. 功能与 UI/UX 审计结论

### 6.1 功能完整性

- 主要页面路由、前端 API 文件及后端 feature/router 均可建立对应关系，完整映射见 §3。Mock 运行时被单独装配在管理面之后；文档和源码均显示其执行面采用 Mock Token 与管理 JWT 分离。
- 代码里可见真实的 service、数据库模型和迁移；不能据此认定 LLM、ZAP、Playwright、Webhook、数据库 Provider 等外部流程当前环境可用。本次未运行这些外部依赖或执行写入型业务流程。
- `collectPages` 相关列表代码当前通过拉取全部页处理数据截断问题，但在大数据量下存在 §4 的扩展性风险。
- 既有未提交改动中可见接口编辑后重算结构 hash、导入时以当前持久化结构重新比较、Mock 上下文头注入业务 API 动作，以及 API 搜索受控输入、项目切换重置、报告页 Hook 顺序和多个列表分页/错误态修正等改动（例如 `api_catalog/services/api_service.py`、`import_service.py`、`business_flow_executor.py`、`ApiToolbar.tsx`、`ApiCatalog/index.tsx`、`Reports/ReportList.tsx`）。由于后端集成测试不可运行，这些修订仅完成静态检查，不作为已回归确认的修复结论。

### 6.2 UI/UX

- 已静态枚举全部前端路由，并扫描页面请求、mutation、错误状态、表格分页、断点 CSS 和危险 DOM 注入 API。路由与页面分组见 §3.1。
- 当前没有任何页面截图：CUA 浏览器清单为空，`iab` 不可用；运行 Vite 后，审计 shell 也无法连到开发服务器。未通过截图或真实点击确认布局溢出、文字截断、对齐、弹窗遮挡、移动端导航或交互反馈问题。
- 因缺少浏览器与登录数据，本次 **没有将静态布局推断登记为 UI 已确认缺陷**。页面逐一可访问性和交互验收仍未完成，截图证据也受运行条件限制。

## 7. 测试与可执行验证

| 命令/步骤 | 结果 | 说明 |
|---|---|---|
| `cd frontend && npm run typecheck` | 通过 | `tsc -b --noEmit` 退出码 0 |
| `cd frontend && npm run build` | 通过，有警告 | TypeScript 与 Vite 构建成功；一个 chunk 588.51 kB，见 PERF-001 |
| `cd frontend && node --test tests/pagination.test.mjs` | 2 通过，0 失败 | 覆盖分页收集、响应元数据、空页失败和网络失败；未覆盖 React 页面或接口服务 |
| Python AST 静态解析 `backend/app/**/*.py` | 367 文件通过，0 语法错误 | 未导入模块、未检查运行依赖或类型正确性 |
| `python3 -m pytest -q backend/tests/test_23_security_mutation.py backend/tests/test_28_zap_connector.py` | 未执行测试体 | pytest 加载 `backend/tests/conftest.py` 时因系统 Python 缺少 `psycopg` 报 `ModuleNotFoundError`；没有 DB 连接/删除操作发生 |
| 检查 `backend/.venv/bin/python` 与端口 | 后端环境不可运行 | `.venv` 不存在；本机 PostgreSQL `5432` 和后端 `8001` 未监听 |
| 启动 `npm run dev -- --host 127.0.0.1` | 在沙箱中失败 | 首次监听被 `EPERM` 阻止；获准提升后 Vite 显示已在 5173 启动，但审计 shell 无法连通该进程 |
| CUA 浏览器状态 / 打开本地登录页 | 受限 | 浏览器清单为空，`iab` 返回 Browser unavailable；未登录、未操作页面、未生成截图 |
| 构建产物密钥检查 | 未发现命中 | 对本地选择的敏感环境变量值做精确匹配，均未出现在 JS/HTML；0 个 source map。该扫描不构成完整秘密扫描器 |

全量后端测试未运行的原因是测试夹具依赖 PostgreSQL 驱动、会创建并在 teardown 删除隔离测试数据库，而本机既缺少项目虚拟环境依赖也没有 PostgreSQL 服务。没有为绕过限制安装依赖、修改连接地址或启动数据库。前端浏览器验收未运行，不能把构建通过视作 UI/业务流程通过。

## 8. 整改优先级与实施计划

| 优先级 | 建议顺序 | 修复事项 | 涉及范围 | 完成标准 |
|---|---:|---|---|---|
| P1 | 1 | 开发数据库仅绑定回环地址、移除固定默认凭据；部署环境禁止复用 | `compose.yaml`、测试配置、本地启动文档 | 从非本机无法连接开发 DB；启动配置无可复用默认密码 |
| P2 | 2 | 拒绝示例/弱 JWT 密钥；明确测试、开发、生产密钥门禁 | `backend/app/shared/config.py`、环境示例、启动流程 | 示例值启动失败；密钥强度校验有单元测试 |
| P2 | 3 | 评估 JWT Cookie/BFF 或加强 localStorage 威胁缓解 | 前端 `client.ts`、认证 API、CSP/部署配置 | 令牌存储策略、CSRF/XSS 防护与失效行为写入并通过安全测试 |
| P2 | 4 | 将全量页收集改为服务器分页/搜索，树和选项按需加载 | `frontend/src/api/pagination.ts` 及调用页面、必要的后端列表 API | 大数据集下请求量受控；搜索能找到非首屏结果；错误/取消状态可见 |
| P2 | 5 | 建立前端统一测试、Lint 和浏览器关键路径门禁，并恢复可运行后端环境 | `frontend/package.json`、CI、测试设施；后端依赖/DB fixture | `npm test`/lint/Playwright 可重复执行；后端全套测试能在隔离 DB 通过 |
| P3 | 6 | 更新目标架构与仓库结构、迁移、测试、未接入能力文档 | `docs/target-architecture.md`、README、文档索引 | 文档中的模块/迁移状态与源码对齐，历史基线明确标注日期 |
| P3 | 7 | 按性能数据拆分大 chunk | Vite 构建配置与高体积依赖 | 明确初始 chunk 预算，并以加载/解析实测验证优化效果 |

### 审计限制与结论边界

1. 本报告覆盖当前工作区源码清点、模块映射、路由/依赖/配置静态检查和已能执行的前端验证；由于 367 个后端 Python 文件和 169 个前端 TS/TSX 文件规模较大，不能将其表述为逐语句人工证明无缺陷。
2. 418 个 API 方法/端点声明全部进入静态路由清单，但没有逐接口请求验证。没有数据库或 API 服务，故权限越权、事务一致性、字段映射、超时/重试/重复提交及异常数据状态未形成动态结论。
3. 46 个路由元素已枚举，但浏览器不可用；UI 截图、不同视口测量、用户操作路径和页面状态动态检查未完成。
4. 未连接实际部署网络、外部 LLM、MCP、ZAP、目标数据库或通知服务。因此有关外部可达性、真实凭据强度和集成行为均按“待验证”处理。
5. 工作区已有未提交代码变化。报告针对审计时当前文件状态，不代表这些改动已经提交、回滚或通过后端集成验证。

## 9. 整改分支复核（2026-10-28）

整改分支：`codex/full-project-audit-remediation`。首次审计列出的 7 项问题仍保留在 §4 作为修复前证据；复核新增 DEP-001，因此本报告共记录 8 项问题。当前工作区仍包含本审计开始前已有的其他未提交修改，不能将全部改动归因于本次整改。

| 编号 | 复核状态 | 已实施内容 | 残余限制 |
|---|---|---|---|
| SEC-001 | 已修复（静态） | Compose 仅发布到 `127.0.0.1`；用户、密码和库名必须显式提供；测试密码不再有仓库默认值；启动文档更新 | 未在另一台设备上验证网络不可达；测试需配置 `TEST_POSTGRES_PASSWORD` |
| SEC-002 | 已实现（动态待验） | 浏览器登录/注册/退出改为 HttpOnly Cookie；Cookie 默认 Secure、SameSite=Lax、仅 `/api/v1` 路径；写请求校验允许的 Origin；Cookie 优先于兼容 Bearer；Axios 使用 `withCredentials`；前端不再持久化 JWT；两种注册入口共用 service 层事务 | 后端集成测试受 psycopg 缺失阻断；部署前端与 API 需保持同站或由反向代理统一来源。旧 Bearer API 为兼容第三方客户端仍返回 JWT，不属于浏览器 UI 路径 |
| SEC-003 | 已实现（动态待验） | `SECRET_KEY` 至少 32 字符、至少 12 种不同字符且拒绝常见占位标记；`.env.example` 不再包含可直接用的签名密钥 | 配置单测已添加，但因后端测试夹具导入 psycopg 失败，尚未执行 |
| ARCH-001 | 部分修复 | `collectPages` 与 `collectArrayPages` 限制最多 5,000 条/50 页；超限抛出中文错误，不静默返回不完整结果 | 主要列表仍有全量收集调用；后续应改为服务端分页、远程搜索与取消请求，5,000 条是保护上限而非目标数据量 |
| QUAL-001 | 部分修复 | 新增 `npm test`、严格 `npm run lint`；Node 内置测试共 4 项通过，ESLint 全前端 0 warning/error | 浏览器逐页回归未能运行；后端 pytest 被缺少 psycopg 阻断；无 CI 工作流可以接入门禁 |
| DOC-001 | 已修复 | `docs/target-architecture.md` 顶部标注为历史快照并链接当前审计 | 旧章节内容仍保留作设计背景，读取时应以该提示和当前源码为准 |
| PERF-001 | 已修复（构建实测） | Vite/Rollup 按 React、Router、Query、工具库拆分共享 chunk | 未采集真实首屏下载、解析或低带宽设备性能数据 |
| DEP-001 | 缓解，依赖升级待议 | Vite dev server 改为仅本机监听；登录跳转新增同站路径校验，拒绝反斜杠/控制字符 | 4 条 npm 公告仍在锁文件所用版本上；按仓库 major 升级约定，Vite 8 / React Router 7 迁移需先完成计划与完整回归 |

### 整改后验证记录

| 命令 | 结果 | 说明 |
|---|---|---|
| `cd frontend && npm test` | 4 通过，0 失败 | 分页响应/超限与登录回跳安全单测 |
| `cd frontend && npm run lint` | 通过 | ESLint + TypeScript ESLint + React Hooks；`--max-warnings=0` |
| `cd frontend && npm run typecheck` | 通过 | `tsc -b --noEmit` |
| `cd frontend && npm run build` | 通过 | 3297 modules；最大 chunk 335.45 kB，未出现 500 kB 警告 |
| `POSTGRES_USER=… POSTGRES_PASSWORD=… POSTGRES_DB=… docker compose config --quiet` | 通过 | 使用临时配置值校验 Compose 展开；没有启动容器或数据库 |
| Python AST 静态解析 | 411 个文件通过，0 语法错误 | 覆盖 backend/app、tests、scripts；不代表类型或运行行为正确 |
| `TEST_POSTGRES_PASSWORD=… python3 -m pytest -q tests/test_02_auth_flow.py -k 'browser_session or settings_reject'` | 未进入测试体 | `backend/tests/conftest.py` 导入失败：`ModuleNotFoundError: No module named 'psycopg'`；没有数据库连接或写入 |
| `cd frontend && npm audit --json` | 4 条公告（3 中危、1 高危） | 涉及 Vite/esbuild 与 React Router；升级需要 major 迁移，见 DEP-001 |

本轮未能启动浏览器或后端服务，因此没有生成 UI 截图，也没有验证 cookie 的真实浏览器发送、Origin 拒绝、注销清理、CORS 部署配置及各页面超限错误态。该状态不能视为动态验收通过。

### 剩余整改优先级

| 优先级 | 下一步 | 影响范围 | 完成标准 |
|---|---|---|---|
| P2 | 在装有 psycopg 与隔离 PostgreSQL 的环境运行后端全量测试及新增 Cookie/密钥测试 | 后端认证与配置 | 测试通过，确认 Set-Cookie、Origin 拒绝、退出清理及密钥校验 |
| P2 | 按仓库 major 升级流程评估 Vite 8、React Router 7 | 前端依赖/构建/路由 | 提交迁移计划、逐页导航回归与 npm audit 清零 |
| P2 | 把树/选择器全量收集迁移为服务端搜索和分页 | 高频列表与选择器 | 大数据量下首屏和请求数稳定，支持定位非首屏记录 |
| P3 | 在可用浏览器补跑登录、角色、错误态、移动端与超限路径并保存截图 | 46 个路由与关键交互 | 每个页面状态有可复现证据和截图 |
