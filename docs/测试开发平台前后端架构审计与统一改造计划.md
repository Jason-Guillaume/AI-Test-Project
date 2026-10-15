# 测试开发平台前后端架构审计与统一改造计划

分析日期：2026-10-15。范围是当前工作区源码，含未提交的测试数据中心与 Alembic `0009`。本文件只做审计和分阶段改造计划，不改功能代码、不建迁移、不重命名已有 API。

后续可以把 **Phase A / Phase B / Phase C** 整段交给 Claude Code 执行。每一阶段的允许改动、禁止项、验收命令都写在对应章节。

---

## 1. Executive Summary

平台不需要大重构。第一阶段和第二阶段以后用的是同一套 FastAPI feature、同一套 `{code, message, request_id}` 错误信封、同一套项目角色函数 `app/shared/roles.py`。后期模块（接口、业务、测试、造数、Agent、报告）已经比早期模块更接近目标结构。

真正要收敛的是七件事，而且都应该用兼容层做，不要搬目录、不要改表：

1. 项目可见性校验被复制了四份，新模块还会再抄一份。
2. HTTP 出站有两套实现：`DebugService` 自己发 httpx，`ApiRequestExecutor` 又发一套。
3. 用例执行业务动作时，没有调用已经公开的 `run_action`，而是在 `test_case_executor._execute_business_action` 里再写了一遍绑定、映射和 HTTP。
4. 环境接口全部锁在平台管理员，控制台执行、Agent、造数却都要选环境。
5. 错误码同时存在 `ERR_*` 和裸码（`FIXTURE_NOT_FOUND`）。
6. 切换项目时，测试计划、套件、用例、报告、飞书渠道的 Query 缓存不会失效。
7. `agent`、`reports`、`notifications` 互相引用，脱敏和 LLM 调用落在 Agent 包里，报告和飞书从下层反向依赖它。

判定：先定规范（Phase A，只加文档），再抽公共底座（Phase B，行为不变），再按依赖从下往上逐个 Feature 改调用点（Phase C）。用户、组织、看板、缺陷不要为了目录整齐去动。

---

## 2. 当前项目架构图

```
浏览器
  React 18 + antd + React Query
  /admin/*  平台管理          /console/*  项目控制台
        \                         /
         axios client  /api/v1    （Vite 不改写路径）
                    |
              FastAPI app/main.py
                    |
     +--------------+-------------------------------+
     | 平台层                                        |
     | users / organizations / projects             |
     | model_configuration / environment            |
     | captcha / dashboard / notifications(收件箱)  |
     +----------------------------------------------+
                    |  project_id + roles
     +--------------v-------------------------------+
     | 领域层                                        |
     | api_catalog  →  business（绑定接口并执行）    |
     | defects（旁路，只挂项目）                     |
     +----------------------------------------------+
                    |  execute_flow / run_action / ApiRequestExecutor
     +--------------v-------------------------------+
     | 测试与造数层                                  |
     | test_management（资产、计划、Run）            |
     | test_data（Fixture、Provider、Data Factory） |
     +----------------------------------------------+
                    |  TestRun / CaseExecution
     +--------------v-------------------------------+
     | 交付层                                        |
     | reports → notifications.channel（飞书）      |
     +----------------------------------------------+
                    |  反向依赖 sanitizer / LLM（应上移到 shared）
     +--------------v-------------------------------+
     | 智能层                                        |
     | agent（LangGraph，人工确认，调用以上各层）    |
     +----------------------------------------------+
                    |
              PostgreSQL 16
              Alembic 0001 → 0009
```

运行时一条用例的真实调用链：

`RunService.create_and_execute_run`
→ `test_data.runtime.lifecycle`（RUN/CASE Fixture）
→ `DataFactory` → Provider（API / Business / Faker / DB / Pool）
→ `test_case_executor.execute`
→ `ApiRequestExecutor` 或 `execute_flow` 或 `_execute_business_action`
→ 断言引擎
→ `ReportService` 另一次请求生成报告

`bootstrap/routes.py` 不是运行时装配点。运行时只认 `backend/app/main.py` 的 `include_router`。`bootstrap/routes.py` 目前漏了 `api_catalog`、`test_management`、`reports`、`notification channel`。

---

## 3. 模块清单

| Feature | 层 | 后端目录 | 端点数 | 前端入口 | 迁移 |
|---|---|---|---|---|---|
| 验证码 | 平台 | `features/captcha` | 1 | 登录/注册 | 无表 |
| 认证与用户 | 平台 | `features/users` | 11 | `/login` `/register` `/admin/users` `/console/profile` | `user`（0001） |
| 组织 | 平台 | `features/organizations` | 9 | `/admin/organizations` | `organization*`（0001） |
| 项目 | 平台 | `features/projects` | 14 | `/admin/projects` `/console/projects` | `project*`（0001） |
| 模型配置 | 平台 | `features/model_configuration` | 7 | `/admin/model-configs` | `model_configuration`（0001） |
| 环境 | 平台 | `features/environment_configuration` | 6 | `/admin/environments`；控制台多处偷偷调用 | `environment`（0001） |
| 看板 | 平台 | `features/dashboard` | 4 | `/admin/dashboard` `/console` | 无新表 |
| 站内通知 | 平台 | `features/notifications/router.py` | 6 | `/console/notifications` | `notification`（0001） |
| 缺陷 | 领域 | `features/defects` | 5 | `/console/defects` | `bug`（0002） |
| 接口管理 | 领域 | `features/api_catalog` | 23 | `/console/api-catalog` | 8 表（0003） |
| 业务管理 | 领域 | `features/business` | 47 | `/console/business-management` | 10 表（0004）+ 执行表（0005） |
| 测试管理 | 测试 | `features/test_management` | 54 | 测试资产/套件/计划/执行中心/历史 | 13 表（0006） |
| 测试数据 | 测试 | `features/test_data` | 44 | `/console/test-data` | 17 表（0009） |
| Agent | 智能 | `features/agent` | 6 | `/console/agent` | 2 表（0007） |
| 测试报告 | 交付 | `features/reports` | 5 | `/console/test-reports` | `test_report`（0008） |
| 飞书渠道 | 交付 | `features/notifications/channel_router.py` | 9 | `/console/notification-channels` | `notification_channel` `notification_record`（0008） |

业务 HTTP 端点合计 251。另有根路径 `/healthz`、`/health` 与 `/api/v1/meta`。

---

## 4. 后端 Architecture Inventory

图例：事务列写的是**谁 commit**。权限列写的是**实际代码位置**，不是文档声称。

| Feature | Router | Service | Executor / Provider | Permission | Error | 事务 | 风险 |
|---|---|---|---|---|---|---|---|
| captcha | `captcha/router.py` | `captcha/service.py` 函数 | 无 | 无登录；IP 限流 | `shared.errors` | 无库 | 进程内字典，多实例不可用 |
| users | `users/auth.py` `users/admin.py` | `users/service.py` 类 | 无 | 平台角色 + `token_version` | `bad_request` / `conflict` | **auth 路由自己 commit**；service 也 commit | 注册事务在路由 |
| organizations | `organizations/router.py` | `organizations/service.py` 只有 `ensure_personal_organization` | 无 | 路由内手写组织角色 | `bad_request`（名称冲突也是 400，不是 409） | **路由 commit 5 处** | 业务规则在路由 |
| projects | `projects/router.py` | `projects/service.py` 类 | 无 | service 内 `has_project_role`；写项目要 editor，不是 member | `not_found` 有两处在路由 | service commit | 写权限门槛高于后期模块 |
| model | `model_configuration/router.py` | 模块级函数 | 无 | 路由 `require_platform_admin` | shared | service commit | 密钥只在本模块加密 |
| environment | `environment_configuration/router.py` | 模块级函数 | 无 | **全部端点** `require_platform_admin` | shared | service commit | 控制台无法合法读环境 |
| dashboard | `dashboard/router.py` | `dashboard/service.py` | 无 | 登录；`/platform` 要平台管理员 | shared | 只读 | 直接 import `defects.models.bug` |
| notifications 收件箱 | `notifications/router.py` | 逻辑在路由 | 无 | 路由内按 user_id | `not_found` | **路由 commit** | 没有 service |
| defects | `defects/router.py` | `DefectService` | 无 | service 内联 viewer/member，与后期 `_access` 同口径 | `not_found` 隐藏越权 | service commit | 列表用 `?project_id=`，不是嵌套路径 |
| api_catalog | `api_catalog/router.py` | `ApiService` 等；调试 `DebugService` | `parsers/openapi_parser.py`；调试自己 httpx | service 私有 `_get_project_or_404`；调试路由 `require_platform_admin` | shared；调试另有白名单 403 | service commit | 第二套 HTTP 客户端；调用 `_load_body` 私有函数 |
| business | `business/router.py` | `services/*` 六个类 | `executors/api_executor.py` `business_flow_executor.py` `mapping_resolver.py` `context.py` `sensitive.py` | `services/_access.py` | `not_found` / `AppError` | **service commit，且 `execute_flow` 自己 commit** | 执行器持有事务 |
| test_management | `test_management/router.py` | `services/*` | `executors/test_case_executor.py` `assertion_engine.py` | 再抄一份 `_access.py` | 执行失败多数变成结果状态，不抛 HTTP | **Run 逐用例 commit；内部 `execute_flow` 再 commit** | 动作执行复制；列表返回裸数组 |
| test_data | `test_data/router.py` | `services/*` | `providers/*` `runtime/data_factory.py` `lifecycle.py` `cleanup_runner.py` `variable_resolver.py` | 第三份 `_access.py`；连接/策略 `require_admin` | `AppError` + 裸错误码 | Factory / Lifecycle / Cleanup / Service 都会 commit | 最接近目标，但事务层多 |
| agent | `agent/router.py` | `services/session_service.py` | `graph.py` + `nodes/*` + `providers/llm_provider.py` | session service 调用测试模块 `_access` | 节点把 `HTTPException` 收成 state.error | session service commit；`tools/execution_tool.py` 再 commit | 路由直接 `run_agent`；包被报告反向依赖 |
| reports | `reports/router.py` | `services/report_service.py` `ai_summary.py` | 无独立执行器 | 借用 `test_management.services._access` | `ERR_REPORT_*` | service commit | import Agent 的 sanitizer 和 LLM |
| 飞书渠道 | `notifications/channel_router.py` | `channel_service.py` `feishu_service.py` | httpx POST webhook | 借用测试模块 `_access` | `ERR_FEISHU_*` / `ERR_NOTIFICATION_*` | service commit | 路由编排了 reports + channel + feishu 三个 service |

### 4.1 各模块目录形态

早期（0001 一带）是四文件：`router.py` + `schemas.py` + `service.py`，模型在 `app/models/`。

`organizations` 更早：写操作在路由里，service 几乎是空的。

`defects` 开始 feature-local 模型（`features/defects/models/bug.py`），但仍然是单文件 `service.py`。

`api_catalog` 起变为 `models/` + `services/` + `parsers/`。

`business` 起增加 `executors/`。

`test_data` 增加 `providers/` + `runtime/` + `security/`。

`agent` 增加 `nodes/` + `tools/` + `providers/` + `prompts/`，没有把测试放进 feature 目录。测试一律在 `backend/tests/`。

不要要求每个 Feature 补齐 `executors/`、`providers/`、`runtime/`、`errors.py`。没有执行、没有可替换外部能力、没有运行时上下文的模块保持现在的四文件。

### 4.2 Project Scope 方式

| 方式 | 模块 |
|---|---|
| 资源行上有 `project_id`，用 id 路径再回溯 | api、business、test、test_data、reports、agent、渠道 |
| 列表嵌套在 `/projects/{project_id}/...` | 上面这些的列表 |
| `?project_id=` 过滤，资源路径不带项目 | defects：`GET /bugs?project_id=` |
| 平台级，没有 project_id | user、organization、model、environment、captcha |
| 组织级 | organization 成员 |
| 收件箱按 user_id | notifications |

后期模块的回溯函数是合格的：`resolve_case_project_id`、`resolve_flow_project_id`、`resolve_fixture_project_id`。找不到实体返回 404，可见性再走 `get_project_or_404`。

### 4.3 已知特殊实现

- 环境按 **name** 定位，不按 id。执行器也按 name 找环境。
- 测试管理多数列表 `response_model=list`，直接返回数组。`frontend/src/api/testManagement.ts` 第 12–14 行写明了这一点。Schema 里同时存在未使用的分页模型。
- `execute_flow` 失败路径和成功路径都会 `db.commit()`（`business_flow_executor.py` 约 198、205 行）。调用方不能把它包进自己的未提交事务。
- `run_action` 是给 Data Factory 用的薄封装，**不跑整条流程、不自己 commit**。用例执行器没有用它。
- Agent 无 LangGraph checkpointer。每次请求从 `agent_session` / `agent_message` 重建状态。
- 造数步骤 `WAIT` / `DATABASE_QUERY` / `EXTERNAL_PROVIDER` 只保存，执行即 `FIXTURE_STEP_UNSUPPORTED`。
- 被测库连接密码、模型 Key、飞书 Webhook 都走 `app/shared/crypto.py` 的 Fernet。响应不回明文。

---

## 5. 前端 Architecture Inventory

前端没有 `src/features/`。页面在 `src/pages/{auth,admin,console}`。请求在 `src/api/*.ts`（18 个文件）。类型几乎全在 `src/types/index.ts`（2215 行）。共享组件只有 6 个：`ResourceTable`、`PageState`、`ResultPages`、`RoleTag`、`RouteGuards`、`QueryProvider`。

没有前端测试文件（无 `*.test.ts` / `*.spec.tsx`）。

| 页面群 | 组织方式 | API Client | Query Key 前缀 | 主要组件 | 风险 |
|---|---|---|---|---|---|
| 登录注册 | `pages/auth/*.tsx` 单文件 | `api/auth.ts` `api/captcha.ts` | 无 | 表单 | 低 |
| 管理端 | `pages/admin/*.tsx` 单文件 | users / orgs / projects / modelConfigs / environments / dashboard | `users` `organizations` `model-configs` `environments` `dashboard` | `ResourceTable` | 环境 key 与控制台混用 |
| 工作台、项目、缺陷、通知、个人中心 | `pages/console/*.tsx` 单文件 | 对应 api | `dashboard` `projects` `bugs` `notifications` `project` | `ResourceTable` + Modal | 第一代样板，页面自己写失效 |
| 接口管理 | `pages/console/ApiCatalog/` 目录 | `api/apiCatalog.ts` | `api-catalog` | 树 + 详情 Tab + `JsonView` | 最接近 Catalog Pattern |
| 业务管理 | `pages/console/BusinessManagement/` | `api/business.ts` | `business` | 域树 + 流程详情 + 多个 Editor | 子面板都失效整个 `business` |
| 测试资产 | `TestManagement/TestAsset.tsx` 1201 行 | `api/testManagement.ts` | `test-strategies` `test-points` `test-cases` `test-case-detail` `fixtures` | 一个文件里的策略/用例/步骤/断言 | 页面过重；切项目不失效这些 key |
| 套件 / 计划 / 执行 | `TestSuites.tsx` `TestPlans.tsx` `ExecutionCenter.tsx` `ExecutionHistory.tsx` | 同一个 client | `test-suites` `test-plans` `plan-suites` `test-runs` `case-executions` | 表 + Modal | 切项目不失效 |
| 测试数据 | `pages/console/TestData/` 多文件 | `api/testData.ts` | `test-data` | Tab：Fixture 树、Provider、资产、执行抽屉 | 切项目会失效，结构最好 |
| Agent | `Agent/AgentPage.tsx` 859 行 | `api/agent.ts` | `agent` | 会话列表 + 对话 + 工作区 | 单文件过重，但 key 含 projectId |
| 报告 | `Reports/ReportList.tsx` `ReportDetail.tsx` | `api/reports.ts` | `test-reports` `test-report-detail` `report-notifications` | 表 + 详情 | 切项目不失效 `test-reports` |
| 飞书 | `NotificationChannels.tsx` 单文件 | `api/notificationChannels.ts` | `notification-channels` `channel-records` | 表 + Modal | 切项目不失效 |

类型定义位置：页面和 api 都 `import ... from '@/types'`。个别请求体写在 api 文件里（例如 `defects.ts` 的 `BugCreate`），与 `types/index.ts` 重复一份契约的风险已经出现。

缓存失效策略的唯一集中点是 `frontend/src/hooks/useConsoleScope.tsx`：

- 切组织会失效：`projects` `dashboard` `bugs` `business` `test-data`。
- 切项目会失效：`project` `notifications` `bugs` `api-catalog` `business` `agent` `test-data`。
- **不会**失效：`test-strategies` `test-points` `test-cases` `test-case-detail` `test-suites` `test-plans` `test-runs` `test-reports` `notification-channels` `environments`。

这是后期页面接上了菜单、没有回头改 Scope Provider 的结果。

---

## 6. 第一阶段与后续阶段架构差异

依据是目录和事务代码，不是阶段名称。

| 维度 | 第一阶段（users / orgs / projects / model / env / dashboard / notifications / defects） | 后期（api_catalog 起） |
|---|---|---|
| 目录 | 单文件 `service.py`，或路由里写业务 | `models/` `services/`，再按需 `executors/` `providers/` `runtime/` |
| 模型注册 | `app/models/__init__.py` 导入，0001 `create_all` | feature-local，0002 起 `op.create_table`，禁止进入 `app/models/__init__.py` |
| 事务 | 组织、注册、站内通知在 **路由 commit**；其余在 service | service commit；执行器、Data Factory、Run 还会再 commit |
| 权限 | 各 service 内联 `has_project_role`；环境/模型用平台管理员依赖 | 复制三份几乎相同的 `_access.py`，再互相 import 私有 `_access` |
| 错误 | 只抛 `HTTPException` 工厂（`bad_request` 等），码是 `ERR_*` | 增加 `AppError`；报告用 `ERR_REPORT_*`；造数用无前缀裸码 |
| 分页 | `{items,total,page,page_size}` | 测试资产列表改回裸数组；执行记录仍分页 |
| 路径 | `/bugs?project_id=`、`/environments/{name}` | `/projects/{project_id}/资源` + `/资源/{资源_id}` |
| 前端 | 单文件页面 + `ResourceTable` + Modal | 目录 + 树/详情；`TestAsset.tsx` 仍是单文件巨页 |
| 类型 | 追加进 `types/index.ts` | 继续追加进同一个文件 |

后期并没有换框架。差异是分层变厚了，公共函数没有抽出去，于是每个新模块抄一份。

---

## 7. 当前主要架构问题

按对后续 Mock / Security / UI 的阻塞程度排序。细节在第 32–34 节。

1. 控制台读环境被平台管理员接口挡住（`environment_configuration/router.py` 每个端点都是 `require_platform_admin`）。路由文件自己的 docstring 写过：控制台应该另做只读接口。现在执行中心、计划、业务流程、Agent、测试数据、接口调试都 `useQuery(['environments'])`。
2. 项目访问函数复制四份，且飞书、报告、Agent 直接 import `test_management.services._access`。
3. 两套 HTTP 执行器，出站白名单和响应截断会漂。
4. 业务动作执行有两条路径：`run_action` 与 `_execute_business_action`。
5. 错误码命名空间不统一，新模块没有登记处。
6. 项目切换缓存漏了测试与报告。
7. Agent 包被报告和飞书反向依赖。
8. 执行器与 Run 的 commit 边界叠在一起。
9. `types/index.ts` 2215 行，新旧模块都往里加。
10. `bootstrap/routes.py` 与 `main.py` 不一致。它不跑请求，但会让后续执行者漏注册。

---

## 8. 重复实现

| 能力 | 位置 | 重复 | 保留 | 迁移 | 风险 |
|---|---|---|---|---|---|
| 项目可见/可写 | `business/services/_access.py`、`test_management/services/_access.py`、`test_data/services/_access.py`、`api_catalog/services/api_service.py` 的 `_get_project_or_404`、`defects/service.py` 内联 | 5 处同口径 | 新建 `app/shared/access.py` 的 `get_project_or_404` / `require_writable_project` | 各 feature 改为调用 shared；**实体回溯函数留在 feature** | 低。语义已经相同：不可见 404，不可写 403 |
| 组织写流程 | `organizations/router.py` | 1 处，但是路由里的完整 CRUD | 暂留 | P2，单独阶段，不进 P0 | 中。测试覆盖组织隔离 |
| HTTP 出站 | `business/executors/api_executor.py`；`api_catalog/services/debug_service.py` | 2 个 httpx.Client，两套白名单、两套 200KB 截断 | `ApiRequestExecutor` | DebugService 改为调用它 | 中。调试响应字段要保持 |
| 飞书 / LLM HTTP | `feishu_service.py`、`llm_provider.py` | 各 1，职责不同 | 各自保留 | 不合并进 ApiRequestExecutor。它们不是被测出站 | 低 |
| 变量模板 | `test_data/runtime/variable_resolver.py`；`test_case_executor._resolve_tokens` 已是委托 | 执行器侧已收口 | `resolve_template` | 禁止新正则 | 低 |
| 映射取值 | `mapping_resolver.resolve_input_mappings` 按变量名精确取，不做 `${}` | 与模板解析是两段，不是重复 | 两段都留 | 调用顺序写进规范：先模板，再映射 | 误合并会破坏业务映射 |
| JSONPath | `mapping_resolver._jsonpath_extract`；`assertion_engine` import 这个私有函数 | 1 个实现、1 个越界调用 | 把函数改为公开 `jsonpath_extract`，仍放在 mapping 模块或 `shared/jsonpath.py` | 断言引擎改 import 公开名 | 低 |
| 脱敏 | `business/executors/sensitive.py` 的 `SensitiveDataMasker`；`agent/providers/sanitizer.py` 在其上加文本规则 | 调用点：执行器、造数、资产、池、报告 | Masker 迁到 `app/shared/security/masking.py`；sanitizer 迁到 `app/shared/security/sanitizer.py` | 旧路径留一层 re-export，一个阶段后再删 | 低 |
| 环境读取 | 各执行器 `db.query(Environment)` | 多处 | `environment_configuration` 增加 `get_active_environment` 公开函数 | 执行器改为调用它，不改表 | 中。现在按 name |
| 分页切片 | `app/shared/pagination.py` 与各 schema 手写信封 | 信封字段一致，测试列表除外 | 保持 `{items,total,page,page_size}` | 裸数组列为 Legacy，不改 | 改了会破坏前端 |
| 状态字符串 | Run、Case、Flow、Provider、Fixture 各用各的 SUCCESS/FAILED/ERROR/PASSED | 不能合成一个枚举 | 文档冻结现有枚举 | 新模块不得发明同义词 | 改枚举会坏历史数据 |
| 前端 Query 失效 | 每个页面 `invalidateQueries` + Scope 里再写一份 | 两层 | Scope 负责切项目；页面只失效自己的前缀 | 补漏的前缀 | 漏失效导致串项目数据 |

---

## 9. 模块耦合问题

真实 import 方向（服务层 / 执行器，不含 `main.py`）：

```
dashboard → defects.models
api_catalog.debug → api_service 私有 _load_body / _load_params
business.executor → api_catalog.models.ApiInterface
test_management → business.executors（execute_flow、mapping、sensitive）
test_management.case_service → test_data.models（Fixture、TestCaseFixture）
test_management.run_service → test_data.runtime.lifecycle
test_data.providers → business.executors（run_action / execute_flow / ApiRequestExecutor / masker）
reports → test_management.models + test_management.services._access
reports → agent.providers.sanitizer
reports.ai_summary → agent.prompts + agent.providers.llm_provider（函数内）
notifications.channel → test_management.services._access
notifications.feishu → agent.providers.sanitizer
notifications.feishu → reports.models（类型/发送时）
agent.tools → api/business/test 的 models 与部分 service
agent.tools.notification_tool → notifications.services + reports.services
agent.tools.execution_tool → test run
```

没有发现测试数据 import 测试管理，也没有发现业务 import 测试或 Agent。低层没有依赖 Agent 的**业务服务**，但报告和飞书依赖了 Agent **包内的工具函数**。这是包级双向依赖：

- `agent.tools.notification_tool` 在模块顶部 import `reports.services` 和 `notifications.services`。
- `reports.services.report_service` 在模块顶部 import `agent.providers.sanitizer`。
- `notifications.services.feishu_service` 在模块顶部 import `agent.providers.sanitizer`。

Python 没把这走成启动即炸的环，是因为 sanitizer 不再 import 回去。结构上已经是环。Security 或报告若再从 Agent 包拿函数，环会变成真的循环导入。

另外三处越界：

- 断言引擎调用 `_jsonpath_extract`（下划线私有）。
- `DebugService` 调用 `_load_body` / `_load_params`。
- 渠道、报告、Agent 工具调用另一个 feature 的 `_access`。

Agent 节点会 `except HTTPException`（`context_loader.py`、`test_point_generator.py`、`notification_sender.py`）。这是把 HTTP 异常当成领域错误。可以留到 Agent 迁移阶段，改成捕获 `AppError`。

前端没有跨 feature 引用内部组件的严重情况。`ApiCatalog/JsonView.tsx` 只在接口模块内使用，测试数据和报告各自又写了一套 JSON 展示。这是重复，不是非法耦合。

---

## 10. 权限差异

角色定义只在 `app/shared/roles.py`：

- 平台：`admin` / `test` / `dev`。平台角色不自动等于项目角色。平台管理员在 `project_role_for` 里视同可管理。
- 组织：`owner` / `admin` / `member`。
- 项目：`viewer` < `member` < `editor` < `owner`。另有判定用的 `admin`（平台管理员），不落成员表。

实际门槛并不统一：

| 操作 | 实际门槛 | 代码 |
|---|---|---|
| 项目内业务读 | viewer，不可见 404 | business / test / test_data / defects / api |
| 项目内业务写 | member，不足 403 | 同上 |
| 改项目、成员、出站目标 | **editor 或 owner** | `projects/service.py` |
| 环境、模型 | 平台管理员，连列表也是 | environment / model router |
| 接口调试 | 平台管理员 | `api_catalog/router.py` |
| 被测库连接与写库策略 | 平台管理员，且先过项目可见 | `test_data.services._access.require_admin_project` |
| 组织创建与成员 | 路由内组织角色 | `organizations/router.py` |
| 站内通知 | 本人 | `notifications/router.py` |

这不是 bug。项目设置比项目内资源更严，应当保持。问题是「viewer/member」这段被复制，而「平台管理员才能碰环境」被控制台绕着调用。

唯一入口目标：

- 项目读：`shared.access.get_project_or_404`
- 项目写：`shared.access.require_writable_project`（member+）
- 项目设置写：继续用 `projects.service` 里的 editor/owner，不降级
- 平台管理员：只使用 `app.shared.auth.require_platform_admin` 或 `roles.is_platform_admin`。禁止 feature 再写 `if user.role == "admin"`。
- 实体属于哪个项目：留在该 feature 的 `resolve_*_project_id`。

禁止未来 Feature 复制 `_access.py` 全文。允许复制的只有实体回溯。

---

## 11. 错误处理差异

对外形状已经统一。`register_exception_handlers` 把 `HTTPException`、`AppError`、校验错误、未捕获异常都收成：

```json
{"code": "...", "message": "...", "request_id": "..."}
```

不统一的是 **code 字符串**：

| 来源 | 例子 | 问题 |
|---|---|---|
| 核心工厂 | `ERR_BAD_REQUEST` `ERR_NOT_FOUND` `ERR_FORBIDDEN` `ERR_CONFLICT` | 第一阶段全部如此 |
| 报告 / 飞书 | `ERR_REPORT_NOT_FOUND` `ERR_FEISHU_SEND_FAILED` | 有 `ERR_` 前缀，领域名在中间 |
| 造数 | `FIXTURE_NOT_FOUND` `DATABASE_TABLE_NOT_ALLOWED` | **没有 `ERR_`**，`errors.py` 第 46 行写明是故意的 |
| 执行器内部 | `API_DEPRECATED` `INPUT_MAPPING_FAILED` `ACTION_NOT_FOUND` | 写进执行记录的 `error_code` 列，不一定变成 HTTP |

组织名称冲突用 `bad_request`（400），用户名冲突用 `conflict`（409）。这是历史行为，不要在架构阶段改状态码。

目标命名（只约束**新代码**和造数码的别名，不改已返回给前端的旧码）：

- 新码形式：`ERR_<DOMAIN>_<REASON>`。
- 领域：`AUTH` `ORG` `PROJECT` `API` `BUSINESS` `TEST` `DATA` `AGENT` `REPORT` `NOTIFY`。
- 预留：`MOCK` `SECURITY` `UI` `MOBILE`。
- 造数现有裸码保留为兼容值。Phase B 在 `AppError` 上可以同时带 canonical code，HTTP 体仍返回旧码，直到前端改完。不要一次改掉 `FIXTURE_NOT_FOUND`。

执行记录里的 `error_code` 与 HTTP `code` 不是同一个通道。规范里分开写：HTTP 信封 vs 执行结果错误码。

---

## 12. Executor 差异

| 类型 | 文件 | 成功形态 | 时间 | 错误 | 是否 commit | 是否该套统一结果 |
|---|---|---|---|---|---|---|
| `ApiRequestResult` | `api_executor.py` | `success` 属性：无 error 且 2xx/3xx | `response_time_ms` | `error_message` | 否 | 否。它是 HTTP 传输结果 |
| `ActionRunResult` | `business_flow_executor.py` | `status` | `duration_ms` | `error_code` + `error_message` | 不 commit（`run_action`） | 是，作为动作级结果 |
| `FlowExecution` 行 | 同文件 `execute_flow` | 行上的 `status` | 行上的时间 | 行上的错误 | **会 commit** | 持久化模型不动 |
| `CaseExecutionResult` | `test_case_executor.py` | PASSED/FAILED/ERROR/SKIPPED | `duration_ms` | `error_code` | 否，由 RunService commit | 是 |
| `ProviderResult` | `providers/base.py` | SUCCESS/FAILED | 无 duration | `error_code` | 否 | 是，补 duration 可选 |
| `GenerationResult` | `data_factory.py` | status + outputs | 无 | `error_code` | Factory 自己 commit | 只在边界适配，不改 `data_execution` 表 |
| `Debug` 返回 schema | `debug_service.py` | HTTP 字段 | `response_time_ms` | 抛 HTTP | 不落库 | 改为调用 ApiRequestExecutor 后映射到现有 schema |

没有 `started_at` / `finished_at` / `warnings` / `metadata` 的公共对象。数据库里的执行表已经有自己的列。统一结果应是**内存边界对象**，不是新表。

---

## 13. Runtime / Variable 差异

现在有四套「上下文」，职责不同，不应合成一个类：

| 对象 | 文件 | 存什么 |
|---|---|---|
| `ExecutionContext` | `business/executors/context.py` | 一次流程的 `variables` 与各动作输出 |
| `ResolveScope` | `test_data/runtime/variable_resolver.py` | 模板求值的只读字典：fixture / data / env / runtime / faker |
| `ProviderContext` | `providers/base.py` | 一次 Provider 调用的 db、环境、actor、scope |
| `AgentState` | `agent/state.py` | 会话阶段、意图、草稿、人工 action。不是变量袋 |

`ExecutionContext` 文档写的优先级：Runtime variables > 请求变量 > Environment > 接口默认值。

`variable_resolver` 文档写的优先级：已注入的 Fixture runtime > `test_case_data` > Environment > Provider 字面量。并写明「解析器不决定优先级，调用方把 dict 放进 ResolveScope」。

`mapping_resolver` 不识别 `${}`。它用变量名当键，从 context dict 取值，填到 header/query/path/body。

用例执行器已经把 `${}` 委托给 `resolve_template`（`_resolve_tokens`）。业务动作那条复制路径先 `_load_data_values` 再 `resolve_input_mappings`。两条路径的先后顺序必须保持：先解析模板，再做位置映射。

可以渐进迁移。不要重写 `execute_flow` 的上下文结构，`flow_execution.context_json` 已被历史执行依赖。

---

## 14. 前端目录差异

第一代：`pages/console/Defects.tsx`、`Projects.tsx`、`Notifications.tsx`、`Profile.tsx`、`Workbench.tsx`，以及全部 `pages/admin/*`。一个路由一个文件。

第二代：`ApiCatalog/`、`BusinessManagement/`、`TestManagement/`、`TestData/`、`Reports/`、`Agent/`。目录内再拆树、Tab、抽屉。

例外：`TestAsset.tsx` 用了目录，却把策略、测试点、用例、数据、步骤、断言全写在 1201 行里。`AgentPage.tsx` 859 行。`NotificationChannels.tsx` 仍是单文件。

API client 都从 `./client` 的 `api.get/post` 出发，没有页面直接使用 axios。风格差异主要是返回类型：有的 `Paginated<T>`，测试管理列表是 `T[]`。

---

## 15. Query Key 差异

没有 `queryKeys` 对象。每个页面手写数组。

| 前缀 | 是否含 projectId | 切项目时 Scope 是否失效 |
|---|---|---|
| `api-catalog` | 列表含，详情有的只有 apiId | 是 |
| `business` | 列表含，详情多用 flowId | 是 |
| `agent` | 会话列表含 | 是 |
| `test-data` | 含 | 是 |
| `bugs` | 不含，靠 query 对象 | 是 |
| `test-cases` / `test-plans` / `test-suites` / `test-runs` | 查询时含 `currentProjectId`，但前缀失效没做 | **否** |
| `test-reports` | 含 | **否** |
| `notification-channels` | 含 | **否** |
| `environments` | 平台级，不含项目 | 不需要按项目失效；但控制台和管理端共用前缀 |

页面内失效大多用前缀（`['business']`、`['test-data','fixtures']`），这是对的。缺的是 Scope 里的项目切换清单。

---

## 16. 推荐最终后端架构

保持单体、保持 feature 目录、保持 Alembic 历史。

```
app/
  main.py                 运行时唯一路由装配
  bootstrap/routes.py     与 main 保持同一份清单（文档装配点）
  models/                 只放 0001 基线九张业务表 + Base 再导出
  shared/
    access.py             项目读/写门槛（新）
    errors.py             信封 + 错误码登记
    roles.py              角色判定，不搬
    security/
      crypto.py           现有 crypto 可逐步再导出
      masking.py          从 business 迁出
      sanitizer.py        从 agent 迁出
      outbound.py         出站校验留在 ApiRequestExecutor，对外一个函数
    execution/
      result.py           内存用 ExecutionResult，不建表
  features/<name>/        见第 18 节
```

分层归属：

| 层 | Feature | 可以依赖 | 不可以依赖 |
|---|---|---|---|
| 平台 | users, organizations, projects, model, environment, captcha, dashboard, notifications 收件箱 | shared | 任何测试/Agent/报告 |
| 领域 | api_catalog, business, defects | 平台模型、shared、ApiRequestExecutor | test、agent、report |
| 测试 | test_management, test_data | 领域的公开执行函数、shared | agent、report |
| 交付 | reports, notifications 渠道 | 测试的只读模型和公开查询、shared.security | agent 包内部 |
| 智能 | agent | 以上各层的公开 contract | 别人的 `_` 私有函数；不拥有脱敏实现 |

`defects` 留在领域层，看板可以只读它的模型。这是现有统计方式，不必为了分层去建查询服务，除非看板要开始写缺陷。

---

## 17. 推荐最终前端架构

不要在 Phase A/B 搬目录。目标形态是约束**新代码**和**正在改的页面**。

```
src/
  api/                继续按模块一个文件；新模块禁止写在页面里
  types/              按域拆文件，index.ts 只 re-export
  query/queryKeys.ts  新的 key 工厂
  components/         只放第二次复用且稳定的组件
  hooks/              useAuth、useConsoleScope 留下
  pages/console/<Feature>/   继续用目录，不再新增单文件巨页
```

不引入 `src/features/` 与 `src/app/`。当前别名是 `@/`，搬到 `src/features` 会改几百个 import，对 Mock 没有帮助。

若某个页面在 Phase C 被拆小，组件放在该页面目录内，例如 `pages/console/TestManagement/components/`。只有两个以上模块使用，才升到 `src/components/`。

---

## 18. Feature 标准模板

需要什么就建什么。

```
app/features/<feature>/
  __init__.py          只写模块说明，不在 import 时连上全部 service
  router.py            只做 HTTP
  schemas.py           Pydantic v2，snake_case
  models/              有表才建；不加入 app/models/__init__.py
  services/
    _access.py         只保留 resolve_*；项目门槛改调 shared.access
    <资源>_service.py  业务规则与 commit
  executors/           有多步执行才建
  providers/           有可替换外部能力才建
  runtime/             有一次执行的变量生命周期才建
```

不建 `features/<name>/tests/`。测试继续放 `backend/tests/test_<nn>_<feature>.py`，和现有 20 个文件一致。

不建每模块 `errors.py`，除非该模块错误码超过 15 个。错误码常量仍汇总在 `app/shared/errors.py`，按注释分段。造数已经这样，保持。

各层职责：

| 层 | 做 | 不做 |
|---|---|---|
| Router | 参数、`Depends` 认证、调用一个 service 方法、`response_model` | commit、httpx、SQL、LangGraph、循环造数 |
| Service | 规则、可见性、跨表、commit/rollback | 拼 HTTP 响应头以外的传输细节；不调用别的 feature 的 `_` 函数 |
| Executor | 一次无事务或由调用方指定的执行步骤，返回内存结果 | 决定 HTTP 状态码；不在中途 commit，除非函数名和文档明确写了「此函数提交」且只有一个这样的函数 |
| Provider | 一种外部或可替换数据来源，输入配置、输出 `ProviderResult` | 编排多个 Fixture、不写 Run 状态机 |
| Runtime | 把 Provider / Executor 按生命周期串起来 | 不解析权限角色 |

对外 Contract 放在该 feature 的 `services/__init__.py` 或执行器模块的 `__all__`。其他 feature 只能 import 这些名字。

---

## 19. Public Service Contract 规范

以下名字视为稳定入口。没有列出的函数，其他 feature 不得 import。

**环境**

- `get_active_environment(db, name) -> Environment`（新，公开）
- `list_environment_options(db) -> list[{name, display_name}]`（新，给非管理员）
- 现有的创建、删除、设默认仍只给平台管理员

**API Catalog**

- `get_api(db, api_id, user) -> ApiInterface`（可见性在内）
- `load_request_bundle(db, api) -> params, body`（把 `_load_params` / `_load_body` 改成公开名，旧私有名保留一个版本）
- 不公开 debug。调试继续走路由。

**Business**

- `execute_flow(db, flow_id, *, environment_id, variables, actor)`  
  文档必须写：此函数会 commit。调用方不得假设外层事务还在。
- `run_action(db, action_id, *, environment, variables, actor, project_id) -> ActionRunResult`  
  文档必须写：不 commit。
- `get_flow` / `get_action` 若尚未独立函数，在 Phase C 从现有 service 方法升为模块级包装，不改 URL。

**Test Management**

- `CaseService` 的创建/更新用例保持为用例资产入口。
- `RunService.create_and_execute_run` 是执行入口。
- `test_case_executor.execute` 只给 Run 和 Agent 的 execution tool。

**Test Data**

- `LifecycleManager.setup_run` / `setup_case` / `cleanup_case` / `cleanup_run`
- `DataFactory.generate` / `cleanup` 给手动造数 API
- Provider 类不给 feature 外直接 new。外部只碰 Factory。

**Reports**

- `ReportService.generate` / `get_report`
- AI 总结函数不得被 Agent 以外的人绕过报告服务去调。Agent 只调报告服务。

**Notifications**

- `FeishuNotificationService.send_report`
- `ChannelService.resolve_channel`

**禁止**

- import 任何 `_` 开头的函数（迁移完成前的 re-export 除外）。
- import 别的 feature 的 `_access`。
- Agent 以外的代码 import `agent.providers` 或 `agent.prompts`。提示词可以留在 Agent；脱敏必须离开 Agent 包。

---

## 20. 模块依赖规则

允许的方向：

```
shared
  ↑
平台模型（user / org / project / environment / model）
  ↑
api_catalog
  ↑
business
  ↑
test_data
  ↑
test_management
  ↑
reports
  ↑
notifications.channel
  ↑
agent
```

`test_management` 可以调用 `test_data` 的生命周期，`test_data` 不可以 import `test_management`。当前代码满足这一点。

`reports` 可以读 `TestRun` / `CaseExecution` 模型。这是交付层读测试层的事实来源，允许，但应限制在 `report_service` 一个文件。

`dashboard` 读 `Bug` 计数，允许只读。

禁止：

- 平台层 import 测试层或 Agent。
- `api_catalog` import `business`。
- `business` import `test_management` 或 `test_data`。
- 任何模块 import `agent.nodes` 或 `agent.tools`。
- 路由 import 另一个 feature 的 service 来「顺便编排」。飞书路由现在编排了报告服务，Phase C 把编排收进一个 `notify_report` 应用服务，路由只调它。

---

## 21. RuntimeContext 规范

不新建替代 `ExecutionContext` 的大一统类。规范如下：

1. 业务流程执行只使用 `ExecutionContext`。变量键保持现在的平铺名字，保证已存的 `context_json` 还能读。
2. 用例和造数使用 `ResolveScope`。Fixture 输出以 `fixture.<KEY>.<name>` 注入，同时保留分组 dict 给映射使用。
3. `AgentState` 只描述会话。需要把造数结果交给用例时，写成普通 dict 交给 `execute`，不把 ORM 放进 state。
4. `ProviderContext` 只在 Provider 内部。可以带 Session，因为 Provider 要读配置；`ResolveScope` 继续禁止带 Session。
5. 新执行器若要变量，接收 `ResolveScope` 或 `ExecutionContext` 之一，不要再造第三个字典约定。

迁移：Phase C 的测试管理只把 `_execute_business_action` 改成调用 `run_action`，把 `ResolveScope` 里已经解析好的值放进 `run_action` 的 `variables`。不改 `ExecutionContext` 的字段。

---

## 22. VariableResolver 规范

唯一模板入口：`app.features.test_data.runtime.variable_resolver.resolve_template`。

表达式：

| 表达式 | 含义 |
|---|---|
| `${env.xxx}` | 环境的允许字段与 default header。键名单只在 `resolve_env_key` |
| `${data.xxx}` | 本用例已解析的测试数据 |
| `${runtime.xxx}` | 本次执行注入的运行时变量 |
| `${fixture.<KEY>.<name>}` | Fixture 契约输出 |
| `${faker.xxx}` | 白名单生成器，不缓存 |

优先级（调用方组装 scope 时遵守，解析器不重新排序）：

```
runtime（含已注入 fixture 输出）
  > 本请求 / 本用例 data
  > fixture 契约（若还没灌进 runtime）
  > environment
  > Provider 或接口默认值
```

缺失：必填失败用 `ERR_DATA_VARIABLE_RESOLVE_FAILED` 的兼容码，HTTP/执行记录继续返回现有 `VARIABLE_RESOLVE_FAILED`。非必填继续替换成空串。嵌套最多 3 层。

`mapping_resolver` 不增加模板语法。业务映射仍然是「变量名 → 位置」。谁要在映射值里写 `${}`，必须先走 `resolve_template`。

禁止在新模块里写新的 `\$\{` 正则。

---

## 23. ExecutionResult 规范

在 `app/shared/execution/result.py` 增加内存对象，不建表：

```text
ExecutionResult
  status          调用方枚举，不强制全局枚举
  started_at
  finished_at
  duration_ms
  input           已脱敏
  output          已脱敏
  error_code
  error_message
  warnings        list[str]，默认空
  metadata        dict，默认空
```

适配，不替换：

| 现有对象 | 做法 |
|---|---|
| `ApiRequestResult` | 保留。需要边界时写 `to_execution_result()`，HTTP 字段进 metadata |
| `ActionRunResult` | 补 `started_at` 可选；已有字段不动 |
| `CaseExecutionResult` | 已有 status/duration/error。补 warnings 默认空。落库列不增 |
| `ProviderResult` | 补可选 duration。`outputs` 映射到 `output` |
| `GenerationResult` | 不改。Data Factory 对服务层仍返回它 |
| 数据库行 | 不改列名，不回填旧数据 |

新执行器（Mock、Security、UI、Mobile）直接返回 `ExecutionResult`，再由各自的 service 映射到自己的表。不要让它们返回 `ApiRequestResult`。

---

## 24. Error 规范

HTTP 体保持：

```json
{"code": "ERR_...", "message": "...", "request_id": "..."}
```

规则：

- 业务代码只抛 `AppError` 或现有工厂（`bad_request`、`not_found`、`forbidden`、`conflict`）。工厂内部继续变成 HTTPException，全局处理器不变。
- 新错误码写入 `shared/errors.py` 的分段常量。命名 `ERR_<DOMAIN>_<REASON>`。
- 不可见资源继续 404 + `ERR_NOT_FOUND`，message 用「不存在」，不要写「无权」。
- 可见但角色不够继续 403 + `ERR_FORBIDDEN`。
- 冲突继续 409。不要把新的唯一约束违反映射成 400。组织名称那个 400 视为 Legacy。
- 执行失败如果要落执行记录，不要抛 HTTP 500。沿用 Run 的做法：记 `ERROR` 或 `FAILED`，整次 API 仍返回 200 和执行记录。造数准备失败记 `ERROR`，不记 `FAILED`。这个口径已经在 `lifecycle.py`，保持。
- 前端继续用 `getErrorMessage`。新码可以分支，旧码不能删。

Phase B 不做错误码大替换。只加登记表和「新码必须走登记」的注释。造数裸码列一张兼容表，写进 `ERROR_CONVENTIONS.md`。

---

## 25. Permission 规范

调用入口只允许：

| 问题 | 函数 |
|---|---|
| 当前用户是谁 | `Depends(get_current_user)` |
| 是不是平台管理员 | `Depends(require_platform_admin)` 或 `is_platform_admin` |
| 能不能看见这个项目 | `get_project_or_404` |
| 能不能改这个项目里的业务资源 | `require_writable_project`（member+） |
| 能不能改项目设置 | `projects.service` 现有 editor/owner 判断 |
| 这个资源属于哪个项目 | feature 自己的 `resolve_*_project_id` |
| 组织角色 | `roles.py` 已有组织函数。组织路由在它被改到的那个阶段改调用，不在 Phase B 重写组织 |

`shared/access.py` 的实现从 `test_management/services/_access.py` 的前 56 行拷出（三份拷贝已一致）。feature 里的同名函数改成：

```python
from app.shared.access import get_project_or_404, require_writable_project
```

删掉函数体。回溯函数不动。

渠道和报告删除对 `test_management.services._access` 的依赖，改 import shared。

---

## 26. React Query 规范

新增 `frontend/src/query/queryKeys.ts`。页面改为使用它，但 key 的**数组内容保持不变**，这样上线不丢缓存语义、也不强迫刷新策略突变。

```text
queryKeys.apiCatalog.all = ['api-catalog']
queryKeys.business.all = ['business']
queryKeys.test.cases = ['test-cases']
queryKeys.test.plans = ['test-plans']
queryKeys.test.suites = ['test-suites']
queryKeys.test.runs = ['test-runs']
queryKeys.testData.all = ['test-data']
queryKeys.agent.all = ['agent']
queryKeys.reports.all = ['test-reports']
queryKeys.channels.all = ['notification-channels']
```

项目级查询必须把 `projectId` 放进 key。已经这样做的保持。

`useConsoleScope` 的 `setProjectId` 增加失效：

- `test-strategies` `test-points` `test-cases` `test-case-detail`
- `test-suites` `suite-cases` `test-plans` `plan-suites`
- `test-runs` `case-executions`
- `test-reports` `test-report-detail`
- `notification-channels` `channel-records`

`setOrgId` 同样补上这些前缀，因为组织一变，当前项目集合就变。

页面里的 `invalidateQueries` 改为 `queryKeys.xxx.all`，不要手写另一套前缀。不要在 Scope 里 `removeQueries` 全表，失效就够。

`environments` 保持平台级 key。等只读选项接口落地后，控制台改用 `['environment-options']`，与管理端全量列表分开，避免管理员的 `include_inactive` 缓存串到控制台。

---

## 27. API Client 规范

`frontend/src/api/client.ts` 已是唯一 axios 实例：baseURL `/api/v1`，超时 30 秒，401 清令牌。保持。

规则：

- 页面禁止 import axios。当前满足。
- 新接口写在 `src/api/<module>.ts`，方法名 `list/get/create/update/remove`。
- 分页类型只用 `Paginated<T>`，字段 `items/total/page/page_size`。
- 测试管理现有裸数组函数保持返回 `T[]`，在函数注释标明 Legacy。不要悄悄改成信封。
- 上传：走现有 `api` 实例的 `FormData`，不新起 axios。接口导入已经是这个方向的话就沿用该函数的写法。
- 下载：同样走 `client`，`responseType: 'blob'`，加在 client 的一个 `api.download` 包装里，Phase B 再加。现在没有下载功能，不必预做。
- 取消：查询用 React Query 的 signal，从 `queryFn({ signal })` 传到 axios config。新查询要带上。旧查询不强制补。
- 错误展示继续 `getErrorMessage(error, fallback)` + `App.useApp().message`。禁止 `antd` 的静态 `message`。

---

## 28. UI Pattern 规范

只认三种。新页面必须选一种。旧页面不为了贴合而重画，除非该页已经因为别的原因打开。

**Catalog**：左树或列表，右详情，编辑用抽屉。  
现况：接口管理符合。业务管理符合。测试数据的 Fixture 符合。  
不改。

**Management**：工具栏、筛选、表、详情。  
现况：缺陷、套件、计划、执行历史、报告列表、飞书渠道、管理端各表符合 `ResourceTable`。  
`TestAsset.tsx` 不符合，它是 Catalog 和 Management 焊在一起。Phase C 拆文件，不改交互。

**Workspace**：导航、主工作区、检查器。  
现况：Agent 近似（会话列表 + 对话 + 工作区快照）。执行中心是「选计划然后跑」，更接近 Management。不要把它改成 Workspace。

需要改造的页面（只拆文件，不改布局）：

| 页面 | 原因 | 阶段 |
|---|---|---|
| `TestAsset.tsx` | 1201 行，三个资源焊在一起 | Phase C，测试管理那一次 |
| `AgentPage.tsx` | 859 行 | Phase C，Agent 那一次，可只拆会话列表和消息区 |
| `NotificationChannels.tsx` | 仍是单文件，但不到必须拆 | P2，碰到再拆 |

不抽「统一页面框架」组件。

---

## 29. 测试规范

后端测试在 `backend/tests/`，数据库 `testplatform_test`。正式文件是 `test_01` 到 `test_19`（含 schema、认证、隔离、缺陷、接口、业务、执行器、测试资产、Agent、报告、造数）。`test_tmp_audit.py` 不作为模板，Phase A 只确认它是否还被需要，不在架构阶段删掉，除非它已经不收集。

前端没有测试。架构阶段不引入 Jest/Vitest。回归靠 `npm run typecheck` 和 `npm run build`，再加上手点本次改到的页面。

| 种类 | 放哪 | 断言什么 |
|---|---|---|
| 迁移 | `test_01_schema_and_seed.py` | head 等于当前修订；基线表仍在 |
| API | `tests/test_*` 的客户端用例 | 状态码、错误信封、404 隐藏 |
| Service | 同一文件里直接调 service | 权限和事务 |
| Executor | `test_11` `test_15` `test_19` 这一类 | 不发真实外网；httpx mock 或本地 |
| 安全 | 出站白名单、脱敏、生产库禁止 | 必须有一条反例 |

命名保持 `test_<nn>_<主题>.py` 与 `test_<行为>`。新文件取下一个编号，不把测试搬进 feature 目录。

每个新 Feature 的最低要求：

- 一条可见性：别人的项目返回 404。
- 一条写权限：viewer 写返回 403。
- 一条成功路径。
- 若有执行器：一条失败变成记录状态而不是 500。
- 若有迁移：head 断言三处一起改（现在是 `test_01`、`test_10`、`test_18`）。

架构改造的每一阶段结束跑：

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
cd frontend && npm run typecheck && npm run build
```

---

## 30. 安全能力复用规范

| 能力 | 现在 | 以后唯一入口 |
|---|---|---|
| 密钥加密 | `app/shared/crypto.py` | 保持。模型 Key、Webhook、被测库密码都用它 |
| 结构脱敏 | `business/executors/sensitive.py` | `app/shared/security/masking.py`，旧模块 re-export |
| 文本脱敏 | `agent/providers/sanitizer.py` | `app/shared/security/sanitizer.py` |
| 出站白名单 + 私网拦截 | `ApiRequestExecutor._check_outbound` | 执行器上的公开方法 `assert_outbound_allowed`。调试、造数 API、未来 Mock 回源都走它 |
| 项目隔离 | 多份 `_access` | `shared.access` |
| 被测库表白名单 | `test_data/security/db_guard.py` `sql_builder.py` | 留在 test_data。别的模块不准自己拼 SQL |
| 提示词注入清洗 | `sanitize_text` 在进 LLM 之前 | Agent 继续调用 shared sanitizer |

调用规范：

- 快照落库前必须 mask。已经做了的执行器不要再 mask 第二次导致 `***` 套 `***`。
- 日志禁止打印解密后的密钥、Webhook、数据库密码。
- 新的浏览器或手机执行器不得关闭出站校验。UI 自动化若访问的是环境 `base_url`，同样检查项目出站目标。
- 生产环境名（`prod` / `production` / `prd`）禁止数据库写。策略行不能打开。这段留在 `db_guard`，Mock 和 Security 不得复制一份环境名判断。

---

## 31. Alembic 规范

现状：

- `0001` 用 `Base.metadata.create_all` 建基线表。这些模型在 `app/models/__init__.py`。
- `0002` 到 `0009` 是 feature-local 模型，显式 `op.create_table`。注释写明不能再被 0001 看见。
- head 断言在 `test_01_schema_and_seed.py`、`test_10_business.py`、`test_18_test_data_crud.py`，当前都是 `0009`。

未来新表：

1. 模型放在 `app/features/<feature>/models/`。
2. 不要加入 `app/models/__init__.py`。
3. `alembic revision` 的 `down_revision` 接当前 head。
4. 建表用显式 `op.create_table`，索引名稳定，`downgrade` 用 `IF EXISTS` 逆序删。
5. 外键、唯一约束写在表定义里，命名 `fk_*` / `uq_*` / `ix_*`，与 0003 以后的脚本一致。
6. 同一提交带上模型、迁移、head 断言。
7. 不修改 `0001`–`0009` 的文件。要改结构就新增 `0010`。
8. 架构收敛本身不应产生迁移。Phase B/C 若只搬 Python 函数，修订号保持 `0009`。

环境只读接口不改 `environment` 表。

---

## 32. P0 问题

会挡住 Mock、Security 或 UI/Mobile 接到同一条执行链上。

| ID | 问题 | 证据 | 做法 |
|---|---|---|---|
| P0-1 | 非管理员不能读环境 | `environment_configuration/router.py` 列表也 `require_platform_admin`；控制台多处 `['environments']` | 新增 `GET /environment-options`，登录即可，只返回 name 与显示名。旧接口不动 |
| P0-2 | 项目门槛四处复制 | 三个 `_access.py` + api_service + defects | `shared/access.py`，调用点改 import |
| P0-3 | 两套 HTTP 执行器 | `debug_service.py` 与 `api_executor.py` | 调试改为调用 `ApiRequestExecutor`，响应 schema 不变 |
| P0-4 | 业务动作执行复制 | `test_case_executor._execute_business_action` 对标 `run_action` | 用例改调 `run_action`，断言仍在用例执行器 |
| P0-5 | 错误码没有登记规则 | `shared/errors.py` 46 行起裸码 | 写规范 + 新码必须 `ERR_<DOMAIN>_`；旧码保留 |
| P0-6 | 切项目缓存漏测试与报告 | `useConsoleScope.tsx` `setProjectId` | 补前缀失效 |
| P0-7 | 脱敏/LLM 放在 Agent 包导致反向依赖 | `report_service.py`、`feishu_service.py`、`ai_summary.py` | sanitizer 迁到 shared，旧路径 re-export |

P0 不包含重写组织路由、不包含拆 `types/index.ts` 的全部历史类型、不包含改 URL。

---

## 33. P1 问题

维护成本高，不挡新模块开工，但应在对应 Feature 被下次改到时处理。

| ID | 问题 | 做法 |
|---|---|---|
| P1-1 | 组织、注册、站内通知在路由 commit | 迁到 service，行为不变 |
| P1-2 | `execute_flow` 与 `RunService` 双 commit | 文档化；新代码禁止再包一层事务。不改变 `execute_flow` 的 commit，因为已有调用方依赖「返回时已落库」 |
| P1-3 | Data Factory、Lifecycle、Cleanup 各自 commit | 保持。在 `EXECUTION_CONVENTIONS.md` 写明谁是边界。不合并成一个事务，否则长造数会锁太久，也和「逐步可见」冲突 |
| P1-4 | 测试列表裸数组，schema 里却有分页模型 | 标记 Legacy。新列表必须信封。不改旧端点 |
| P1-5 | `types/index.ts` 2215 行 | 按第 21 节拆文件，index re-export |
| P1-6 | `bootstrap/routes.py` 漏四个路由 | 补登记，与 main 对齐 |
| P1-7 | `TestAsset.tsx` 1201 行 | 按资源拆文件，不改交互 |
| P1-8 | JSONPath 私有跨模块 | 公开函数名 |
| P1-9 | 渠道路由编排三个 service | 收成一个应用层函数 |
| P1-10 | Agent 节点捕获 `HTTPException` | 改为 `AppError` |

---

## 34. P2 问题

只在顺便改到该文件时做。

- 早期模块从函数式 service 改成类。没有调用方收益。
- 管理端页面套 Catalog Pattern。它们是表，保持 Management。
- 把 `JsonView` 提升为共享组件。第二处出现再提。
- 删除 `test_tmp_audit.py`，先确认没有人本地依赖。
- 更新 `.claude/skills/develop-this-project/SKILL.md` 里过期的 head 和端点表。那是文档债，不要和功能 PR 混。
- 用户、组织、看板、缺陷的目录形态。

---

## 35. Phase A 改造计划

**目标：** 不改功能，不改 Python 行为，不改前端行为。产出规范，让 Phase B/C 有同一份依据。

**允许改动的文件（只新增文档）：**

- `docs/architecture/ARCHITECTURE.md`
- `docs/architecture/BACKEND_CONVENTIONS.md`
- `docs/architecture/FRONTEND_CONVENTIONS.md`
- `docs/architecture/MODULE_DEPENDENCIES.md`
- `docs/architecture/ERROR_CONVENTIONS.md`
- `docs/architecture/EXECUTION_CONVENTIONS.md`

内容从本文第 16–31 节压缩成可执行条文，不要再做一轮开放式设计。

**禁止：** 改 `backend/app`、`frontend/src`、`alembic/versions`。

**验收：** 文档里的路径在仓库中存在；规范中的「禁止 import」能在本文第 9 节找到当前违规样本。不跑全量测试也可以，因为没有代码变化。若执行者改了代码，则本阶段失败，回滚那些代码。

**预估：** 6 个新 markdown，不改现有源文件。

**风险：** 规范写得和代码不符，后面照着改会破坏行为。缓解：每条规范必须点名一个现有函数作为样板（例如项目门槛以 `test_management/services/_access.py` 前 56 行为样板）。

---

## 36. Phase B 改造计划

**目标：** 公共底座就位，现有 API 与页面行为不变。可以有一个**新增**的只读环境接口。

**顺序固定，一个提交做一件事：**

1. 新增 `app/shared/access.py`，三份 `_access.py` 和 api/defects 的项目门槛改为调用它。回溯函数不动。跑全量 pytest。
2. 新增 `app/shared/security/masking.py` 与 `sanitizer.py`，旧文件变成 re-export。报告、飞书、造数的 import 可先不动（re-export 保证）。再把报告和飞书的 import 改到 shared。跑 `test_16` `test_17` `test_19`。
3. 新增 `app/shared/execution/result.py` 和适配函数，不改调用方。本步可以没有行为变化，只被后续 Mock 使用。若适配函数无人调用，至少加一个单测锁定字段。
4. 新增 `GET /api/v1/environment-options`。实现放在 environment service。返回 `[{name, display_name, is_default}]`，不含 header、不含 base_url。任何登录用户可调用。管理端原接口不动。
5. 前端 `queryKeys.ts`，`useConsoleScope` 补失效前缀。把执行中心、计划、业务流程、Agent、测试数据的环境查询改到 `environment-options`。接口调试若需要 base_url，仍走管理员接口，调试本身就仅管理员。
6. `bootstrap/routes.py` 补上 `api_catalog`、`test_management`、`reports`、`notification channel`，顺序与 `main.py` 一致。
7. `shared/errors.py` 增加新域码的注释段，不改旧常量的值。

**禁止：** 改表、改已有 URL、改测试列表的裸数组、改 `execute_flow` 的 commit、移动页面目录、拆 `types/index.ts`（那是 P1，可单独放在 Phase B 末尾的可选提交，见下）。

**可选提交（仍属 Phase B，可后置）：** 把 `types/index.ts` 按域拆到 `types/auth.ts`、`types/project.ts`、`types/apiCatalog.ts`、`types/business.ts`、`types/testManagement.ts`、`types/testData.ts`、`types/agent.ts`、`types/report.ts`、`types/common.ts`。`types/index.ts` 只 re-export。禁止改字段名。

**修改文件预估：**

- 新增约 6 个 Python/TS 文件。
- 修改约 12 个现有文件（三份 `_access`、api_service、defects service、report_service、feishu_service、ai_summary、environment router/service、useConsoleScope、bootstrap/routes、errors.py）。
- 前端环境查询约 6 个页面的 queryFn。

**风险：**

- `get_project_or_404` 拷错，把 editor 门槛套到普通写操作上。缓解：shared 版只含 viewer/member 两档，不包含项目设置。
- 环境选项接口被做成返回 base_url。缓解：schema 里不要那些字段，测试断言响应键集合。
- re-export 循环。缓解：masking 不 import business；business 的旧模块 import shared。

**回归：** 全量 pytest；前端 typecheck 与 build。手工：用非管理员打开执行中心，环境下拉有名字；用管理员打开环境管理，仍能看到 header。

**回滚：** 每个提交独立。环境接口是加法，回滚提交即可。shared.access 若出问题，把 import 改回本地函数（函数体在 git 历史里）。

---

## 37. Phase C 改造计划

**目标：** 旧调用点改到公共底座和公开 contract。一个 Feature 一个分支、一轮测试、一次提交。禁止一个分支改两个 Feature。

每个 Feature 的完成定义：

- 不再 import 其他 feature 的 `_` 函数和 `_access`。
- 路由不新增 commit。
- 该模块的既有测试通过，全量测试通过。
- 不改 URL，不改表。

**Feature 任务卡：**

**C1 环境。** 确认控制台都走 options。执行器里散落的环境查询改为 `get_active_environment`。不改按 name 查找。

**C2 接口管理。** `DebugService.execute` 改为组装 URL 后调用 `ApiRequestExecutor`。`_load_body` 提升为公开函数，调试与将来 Mock 都用它。删除调试里第二份白名单判断，保留「非管理员 403」在路由层。响应 schema `ApiDebugResponse` 字段一个不改。

**C3 业务。** 确认 `run_action` 与 `execute_flow` 的文档和 `__all__`。把 `_jsonpath_extract` 改名为公开 `jsonpath_extract`，旧名 re-export 一个版本。不改映射语义，不改 commit。

**C4 测试管理。** `_execute_business_action` 改为调用 `run_action`，然后把 `ActionRunResult` 映射成现有 `CaseExecutionResult`（断言逻辑留在用例执行器）。若结果字段对不上，停止并保持旧函数，不要两套同时生效。列表裸数组不动。拆 `TestAsset.tsx` 为同目录下的多个文件，路由不变。

**C5 测试数据。** 只改 access import 与 masker import。Provider 不改行为。不把 Factory 的 commit 上移。

**C6 报告。** 去掉对 `agent.providers` 的 import，改 shared sanitizer。AI 总结若必须调 LLM，通过一个放在 `shared` 或 `model_configuration` 的薄函数 `complete_chat`，由 `llm_provider.py` 再导出，报告不 import `agent.prompts` 以外的 Agent 运行时。提示词文件可以留在 `agent/prompts`，由报告传入模板名的做法改为：模板仍由 Agent 加载，报告服务接收已经生成的文本；或者把 `report_summary.md` 的加载函数挪到 reports。选后者，避免 reports import agent。

**C7 飞书。** 同样改 sanitizer import。路由里的三服务编排收进 `notify_report()`。

**C8 Agent。** `notification_tool` 只调 `notify_report`。`execution_tool` 只调 `RunService`。节点改捕获 `AppError`。不改图的节点名单和暂停点。

**C9 及以后不做：** defects、dashboard、users、organizations。除非 P1-1 被单独立项。

**预估：** C1–C8 大约 8 个提交。每个提交 3–15 个文件。C4 最大，因为含页面拆分和动作执行替换。

**风险与缓解：**

- C4 行为变化。先加对比测试：同一用例，旧路径与 `run_action` 的 status、error_code、断言结果一致，再删旧路径。
- C2 调试少了字段。用现有接口测试锁定 `status_code/response_body/response_headers/response_time_ms/request_url`。
- C6 提示词路径改了导致总结变空。保留原 prompt 文件内容，只改加载位置。

**回滚：** 每个 Feature 提交可单独 revert。C4 若已经删了 `_execute_business_action`，revert 整个提交，不要留半套调用。

---

## 38. 各 Feature 迁移顺序

用户给出的顺序是环境 → 接口 → 业务 → 测试 → 造数 → Agent → 报告 → 通知 → 缺陷 → 看板 → 用户 → 组织。

调整为：

1. **Phase B 底座**（access、security、错误登记、环境选项、queryKeys）。这不是某个 Feature，必须最先。
2. **环境**（C1）。所有执行器都要读它。
3. **接口**（C2）。HTTP 只留一个执行器，后面都依赖它。
4. **业务**（C3）。先稳住 `run_action`，测试管理才能改调用。
5. **测试管理**（C4）。依赖 C3。
6. **测试数据**（C5）。它已经在调 `run_action`，放在测试管理之后是为了避免两个执行路径同时改。它本身改动小。
7. **报告**（C6），然后 **飞书**（C7），然后 **Agent**（C8）。原因：先切断报告对 Agent 包的依赖，Agent 再改为只调交付层的公开函数。若先改 Agent，报告仍然 import Agent，环还在。
8. **缺陷、看板、用户、组织不进迁移队列。**

和原建议的差别：报告和飞书要在 Agent **之前**，否则去不掉反向依赖。造数放在测试管理之后，而不是之前，因为造数侧已经是较新的调用方式，风险在测试管理那份复制。

---

## 39. 每阶段修改文件预估

| 阶段 | 新增 | 修改 | 不碰 |
|---|---|---|---|
| A | `docs/architecture/` 下 6 个 md | 无 | 全部源码 |
| B | `shared/access.py`、`shared/security/*`、`shared/execution/result.py`、`frontend/src/query/queryKeys.ts`、可选 `types/*.ts` | 约 12–20 个调用点；Scope；environment 路由；bootstrap；errors 注释 | Alembic、组织路由、Agent 图、测试列表 URL |
| C1 | 无或一个 options 测试 | environment service、若干执行器的查询 | 环境表 |
| C2 | 无 | `debug_service.py`、`api_service.py` 公开加载函数、相关测试 | 调试 URL |
| C3 | 无 | `mapping_resolver.py`、`business/executors/__init__.py` | `execute_flow` 的 commit 和表 |
| C4 | `TestManagement` 下拆出的 tsx | `test_case_executor.py`、`TestAsset.tsx` 变薄 | 用例 API 路径 |
| C5 | 无 | test_data 的 import | Provider 配置 schema |
| C6–C8 | 可能一个 `notify_report` | reports、feishu、agent tools、prompt 加载 | 会话表、报告表、渠道表 |
| 不做 | — | users、organizations、dashboard、defects | 整模块 |

---

## 40. 每阶段风险

| 阶段 | 主要风险 | 发现方式 |
|---|---|---|
| A | 规范与代码矛盾 | 抽查三条规范对应的文件是否存在 |
| B | 权限函数行为漂移；环境选项泄密 | pytest 越权用例；响应键断言 |
| B | 缓存前缀写错导致过度刷新 | 只影响体验，不影响数据。手切项目看列表是否更新 |
| C2 | 调试结果字段变化 | `test_api_catalog` 里的 debug 用例 |
| C4 | 动作用例结果变化 | 新旧结果对比测试，通过后才删旧函数 |
| C6 | 循环导入 | 启动 `import app.main` 与 pytest 收集 |
| 全部 | 误改 0001–0009 | PR 里不得出现 `alembic/versions/000*.py` |

---

## 41. 回归测试要求

Phase A：无代码则不强制 pytest。

Phase B 每个提交：

```bash
cd backend && .venv/bin/python -m pytest tests/ -q
cd frontend && npm run typecheck && npm run build
```

重点用例：`test_05_isolation`、`test_04_admin_authorization`、`test_api_catalog`、`test_11_business_executor`、`test_15_test_executor`、`test_16_agent`、`test_17_report_notification`、`test_18_test_data_crud`、`test_19_data_factory`。

Phase C 的 C4 额外要求：至少一条 API 用例、一条 BUSINESS_FLOW 用例、一条 BUSINESS_ACTION 用例，状态与断言条数与改前一致。

手工：

- 非管理员：执行中心能选出环境名字，不能看到环境 header。
- 切换项目：测试计划、报告列表变成新项目的数据。
- 管理员：模型配置仍不回显 api_key。
- 已有 Agent 会话打开后阶段不变。

---

## 42. 回滚策略

- 一个提交一件事，revert 该提交即可。
- 不使用 squash 把 Phase B 和 Phase C 合成一个提交。
- 数据库无迁移则可回滚到上一个后端进程，不需要 `downgrade`。
- 若某个提交已经加了 `0010`（本计划默认不加），回滚代码前先 `downgrade` 到 `0009`，且该迁移必须是空表或纯加法。本计划范围内不应出现。
- re-export 至少保留到 C8 完成并全量测试通过之后，再单独提交删除旧路径。删除旧路径是可选 P2，失败就恢复 re-export。
- 前端 `types/index.ts` 的 re-export 永久保留，旧 import 不强制清理。

---

## 43. 后续 Mock / Security / UI / Mobile 扩展方式

底座完成 Phase B，并且 C2、C3 完成后，才开始这些模块。它们都是新 feature，走第 18 节模板，不改旧 URL。

| 模块 | 目录 | 依赖 | 禁止依赖 | 复用 |
|---|---|---|---|---|
| Mock | `features/mock` | api_catalog 的公开 `get_api` / `load_request_bundle`；环境 options | 不 import debug 私有函数；不自己 httpx 到被测系统，回源必须走 `ApiRequestExecutor` | 出站校验、错误码 `ERR_MOCK_*`、项目 access |
| Security | `features/security` | 用例执行入口 `RunService` 或一个新的 `execute_case` 包装；环境 options | 不复制 `_execute_business_action`；不直接写被测库 | `db_guard` 若要写库；masking；`ExecutionResult` |
| Web UI | `features/ui_automation` | 环境 options、项目 access、出站校验（浏览器打开的 origin 必须在白名单） | 不进入 business 的映射器；不把 Playwright 会话放进 AgentState | `ExecutionResult`；报告只消费结果，不 import UI 的 driver |
| Mobile | `features/mobile` | 同 UI | 不和 UI 共享 driver 进程；可以共享 `ExecutionResult` 和用例资产上的新 `target_type` | 新 `target_type` 用加法：`WEB` / `MOBILE`。旧的 API / BUSINESS_* 不改含义 |
| 性能 / 慢 SQL / JVM / 日志 | 各自 feature | 项目 access、环境 name | 不读被测库密码以外的途径；慢 SQL 若查被测库，走连接服务的只读策略，不复用 INSERT provider | masking；错误码各域 |
| CI | 不新建执行引擎 | 调已有「创建 Run」API | 不直连数据库 | 现有认证 |

用例 `target_type` 现在是 `API` / `BUSINESS_FLOW` / `BUSINESS_ACTION`。将来加法扩展，执行器路由加分支，不改旧分支的函数。

Agent 将来若要「生成安全用例」，只通过测试管理的公开创建用例，不写安全模块的表。

---

## 44. 最终架构判定

### 1. 当前架构是否需要大重构？

不需要。框架、错误信封、角色模型和 feature 划分能继续用。需要的是收口公共函数和两条执行路径，不是换目录或换技术栈。

### 2. 哪些模块必须改？

必须动调用点的是：环境（加只读接口）、接口调试（改走统一 HTTP 执行器）、业务（公开已有函数）、测试管理（动作执行改调 `run_action`，并补缓存）、报告与飞书（脱离 Agent 包）、Agent 工具（改调交付层公开函数）、`useConsoleScope`。

### 3. 哪些模块不建议动？

用户、组织、看板、缺陷、验证码、模型配置的业务行为。项目设置的 editor/owner 门槛。Alembic `0001`–`0009`。已有 URL。`execute_flow` 的 commit 语义。测试列表的裸数组。Agent 的节点图和暂停点。

### 4. 哪些公共能力应该立即抽取？

`get_project_or_404` / `require_writable_project`、脱敏与文本清洗、环境只读选项、Query Key 前缀、错误码登记。HTTP 执行不新写第三套，调试并到现有 `ApiRequestExecutor`。

### 5. 哪些重复实现必须消除？

项目门槛复制、调试与执行器双 HTTP、用例里的第二套业务动作执行、报告/飞书对 Agent 包的依赖。变量正则已经收口，不要再动出第二份。映射解析和模板解析不是重复，不要合并。

### 6. 当前哪些问题会阻塞 Mock 开发？

P0-1（没有合法的环境读取）、P0-3（没有唯一 HTTP 执行器，Mock 回源会再抄 httpx）、P0-2（Mock 会再抄一套权限）。Mock 的接口定义应来自 API Catalog 公开加载函数，而现在加载函数是私有的。

### 7. 当前哪些问题会阻塞 Security 开发？

P0-4（安全用例若打业务动作，会碰到复制的执行路径）、P0-5（安全错误码没有命名空间就会再造一套）、被测库策略在 test_data 内，安全扫描若自己连库会绕过 `db_guard`。生产禁写已经有了，必须复用而不是再判断环境名。

### 8. 当前哪些问题会阻塞 Web UI / Mobile 自动化？

P0-1，自动化必须知道环境但拿不到非管理员可读的环境标识。另外没有 `ExecutionResult` 时，UI 运行记录会再发明一套 status。出站白名单今天只包在 HTTP 执行器里，浏览器 origin 还没有统一检查入口，所以 P0-3 的「公开 assert_outbound」要先做，否则 UI 模块会跳过白名单。

### 9. 是否应该拆分前端 `types/index.ts`？

应该拆，但用方案 A，并且 `index.ts` 永久 re-export。

方案 A：`src/types/<域>.ts`，`index.ts` 再导出。旧的 `import from '@/types'` 不用改。新模块只改自己的域文件，并在 index 加一行。

方案 B：类型放在各 feature 目录。会和 `src/api` 分裂，页面与客户端不知道该从页面目录还是 api 目录引类型。当前仓库没有 `src/features`，方案 B 会强迫提前大搬迁。

选择 A。拆分放在 Phase B 的可选提交，不挡 P0。

### 10. 是否应该统一 RuntimeContext？

不应合成一个类。`ExecutionContext`、`ResolveScope`、`AgentState` 职责不同。应统一的是模板语法和优先级，入口已经是 `resolve_template`。Phase C 只让复制的动作执行改用 `run_action`，不重写流程上下文。

### 11. 是否应该统一 ExecutionResult？

应该有一个内存对象给**新**执行器。不应把 `ApiRequestResult`、`FlowExecution`、`CaseExecution` 改成同一张表或同一个必填字段集。适配函数即可。

### 12. 是否存在跨 Feature 循环依赖？

存在包级双向依赖，还没有形成「import 即崩溃」的模块环：

- Agent 工具 import 报告服务和通知服务。
- 报告服务和飞书服务 import Agent 的 sanitizer。
- 报告的 AI 总结 import Agent 的提示词，并在函数内 import LLM Provider。

测试数据与测试管理是单向的（测试管理 → 测试数据）。业务不依赖测试。把 sanitizer 移出 Agent 包后，环断开。

### 13. 最终推荐的 Feature 目录模板是什么？

`router.py` + `schemas.py` + 按需的 `models/`、`services/`、`executors/`、`providers/`、`runtime/`。项目门槛用 `app/shared/access.py`。测试放在 `backend/tests/`。不要空建目录，不要每模块一个 `errors.py`。

### 14. 建议按照什么顺序交给 Claude Code 执行？

1. 只做 Phase A 文档。
2. Phase B 按第 36 节的 7 步，每步一个提交并跑全量测试。
3. Phase C 按 C1 环境 → C2 接口 → C3 业务 → C4 测试管理 → C5 测试数据 → C6 报告 → C7 飞书 → C8 Agent。
4. 不要把用户、组织、缺陷、看板放进同一批任务。

### 15. 完成 Architecture Alignment 后，平台是否具备继续扩展大型测试能力的稳定基础？

具备，前提是 Phase B 和 C2、C3、C4 完成。那时新能力有地方放（新 feature）、有权限入口、有唯一 HTTP 与动作执行入口、有环境只读契约、有错误码登记、有执行结果对象。不需要微服务，不需要重做数据库，也不需要等用户和组织模块改完。

在那之前就开始 Mock / Security / UI，会把现在的复制再加一份。
