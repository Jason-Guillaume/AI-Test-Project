# 旧系统现状分析（test-projects）

> 本文档只描述旧项目「是什么」，供迁移决策使用；不提出新方案（新方案见同目录新平台文档）。
> 所有事实均从旧项目源码读出，代码位置以 `test_project_back/...`、`test_project_front/...` 引用。
> 旧项目根目录：`/Users/a1/Desktop/test-projects`。本文档不含任何真实密钥、密码。

## 0. 结论摘要

旧项目（代号 TestPilot）不是一个「测试管理壳子」，而是一个已经长成一个体的多领域平台：

| 维度 | 旧项目实测值 | 证据 |
| --- | --- | --- |
| 后端规模 | 492 个 `.py` 文件，约 80,000 行 | `find app -name '*.py' \| wc -l` |
| 后端接口数 | 395 个路由装饰器（含 3 个系统级） | `grep -rh '@.*\.\(get\|post\|put\|delete\|patch\|ws\)(' app/ \| wc -l` |
| 后端表数量 | 90 张 ORM 表 | `grep -rh '__tablename__ = ' app/ \| wc -l`（不带 `=` 的写法会多命中 `app/bootstrap/model_registry.py:3` 的一处 docstring，得到 91） |
| 数据库迁移 | 50 个 Alembic 版本文件 | `ls migrations/versions/*.py \| wc -l` |
| 前端规模 | 188 个 `.vue`/`.js` 文件，约 55,400 行 | `find src \( -name '*.vue' -o -name '*.js' \)` |
| 前端页面 | 42 条路由记录（2 条为 redirect、2 条访客页），73 个 `.vue` view 文件 | `src/router/index.js`、`find src/views -name '*.vue'` |
| API 前缀 | **无**统一前缀，全部为 `/users`、`/project`、`/agent/...` | `app/bootstrap/routes.py` |
| 统一错误信封 | **无**；503 处 `raise HTTPException(detail="...")`，0 个 `exception_handler` | 全文检索 `raise HTTPException` / `exception_handler` |
| 分页约定 | `skip` / `limit`，各接口默认值与上限不一（10/20/50/200/500） | `app/features/auth/api/router.py:104`、`app/features/project/api/router.py:75` |

迁移的关键判断：**旧平台的技术债不在「功能不够多」，而在「没有统一契约」**——错误信封、分页、状态码、权限判定、前后端路径约定都是各模块自定。第一阶段（Phase 1，已交付）只重建了其中的骨架部分（用户 / 组织 / 项目 / 模型配置 / 环境 / 通知 / 看板），十个业务领域能力在新平台第一阶段均未接入。

---

## 1. 旧后端技术栈与目录结构

### 1.1 技术栈

| 项 | 取值 | 来源 |
| --- | --- | --- |
| 运行时 | FastAPI（`app/main.py` → `app/bootstrap/application.py:create_app`），工厂模式 | `app/bootstrap/application.py` |
| ORM | SQLAlchemy 2.0，`declarative_base()` + `Column()` 风格（非 2.0 的 `Mapped`/`mapped_column`） | `app/shared/database.py` |
| 迁移 | Alembic，`script_location = migrations`，`sqlalchemy.url = driver://unused`（URL 由 `.env` 注入） | `alembic.ini` |
| 参数校验 | Pydantic v2（`model_config`、`field_validator`、`model_dump`） | `app/features/auth/api/schemas.py` |
| JWT | PyJWT，HS256，手工 `jwt.encode`/`jwt.decode` | `app/features/auth/api/router.py:272`（encode）、`app/shared/deps.py:29`（decode） |
| 口令 | passlib `CryptContext(schemes=["bcrypt_sha256", "bcrypt"])` | `app/features/auth/api/router.py:33` |
| 进程调度 | APScheduler（`app/shared/scheduler.py`）+ 内嵌 worker 线程 | `app/bootstrap/lifespan.py` |
| 向量 | `pgvector`（`rag_document.embedding`，维度 384） | `app/shared/config.py:RAG_EMBEDDING_DIMENSIONS` |
| 可观测 | OpenTelemetry（OTLP/HTTP traces，默认 `OTEL_ENABLED=false`）+ Langfuse | `app/features/observability/telemetry.py` |
| 出站加密 | `cryptography` Fernet；SSH 用 paramiko；PDF 用 reportlab；浏览器用 playwright | `requirements.txt` |
| 数据库 | 平台主库 PostgreSQL（`postgresql+psycopg`）；被测目标库另有 MySQL 驱动（PyMySQL） | `app/shared/config.py`、`requirements.txt` |

依赖声明（`test_project_back/requirements.txt`）：`fastapi>=0.115`、`SQLAlchemy>=2.0`、`alembic>=1.16`、`psycopg[binary]>=3.2`、`PyMySQL>=1.1`、`pydantic-settings>=2.0`、`PyJWT>=2.0`、`passlib[bcrypt]>=1.7`、`httpx>=0.28`、`APScheduler>=3.10`、`pgvector>=0.3,<1`、`cryptography>=43.0`、`paramiko>=3.5`、`playwright>=1.45`、`openpyxl>=3.1`、`Faker>=37.0`、`Jinja2>=3.1`、`jsonschema>=4.0`、`PyYAML>=6.0`、OpenTelemetry 三件套。

### 1.2 目录结构

```text
test_project_back/
├── app/
│   ├── main.py                  # 仅 5 行：app = create_app()
│   ├── bootstrap/               # application / lifespan / routes / model_registry
│   ├── shared/                  # config、database、deps(认证)、rate_limit、scheduler、
│   │                            # request_context、retention、outbound_policy
│   ├── agent/                   # AI 智能体核心（graph、generator、generation、execution、
│   │   │                        # autonomy、specialists、rag、reporting、parser、orchestration、skills）
│   │   ├── api/                 # /agent/** 全部路由
│   │   ├── models/              # 12 张表
│   │   └── rag/
│   ├── features/                # 20 个业务 feature，多数自带 api/ + models/ + application/
│   │   ├── auth/                # 用户 CRUD、登录注册
│   │   ├── project/             # 项目 / 组织 / 成员 / 模块 / 出站目标 + access 判定
│   │   ├── test_cases/          # 用例库 + xmind 导入导出
│   │   ├── defects/             # 缺陷 + 回归关联
│   │   ├── suites/              # 测试套件
│   │   ├── automation/          # 接口自动化任务
│   │   ├── case_generation/     # 阶段化用例生成
│   │   ├── script_generation/   # 脚本生成
│   │   ├── code_analysis/       # 静态代码扫描
│   │   ├── visual_automation/   # DOM 浏览器自动化
│   │   ├── mobile_automation/   # 移动端自动化
│   │   ├── data_factory/        # 数据工厂
│   │   ├── slow_sql/            # 慢 SQL 分析
│   │   ├── sql_log/             # SQL 日志采集（SSH 到 Linux 主机）
│   │   ├── jvm_monitoring/      # JVM 监控（Prometheus）
│   │   ├── observability/       # 测试可观测性（trace/baseline/gate/flaky）
│   │   ├── model_configuration/ # 大模型连接配置
│   │   ├── environments/        # 执行环境（仅 model + application，无 api/）
│   │   ├── notifications/       # 通知中心
│   │   └── dashboard/           # 看板
│   ├── utils/                   # 仅 time.py
│   ├── config.py                # 兼容入口：re-export app.shared.config
│   ├── deps.py                  # 兼容入口：re-export app.shared.deps
│   ├── database.py              # 兼容入口：re-export app.shared.database
│   └── worker.py                # 23 行：APP_PROCESS_ROLE=worker 的独立调度进程入口
├── migrations/versions/         # 50 个迁移
├── tests/                       # tests/ 17 个 + tests/agent/ 25 + tests/scripts/ 4 + tests/features/ 71（共 118 个 .py）
└── docs/
```

注意 `app/config.py`、`app/deps.py`、`app/database.py` 是**兼容垫片**：文件体只有 7 行，用 `sys.modules[__name__] = importlib.import_module(...)` 把旧 import 路径转发到新模块（config→`app.shared.config`、deps→`app.shared.deps`、database→`app.shared.database`）。说明代码至少经历过一次目录重构。

### 1.3 顶层路由组装

`app/bootstrap/routes.py` 把 21 个模块 router 平铺注册到同一个 `APIRouter()` 上，**没有任何全局前缀**：

| 注册顺序 | 模块 router | 前缀 |
| --- | --- | --- |
| 1 | `app/features/auth/api/router.py` | `/users` |
| 2 | `app/features/dashboard/api/router.py` | `/dashboard` |
| 3 | `app/features/project/api/router.py` | `/project` |
| 4 | `app/features/project/api/organization.py` | `/organizations` |
| 5 | `app/features/test_cases/api/router.py` | `/testcases` |
| 6 | `app/features/defects/api/router.py` | `/bugs` |
| 7 | `app/agent/api/__init__.py` | `/agent`（内部再嵌套 16 个子 router，其中 15 个来自 `app/agent/api/`，另 1 个是 `app/features/data_factory/api` 挂进来的 `/agent/data-factory`） |
| 8 | `app/features/automation/api/router.py` | `/agent/automation` |
| 9 | `app/features/case_generation/api/router.py` | `/agent/generation-runs` |
| 10 | `app/features/script_generation/api/router.py` | `/agent/script-templates` |
| 11 | `app/features/code_analysis/api/router.py` | `/code-analysis` |
| 12 | `app/features/model_configuration/api/router.py` | `/agent/model-configs` |
| 13 | `app/features/mobile_automation/api/router.py` | `/mobile-automation`（另有 `mobile_agent_ws_router`） |
| 14 | `app/features/jvm_monitoring/api/router.py` | `/agent/jvm` |
| 15 | `app/features/slow_sql/api/router.py` | `/agent/slow-sql` |
| 16 | `app/features/visual_automation/api/router.py` | `/agent/visual` |
| 17 | `app/features/sql_log/api/router.py` | `/agent/sql-log` |
| 18 | `app/features/notifications/api/router.py` | `/notifications` |
| 19 | `app/features/suites/api/router.py` | `/suites` |
| 20 | `app/features/observability/api/router.py` | `/agent/observability` |

同一批能力挂在两组前缀下（`/agent/*` 与 `/code-analysis`、`/mobile-automation`、`/suites`、`/testcases`、`/bugs`、`/organizations`、`/notifications`、`/project`），说明前缀命名是逐模块随手决定的，从未统一。

系统级接口（`app/bootstrap/routes.py:32-79`）：`GET /`、`GET /health`、`GET /ready`。三者**均无需登录**。`/ready` 会探测 `database`、`pgvector`、`ruff`/`semgrep`/`eslint`/`gitleaks` 二进制、`llm` 配置，整体状态只可能是 `ready` 或 `not_ready`——源码里 `overall = "degraded"` 那一句紧跟其后必然被 `if checks["database"] != "up": overall = "not_ready"` 覆盖，`degraded` 是不可达的死代码。各单项检查的取值则是 `up` / `down` / `unavailable` / `unconfigured` / `unknown`。

---

## 2. 旧 API 清单

共 395 个路由装饰器。以下按模块列出**真实路径**（router 前缀 + 装饰器路径），并标注用途与关键入参/出参。为控制篇幅，同一子前缀下的高频 CRUD 用一行概括，行尾括号内给文件位置。

### 2.1 系统级（3 个，无需登录）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/` | `{"message": "Welcome to Test Platform"}`，兼容根路径健康检查 |
| GET | `/health` | `{"status": "ok"}`，不访问数据库 |
| GET | `/ready` | 依赖就绪检查，返回 `{status, checks}`，`checks` 含 database / pgvector / scanner:{ruff,semgrep,eslint,gitleaks} / llm；`status` 仅取 `ready` 或 `not_ready` |

位置：`app/bootstrap/routes.py:32-80`。

### 2.2 用户（`/users`，9 个）

| 方法 | 路径 | 用途 / 入参要点 | 权限 |
| --- | --- | --- | --- |
| POST | `/users/register` | 公开注册；`{username(min3,max50), password(min12,max100)}`；返回 201 + `UserResponse`；同时 `ensure_personal_organization` 建个人组织 | 匿名，按 IP 限流 10 次/小时 |
| POST | `/users/` | 管理员创建用户（不占公开注册限额） | `require_admin` |
| GET | `/users/` | 用户列表；`skip(ge0)`、`limit(ge1,le500,默认10)`、`user_id`；返回 `{total, items}` | `require_admin` |
| GET | `/users/me` | 当前用户 | 登录 |
| PUT | `/users/me/password` | 改密；`{old_password(min6), new_password(min12)}`；成功 `{"message":"密码修改成功"}`；`token_version+1` | 登录 |
| GET | `/users/{user_id}` | 单查；查自己或管理员 | 登录 / admin |
| PUT | `/users/{user_id}` | 部分更新；`role`、`is_active` 仅管理员；改 role/is_active 时 `token_version+1` | 登录 / admin |
| DELETE | `/users/{user_id}` | 204；`db.delete(user)` 直接删 | `require_admin`，不能删自己 |
| POST | `/users/login` | `{username, password}` → `{access_token, token_type, user}`；按 IP 60 次/分 + 用户名 10 次/分限流 | 匿名 |

位置：`app/features/auth/api/router.py`。JWT claims：`sub`（用户 id 字符串）、`exp`（UTC，默认 8 小时 = `ACCESS_TOKEN_EXPIRE_MINUTES=480`）、`ver`（`token_version`）。

### 2.3 看板（`/dashboard`，6 个，全部只读）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/dashboard/status` | 概况卡片；`DashboardStats{cards:[OverviewCard]}`，统计当前用户可见项目的用例/执行/缺陷；`OverviewCard` 含 `bar: int(0..100)` |
| GET | `/dashboard/execution-trend` | 执行趋势 `ExecutionTrend` |
| GET | `/dashboard/risk` | 风险分析 `RiskAnalysis{items:[RiskItem{percent 0..100}]}` |
| GET | `/dashboard/defect-analysis` | 缺陷分析 `DefectAnalysis` |
| GET | `/dashboard/recent-tasks` | 最近任务 `RecentTasksResponse{items}` |
| GET | `/dashboard/expiring` | 即将到期资源清单（`PLATFORM_RETENTION_DAYS` 相关的过期预告） |

位置：`app/features/dashboard/api/{overview,trends,risk,defects,recent,retention}.py`；统计口径经 `_visible_project_ids` 收敛，见 `app/features/dashboard/api/common.py`。

### 2.4 项目（`/project`，12 个）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/project/` | 项目列表（`skip/limit`） |
| POST | `/project/` | 新增项目，201 |
| GET | `/project/{project_id}` | 单查 |
| PUT | `/project/{project_id}` | 修改 |
| DELETE | `/project/{project_id}` | 删除；query `cascade`，`cascade=true` 走 `delete_project_with_dependencies`（按外键图从叶到根删），否则 `db.delete` 遇 `IntegrityError` 返回 **409**「项目下存在关联数据…」 |
| GET/POST | `/project/{project_id}/modules` | 项目业务模块列表 / 新增 |
| PUT/DELETE | `/project/{project_id}/modules/{module_id}` | 修改 / 删除模块 |
| GET | `/project/{project_id}/members` | 成员列表 |
| POST | `/project/{project_id}/members` | 添加成员（幂等 upsert），201 |
| DELETE | `/project/{project_id}/members/{user_id}` | 移除成员；仅负责人或平台 admin |

位置：`app/features/project/api/router.py`。

### 2.5 组织（`/organizations`，7 个）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/organizations` | 组织列表；非 admin 只列自己拥有的 + 自己是成员的组织；返回 `{items:[{id,name,owner_id,my_role}]}` |
| POST | `/organizations` | 创建组织（创建者自动成为 `owner`），201 |
| GET | `/organizations/{organization_id}/members` | 成员表；需先 `require_organization_member` |
| GET | `/organizations/{organization_id}/candidates?username=` | 找可邀请的活跃用户；需组织 admin |
| GET | `/organizations/{organization_id}/models` | 可分配的启用模型（只回 `domain_id` + `label`）；需组织 admin |
| PUT | `/organizations/{organization_id}/members/{member_id}` | 幂等 upsert；`{user_id, role∈{member,admin}, agent_enabled, allowed_model_ids(≤30)}`；写 `AgentAuditLog` |
| DELETE | `/organizations/{organization_id}/members/{member_id}` | 204；负责人不可移除（409）；仍负责组织内项目时 409；连带清理组织下所有项目的 `project_member` 行 |

位置：`app/features/project/api/organization.py`。非成员访问组织侧接口一律 **404**「组织不存在或无权访问」；成员表内权限不足为 **403**「需要组织管理员权限」。

### 2.6 用例 / 缺陷 / 套件

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET/POST | `/testcases/` | 用例列表 / 新增（`skip/limit`） |
| POST | `/testcases/import` | xmind / Excel 导入（`app/features/test_cases/xmind_io.py`） |
| GET | `/testcases/export` | 导出 |
| GET/PUT/DELETE | `/testcases/{case_id}` | 单查 / 修改 / 删除 |
| GET/POST | `/bugs/` | 缺陷列表 / 新增（`skip/limit/title/status/assignee/...`） |
| GET/PUT/DELETE | `/bugs/{bug_id}` | 单查 / 修改 / 删除 |
| GET/POST | `/bugs/{bug_id}/regressions` | 缺陷↔回归测试点关联查询 / 添加 |
| DELETE | `/bugs/{bug_id}/regressions/{regression_id}` | 按关联 id 删除 |
| DELETE | `/bugs/{bug_id}/regressions` | 按测试点删除 |
| GET/POST | `/suites/` | 套件列表 / 新增 |
| GET/PATCH/DELETE | `/suites/{suite_id}` | 单查 / 修改 / 删除 |
| POST | `/suites/{suite_id}/cases` | 向套件添加用例 |
| PATCH/DELETE | `/suites/{suite_id}/cases/{case_id}` | 修改 / 移除套件内用例 |
| PUT | `/suites/{suite_id}/cases/order` | 用例排序 |
| POST | `/suites/{suite_id}/run` | 执行套件 |
| GET | `/suites/{suite_id}/executions` | 套件执行记录 |
| GET | `/suites/executions/{batch_id}` | 批次详情 |
| POST | `/suites/executions/{batch_id}/cancel` | 取消批次 |

位置：`app/features/test_cases/api/router.py`、`app/features/defects/api/router.py`、`app/features/suites/api/router.py`。

### 2.7 智能体核心（`/agent`，76 个，节选主链路）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/agent/parse`、`/agent/parse/upload` | 解析 Swagger/cURL/HAR/Postman/Markdown 文档为接口端点（`app/agent/api/documents.py`、`app/agent/parser/*`） |
| GET/DELETE | `/agent/endpoints`、`/agent/endpoints/{endpoint_id}` | 接口资产清单 |
| POST | `/agent/generate`、`/agent/generate/stream` | 按接口生成用例（SSE 流式） |
| GET/DELETE | `/agent/testcases` | 生成用例列表 / 清理；另有 `/agent/testcases/versions`、`PATCH /agent/testcases/batch-status`、`PATCH /agent/testcases/{testcase_id}/status` |
| POST | `/agent/execute`、`/agent/execute/stream` | 执行用例，产出持久化报告 |
| GET/DELETE | `/agent/executions` | 执行记录 |
| POST | `/agent/executions/{execution_id}/feedback` | 人工确认失败并沉淀 badcase |
| POST | `/agent/chat`、`/agent/chat/stream` | 对话式智能体 |
| POST | `/agent/chat/v2`、`/agent/chat/v2/stream`、`/agent/chat/v2/resume` | 第二代对话 |
| GET | `/agent/chat/sessions`、`/agent/chat/sessions/{session_id}` | 会话列表 / 详情 |
| PATCH/DELETE | `/agent/chat/sessions/{session_id}` | 改名 / 删除 |
| GET | `/agent/chat/v2/trace/{thread_id}` | 对话 trace |
| POST/GET | `/agent/runs`、`/agent/runs`、`/agent/runs/{run_id}` | 创建 / 列表 / 详情运行 |
| GET | `/agent/runs/{run_id}/events` | 运行事件流 |
| POST | `/agent/runs/{run_id}/{approval,cancel,pause,resume}` | 运行控制 |
| POST/GET | `/agent/workflows`、`/agent/workflows/{run_id}` | 统一业务编排（feature flag 控制，见 §7） |
| POST | `/agent/workflows/{run_id}/{approval,cancel,pause,resume,data-callback}` | 编排控制 + 数据工厂回调 |
| GET | `/agent/workflows/{run_id}/events` | 编排事件流 |
| GET | `/agent/knowledge` 组 | `POST /agent/knowledge`、`POST /agent/knowledge/upload`、`PATCH/DELETE /agent/knowledge/{document_id}`、`GET /agent/rag/documents`、`POST /agent/rag/reindex`、`POST /agent/rag/search-preview` |
| GET/POST | `/agent/templates`、`/agent/templates/upload` | 用例模板；`PATCH/DELETE /agent/templates/{template_id}` |
| POST | `/agent/action-approvals`、`/agent/action-approvals/{approval_id}/decision` | 高危动作审批 |
| GET | `/agent/reports`、`/agent/reports/{report_id}` | 报告列表 / 详情 |
| GET | `/agent/reports/{report_id}/download` | 下载（json/html/pdf，reportlab） |
| GET/POST/DELETE | `/agent/recycle-bin`、`/agent/recycle-bin/{batch_id}/restore`、`/agent/recycle-bin/{batch_id}` | 回收站 |
| GET | `/agent/models`、`/agent/health`、`/agent/skills`、`/agent/business-packs`、`/agent/audit` | 模型清单、智能体健康、技能目录、业务包、审计 |
| GET/POST | `/agent/environments`、`POST /agent/auth` | 环境清单、项目执行鉴权配置 |
| DELETE | `/agent/environments/{name}` | 删除环境（仅管理员） |

位置：`app/agent/api/`。**注意**：`app/features/data_factory/api/router.py` 被 `app/agent/api/__init__.py` 挂到 `/agent` 下，因此数据工厂的真实前缀是 **`/agent/data-factory`**，而非顶层 `/data-factory`。

### 2.8 接口自动化（`/agent/automation`，8 个）

`POST /agent/automation/tasks`、`GET /agent/automation/tasks`、`GET /agent/automation/tasks/{task_id}`、`PATCH /agent/automation/tasks/{task_id}`、`POST /agent/automation/tasks/{task_id}/run`、`GET /agent/automation/runs`、`GET /agent/automation/runs/{run_id}`、`GET /agent/automation/runs/{run_id}/logs`。位置：`app/features/automation/api/router.py`。

### 2.9 阶段化用例生成（`/agent/generation-runs`，23 个）

`POST /`（创建生成任务）、`GET /`（最近任务）、`GET /metrics/quality`、`POST /evolution/discover`、`GET /evolution/rules`、`GET /evolution/metrics`、`PATCH /evolution/rules/{rule_id}`、`GET /{run_id}`、`GET/POST /{run_id}/test-points`、`POST /{run_id}/test-points/review`、`POST /{run_id}/coverage-gaps/fill`、`POST /{run_id}/resume`、`POST /{run_id}/compile-api-cases`、`POST /{run_id}/compile-web-projection`、`POST /{run_id}/compile-web-cases`、`POST /{run_id}/compile-mobile-projection`、`POST /{run_id}/compile-mobile-cases`、`GET /{run_id}/projections`、`POST/GET /{run_id}/quality-review(s)`、`POST/GET /{run_id}/badcases`。位置：`app/features/case_generation/api/router.py`。

### 2.10 脚本生成（`/agent/script-templates`，13 个）

`GET /`、`GET/POST /artifacts`、`GET/DELETE /artifacts/{artifact_id}`、`POST /upload`、`PATCH/DELETE /{template_id}`、`POST /generate`、`GET /batches/{batch_id}/download`、`GET /{artifact_id}/download`、`POST /{artifact_id}/execute`、`POST /artifacts/{artifact_id}/execute`。
**两个 `execute` 端点都固定返回 501**：`{"code":"SCRIPT_CLOUD_EXECUTION_UNAVAILABLE","message":"云端脚本执行暂未开放，当前仅支持下载脚本到本地执行"}`（`app/features/script_generation/api/router.py:370-396`）——这是旧项目里唯一显式用状态码声明「未接入」的地方。

### 2.11 模型配置（`/agent/model-configs`，8 个，全部仅管理员）

`GET /agent/model-configs/providers`、`POST /agent/model-configs/provider-models`、`GET /agent/model-configs/`、`POST /agent/model-configs/`、`PUT /agent/model-configs/{config_id}`、`PUT /agent/model-configs/{config_id}/default`、`POST /agent/model-configs/{config_id}/test`、`DELETE /agent/model-configs/{config_id}`。
位置：`app/features/model_configuration/api/router.py`。响应经 `configuration_to_dict` 白名单化：只回 `has_api_key`（bool）+ `masked_api_key`（`前3位****后4位`），绝不回传 `api_key_encrypted` 或明文（`app/features/model_configuration/application/service.py:40-70`）。

### 2.12 数据工厂（`/agent/data-factory`，43 个）

- 模板：`POST/GET /templates`、`GET/PUT/DELETE /templates/{template_id}`、`POST /templates/{template_id}/validate|publish|review|restore`、`GET /templates/{template_id}/versions`、`GET /templates/{template_id}/export`、`GET /templates/{template_id}/versions/{version}/export`、`DELETE /templates/{template_id}/purge`、`POST /templates/bulk-archive`、`POST /templates/bulk-purge`
- 运行：`POST/GET /runs`、`POST /runs/batch`、`POST /runs/preview`、`GET /runs/events`（SSE）、`GET /runs/{run_id}`、`GET /runs/{run_id}/manifest|lineage`、`POST /runs/{run_id}/cleanup`、`GET /cleanup/tasks`、`POST /{run_id}/cancel`
- 数据库：`POST /db/plan/compile`、`POST /db/plan/match-endpoints`、`POST /db/plan/compile-api`、`GET /db/connections`、`GET /db/connections/candidates`、`GET /db/connections/{connection_id}/catalog`、`PUT /db/connections/{connection_id}/policy`
- 其他：`GET /relations`、`GET /audit`、`GET /notifications`、`POST /notifications/{notification_id}/read`、`GET /batches`、`GET /batches/{batch_tag}`、`POST /batches/{batch_tag}/cleanup`、`POST /batches/{batch_tag}/expire`、`POST /ai/field-suggestions`、`POST /ai/relation-review`

位置：`app/features/data_factory/api/`。

### 2.13 静态代码分析（`/code-analysis`，18 个）

`GET /code-analysis/engines`、`POST/GET /code-analysis/repositories`、`PATCH/DELETE /code-analysis/repositories/{repository_id}`、`POST/GET /code-analysis/profiles`、`POST /code-analysis/targets`、`POST/GET /code-analysis/runs`、`GET /code-analysis/runs/{run_id}`、`POST /code-analysis/runs/{run_id}/cancel`、`GET /code-analysis/runs/{run_id}/findings`、`GET /code-analysis/runs/{run_id}/report`、`PATCH /code-analysis/issues/{issue_id}`、`GET /code-analysis/layers`、`POST /code-analysis/layers/analyze`。
扫描器插件：`bandit`、`eslint`、`gitleaks`、`ruff`、`semgrep`（`app/features/code_analysis/scanner_plugins/`），Git 检出在 `CODE_SCAN_WORKSPACE_DIR=runtime/code_analysis/workspaces` 下异步执行。

### 2.14 移动端自动化（`/mobile-automation`，26 个 REST + 1 个 WebSocket）

实际 27 个装饰器（`app/features/mobile_automation/api/router.py`），其中 WebSocket 为 `@mobile_agent_ws_router.websocket("/mobile-agent")`。上文原只节选了写入与签发链路，完整清单还包括只读/管理端点：`GET /overview`、`GET /devices`、`GET /devices/{device_id}`、`POST /devices/{device_id}/agent-credential`、`GET /devices/{device_id}/reservations`、`GET /sessions`、`GET /sessions/{session_id}`、`PATCH /sessions/{session_id}`、`GET /sessions/{session_id}/events`、`PUT|GET /sessions/{session_id}/case`、`POST /scripts/generate`、`GET /plans`、`GET /plans/{plan_id}/runs`、`GET /runs/{run_id}`、`GET /runs/{run_id}/events`、`POST /runs/{run_id}/cancel`，以及已节选的 `POST /devices/register`、`DELETE /devices/{device_id}/agent-credential`、`POST|DELETE /devices/{device_id}/reservations[/{reservation_id}]`、`POST /sessions`、`POST /sessions/{session_id}/events`、`POST /plans`、`POST /plans/{plan_id}/run`、`POST /ws-token`。

浏览器端用 `REST` 换 60 秒 `ws_token`（`MOBILE_WS_TOKEN_TTL_SECONDS=60`），原生设备 Agent 用管理员签发的可撤销设备凭据。

### 2.15 DOM 浏览器自动化（`/agent/visual`，6 个）

`POST/GET /agent/visual/sessions`、`DELETE /agent/visual/sessions/{session_id}`、`POST /agent/visual/sessions/{session_id}/detect`、`POST /agent/visual/sessions/{session_id}/step`、`POST /agent/visual/sessions/{session_id}/projected-run`。
基于 Playwright，仅用 DOM locator，**不使用截图/坐标/视觉模型**（`app/shared/config.py:VISUAL_*` 注释与 `app/features/visual_automation/infrastructure/browser.py`）。

### 2.16 慢 SQL 与 SQL 日志

- `/agent/slow-sql`（25 个）：`GET /health`、`GET /rules`、`POST /static-analyze`、`POST /analyze`、`POST /runs/{run_id}/cancel|retry`、`POST /runs/process`、`GET /runs`、`GET /runs/{run_id}`、`GET /connections`、`POST /connections`、`POST /connections/test`、`PUT/DELETE /connections/{connection_id}`、`POST /connections/{connection_id}/test`、`DELETE /connections/{connection_id}/records`、`GET /connections/{connection_id}/overview|performance`、`GET /connections/{connection_id}/schemas`、`GET .../schemas/{schema}/tables`、`GET .../tables/{table}`、`GET .../dictionary`、`GET .../relationships`、`POST /connections/{connection_id}/query`、`GET /connections/{connection_id}/query-history`
- `/agent/sql-log`（20 个）：`GET /health`、`POST/GET /hosts`、`PUT/DELETE /hosts/{host_id}`、`POST /hosts/test`、`POST /hosts/{host_id}/discover`、`GET /hosts/{host_id}/sources`、`POST/GET /runs`、`POST /runs/{run_id}/cancel|retry`、`POST /runs/process`、`GET /runs/trend`、`GET /runs/compare`、`GET /runs/{run_id}`、`GET /runs/{run_id}/entries`、`GET /runs/{run_id}/fingerprints/{fingerprint}/diagnose`、`GET /runs/{run_id}/summary`、`GET /runs/{run_id}/summary/export`

位置：`app/features/slow_sql/api/`、`app/features/sql_log/api/`。慢 SQL 目标是 **MySQL/MariaDB**（PyMySQL + SSH），与平台主库 PostgreSQL 是两套连接。

### 2.17 JVM 监控（`/agent/jvm`，24 个）

`GET /agent/jvm/health`、`POST/GET /agent/jvm/connections`、`POST /agent/jvm/prometheus/test`、`GET/PUT/DELETE /agent/jvm/connections/{connection_id}`、`POST /agent/jvm/connections/{connection_id}/test`、`GET /agent/jvm/connections/{connection_id}/discover`、`GET/POST /agent/jvm/tasks`、`GET/PUT/DELETE /agent/jvm/tasks/{task_id}`、`POST /agent/jvm/tasks/{task_id}/run`、`GET /agent/jvm/tasks/{task_id}/trends|capabilities|runs`、`GET/PUT /agent/jvm/tasks/{task_id}/agent`、`POST /agent/jvm/tasks/{task_id}/agent/test`、`POST /agent/jvm/tasks/{task_id}/diagnostics`、`GET /agent/jvm/alerts`、`GET /agent/jvm/comparison`。
数据源是 Prometheus（`app/features/jvm_monitoring/infrastructure/prometheus.py`）。

### 2.18 测试可观测性（`/agent/observability`，20 个）

`GET /agent/observability/health`、`POST/GET /agent/observability/connections`、`POST /agent/observability/connections/test`、`GET/PUT/DELETE /agent/observability/connections/{connection_id}`、`POST /agent/observability/connections/{connection_id}/test`、`PUT/GET /agent/observability/bindings/{project_id}[/{environment}]`、`GET /agent/observability/executions/{execution_id}`、`POST /agent/observability/executions/{execution_id}/trace/refresh`、`GET /agent/observability/flaky-cases`、`PUT/GET /agent/observability/baselines/policies`、`GET /agent/observability/endpoints/{endpoint_id}/baseline`、`GET /agent/observability/reports/{report_id}`、`PUT/GET /agent/observability/gates/policy`、`GET /agent/observability/alerts`、`GET /agent/observability/reports/{report_id}/gate`。

### 2.19 通知中心（`/notifications`，18 个）

`GET /notifications/channels`、`GET /notifications/events`、`GET/POST /notifications/templates`、`GET/PATCH/DELETE /notifications/templates/{template_id}`、`GET/POST /notifications/configs`、`GET/PATCH/DELETE /notifications/configs/{config_id}`、`GET/POST /notifications/subscriptions`、`PATCH/DELETE /notifications/subscriptions/{subscription_id}`、`POST /notifications/send`、`POST /notifications/test`。
位置：`app/features/notifications/api/router.py`。模板用 Jinja2，webhook URL 与渠道扩展配置经 `EncryptedText`/`EncryptedConfig`（`enc:v1:` 前缀）落库。

---

## 3. 数据表清单与关系

ORM 表共 **90 张**（`grep -rh '__tablename__ = ' app/ \| wc -l`），迁移文件 50 个。全部 90 张表都能在 `migrations/versions/` 中找到 `op.create_table` 或 `_create_table_if_missing`。

迁移链里另有 **7 张早已被 CI/CD 功能退役的表**（`jenkins_connection`、`mobile_jenkins_build`、`pipeline`、`pipeline_run`、`pipeline_step_run`、`timed_task`、`webhook_config`）：它们在早期迁移里被 `op.create_table` 建出、在 `app/` 下没有任何 ORM 模型，然后被 `migrations/versions/0031_remove_cicd_schema.py` 的 `upgrade()` **一次性全部 drop 掉**（`TABLES` 元组正好就是这 7 张，`downgrade()` 为空操作）。所以**迁移到 head 的库上这 7 张表并不存在**，线上 schema 就是 90 张 ORM 表 + `alembic_version`；`0031` 的作用是保证老库升级时能平滑清掉历史残留。

### 3.1 基础骨架（第一阶段重建的部分）

| 表 | 位置 | 关键字段 | 关系 |
| --- | --- | --- | --- |
| `user` | `app/features/auth/models.py` | `id`、`username(50,unique)`、`hashed_password`、`role(20,默认"test")`、`is_active`、`token_version(默认0)`、`created_at`、`updated_at` | 被 **76 处** `ForeignKey("user.id", ...)` 声明引用（见 §8.2 第 10 条的口径），其中 60 处不带 ondelete、6 处 `CASCADE`、10 处 `SET NULL` |
| `organization` | `app/features/project/models/organization.py` | `name(100)`、`owner_id → user.id`（无 ondelete） | 1:多 → `organization_member`、`project` |
| `organization_member` | 同上 | `organization_id(CASCADE)`、`user_id(CASCADE)`、`role(默认"member")`、`agent_enabled`、`allowed_model_ids JSON` | 唯一 `(organization_id,user_id)`；平台 admin 不占行，用虚拟 `platform_admin` |
| `project` | `app/features/project/models/project.py` | `name(100,unique)`、`description(500)`、`owner_id → user.id`（**NOT NULL，无 ondelete**）、`organization_id`（可空） | 1:多 → `project_member`、`project_module`、`project_outbound_target`、`bug`、`testcase`… |
| `project_member` | `app/features/project/models/project_member.py` | `project_id(CASCADE)`、`user_id(CASCADE)`、`role(30,默认"member")`、`created_by → user.id` | 唯一 `(project_id,user_id)` |
| `project_module` | `app/features/project/models/project_module.py` | `name`、`code`、`match_tags`/`path_prefixes`/`source_groups` JSON、`is_system`、`status`、`sort_order` | 项目业务模块，用于接口自动归类 |
| `project_outbound_target` | `app/features/project/models/outbound_target.py` | `project_id(CASCADE)`、`scheme`、`host`、`port`、`is_production`、`enabled`、`approved_by` | 唯一 `(project_id,scheme,host,port)` |
| `model_configuration` | `app/features/model_configuration/models/model_configuration.py` | `domain_id(unique)`、`label`、`provider`、`api_base`、`api_key_encrypted`（**永不回传**）、`model_name`、`temperature`、`max_tokens`、`timeout`、`cost_per_1k_*`、`is_enabled`、`is_default`、`sort_order`、`created_by` | 平台级，无项目归属 |
| `environment` | `app/features/environments/models/environment.py` | `name(50,unique)`、`display_name`、`base_url(500)`、`gateway_prefix`、`default_headers JSON`、`description`、`is_default`、`is_active`、`created_by/updated_by (SET NULL)` | 平台级；索引 `(is_active,is_default)` |
| `notification_template` | `app/features/notifications/models/notification.py` | `project_id(CASCADE)`、`event_type`、`channel`、`title_template`、`body_template`（Jinja2）、`is_active` | 索引 `(project_id,event_type,channel)` |
| `notification_config` | 同上 | `project_id(CASCADE)`、`user_id(CASCADE)`、`channel`、`webhook_url EncryptedText`、`extra_config EncryptedConfig`、`is_enabled` | SMTP / 机器人凭据加密落库 |
| `notification_subscription` | 同上 | `project_id`、`user_id`、`event_type`、`channel`、`config_id(CASCADE)`、`template_id(SET NULL)`、`filters JSON` | 事件 → 渠道 订阅 |

> **概念区分**：`environment.base_url`、`slow_sql_connection`、`prometheus_connection`、`code_repository`、`linux_host_connection` 存的是**被测目标**的连接信息（PostgreSQL 主库之外）；平台主库只有 `DATABASE_URL` 一个连接串。两者不是互斥关系。

### 3.2 用例 / 缺陷 / 套件 / 自动化

| 表 | 说明 |
| --- | --- |
| `testcase` | 用例库主表，`project_id`、`creator_id`，支持 xmind / Excel 导入导出 |
| `bug`、`defect_regression_link` | 缺陷与回归测试点多对多 |
| `test_suite`、`suite_case`、`suite_execution` | 套件、套件内用例、套件执行 |
| `test_module`、`test_point` | 阶段化测试设计（`case_generation` 域） |
| `automation_task`、`automation_run`、`automation_run_log` | 接口自动化任务与运行日志 |

### 3.3 智能体域（12 张）

`agent_chat_session`、`agent_run`、`agent_action_approval`、`agent_audit_log`、`api_endpoint`、`api_testcase`、`execution_record`、`test_report`、`report_export_task`、`case_template`、`project_auth_config`、`agent_recycle_bin_item`（`app/agent/models/`）。

### 3.4 用例生成 / 脚本 / 观测

`case_generation_run`、`case_generation_link`、`case_quality_review`、`generation_badcase`、`generation_evolution_rule`、`scenario_execution_evidence`（`app/features/case_generation/models/`）；`script_template`、`script_artifact`（`app/features/script_generation/models/`）；`telemetry_connection`、`observability_binding`、`performance_baseline_policy`、`performance_gate_policy`、`performance_evaluation`、`execution_observation`（`app/features/observability/models/`）。

### 3.5 数据工厂（12 张）

`data_template`、`data_template_version`、`data_artifact`、`data_export_job`、`data_factory_run`、`data_factory_step_run`、`data_lineage`、`data_factory_cleanup_task`、`data_factory_audit_event`、`data_factory_resource_relation`、`data_factory_notification`、`data_factory_db_policy`（`app/features/data_factory/models/data_factory.py`）。

### 3.6 移动端 / 慢 SQL / SQL 日志 / JVM

- 移动端（9 张）：`mobile_device`、`mobile_device_reservation`、`mobile_device_credential`、`mobile_recording_session`、`mobile_recording_event`、`mobile_test_case`、`mobile_generated_script`、`mobile_test_plan`、`mobile_test_run`
- 慢 SQL（3 张）：`slow_sql_connection`、`slow_sql_analysis_run`、`slow_sql_query_history`
- SQL 日志（5 张）：`linux_host_connection`、`sql_log_source`、`sql_log_collection_run`、`sql_log_entry`、`sql_log_fingerprint_summary`
- JVM（4 张）：`prometheus_connection`、`jvm_monitoring_task`、`jvm_analysis_run`、`jvm_diagnostic_agent`
- 代码分析（7 张）：`code_repository`、`code_scan_profile`、`code_scan_target`、`code_scan_run`、`code_engine_execution`、`code_issue`、`code_issue_occurrence`
- RAG（1 张）：`rag_document`（含 `pgvector` 的 `Vector(384)` 列，启动时补建 HNSW 余弦索引，见 `app/bootstrap/lifespan.py:_ensure_rag_hnsw_index`）

### 3.7 关系示意

```text
user ─┬─< organization.owner_id（无 ondelete）
      ├─< organization_member（CASCADE 双向）
      ├─< project.owner_id（NOT NULL，无 ondelete）
      ├─< project_member（project/user CASCADE，created_by 无 ondelete）
      └─< 76 处 *_created_by / creator_id / executor_id / reporter_id / assignee_id 等 FK（60 处无 ondelete，见 §8.2 第 10 条）

organization ─< organization_member >─ user
organization ─< project ─< project_member >─ user
project ─< project_module / project_outbound_target / testcase / bug / data_template / ...
organization_member.agent_enabled + allowed_model_ids  ──控制──>  能否调用 /agent/** 与选哪个 model_configuration
environment.base_url  ──决定──>  execution_record.environment 指向的真实被测服务器
```

---

## 4. 认证与权限模型

### 4.1 JWT

- 签发：`app/features/auth/api/router.py:262-275`，claims = `sub`（`str(user.id)`）、`exp`（UTC + `ACCESS_TOKEN_EXPIRE_MINUTES`，默认 **480 分钟**）、`ver`（`token_version`）。
- 校验：`app/shared/deps.py:get_current_user`，`jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])`，`ALGORITHM="HS256"`。
- `oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/users/login")`（`app/shared/deps.py:20`），**仅供 Swagger 文档展示**，实际登录用 `POST /users/login` JSON 体。

### 4.2 token_version 撤销语义

`token_version` 只在两处 +1：

| 触发 | 位置 |
| --- | --- |
| 修改密码 | `app/features/auth/api/router.py:145` |
| 修改 `role` 或 `is_active` | `app/features/auth/api/router.py:207` |

**修改用户名不会 +1**（`router.py:206` 的条件只匹配 `("role", "is_active")`，`username` 不在其中）。校验失败统一 401「登录失效，请重新登录」，`WWW-Authenticate: Bearer`（`app/shared/deps.py:32-46`）。

### 4.3 三套角色并存

| 层次 | 取值 | 来源 | 判定入口 |
| --- | --- | --- | --- |
| 平台角色 | `admin` / `test` / `dev`（`user.role`，`Literal` 约束） | 注册默认 `test` | `is_admin()` → `user.role == "admin"`（`app/shared/deps.py:48-50`） |
| 组织角色 | `owner` / `admin` / `member` + 虚拟 `platform_admin` | `organization_member.role` | `organization_role()`（`app/features/project/application/organization.py:32-44`） |
| 项目角色 | `viewer` / `member` / `editor` + 虚拟 `owner`/`admin` | `project_member.role` | `project_with_role()` → `accessible_project()`（`app/features/project/application/access.py`） |

项目角色等级：`viewer=0 < member=1 < editor=2 < owner=3 < admin=4`（`PROJECT_ROLE_RANKS`，`app/features/project/application/access.py:27-33`）。未登记的角色字符串一律降级为 `viewer`（`normalize_project_role`）。

`organization_role` 的判定顺序：① `user.role == "admin"` → `platform_admin`；② `organization.owner_id == user.id` → `owner`；③ 查 `organization_member.role`；④ 无则 `None`。

### 4.4 accessible_project 判定顺序

`project_with_role()`（`app/features/project/application/access.py:66-95`），按顺序短路：

1. `project` 不存在 → `(None, None)`
2. 平台 admin → `(project, "admin")`
3. **组织边界**：`project.organization_id` 非空且用户不在该组织的 `organization_member` 中 → `(project, None)`
4. `project.owner_id == user.id` → `owner`
5. 组织角色是 `owner`/`admin`/`platform_admin` → `owner`（组织管理员继承项目负责人权限）
6. 查 `project_member.role` → 归一化后的角色
7. 无成员行 → `None`

第 3 步意味着：**历史残留的跨组织 `project_member` 行不会授权**——组织边界优先于项目成员关系。

`accessible_project(min_role=...)`：不可访问 → **404**「项目不存在或无权访问」（隐藏存在性）；可访问但等级不足 → **403**，文案按目标角色给出（viewer→「当前项目角色为只读，无法修改项目数据」，editor→「需要项目维护者或负责人权限才能修改项目配置」，owner→「只有项目负责人或管理员可以执行该操作」）。

### 4.5 401 / 403 / 404 文案实测

| 状态 | 文案 | 触发条件 | 位置 |
| --- | --- | --- | --- |
| 400 | 「用户名或密码错误」 | 登录时用户不存在 **或** 口令错（不区分） | `app/features/auth/api/router.py:245-254` |
| 400 | 「该用户名已存在」 | 注册 / 创建用户 / 改名冲突 | 同上（:52-53、:70-71、:85-86、:99-100） |
| 400 | 「旧密码错误」 | 改密校验失败 | `router.py:140-141` |
| 400 | 「不能修改自己的角色」/「不能停用自己的账户」/「不能删除自己的账户」 | 自我保护 | `router.py:196、198、225-226` |
| 401 | 「登录失效，请重新登录」 | JWT 解码失败 / `exp` 过期 / `ver` 不匹配 | `app/shared/deps.py:32-36、47-48` |
| 401 | 「用户不存在」 | `sub` 指向已删除用户 | `app/shared/deps.py:39-40` |
| 403 | 「该账户已被禁用」 | `is_active=False` | `app/shared/deps.py:41-42`、`router.py:256-260` |
| 403 | 「仅管理员可…」「需要组织管理员权限」 | 平台 / 组织级权限不足 | `app/shared/deps.py:57-60`、`application/organization.py:59-60` |
| 403 | 「组织管理员尚未开放智能体权限」「管理员尚未分配该模型」「所选模型已停用或不存在」「项目尚未归属组织，无法运行智能体」「未分类或生产环境的智能体执行尚未开放」 | Agent 授权链 | `app/features/project/application/organization.py:64-82、12-19` |
| 403 | 「当前项目角色为只读，无法修改项目数据」/「需要项目维护者或负责人权限才能修改项目配置」/「只有项目负责人或管理员可以执行该操作」 | 项目角色等级不足 | `app/features/project/application/access.py:41-45、119-123` |
| 404 | 「项目不存在或无权访问」 | 跨项目 / 跨组织访问 | `app/features/project/application/access.py:116-118` |
| 404 | 「组织不存在或无权访问」 | 非成员访问组织侧接口 | `application/organization.py:51-52` |
| 409 | 「项目下存在关联数据。如需删除，请确认同时清理项目下的全部数据。」 | 非级联删项目遇外键 | `app/features/project/api/router.py:253-258` |
| 409 | 「组织负责人不能移除」「该成员仍负责组织内项目，请先转移项目」 | 组织成员删除前置 | `app/features/project/api/organization.py:111-118` |
| 422 | 参数与业务约束校验（Pydantic 与手写 `status_code=422`） | 参数与业务约束 | 全文，共 75 处 |
| 429 | 「认证请求过于频繁，请稍后重试」 | 登录 / 注册限流，带 `Retry-After` | `app/shared/rate_limit.py:135-138、144-147` |
| 501 | `detail = {"code":"SCRIPT_CLOUD_EXECUTION_UNAVAILABLE","message":"云端脚本执行暂未开放，当前仅支持下载脚本到本地执行"}` | 脚本云端执行未接入 | `app/features/script_generation/api/router.py:370-378` |

---

## 5. 旧前端现状

### 5.1 技术栈

| 项 | 取值 | 来源 |
| --- | --- | --- |
| 框架 | Vue 3.5（组合式 API） | `test_project_front/package.json` |
| 语言 | **纯 JavaScript**，无 TypeScript（无 `tsconfig.json`，只有 `jsconfig.json` 做路径别名） | 目录列表 |
| UI 库 | element-plus 2.14 + lucide-vue-next 图标 | `package.json` |
| 图表 | echarts 6 | `package.json` |
| HTTP | axios 1.18，`baseURL: '/api'` | `src/utils/request.js:15-18` |
| 构建 | Vite 8（`rolldownOptions` 分包：echarts / element-plus / icons / vue / vendor） | `vite.config.js` |
| 包管理 | pnpm（`corepack pnpm install`） | `快速启动.md` |
| 测试 | `@playwright/test` + Node 原生 `node --test` 单测 | `package.json` scripts |

规模：188 个 `.vue`/`.js` 文件、约 55,400 行；73 个 view、19 个 `src/api/*.js` 模块、16 个 composable、13 个独立组件。

### 5.2 路由与页面清单（`src/router/index.js`）

访客页：`/login`、`/register`（`meta.guest`）。主布局 `src/layouts/MainLayout.vue`，默认重定向 `/dashboard`，捕获未匹配路由并重定向到 `/dashboard`。

| 分组 | 路由 |
| --- | --- |
| 概览与资产 | `/dashboard`、`/projects`、`/organizations`、`/testcases`、`/assets/apis`、`/bugs`、`/reports`、`/recycle-bin` |
| 数据与环境 | `/data-factory`、`/database-connections`、`/settings/target-services` |
| 智能体 | `/agents/api-agent`（`meta.hidden`）、`/agents/orchestrator`、`/agents/web-vision` |
| 移动端 | `/mobile-automation`、`/mobile-automation/workspace`、`/mobile-automation/runs/:runId` |
| 工程化 | `/suites`、`/coverage`、`/defect-regression`、`/notifications`、`/observability`、`/knowledge` |
| 慢 SQL | `/slow-sql`、`/slow-sql/collect`、`/slow-sql/diagnose`、`/slow-sql/runs/:runId` |
| JVM | `/agents/jvm`、`/agents/jvm/create`、`/agents/jvm/connections`、`/agents/jvm/:taskId` |
| 代码分析 | `/code-analysis`、`/code-analysis/runs/:runId` |
| 账号 | `/users`（`meta.roles:['admin']`）、`/settings/models`（`meta.roles:['admin']`）、`/profile` |
| 重定向 | `/agents` → `/agents/api-agent`；`/agents/test-design` → `/agents/api-agent` |

路由守卫（`src/router/index.js` 尾部）只做三件事：未登录跳 `/login?redirect=`、已登录访问访客页跳 `/dashboard`、`meta.roles` 不含当前 `user.role` 时跳 `/dashboard`。**无后端 404 隐藏配合的前端权限路由**——非 admin 直接进 `/users` 会被重定向，而不是看到受限页面。

侧边栏菜单（`src/layouts/MainLayout.vue:89-151` 的 `navGroups` computed）把页面分为 **5 组**：`workspace`「工作台」（质量总览 / 项目管理 / 组织与权限 / 用例库 / 缺陷管理）、`assets`「测试资产」（接口资产 / 数据工厂 / 数据库连接 / 知识库 / 回收站）、`intelligence`「智能测试」（接口智能体 / 统一业务编排 / UI 自动化智能体 / 移动端自动化）、`quality`「质量治理」（覆盖度中心 / 缺陷回归中心 / 测试套件 / 通知中心 / 测试可观测性 / 慢 SQL 治理 / JVM 性能诊断 / 代码静态分析 / 测试报告）、`team`「团队与设置」（团队成员 / 模型配置 两项仅 `user.role === 'admin'` 才出现，其余为环境配置 / 个人中心）。注意 `accent` 是**菜单项**上的样式标记（`intelligence` 与 `quality` 组内的项带 `accent: true`），不是分组属性。

### 5.3 如何调用 API：`/api` 代理**剥离前缀**

`test_project_front/vite.config.js:19-28`：

```js
server: {
  host: true,
  allowedHosts: ['api.project.local'],
  proxy: {
    // 前端请求 /api/xxx → 转发到 TestPilot 后端。
    '/api': {
      target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8888',
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/api/, ''),  // 去掉 /api 前缀再发给后端
    },
  },
},
```

配套的是 `src/utils/request.js:15-18`：

```js
const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
});
```

因此浏览器地址栏看到的是 `/api/users/login`，实际打到后端的是 `/users/login`。`/api` 只是**开发期前缀**，后端从不认识它。

### 5.4 登录态保存

`src/utils/auth.js`：

- `localStorage['access_token']` 存 JSON `{token, expires_at}`，`expires_at` 由 `parseJwtExp()` 解析 JWT 的 `exp` 得出，非 JWT 时回退到 `DEFAULT_TOKEN_TTL_MS = 8*3600*1000`（对齐后端 8 小时）。
- `localStorage['user']` 存完整 `UserResponse`（含 `role`、`is_active`）。
- `isTokenExpired()` 把「距过期 5 分钟内」也算过期（`TOKEN_EXPIRY_WARNING_MS`），但**没有刷新令牌机制**——过期就只能重登。
- 旧版兼容：`getStoredToken()` 允许值直接是明文 token（历史遗留）。
- 请求拦截器把 `Authorization: Bearer <token>` 挂在每个请求上（`src/utils/request.js:152-160`）；响应拦截器对 401 `clearAuth()` 并派发 `auth-expired` 自定义事件，对 403 且 `detail === '该账户已被禁用'` 同样清登录态并派发 `auth-expired`（`reason: 'disabled'`）（`src/utils/request.js:189-201`）。此外还有一个 `isAuthenticationRequest()` 辅助函数把 `/users/login`、`/users/register` 判为「认证类请求」（`:140-145`）。

### 5.5 错误处理与分页处理

- 错误处理是**唯一集中的**：`src/utils/error.js` 的 `getErrorMessage()` 要同时兼容三种后端形态——`detail` 是数组（FastAPI 校验错误）、字符串（业务错误）、对象；并带一个 TLS 错误的正则翻译。`getErrorCategory()` 把错误分为 `retryable` / `auth` / `permanent`。
- 重试逻辑内嵌在 `src/utils/request.js`：只对 `GET/HEAD/OPTIONS` 重试，退避 `[1000, 2000, 4000]`，最多 3 次，遇 `400/401/403` 或 `DATA_TEMPLATE_` 业务码前缀立即放弃。
- **没有统一分页**：前端直接透传 `skip`/`limit`，全仓 `skip: 0` 出现 49 次、`limit: 100` 24 次、`limit: 500` 20 次、`limit: 200` 15 次；各页面自己写 `res.data.total` / `res.data.items`。

---

## 6. 已接入能力 vs 未接入能力

下表按能力逐个核对旧项目源码。**「旧项目状态」列只描述旧项目实测情况；「新平台第一阶段（Phase 1，已交付）」一列统一为未接入**——第一阶段只交付了用户 / 组织 / 项目 / 模型配置 / 环境 / 通知 / 看板骨架，十个业务领域能力在新平台中都没有实现。

| 能力 | 旧项目实现证据 | 旧项目状态 | 新平台第一阶段 |
| --- | --- | --- | --- |
| AI 智能体 | `app/agent/`（graph、autonomy、specialists、chat、runs），76 个 `/agent/**` 路由，`app/agent/models/` 12 张表（另有 RAG 1 张，见 §3.3 / §3.6） | 已接入 | **未接入** |
| 用例生成 | `POST /agent/generate`、`/agent/generation-runs`（23 个路由）、`app/features/case_generation/`、6 张表 | 已接入 | **未接入** |
| API 执行 | `POST /agent/execute[+/stream]`、`app/agent/execution/executor*.py`、`execution_record` | 已接入 | **未接入** |
| UI 自动化 | `app/features/visual_automation/`（Playwright DOM locator，非视觉模型），`/agent/visual` 6 个路由 | 已接入 | **未接入** |
| 移动端控制 | `app/features/mobile_automation/`，9 张表，设备注册 / 预约 / 凭据 / 计划 / WebSocket | 已接入 | **未接入** |
| 数据工厂 | `app/features/data_factory/`，43 个 `/agent/data-factory/**` 路由，12 张表 | 已接入 | **未接入** |
| 慢 SQL 分析 | `app/features/slow_sql/`（MySQL 目标库 + EXPLAIN + 规则目录 + 可选 AI），25 个路由，3 张表 | 已接入 | **未接入** |
| SQL 日志采集 | `app/features/sql_log/`（SSH 采集 Linux MySQL 慢日志），20 个路由，5 张表 | 已接入 | **未接入** |
| JVM 诊断 | `app/features/jvm_monitoring/`（Prometheus + 深度诊断 Agent），24 个路由，4 张表 | 已接入 | **未接入** |
| 代码扫描 | `app/features/code_analysis/`（bandit/eslint/gitleaks/ruff/semgrep），18 个 `/code-analysis/**` 路由，7 张表 | 已接入 | **未接入** |
| 统一编排 | `app/agent/api/orchestration.py`（1900+ 行，LangGraph 工作流），`/agent/workflows` 9 个路由；`AGENT_WORKFLOW_ORCHESTRATION_ENABLED` 默认开、可按 `AGENT_WORKFLOW_PROJECT_IDS` 白名单 | 已接入（受 feature flag 控制） | **未接入** |
| 脚本云端执行 | `POST /agent/script-templates/**/execute` 固定返回 501「云端脚本执行暂未开放」 | **未接入** | 未接入 |
| 用例库 / 缺陷 / 套件 | `/testcases`、`/bugs`、`/suites` 共 29 个路由 | 已接入 | **未接入** |
| 测试可观测性 | `app/features/observability/`（trace/baseline/gate/flaky），20 个路由，6 张表 | 已接入 | **未接入** |
| 通知中心 | `/notifications` 18 个路由，3 张表，Jinja2 模板 + 加密渠道配置 | 已接入 | 第一阶段已交付（见新平台文档） |

> 结论：旧项目**没有「缺少功能」的问题**，问题在于这些能力共享同一套 `user.role` + `project_member` 的粗粒度授权，并且全部依赖 `environment.base_url`、`slow_sql_connection`、`prometheus_connection`、`code_repository`、`linux_host_connection` 这些「被测目标连接表」，而新平台第一阶段只重建了 `environment` 一张。

---

## 7. 配置与运行方式

### 7.1 `.env` 关键项（取自 `.env.example`，已脱敏）

| 分组 | 键 | 默认 / 说明 |
| --- | --- | --- |
| 必需 | `DATABASE_URL` | 无默认，缺失则 `RuntimeError`（`app/bootstrap/lifespan.py`）；只接受 `postgresql+` / `postgres` / `sqlite` 前缀 |
| 必需 | `SECRET_KEY` | 无默认，缺失即 `raise RuntimeError`（`app/shared/config.py` 末尾） |
| JWT | `ALGORITHM`=`HS256`、`ACCESS_TOKEN_EXPIRE_MINUTES`=480 | |
| 限流 | `AUTH_LOGIN_IP_LIMIT_PER_MINUTE`=60、`AUTH_LOGIN_USERNAME_LIMIT_PER_MINUTE`=10、`AUTH_REGISTER_IP_LIMIT_PER_HOUR`=10、`AUTH_TRUSTED_PROXY_CIDRS`="" | 只在受信任 CIDR 后解析 `X-Forwarded-For` |
| 连接池 | `DB_POOL_SIZE`=10、`DB_MAX_OVERFLOW`=20、`DB_POOL_TIMEOUT_SECONDS`=30、`DB_POOL_RECYCLE_SECONDS`=1800 | `pool_pre_ping=True` |
| CORS | `CORS_ORIGINS` | 默认 `http://localhost:5173`、`http://127.0.0.1:5173`、`http://localhost:8080`、`http://api.project.local:5173` |
| 部署形态 | `APP_PROCESS_ROLE` ∈ `{api, worker, combined, agent_runner}`，默认 `combined` | 决定 `lifespan` 里注册哪些 worker |
| 建表 | `AUTO_CREATE_SCHEMA`=false | 见 §7.2 |
| 出站安全 | `OUTBOUND_ALLOWED_HOSTS`、`OUTBOUND_ALLOWED_CIDRS`、`HTTP_CA_BUNDLE`、`ALLOW_AGENT_PRODUCTION_EXECUTION`=false | |
| 加密主密钥 | `MODEL_CONFIG_ENCRYPTION_KEY`、`NOTIFICATION_ENCRYPTION_KEYS` | 未设置时回退 `SECRET_KEY` 派生 |
| RAG | `RAG_EMBEDDING_DIMENSIONS`=384 | 必须与 `rag_document.embedding` 维度一致 |
| 代码扫描 | `CODE_SCAN_WORKSPACE_DIR`=`runtime/code_analysis/workspaces`、`CODE_SCAN_REPORT_DIR`、`CODE_SCAN_GIT_TIMEOUT_SECONDS`=180、`CODE_SCAN_MAX_FILES`=20000、`CODE_SCAN_MAX_FILE_BYTES`=5MB、`CODE_SCAN_GIT_SSL_VERIFY`=true、`CODE_SCAN_ALLOWED_GIT_HOSTS`="" | |
| 数据工厂 | `DATA_FACTORY_MAX_ROWS`=10000、`DATA_FACTORY_MAX_TEMPLATE_BYTES`=1MB、`DATA_FACTORY_DEFAULT_TTL_SECONDS`=7200、`DATA_FACTORY_MAX_TTL_SECONDS`=604800、`DATA_FACTORY_RUN_TIMEOUT_SECONDS`=1800 | |
| 慢 SQL / JVM | `SLOW_SQL_ENGINE_CACHE_SIZE`=32、`SLOW_SQL_RETENTION_DAYS`=15、`MYSQL_TLS_CA_BUNDLE`、`JVM_MONITORING_RETENTION_DAYS`=15、`OBSERVABILITY_ALLOWED_HOSTS`=`127.0.0.1,localhost,::1` | |
| 平台清理 | `PLATFORM_RETENTION_DAYS`=15、`PLATFORM_EXPIRY_WARNING_DAYS`=3 | |
| 可视化 | `VISUAL_BROWSER_NAME`=chromium、`VISUAL_BROWSER_HEADLESS`=true、`VISUAL_VIEWPORT_WIDTH/HEIGHT`=1440x900、`VISUAL_NAVIGATION_TIMEOUT_MS`=30000、`VISUAL_ACTION_TIMEOUT_MS`=10000、`VISUAL_LLM_HEURISTIC_FALLBACK`=true | |
| 遥测 | `OTEL_ENABLED`=false、`OTEL_SERVICE_NAME`=testpilot-backend、`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`="" | Langfuse 三组 key（API/UI/Mobile agent） |
| 模型 | `LLM_DEFAULT_MODEL_ID`、`LLM_DOMAIN_{1..3}_{ID,LABEL,BASE_URL,API_KEY,MODEL}`（兼容旧 `LLM_LOW/MEDIUM/HIGH` 前缀） | 仅用于**首次**播种 |
| 环境 | `ENV_DEV_URL`、`ENV_TEST_URL`、`ENV_STAGING_URL`、`ENV_PROD_URL` | 覆盖 `builtin_environments()` 的内置 dev/test/staging/prod 默认地址（默认分别是 `http://localhost:8888`、`http://test-api.example.com`、`http://staging-api.example.com`、空串），未进 Settings，直接 `os.getenv` 读取（`app/agent/config/environment.py:43-62`） |
| 产物目录 | `SCRIPT_ARTIFACT_DIR`=`runtime/api_scripts`、`REPORT_EXPORT_DIR`=`runtime/report_exports` | |
| 编排开关 | `AGENT_WORKFLOW_ORCHESTRATION_ENABLED`（环境变量，未进 Settings）、`AGENT_WORKFLOW_PROJECT_IDS` | `app/agent/api/orchestration.py:130-139` |

前端 `.env.development` 只有两项：`VITE_API_PROXY_TARGET`、`VITE_MOBILE_AGENT_WS_URL`。

### 7.2 建表方式：双轨

- 官方路径是 Alembic：`alembic upgrade head`（`test_project_back/README.md`、`快速启动.md`）。
- `AUTO_CREATE_SCHEMA` 默认为 **false**，此时 `app/bootstrap/lifespan.py:initialize_database()` 完全不建表。
- 设为 true 时执行 `Base.metadata.create_all(bind=engine)` + `sync_table_comments()` + 补建 pgvector `vector` 扩展和 HNSW 索引；并且只在 `model_configuration` 表**首次创建**时播种 3 条默认模型配置（`seed_default_model_configurations`）。
- `seed_builtin_environments()` 只要 `environment` 表存在就会在空表时补 `dev/test/staging/prod`（不依赖 `AUTO_CREATE_SCHEMA`）。
- 存在第三条事实路径：不少表只能通过 `_create_table_if_missing()` 出现（`migrations/versions/0015_data_factory_governance.py:186-203` 建 `project_member`、`data_factory_audit_event` 等），这是为兼容「先用 create_all 跑过、后补迁移」的历史库。

### 7.3 启动命令

```bash
# 后端（README.md / 快速启动.md）
createdb testproject
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8888
pytest                                     # tests/ 下 15 个测试用例文件 + tests/agent 等子目录

# 前端
corepack pnpm install
corepack pnpm dev                          # http://localhost:5173
VITE_API_PROXY_TARGET=http://127.0.0.1:8888 corepack pnpm dev
npm run test:unit / test:e2e / test:e2e:data-factory
```

端口：**后端 8888**（不是新平台的 8001），**前端 5173**。

### 7.4 速率限制

`app/shared/rate_limit.py` 是**进程内滑动窗口**：内存 `dict[str, deque[float]]` + `threading.Lock`，最多跟踪 5 万个 key，每 60 秒清扫一次。文件头注释自述「多 API worker 部署应在受信入口再做共享限额，此处只是每个进程的额外屏障」。只覆盖登录（IP + 用户名双维度）和注册（IP）。返回 429 并带 `Retry-After`。

### 7.5 CORS 与加密密钥来源

- CORS：`allow_origins=CORS_ORIGINS`（四个 localhost 类来源）、`allow_credentials=True`、`allow_methods=["*"]`、`allow_headers=["*"]`、`expose_headers=["X-Request-ID"]`（`app/bootstrap/application.py:30-37`）。
- JWT 密钥：`SECRET_KEY`，缺失直接 `raise RuntimeError("SECRET_KEY 环境变量未设置！")`，**没有开发环境兜底**。
- 模型 API Key 加密：`_fernet()` 取 `MODEL_CONFIG_ENCRYPTION_KEY` 或 `SECRET_KEY`，`sha256 → base64 → Fernet`（`app/features/model_configuration/application/service.py:17-22`）。
- 通知凭据加密：`EncryptedText` / `EncryptedConfig` TypeDecorator，`enc:v1:` 前缀，`MultiFernet` 支持 `NOTIFICATION_ENCRYPTION_KEYS` 多密钥轮换；无前缀的旧值按明文读回，靠启动时的 `backfill_notification_encryption()` 回填（`app/features/notifications/application/encrypted_fields.py`）。

### 7.6 请求上下文

`app/bootstrap/application.py:41-86` 的中间件：接受入站 `X-Request-ID`（须匹配 `[A-Za-z0-9._-]{8,128}`，否则生成 `uuid4().hex`）和 `X-Correlation-ID`，写入 `request.state` 与 `contextvars`，回写两个响应头，并记录带 `duration_ms` 的访问日志。这是旧项目里唯一真正「统一」的横切能力。

---

## 8. 已知问题与技术债

以下每条都给出代码位置。仅列有代码证据的问题。

### 8.1 契约层

1. **没有统一错误信封，也没有全局异常处理器。** 全仓 503 处 `raise HTTPException(detail="...")`，`grep -rn "exception_handler" app/` 结果为 0。错误码只在中途出现一次（501 脚本执行），其余全是自由中文文案。前端被迫在 `src/utils/error.js` 里同时兼容 `detail` 为数组 / 字符串 / 对象三种形态。
2. **状态码语义不统一。** 实测裸数字 `status_code=404` 出现 122 次、409 出现 107 次、422 出现 75 次、400 出现 67 次、403 出现 57 次，另有 `status.HTTP_*` 常量形式 404 出现 14 次、400 出现 9 次、409 出现 6 次、403 出现 4 次、422 出现 2 次，裸数字与常量并存。典型不一致：feature flag 关闭时返回 **404**「统一业务编排尚未开启」（`app/agent/api/orchestration.py:1359`），而脚本云端执行未开放返回 **501**（`app/features/script_generation/api/router.py:370-378`）；非级联删项目遇外键返回 **409**（`app/features/project/api/router.py:253-258`）。
3. **分页参数不统一。** 无 `page`/`page_size`/`keyword` 统一约定，全部是 `skip`/`limit`，且默认值与上限各接口自定：用户列表 `skip=0, limit=10, le=500`（`app/features/auth/api/router.py:106-107`）、模型配置 `skip=0, limit=50, le=200`（`app/features/model_configuration/api/router.py:92-93`）、接口清单 `skip=0, limit=200`（`app/agent/api/endpoints.py:31-32`，且这两个参数连 `Query(...)` 约束都没有）、编排运行 `skip=0, limit=20, le=100`（`app/agent/api/orchestration.py:1397-1398`）、缺陷列表又是另一组。响应体也各写各的（`{total, items}` / `{items}` / `{item}` / `{items, source}`），没有统一的 `{items, total, page, page_size}`。
4. **API 前缀命名无规则。** 同一批智能体能力分别挂在 `/agent/*`、`/code-analysis`、`/mobile-automation`、`/testcases`、`/bugs`、`/organizations`、`/notifications`、`/project`、`/suites` 之下（见 §1.3）；`data-factory` 的真实前缀是 `/agent/data-factory`，容易被误认为 `/data-factory`。
5. **健康检查路径与新平台不同。** 旧项目是 `GET /`、`GET /health`、`GET /ready`（均无需登录），不是新平台的 `/healthz` + `/api/v1/meta`。

### 8.2 权限与认证

6. **权限判定分散在 5 处以上。** `accessible_project()`（`app/features/project/application/access.py:104-124`）、`project_or_404 / project_write_or_403 / project_manage_or_403`（`app/agent/api/dependencies.py:9-40`）、`require_admin()`（`app/shared/deps.py:57-60`）、`require_organization_member / require_organization_admin / require_agent_grant / require_agent_run_grant`（`app/features/project/application/organization.py:48-93`），以及 router 内联判断（如 `app/features/project/api/router.py:318-320` 的 `if current_user.role != "admin" and project.owner_id != current_user.id`、`app/features/project/application/organization.py:38-42` 的 `if user.role != "admin"`）。
7. **平台管理员完全绕过组织/项目边界。** `is_admin()` 只看 `user.role == "admin"`；`accessible_project_ids()` 对 admin 直接 `return None` 表示「不需要额外过滤」（`app/features/project/application/access.py:139-143`，非 admin 分支 `:144-164` 才带上组织边界过滤）；`accessible_project` 里 admin 直接拿 `admin` 角色而跳过组织边界检查（第 2 步先于第 3 步短路，`access.py:72-79`）。
8. **读写权限口径不一致。** 环境列表 `GET /agent/environments` 任意登录用户可读，而 `POST`/`DELETE` 要求 `require_admin`（`app/agent/api/configuration.py:72-118`，读端点只依赖 `get_current_user`）。`environment.default_headers` 是自由 JSON，经 `environment_to_dict()` 原样返回（`app/features/environments/application/service.py:38-57`），可能包含被测系统的凭据，却对全员可见。（注：模型配置侧的正确路径是 `app/features/model_configuration/api/router.py`，不存在 `app/agent/model_configuration/` 这个目录。）
9. **`token_version` 撤销不完整。** 只在改密码和改 `role`/`is_active` 时 +1；**改用户名不会 +1**（`app/features/auth/api/router.py:206-207` 的条件只匹配 `("role", "is_active")`）。停用与撤销共用 403「该账户已被禁用」，过期与撤销共用 401「登录失效，请重新登录」，前端只能靠 `detail === '该账户已被禁用'` 这一条精确字符串区分两种语义（`src/utils/request.js:198-201`）。
10. **删除用户直接 `db.delete(user)`。** `app/features/auth/api/router.py:214-230` 没有做任何级联清理，也没有负责人交接。而 `migrations/versions/0001_schema_baseline_complete_schema_baseline.py` 里 `project.owner_id` 是 `nullable=False` 且外键**不带 ondelete 动作**，`linux_host_connection.created_by` 同样 NOT NULL。

   外键规模的实测口径（旧文档此前的「40 个外键列 / 0 个 ondelete」是错的）：`app/` 下 ORM 模型里有 **76 处** `ForeignKey("user.id", ...)` 声明，其中 60 处不带 ondelete、6 处 `ondelete="CASCADE"`、10 处 `ondelete="SET NULL"`、7 处只写了 `name=`；`migrations/versions/` 里对应 **69 个** `sa.ForeignKeyConstraint(..., ['user.id'], ...)` 块加 **10 处**行内 `sa.ForeignKey("user.id", ...)`，其中 **16 处**声明了 ondelete（6 处 CASCADE、10 处 SET NULL），ORM 与迁移在这点上是一致的。带 CASCADE 的并不只有 `organization_member`/`project_member`，还包括 `mobile_device_reservation.user_id`（0042）、`data_factory_notification.recipient_id`（0015）、`notification_config.user_id`、`notification_subscription.user_id` 等。

   所以结论要按「无 ondelete 的 60 处」来说：**删掉一个还担任项目负责人、或持有任意历史连接/运行记录的关联用户，会直接抛 `IntegrityError` → 500**（`project.owner_id`、`project_outbound_target.approved_by`、`project_member.created_by`、`linux_host_connection.created_by` 等全部是 NOT NULL 且无 ondelete）；带 `SET NULL` 的列（`suite_case.created_by`、`environment.created_by/updated_by` 等）不会报错但会把审计字段洗成空。
11. **速率限制只在单进程内生效。** `app/shared/rate_limit.py` 用内存 `deque` + `threading.Lock`，`combined` 角色下 API 与 worker 共进程，多副本部署时限额被按实例数放大（文件头注释已自述）。

### 8.3 迁移与数据模型

12. **迁移链与 ORM 的口径需要对齐。** 90 张 ORM 表 + 迁移链里 7 张 CI/CD 遗留表：`jenkins_connection`、`mobile_jenkins_build`、`pipeline`、`pipeline_run`、`pipeline_step_run`、`timed_task`、`webhook_config`。这 7 张在 `app/` 下没有任何 ORM 模型，其中 `timed_task` 是 `0001` 建表的一部分。**需要澄清**：`0031_remove_cicd_schema.py` 不是「只 drop 了一部分」——它的 `TABLES` 元组恰好就是这 7 张，`upgrade()` 会（在表存在时）把它们全部 drop 掉，`downgrade()` 是空操作。因此迁移到 head 的库并不存在「残留的 CI/CD 表」，而是干净的 90 张；真正的漂移是**ORM 模型已经提前退役、迁移链里还留着 50 个历史版本的建表/改表步骤**，新旧库必须走完整链条才能对齐。
13. **建表路径三轨并行。** Alembic（官方）、`AUTO_CREATE_SCHEMA=create_all`（本地临时库）、`_create_table_if_missing()`（0015 等历史库兼容）。`project_member` 只在 `0015_data_factory_governance.py` 的 `_create_table_if_missing` 中出现，`downgrade()` 里却直接 `op.drop_table("project_member")`——如果这张表从来不是这个迁移建的，回滚会失败。
14. **没有管理员初始化脚本，且留了一批指向不存在模块的测试。** `test_project_back/` 下确实没有 `scripts/` 目录，也没有 seed_admin 脚本。公开 `POST /users/register` 创建的账号 `role` 一律取列默认值 `"test"`（`app/features/auth/models.py`），而 `POST /users/` 的 `UserCreate` schema 里根本没有 `role` 字段（`app/features/auth/api/schemas.py:31-35`），`PUT /users/{user_id}` 又能改 role 但又要求 `require_admin`——**没有任何自举途径把用户提升为 admin**，只能手工改库。此外 `tests/scripts/` 下 4 个测试文件（`test_ai_test_gen_cli.py`、`test_ai_test_gen_context_builder.py`、`test_ai_test_gen_validator.py`、`test_ai_test_gen_reporting.py`）全部 `from scripts.ai_test_gen...` 导入，而 `scripts/` 目录已不存在，这 4 个测试是悬空导入，直接跑 `pytest` 会在这一步 collection 失败。
15. **模型配置与环境的播种条件不对称。** `seed_default_model_configurations()` 只在 `AUTO_CREATE_SCHEMA=true` 且 `model_configuration` 表是本次首次创建时执行（`app/bootstrap/lifespan.py`），空表但由迁移创建的库不会播种；而 `seed_builtin_environments()` 只要表存在且为空就播种。两处「空表」判定语义不同。

### 8.4 前后端一致性

16. **前端调用了 5 个后端不存在的接口。** `test_project_front/src/api/project.js` 里 `listProjectOutboundTargets`（L22）、`createProjectOutboundTarget`（L26）、`deleteProjectOutboundTarget`（L30）、`getProjectPeople`（L117）、`getProjectMemberCandidates`（L122）分别请求 `/project/{projectId}/outbound-targets`、`/project/people`、`/project/{projectId}/outbound-targets/{targetId}`、`/project/{projectId}/member-candidates`，而 `app/features/project/api/router.py` 只有 12 条路由，全部不含这些路径（`grep -rn "outbound-targets\|/people\|member-candidates" app/` 结果为 0）。`src/views/project/ProjectManagement.vue:70-89` 实际调用了出站目标三个接口，该功能区必然 404。
17. **README 与实现路径漂移。** `test_project_back/README.md` 的核心特色章节演示 `POST /agent/docs/parse`、`POST /agent/cases/generate`、`GET /agent/cases`、`PATCH /agent/cases/{case_id}`；实际路由是 `/agent/parse`（`app/agent/api/documents.py:37`）、`/agent/generate`（`app/agent/api/generation.py:39`）、`/agent/testcases`（`app/agent/api/testcases.py:32`）。文档会直接误导调用方。
18. **前端无类型、无契约。** Vue3 + 纯 JS，`jsconfig.json` 只做 `@` 别名；19 个 `src/api/*.js` 全是用字符串拼 URL，无 DTO 类型、无 OpenAPI codegen。`src/api/user.js`、`src/api/project.js` 末尾还留着一批 `export const register_user = registerUser` 这种「未迁移完的兼容别名」。
19. **分页与错误处理靠约定而非工具。** 49 处 `skip: 0` 硬编码，各页面自己拼 `{total, items}` 的读取逻辑；`getErrorMessage()` 要兼容三种 `detail` 形态，说明后端从未给出稳定错误结构。

### 8.5 运维与安全

20. **`SECRET_KEY` 单点故障。** 模型配置 API Key 加密主密钥 `MODEL_CONFIG_ENCRYPTION_KEY` 未设置时回退用 `SECRET_KEY` 派生（`app/features/model_configuration/application/service.py:17-22`）；通知加密在 `NOTIFICATION_ENCRYPTION_KEYS` 为空时同样回退 `SECRET_KEY`。一个 `SECRET_KEY` 泄露会同时失效 JWT、模型密钥与通知凭据，且模型侧没有多密钥/轮换能力（通知侧有 `MultiFernet`）。
21. **JWT 无刷新机制、有效期 8 小时且无提前刷新。** `ACCESS_TOKEN_EXPIRE_MINUTES=480`；前端 `isTokenExpired()` 把 5 分钟预警窗口当作「已过期」，但既不续期也不提示，只会让下一个请求失败。
22. **CORS 默认放行四个来源且 `allow_credentials=True`。** `CORS_ORIGINS` 默认含 `http://api.project.local:5173` 这种可被 DNS 指向任意机器的域名来源（`app/shared/config.py:32-37`）。
23. **`allowed_model_ids` / `default_headers` 等自由 JSON 无 schema 校验。** `organization_member.allowed_model_ids` 只校验 `max_length=30` 与「模型是否启用」（`app/features/project/api/organization.py:97-101`）；`environment.default_headers` 是任意 JSON，会随请求头透传到被测系统。
24. **`APP_PROCESS_ROLE=combined` 是默认值。** 单进程同时跑 API + 全部 worker + 调度器（`app/bootstrap/lifespan.py`），配置注释自己写明「运行多个 API 进程时应设为 api 角色，且只运行一个 worker」——默认值与推荐部署方式相反。

---

## 9. 附：统计口径

| 统计项 | 值 | 命令 |
| --- | --- | --- |
| 后端 `.py` 文件 | 492 | `find app -name '*.py' \| wc -l` |
| 后端总行数 | 约 80,045 | `find app -name '*.py' -exec cat {} + \| wc -l` |
| 路由装饰器 | 395 | `grep -rhoE '@[a-z_]+\.(get\|post\|put\|delete\|patch\|ws\|websocket)\(' app/ \| wc -l` |
| `raise HTTPException` | 503 | `grep -rhoE 'raise HTTPException' app/ \| wc -l` |
| `exception_handler` | 0 | `grep -rn 'exception_handler' app/` |
| ORM 表 | 90 | `grep -rh '__tablename__ = ' app/ \| wc -l` |
| 迁移文件 | 50（无 `__init__.py`，全部是版本文件） | `ls migrations/versions/*.py \| wc -l` |
| 指向 `user.id` 的外键 | ORM 侧 76 处 `ForeignKey("user.id", ...)`（60 处无 ondelete / 6 处 CASCADE / 10 处 SET NULL）；迁移侧 69 个 `sa.ForeignKeyConstraint` 块 + 10 处行内 `sa.ForeignKey`，共 16 处带 ondelete | `grep -rhF 'ForeignKey("user.id"' app/`、`grep -rhF 'sa.ForeignKey("user.id"' migrations/versions/` |
| 前端 `.vue`/`.js` 文件 | 188（约 55,454 行） | `find src \( -name '*.vue' -o -name '*.js' \)` |
| 前端 view | 73 | `find src/views -name '*.vue' \| wc -l` |
| 前端 API 模块 | 19 | `ls src/api/*.js` |
| 前端 composable | 16 | `ls src/composables/` |
| 前端独立组件 | 13 个 `.vue`（`src/components/` 下另有 2 个 `.js`） | `find src/components -name '*.vue'` |
| 后端测试文件 | `tests/` 17 个顶层 `.py`（含 `conftest.py`、`__init__.py`，即 15 个测试用例文件）+ `tests/agent/` 25 + `tests/scripts/` 4 + `tests/features/` 71（2 个顶层 + 20 个子目录 69 个），合计 118 个 `.py` | `find tests -name '*.py' \| wc -l` |
