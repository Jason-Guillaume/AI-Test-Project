# 目标架构设计（Target Architecture）

> **历史快照：** 本文记录第一阶段重构时的目标与实现状态，不是当前代码库的完整功能清单。当前 feature、迁移、路由与前端页面以源码为准；截至 2026-10-28 的全仓盘点见 [项目审计报告](audit/full-project-audit-report.md)。保留本文是为解释早期设计决策，文中“未接入”与数量不可直接用于判断当前实现。

> 本文描述**测试开发平台**重构后的目标架构，读者是接手**第二阶段**开发的工程师。
> 阅读后应能做到：不依赖原作者，独立新增一个业务模块（后端 feature + Alembic 迁移 + 前端页面）。
>
> **阶段状态**：第一阶段（Phase 1，已交付）。AI 智能体、用例生成、API 执行、UI 自动化、
> 移动端控制、数据工厂、慢 SQL 分析、JVM 诊断、代码扫描、统一编排 —— **全部未接入**。
> 本文任何地方出现这些词，都指「预留了位置」，不代表已经实现（见第 10 节清单）。
>
> 所有事实均取自仓库当前代码，关键结论后附代码路径。拿不准的地方以「待确认」标注，见文末。

---

## 目录

1. [技术选型与理由](#1-技术选型与理由)
2. [仓库结构](#2-仓库结构)
3. [前端结构](#3-前端结构)
4. [认证与授权](#4-认证与授权)
5. [API 规范](#5-api-规范)
6. [数据模型](#6-数据模型)
7. [数据库与配置](#7-数据库与配置)
8. [安全设计](#8-安全设计)
9. [可观测性与质量保障](#9-可观测性与质量保障)
10. [扩展点设计（第二阶段必读）](#10-扩展点设计第二阶段必读)
11. [待确认项](#11-待确认项)

---

## 1. 技术选型与理由

### 1.1 后端

| 依赖 | 版本约束 | 选型理由 |
|---|---|---|
| Python | `>= 3.11`（`backend/requirements.txt` 首行注释；当前 venv 为 3.14） | 用 `X \| None` 联合类型与 `from __future__ import annotations`，3.11 语法与标准库足够 |
| FastAPI | `fastapi==0.141.1` | 依赖注入（`Depends(get_db)` / `Depends(get_current_user)`）天然承载认证与事务边界；路由即契约，Pydantic `response_model` 直接产出 OpenAPI |
| Starlette | `starlette>=0.49,<0.51` | 锁定是为了 **FastAPI 0.141.1 只兼容 0.49/0.50 线**，防止 pip 拉到不兼容主线（`requirements.txt` 已写明） |
| SQLAlchemy | `sqlalchemy>=2.0,<2.1` | 2.0 风格的 `DeclarativeBase` / `sessionmaker` / `db.query()`，元数据可被 Alembic 直接生成迁移 |
| Alembic | `alembic==1.20.0` | 唯一改表入口（第 7 节） |
| psycopg | `psycopg[binary]>=3.3,<4` | PostgreSQL 16 官方驱动；连接串统一 `postgresql+psycopg://` |
| Pydantic | `pydantic>=2.10,<3` + `pydantic-settings>=2.9,<3` | v2 的 `Field(ge=, le=)` 让分页参数、密码长度在声明处即被约束，不落到 service 手写校验 |
| PyJWT | `PyJWT>=2.9,<3` | 无状态 JWT，`ver` 声明承载 token_version 撤销位 |
| bcrypt | `bcrypt>=4.2,<5` | **刻意不依赖 passlib**：passlib 1.7.4 在 bcrypt>=4.1 上读取 `__about__.__version__` 会告警且已停止维护（`app/shared/passwords.py` 头注）。改用 SHA256 预处理 + bcrypt，等价 passlib 的 `bcrypt_sha256`，避免 72 字节截断 |
| cryptography | `cryptography>=43,<51` | Fernet 对称加密模型 API Key |
| pytest / httpx | `pytest>=8.0,<10`、`httpx>=0.27,<1` | `fastapi.testclient.TestClient` 的 HTTP 后端 |

### 1.2 前端

| 依赖 | 版本 | 选型理由 |
|---|---|---|
| React / react-dom | `18.3.1` | `createRoot` + `StrictMode`；`<Outlet />` 嵌套路由 |
| TypeScript | `5.6.3` | `tsconfig.app.json` 开启 `strict`、`noUnusedLocals`、`noUnusedParameters`、`noFallthroughCasesInSwitch`；`npm run typecheck`（`tsc -b --noEmit`）是 CI 前置门槛 |
| Vite | `5.4.10` | 开发代理见 3.4 节（**不做 rewrite**，与旧项目相反） |
| antd | `5.21.6` | 表格/表单/选择器覆盖后台与看板两类页面 |
| @tanstack/react-query | `5.59.16` | 声明式缓存；作用域切换靠 `invalidateQueries`，不手动清缓存 |
| axios | `1.7.7` | 拦截器统一注入 Bearer 头与 401/403 处置 |
| react-router-dom | `6.26.2` | 嵌套路由 + `RequireAdmin`/`RequireAuth`/`GuestOnly` 三个守卫 |
| dayjs | `1.11.13` | `import 'dayjs/locale/zh-cn'` 统一中文日期 |

**运行时版本说明**：`frontend/package.json` 未声明 `engines`，仓库也没有 `.nvmrc`；
本地实测 Node `v24.21.0`。Vite 5 要求 Node >= 18，第二阶段的 CI 应显式钉住 Node 版本。

### 1.3 端口

| 进程 | 端口 | 依据 |
|---|---|---|
| 后端 uvicorn | **8001**（开发实际使用） | `frontend/vite.config.ts` 代理目标 `VITE_API_PROXY_TARGET \|\| 'http://127.0.0.1:8001'` |
| 前端 Vite | **5173** | `frontend/vite.config.ts` 的 `server.port` |
| PostgreSQL | 5432 | `compose.yaml` 端口映射 |

> 注意：`app/main.py` 的模块注释写的是 `--port 8000`，但本机 8000 已被其它进程占用，
> 实际开发用 8001。**以前端代理目标为准**。

---

## 2. 仓库结构

```
ai-test-project/
├── backend/
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   │       └── 0001_initial_schema.py        # 第一阶段唯一迁移
│   ├── alembic.ini                           # sqlalchemy.url 固定为占位，真值来自 DATABASE_URL
│   ├── app/
│   │   ├── main.py                           # 应用工厂 + /api/v1 前缀 + 中间件
│   │   ├── models/                           # ORM 表定义（9 张表）
│   │   │   ├── base.py / identity.py / project.py / configuration.py / notification.py
│   │   ├── shared/                           # 跨模块公共件
│   │   │   ├── auth.py / config.py / database.py / dependencies.py / errors.py
│   │   │   ├── notify.py / pagination.py / passwords.py / rate_limit.py
│   │   │   └── request_context.py / roles.py
│   │   ├── features/                         # 业务模块（见 2.2）
│   │   ├── bootstrap/routes.py               # 顶层路由装配（未被 main.py 引用，见 11 节）
│   │   └── scripts/seed_admin.py             # 仅创建管理员
│   ├── scripts/seed_admin.py                 # 建库 + 迁移 + 内置环境 + 管理员（完整 bootstrap）
│   ├── tests/                                # test_01 .. test_07，共 51 用例
│   ├── requirements.txt
│   ├── .env.example                          # 仅占位值，管理员凭据刻意留空
│   └── .env                                  # 本地真实配置，已 gitignore
├── frontend/
│   └── src/                                  # 见第 3 节
├── docs/
└── compose.yaml                              # 仅平台主库
```

### 2.1 `app/main.py` 做的事

按顺序：
1. `import app.models` —— 集中导入所有 ORM，保证 `Base.metadata` 完整（Alembic 生成迁移依赖这一点）。
2. `lifespan`：`configure_logging()` → 打印版本与去敏后的数据库地址 → **仅当 `AUTO_CREATE_SCHEMA=true`** 才 `Base.metadata.create_all()`。
3. `CORSMiddleware`：`allow_credentials=True`，`expose_headers=["X-Request-ID"]`。
4. 请求上下文中间件 `attach_request_context`：解析/生成 `X-Request-ID`，写入 `request.state`、日志上下文变量，并回写响应头。
5. `register_exception_handlers(application)`（见 4.4）。
6. 三个系统端点：`GET /healthz`（不碰数据库，容器存活探针）与 `GET /health` **不带版本前缀**；`GET /api/v1/meta` 带前缀但同样免登录。
7. 逐个 `include_router(..., prefix="/api/v1")`。

**为什么健康检查与 `/meta` 不加 `/api/v1`**：`/healthz` 是给容器编排用的，不要求带版本语义，也不应依赖数据库可达（`readiness` 语义交给 `/api/v1/dashboard/ready`）。

### 2.2 后端分层规则（新增模块必须遵守）

```
app/features/<module>/
├── __init__.py
├── router.py     # 只做：声明路由、参数与 Depends、把结果转成 response_model
├── service.py    # 只做：业务规则、鉴权判定、事务边界（add/commit/rollback）
└── schemas.py    # 只做：Pydantic 入参与响应模型、常量映射
```

**铁律：路由只做参数与依赖，业务与事务集中在 service。**
为什么：事务边界必须有唯一所有者。若路由直接 `db.commit()`，跨模块复用同一段写入逻辑时会出现
「一处提交一处不提交」的分叉；第一阶段已把 6 个模块的写入全部收进 service
（`app/features/*/service.py`），并且 service 之间只允许互相调用业务函数
（如 `users/service.py` 调 `organizations.service.ensure_personal_organization`），
**禁止** service 之间互相调用 `router.py`。

`app/shared/roles.py` 也是同理放置的：跨模块的角色判定集中在 shared，
避免 feature 之间为拿一个 `is_org_admin` 而互相导入 service 造成循环依赖。

已实现的模块：

| 目录 | 说明 |
|---|---|
| `features/users/` | `auth.py`（自助认证）+ `admin.py`（管理端）+ `service.py`（`UserAdminService`）+ `schemas.py` |
| `features/organizations/` | 组织与组织成员、模型授权 |
| `features/projects/` | 项目、项目成员、出站目标 |
| `features/model_configuration/` | 大模型连接配置（加密） |
| `features/environment_configuration/` | 被测环境路由配置 |
| `features/notifications/` | 通知收件箱（**只有** router + schemas，无 service：见 11 节） |
| `features/dashboard/` | 看板统计 |

### 2.3 `app/shared/` 各模块职责

| 文件 | 职责 | 关键导出 |
|---|---|---|
| `config.py` | pydantic-settings 全局配置 | `settings`、`runtime_secret_key()`、`runtime_model_config_key()`；`SECRET_KEY` 缺失时**导入期直接 `RuntimeError`** |
| `database.py` | engine / SessionLocal / `get_db()` | `engine`（`pool_pre_ping=True` + 连接池参数，仅当 URL 为 postgresql 前缀时生效）、`SessionLocal`（`autoflush=False, expire_on_commit=False`） |
| `auth.py` | JWT 签发与校验、当前用户依赖 | `create_access_token`、`invalidate_user_tokens`、`get_current_user`、`require_platform_admin` |
| `errors.py` | 错误码常量、状态码映射、异常处理器 | `AppError`、`unauthorized/forbidden/not_found/conflict/bad_request`、`register_exception_handlers` |
| `pagination.py` | 统一分页 | `DEFAULT_PAGE_SIZE=20`、`MAX_PAGE_SIZE=200`、`page_params`、`apply_page`、`apply_keyword`、`paginate` |
| `roles.py` | 三层角色常量与判定函数 | 见 4.5 |
| `passwords.py` | 密码哈希 | `hash_password`、`verify_password`（兼容本模块产物 / 旧 bcrypt_sha256 / 原始 bcrypt 三类） |
| `rate_limit.py` | 登录/注册进程内限流 | `enforce_auth_rate_limit`、`reset_rate_limits` |
| `notify.py` | 通知写入工具 | `notify()`、`EVENT_TITLES`、`EVENT_LABELS` |
| `request_context.py` | 请求 ID 与日志注入 | `resolve_request_id`、`request_id_context`、`configure_logging`、`RequestIdFilter` |
| `dependencies.py` | 跨模块依赖组合 | `DB`、`Current`（`Annotated[...]` 别名）、`require_platform_admin` |

**为什么 `dependencies.py` 里再放一份 `require_platform_admin`**：
`auth.py` 版本带 `Depends(get_current_user)`，自己把用户取出来并**返回 `User`**
（供 `actor: User = Depends(require_platform_admin)` 使用，`environment_configuration/router.py` 就是这么接的）。
`dependencies.py` 版本签名列的是 `require_platform_admin(user: User) -> None`，
`user` 是**普通参数**，不含 `Depends`，所以它不是自足的守卫 ——
必须靠同一路由里的另一个 `user: User = Depends(get_current_user)` 把参数喂进来。

> **现状提示（待确认，勿当模板照抄）**：`model_configuration/router.py` 虽然
> `from app.shared.dependencies import require_platform_admin`，但文件内**一次都没调用**，
> 实际是用 `is_platform_admin(actor)` 内联判定的（`actor` 仍来自 `Depends(get_current_user)`）。
> 也就是说「两个版本并存、按是否需要 actor 二选一」更像是预留而非已落地的用法；
> 目前仓库里真正被用作路由依赖的只有 `auth.py` 版本。若要精简，删掉 `dependencies.py` 里这份与
> `model_configuration/router.py` 的无用 import 即可。

---

## 3. 前端结构

### 3.1 目录

```
src/
├── main.tsx                     # ConfigProvider + React Query + App
├── App.tsx                      # 路由表（/admin/* 与 /console/*）
├── api/                         # 按模块封装请求
│   ├── client.ts                # axios 实例、token/user store、拦截器
│   ├── auth.ts  users.ts  organizations.ts  projects.ts
│   └── modelConfigs.ts  environments.ts  notifications.ts  dashboard.ts
├── components/
│   ├── QueryProvider.tsx        # antd ConfigProvider + QueryClientProvider
│   ├── RouteGuards.tsx          # RequireAuth / RequireAdmin / GuestOnly
│   ├── ResourceTable.tsx  PageState.tsx  ResultPages.tsx  RoleTag.tsx
├── hooks/
│   ├── useAuth.tsx              # AuthProvider / useAuth
│   ├── useConsoleScope.tsx      # ConsoleScopeProvider / useConsoleScope
│   └── useCapabilities.ts       # 前端按钮级能力判定（服务端为准）
├── layouts/
│   ├── AdminLayout.tsx          # 平台管理端布局
│   └── ConsoleLayout.tsx        # 控制台布局 + 组织/项目选择器
├── pages/
│   ├── auth/        Login.tsx  Register.tsx
│   ├── admin/       Dashboard Users Organizations Projects ModelConfigs Environments
│   └── console/     Workbench Projects ProjectDetail Notifications Profile
├── types/index.ts               # 全部接口类型集中定义
└── vite-env.d.ts
```

### 3.2 一个 React 应用，两个入口

`src/App.tsx` 的路由树：

```
/login  /register                GuestOnly
/admin/*                          RequireAdmin + AdminLayout
    dashboard users organizations projects model-configs environments
/console/*                        RequireAuth + ConsoleScopeProvider + ConsoleLayout
    (index=工作台) projects projects/:id notifications profile
/403  /404  *                    ForbiddenPage / NotFoundPage
```

`/` 由 `HomeRedirect` 按 `user.role === 'admin'` 决定跳 `/admin/dashboard` 还是 `/console`。

**关键：这两个入口是新设计，旧项目没有。** 旧项目前端是单一角色视角的 Vue3 应用；
重构后把「平台管理员视角」与「测试/开发用户视角」拆成两个布局与两套页面，但共用同一份：
- 登录态（`AuthProvider` 挂在 `BrowserRouter` 之内、`Routes` 之外，**两个入口共享**）
- 请求客户端（`src/api/client.ts` 单例 axios 实例）
- 基础组件与类型（`src/components/*`、`src/types/index.ts`）

`ConsoleScopeProvider` **只**挂在 `/console` 分支下 —— 为什么：组织/项目选择器是控制台概念，
平台管理端是全局视角，把它提到全局会污染管理端的缓存 key。

### 3.3 请求客户端（`src/api/client.ts`）

- `baseURL = '/api/v1'`，与后端 `API_PREFIX` 对齐。
- 令牌存 `localStorage['access_token']`（JSON 包装），用户信息存 `localStorage['user']`。
- 请求拦截器注入 `Authorization: Bearer <token>`。
- 响应拦截器：`401` 或 `403 且 message === '该账户已被禁用'` → 清本地态 + 触发 `onAuthExpired`
  （由 `AuthProvider` 通过 `registerAuthExpiredHandler` 注入，避免 client 反向依赖 router）。

**为什么账户被禁用也要清登录态**：后端对禁用账户返回 403「该账户已被禁用」（令牌本身仍有效），
前端必须区分「令牌过期」和「被停用」两种用户可感知情形，否则会显示不可操作的会话。

- `extractErrorBody` 读取统一错误信封 `{code, message, request_id}`，
  缺失时兜底成 `{code: 'ERR_HTTP', message, request_id: ''}`。

### 3.4 Vite 代理（迁移时必须知道）

`frontend/vite.config.ts`：

```ts
proxy: {
  '/api': {
    target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8001',
    changeOrigin: true,
  },
}
```

**故意不配置 `rewrite`**，`/api/v1/*` 原样转发到后端。
旧项目 `test_project_front/vite.config.js:26` 有
`rewrite: (path) => path.replace(/^\/api/, '')`（剥离前缀后转发），
新后端把业务路由整体挂在 `/api/v1` 下，若沿用剥离写法会导致前后端前缀错位、全部 404。
**做旧前端迁移或加新代理规则时，不要加回 rewrite。**

### 3.5 数据获取与作用域

- 所有列表请求走 `@tanstack/react-query`，缓存 key 约定：
  组织级 `['projects']`、项目级 `['project', id, ...]`、看板 `['dashboard']`、通知 `['notifications']`。
- `ConsoleScopeProvider` 切换组织时 `invalidateQueries(['projects'])` + `['dashboard']`；
  切换项目时 `['project']` + `['notifications']`。
  **为什么**：作用域通过 query 参数传给后端（不靠请求头），若不失效缓存会显示上一个项目的数据。
- 后端绝大多数列表接口都返回 `{items, total, page, page_size}` 信封，前端 `Paginated<T>` 泛型直接复用。
  **已知例外**：`GET /dashboard/projects`（`ProjectSummaryResponse`）只有 `items` 与 `total`，见 5.2 的例外说明。

### 3.6 路由守卫（`src/components/RouteGuards.tsx`）

| 守卫 | 行为 | 用途 |
|---|---|---|
| `RequireAuth` | 未就绪转 loading；无用户 → `/login?redirect=<encoded>` | `/console/*` |
| `RequireAdmin` | 无用户 → `/login`；非 admin → `/403` | `/admin/*` |
| `GuestOnly` | 已登录 → 按角色跳 `/admin/dashboard` 或 `/console` | `/login`、`/register` |

`RequireAuth` 对 `redirect` 做了白名单收敛：只接受以单个 `/` 开头且不以 `//` 开头的路径，
否则回退 `/console` —— 防止开放重定向。

### 3.7 `useCapabilities` 只是 UI 提示

`src/hooks/useCapabilities.ts` 复制了后端 `PROJECT_ROLE_RANKS`（viewer 0 < member 1 < editor 2 < owner 3 < admin 4）
与 `ORG_ROLE_LABELS`，**只用于按钮显隐**，文件头明确写了「服务端鉴权为准」。
为什么保留这份副本：权限判定如果只在后端，用户点了按钮才被 403，体验差；
副本必须与 `app/shared/roles.py` 同步维护，改角色时两边都要改。

---

## 4. 认证与授权

### 4.1 JWT 声明

`app/shared/auth.py::create_access_token`：

| 声明 | 含义 |
|---|---|
| `sub` | 用户 ID 的**字符串形式** |
| `exp` | `now(UTC) + ACCESS_TOKEN_EXPIRE_MINUTES`（默认 480 分钟 = 8 小时） |
| `ver` | `int(user.token_version)`，撤销位 |

- 算法固定 `HS256`，签名密钥取 `settings.SECRET_KEY`。
- 校验必须显式 `jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])`。
  **为什么**：不传 `algorithms` 会让 PyJWT 根据 header 自决算法，存在算法混淆风险。
- `tokenUrl="/api/v1/login"` 与实际挂载点一致（`OAuth2PasswordBearer`），Swagger 登录按钮才能直接用。

### 4.2 token_version 撤销链

`invalidate_user_tokens` 只做 `user.token_version += 1`。会触发递增的动作：

| 触发点 | 代码位置 |
|---|---|
| 修改密码 | `users/service.py::change_password` |
| 管理员停用/启用账户（`is_active` 变化） | `users/service.py::update_user` |
| 平台角色变化（`role` 变化） | 同上 |
| 用户名变化 | 同上 |

`invalidate_user_tokens` 在代码里**只有上述两处调用**。用户被删除后旧令牌同样立即失效，
但机制不同：`db.delete(user)` 之后 `get_current_user` 里 `db.get(User, sub)` 返回 `None`，
走的是 401「用户不存在」分支而非 `ver` 不匹配分支。
（`shared/auth.py::invalidate_user_tokens` 的文档字符串把「被管理员移除」也列为递增场景，
实现上并不如此 —— 见 11 节。）

`get_current_user` 的判定顺序（**顺序即语义**）：

1. JWT 解码失败 / `sub` 无法转 int → **401**（签名错、过期、篡改、缺 `Authorization` 头、非 Bearer 前缀都归到这里）。
2. `db.get(User, user_id)` 为 `None` → **401**。为什么不区分「用户不存在」与「令牌撤销」：不让攻击者用差异反推某个 `sub` 是否存在过。
3. `user.is_active` 为 `False` → **403「该账户已被禁用」**。令牌本身有效，只是账户不可用，前端据此区分「请重新登录」与「联系管理员」。
4. `ver` 与 `token_version` 不一致 → **401**。

### 4.3 状态码语义（跨模块统一，前端依赖这套文案）

| 状态码 | 语义 | 文案 |
|---|---|---|
| 401 | 登录失效（过期 / 被撤销 / sub 指向已删除用户 / 缺少或非法 `Authorization` 头） | **「登录失效，请重新登录」**（统一文案） |
| 403 | 令牌有效但权限不足；账户被禁用 | 「该账户已被禁用」/ 各接口自定义（如「需要组织管理员权限」） |
| 404 | 资源不存在，**或当前用户无权知道它存在**（隐藏存在性） | 「资源不存在」/「组织不存在或无权访问」 |
| 409 | 资源冲突（唯一约束） | 如「用户名已存在」 |
| 400 | 业务校验失败 | 如「旧密码错误」「启用模型前必须填写 API Key」 |
| 422 | 请求体/查询参数校验失败（Pydantic） | 字段级信息拼接文案 |
| 429 | 登录/注册速率超限 | 「请求过于频繁，请稍后再试」 |
| 500 | 兜底未处理异常 | 「服务器内部错误」 |

**401 的归一化处理**：`http_exception_handler` 把所有 401 的 `detail` 强制改写成 `AUTH_REQUIRED_MESSAGE`，
包括 `OAuth2PasswordBearer` 自己抛的英文 `Not authenticated`。
**为什么**：401 的响应体是认证边界，任何差异都会变成账号/令牌存在性的侧信道。

**一个反直觉的点**：登录失败（用户名不存在或密码错误）返回 **400**，不是 401 ——
见 `users/service.py::authenticate`，两种失败合并成同一条 `bad_request("用户名或密码错误")`。
**为什么**：未认证阶段不存在「令牌失效」语义，且必须在响应上无法区分「账号不存在」与「密码错误」
（账号枚举防护，见第 8 节「账号枚举防护」一行）。

**404 隐藏存在性用在这些地方**：
- 组织侧：非成员访问组织详情、改名、成员表、候选用户、成员增删、模型分配、负责人转移时一律 404。
  机制是 `organizations/service.py::require_organization_admin` **内部先调** `require_organization_member`
  （非成员在这里就拿到 404），成员但不是 admin 才继续走到 403；
  只读成员表 `GET /{id}/members` 直接走 `require_organization_member`，对成员本身不判管理权限。
  （**没有**「自行加入组织」这类接口，第一阶段不存在该端点。）
- 项目侧：`projects/service.py::get_accessible_or_404` —— 不可见项目按 404 返回。
- 通知侧：`notifications/router.py::_owned_or_404` 与 `_visible_in_scope`。

**注意这里返回的是 403 而不是 404**（资源对调用者可见，只是权限不够）：
- 跨组织加成员：成员必须是项目所属组织的成员，否则 403「成员必须是项目所属组织的成员」；
  平台管理员也不能绕过 —— 见
  `test_05_isolation.py::test_cross_org_member_addition_is_forbidden_even_for_platform_admin`。
- 项目内成员关系与负责人变更：`projects/service.py::upsert_member` / `remove_member` /
  `transfer_owner` / `delete_project` 权限不足一律 403。

### 4.4 统一错误信封

`app/shared/errors.py`：

```json
{"code": "ERR_NOT_FOUND", "message": "资源不存在", "request_id": "0f3a…"}
```

- `code` 缺省按 `DEFAULT_CODE_BY_STATUS` 从状态码映射；映射之外的状态码兜底 `ERR_INTERNAL`。
- `request_id` 来自 `request.state.request_id`（中间件写入），同时出现在响应头 `X-Request-ID`。
- 401 响应额外带 `WWW-Authenticate: Bearer`。
- `AppError` 是业务层可携带 `(message, status_code, code)` 的统一异常，有独立的 exception handler。
- `RequestValidationError` 走 422 + `ERR_VALIDATION`，`detail` 中的 list/dict 由 `_detail_to_message` 拍平成可读文案。

### 4.5 三层角色模型

**三层不可合并成一个全局 role 字段**，各层存储与判定位置不同：

| 层 | 取值 | 存储 | 虚拟角色 | 判定入口 |
|---|---|---|---|---|
| 平台 | `admin` / `test` / `dev`（默认 `test`） | `user.role` | —— | `is_platform_admin(user)`、`can_access_admin(user)` |
| 组织 | `owner` / `admin` / `member` | `organization.owner_id` + `organization_member.role` | `platform_admin`（虚拟，由平台管理员推导，不落库） | `organization_role`、`is_org_admin`、`is_org_owner`、`can_manage_org` |
| 项目 | `viewer` / `member` / `editor` | `project.owner_id` + `project_member.role` | `owner`、`admin`（虚拟） | `project_role_for`、`has_project_role`、`accessible_project_ids` |

项目角色等级 `PROJECT_ROLE_RANKS`：`viewer 0 < member 1 < editor 2 < owner 3 < admin 4`，
`has_project_role` 用 `>=` 比较，因此 `owner` 天然拥有 `editor` 能力。
`normalize_project_role` 把未知值**降级为 `viewer`**（不是按字面放行）—— 防止脏数据越权。

平台管理员穿透所有层：`project_role_for` 对 admin 直接返回虚拟角色 `admin`，
`accessible_organization_ids` / `accessible_project_ids` 对 admin 返回 `None` 表示「不过滤」。

**关键函数一览**：

| 函数 | 位置 | 作用 |
|---|---|---|
| `require_platform_admin` | `shared/auth.py`（自取 `actor` 并返回 User，**实际在用的只有这一份**）/ `shared/dependencies.py`（需外部传入 `user`，非自足守卫） | 路由级平台管理员守卫 |
| `require_organization_member` | `organizations/service.py` | 非成员 → 404 |
| `require_organization_admin` | `organizations/service.py` | 非 owner/admin/platform_admin → 403 |
| `project_role_for(db, project, user)` | `shared/roles.py` | 返回项目内有效角色或 `None` |
| `has_project_role(role, required)` | `shared/roles.py` | 等级判定 |
| `accessible_organization_ids` | `shared/roles.py` | 可见组织集合 |
| `accessible_project_ids` | `shared/roles.py` | 可见项目集合（组织边界 + 项目内身份） |

### 4.6 组织边界优先于项目成员关系

`shared/roles.py::project_role_for` 的判定顺序：

```python
if is_platform_admin(user):                      return PROJECT_ROLE_ADMIN   # 平台穿透
if project.organization_id and not is_organization_member(...):  return None # ← 组织边界前置
if project.owner_id == user.id:                  return PROJECT_ROLE_OWNER
if org_role in {owner, admin}:                   return PROJECT_ROLE_OWNER  # 组织管理员视同项目 owner
row = project_member 表里查 (project_id, user_id)
if row is None:                                  return None                 # 无成员行 = 不可见
return normalize_project_role(row.role)         # 脏数据降级 viewer，不按字面放行
```

> 注意 `is_organization_member` 与旧项目 `accessible_project` 的口径有一处**有意差异**：
> 新实现把「`organization.owner_id == user.id`」**也算作组织成员**（走 `organization_role`），
> 旧实现只查 `organization_member` 表。因此若历史库里存在「owner 没有对应成员行」的数据，
> 旧项目会判不可见、新项目会判可见。当前写入路径（`ensure_personal_organization` /
> `create_organization` / `upsert_member`）都会同时建成员行，所以正常数据下两者一致；
> 迁移旧库数据时值得抽查这一点。

**为什么组织边界必须是第一道闸门**：
1. 历史数据里可能残留跨组织的 `project_member` 行（组织归属变更、项目迁移后未清理）。
   若先查项目成员表，这些残留行会直接授权。
2. 该口径与旧项目 `accessible_project` 的前置校验一致，是刻意对齐而非新发明。
3. `test_05_isolation.py::test_leftover_cross_org_member_row_stays_invisible` 专门回归了这一点。

`accessible_project_ids` 是两个条件的**叠加**：

```
组织边界：project.organization_id 为 NULL  或  ∈ 用户所在组织
项目内身份：project.owner_id == 用户  或  有 project_member 行  或  是所属组织的 owner/admin
```

**结果**：组织里的普通成员**只看到被分配或自己负责的项目**，不会因为「在同一个组织」就
看到组织内全部项目；组织 owner/admin 能看到本组织全部项目。

---

## 5. API 规范

### 5.1 前缀与命名

- 所有业务接口挂在 **`/api/v1`**（`app/main.py::API_PREFIX`）。
- `/healthz`、`/health` 不带前缀（容器探针）；`/api/v1/meta`、`/api/v1/openapi.json` 免登录。
- **字段命名统一 `snake_case`**（`page_size`、`is_active`、`owner_id`），与数据库列名一致，避免一层映射。
- **分页参数统一 `page` / `page_size`**，不用旧项目的 `skip` / `limit`。
- 环境相关接口用**环境名**（`/environments/{name}`）而非自增 ID —— 执行链路按名称选择环境，路径与语义一致。
- 成员授权是**幂等 upsert，固定返回 200**（组织成员 `PUT /organizations/{id}/members/{member_id}`、
  项目成员 `PUT /projects/{id}/members/{member_id}`）。为什么固定 200：
  前端表单在「新增」和「编辑」之间共用同一个提交动作，若按 201/200 区分会让前端承担存在性判断。

### 5.2 统一分页契约

`app/shared/pagination.py`：

| 请求参数 | 约束 | 默认 |
|---|---|---|
| `page` | `ge=1` | `1` |
| `page_size` | `ge=1, le=200` | `20` |
| `keyword` | 自由文本 | `None` |

响应信封：

```json
{"items": [...], "total": 132, "page": 1, "page_size": 20}
```

- `apply_keyword` 用 `ilike('%keyword%')` 对指定列做不区分大小写模糊匹配。
- 用户/项目列表额外支持 `is_active`、`organization_id` 过滤。
- 通知列表在信封上多一个 `unread_total` 字段（角标用）。

**已知的两条分页执行路径**（第二阶段可收敛）：一部分路由直接复用
`shared.pagination.apply_page`，另一部分（`dashboard.project_summaries`、`notifications.list_notifications`、
`projects.router`、`model_configuration.router`、`environment_configuration` 列表）在函数内联 `offset/limit` 或切片。
**新增模块请优先用 `apply_page` / `paginate`**。

> **例外（信封并不完全一致）**：`GET /dashboard/projects` 走
> `dashboard.service.project_summaries`，响应模型 `ProjectSummaryResponse` 只有
> `{"items", "total"}` —— **没有 `page` / `page_size` 字段**（`page`、`page_size` 仍作为查询参数生效）。
> 前端 `src/pages/console/Workbench.tsx` 只取前 5 条（`page_size=5`）且不做翻页，因此没暴露这个缺口。
> 新增看板类列表时要么补齐两个字段，要么显式说明「不翻页」，别默认复用 `Paginated<T>` 泛型。

少数「天然小集合」的列表不走分页：`GET /organizations`、`GET /me/organizations`、
`GET /{org}/members` 返回全量并以 `page=1, page_size=max(len,1)` 填空信封。
**为什么**：组织数与单组织成员数是平台管理规模，不构成分页成本，保持前端不用翻页。

### 5.3 路由清单

> 全部前缀 `/api/v1`。「鉴权」列：`登录` = `Depends(get_current_user)`；`管理员` = 平台管理员；`公开` = 无依赖。

**系统（无前缀）**

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/healthz` | 公开 | 存活探针，不访问数据库 |
| GET | `/health` | 公开 | 进程健康检查 |
| GET | `/api/v1/meta` | 公开 | 应用元信息 |
| GET | `/api/v1/openapi.json` | 公开 | Swagger |
| GET | `/docs`、`/redoc` | 公开 | 文档页 |

**认证（`features/users/auth.py`，无子前缀）**

| 方法 | 路径 | 鉴权 | 响应 | 说明 |
|---|---|---|---|---|
| POST | `/register` | 公开 + 注册限流 | 201 | 创建账号并自动建个人组织 |
| POST | `/login` | 公开 + 登录限流 | 200 | 返回 `{access_token, token_type, expires_in, user}` |
| GET | `/me` | 登录 | 200 | 当前用户 |
| PATCH | `/me` | 登录 | 200 | 改密码（`old_password` 6–30，`new_password` 12–100） |
| GET | `/me/organizations` | 登录 | 信封 | 可见组织 + 各自有效角色 |
| POST | `/logout` | 登录 | 204 | 服务端无会话，仅提示前端清本地令牌 |

**用户管理（`features/users/admin.py`）**

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| POST | `/users` | 管理员 | 创建账号，同事务建个人组织 |
| GET | `/users` | 管理员 | `page` / `page_size` / `keyword` / `is_active` |
| GET | `/users/{user_id}` | 管理员**或本人** | 非管理员只能查自己 |
| PATCH | `/users/{user_id}` | 管理员**或本人** | 角色/状态仅管理员可改 |
| DELETE | `/users/{user_id}` | 管理员 | 不能删自己、不能删管理员；含负责人交接 |

**组织（`features/organizations/router.py`）**

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/organizations` | 登录 | 仅可见组织（平台管理员为全部） |
| POST | `/organizations` | 登录 | 创建者自动成为 owner |
| PATCH | `/organizations/{id}` | 组织 admin | 改名；非成员 → 404 |
| GET | `/organizations/{id}/members` | 组织成员 | 成员表；非成员 → 404 |
| GET | `/organizations/{id}/candidates?username=` | 组织 admin | 按用户名查可加入用户 |
| GET | `/organizations/{id}/models` | 组织 admin | 可分配的启用模型 |
| PUT | `/organizations/{id}/members/{member_id}` | 组织 admin | **幂等 upsert，固定 200**；带 `agent_enabled` / `allowed_model_ids`（后者仅在 `agent_enabled=true` 时落库并校验「必须存在且启用」，否则被丢弃为空数组）；把负责人降级为 member 之外的角色 → 403「组织负责人至少需要组织管理员角色」 |
| DELETE | `/organizations/{id}/members/{member_id}` | 组织 admin | 负责人不可移除（403）；该成员仍负责组织内项目时也不可移除（403，需先转移项目） |
| POST | `/organizations/{id}/members/{member_id}/upgrade` | 组织 admin | 转移组织负责人 |

**项目（`features/projects/router.py`）**

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/projects` | 登录 | `page` / `page_size` / `keyword` / `organization_id` |
| POST | `/projects` | 登录 | 创建者自动成为负责人 |
| GET | `/projects/{id}` | 项目 viewer+ | 详情，含成员列表 |
| PATCH | `/projects/{id}` | 项目 editor+ | 改 `name`/`description` 任意 editor；改 `organization_id` 时要求操作人是**目标组织**的 owner/admin（否则 403「只能把项目转移到自己管理的组织」）；改 `owner_id` 时要求**新负责人**已是项目所属组织成员（否则 403「新负责人必须是项目所属组织的成员」），并不要求操作人本身是组织 admin |
| DELETE | `/projects/{id}` | 项目 owner+ | |
| POST | `/projects/{id}/owner` | 项目 owner+ | 转移负责人 |
| GET | `/projects/{id}/members` | 项目 viewer+ | 分页 |
| PUT | `/projects/{id}/members/{member_id}` | 项目 editor+ | **幂等 upsert，固定 200**；路径 `member_id` 与请求体 `user_id` 不一致 → 404；把负责人加为成员 → 400「项目负责人不需要单独添加为成员」 |
| PATCH | `/projects/{id}/members/{member_id}` | 项目 editor+ | 改角色（内部复用 upsert） |
| DELETE | `/projects/{id}/members/{member_id}` | 项目 editor+ | 负责人不可移除（**400**，非 403）；成员行不存在 → 404 |
| GET | `/projects/{id}/targets` | 项目 viewer+ | 出站目标列表 |
| POST | `/projects/{id}/targets` | 项目 editor+ | 生产目标强制 https |
| PATCH | `/projects/{id}/targets/{target_id}` | 项目 editor+ | 仅切换 `enabled` |
| DELETE | `/projects/{id}/targets/{target_id}` | 项目 editor+ | |

**模型配置（`features/model_configuration/router.py`）**

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/model-configs/providers` | **公开（未声明依赖）** | 静态供应商目录 |
| GET | `/model-configs` | 管理员 | `page` / `page_size` / `keyword` / `is_enabled` |
| POST | `/model-configs` | 管理员 | `api_key` 只写入不落响应 |
| GET | `/model-configs/{config_id}` | 管理员 | 只回 `has_api_key` + `masked_api_key` |
| PATCH | `/model-configs/{config_id}` | 管理员 | `api_key` 不传 = 保留原密钥 |
| POST | `/model-configs/{config_id}/set-default` | 管理员 | 停用模型不可设默认 |
| DELETE | `/model-configs/{config_id}` | 管理员 | 默认模型不可删 |

> 模块文档字符串声明「全部接口仅平台管理员可用」，但 `/providers` 实际未挂 `Depends`，是免登录的静态目录（只含常量文案，无敏感数据）。若第二阶段要收紧，把它挂上 `get_current_user` 即可。

**环境配置（`features/environment_configuration/router.py`）**

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/environments` | 管理员 | `include_inactive` 默认 `false`；表为空时回退内置环境 |
| POST | `/environments` | 管理员 | |
| GET | `/environments/{name}` | 管理员 | 按名称查 |
| PATCH | `/environments/{name}` | 管理员 | 名称不可修改 |
| POST | `/environments/{name}/set-default` | 管理员 | 停用环境不可设默认 |
| DELETE | `/environments/{name}` | 管理员 | 默认环境不可删 |

**为什么环境读写都只给管理员**：`environment.base_url` 决定测试流量真正打到哪台服务器，
`default_headers` 可能含凭据。第二阶段若控制台需要环境选择器，应**新增一个只回名称与显示名的只读接口**，
而不是放开本组接口（该做法已写在 `environment_configuration/router.py` 文件头）。

**通知（`features/notifications/router.py`）**

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/notifications` | 登录 | `page` / `page_size` / `event_type` / `is_read` / `organization_id` / `project_id`；信封含 `unread_total` |
| GET | `/notifications/summary` | 登录 | 角标用总数/未读数 |
| GET | `/notifications/events` | 登录 | 事件类型目录（中文文案） |
| POST | `/notifications/{notification_id}/read` | 登录 | 仅自己的通知 |
| POST | `/notifications/read-all` | 登录 | 不传 `ids` 即全部 |
| DELETE | `/notifications/{notification_id}` | 登录 | |

> 固定子路径（`/summary`、`/events`、`/read-all`）必须声明在带路径参数的路由之前，
> 否则 FastAPI 按声明顺序匹配会被参数路由抢先（`app/bootstrap/routes.py` 文件头也记了这条规则）。

**看板（`features/dashboard/router.py`）**

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| GET | `/dashboard/overview` | 登录 | 个人总览，含 `scope` 说明统计口径 |
| GET | `/dashboard/projects` | 登录 | 可见项目概况（分页） |
| GET | `/dashboard/ready` | 登录 | 依赖就绪检查（降级语义见 10.3） |
| GET | `/dashboard/platform` | **管理员** | 平台级统计 |

### 5.4 错误码表

| 错误码 | 状态码 | 含义 | 备注 |
|---|---|---|---|
| `ERR_BAD_REQUEST` | 400 | 业务校验失败 | 含「用户名或密码错误」 |
| `ERR_TOKEN_EXPIRED` | 401 | 登录失效 | **统一文案**「登录失效，请重新登录」，含过期/撤销/sub 已删除/缺头 |
| `ERR_FORBIDDEN` | 403 | 权限不足 / 账户被禁用 | 文案因接口而异，前端需按文案分支处理「该账户已被禁用」 |
| `ERR_NOT_FOUND` | 404 | 不存在或无权知道存在 | 隐藏存在性 |
| `ERR_CONFLICT` | 409 | 唯一约束冲突 | 用户名/项目名/环境名/出站目标重复 |
| `ERR_VALIDATION` | 422 | 请求参数校验失败 | Pydantic，字段级信息已拍平成可读文案 |
| `ERR_RATE_LIMITED` | 429 | 登录/注册限流 | 文案「请求过于频繁，请稍后再试」 |
| `ERR_INTERNAL` | 500 | 未处理异常兜底 | 映射表外状态码也落到这里 |

**两个已声明但未被任何响应使用的常量**：`CODE_USER_NOT_FOUND = "ERR_USER_NOT_FOUND"` 与
`CODE_ACCOUNT_DISABLED = "ERR_ACCOUNT_DISABLED"`（`errors.py` 第 24–25 行）。
它们不在 `DEFAULT_CODE_BY_STATUS` 中，也没有任何调用方显式传入，因此：
- 查不到用户实际返回的是 `ERR_NOT_FOUND`；
- 账户被停用实际返回的是 `ERR_FORBIDDEN` + 文案「该账户已被禁用」（前端正是靠**文案**而非错误码判断的）。

第二阶段若要区分这两种情形，要么给这两个常量接上调用方，要么在前端继续以文案分支 —— 目前是后者。

---

## 6. 数据模型

### 6.1 九张表（+ `alembic_version`）

| 表 | ORM | 关键字段 |
|---|---|---|
| `user` | `models/identity.py::User` | `id`、`username`(unique, **nullable**)、`hashed_password`、`role`(默认 `test`)、`is_active`(默认 `true`)、`token_version`(默认 0)、`created_at`、`updated_at` |
| `organization` | `Organization` | `id`、`name`、`owner_id` → `user.id` (**NOT NULL，无级联**)、`created_at`、`updated_at` |
| `organization_member` | `OrganizationMember` | `organization_id`(CASCADE)、`user_id`(CASCADE)、`role`(默认 `member`)、`agent_enabled`(默认 `false`)、`allowed_model_ids`(JSON, 默认 `[]`)；唯一键 `(organization_id, user_id)` |
| `project` | `models/project.py::Project` | `id`、`name`(**全局唯一**，非组织内唯一)、`description`、`owner_id` → `user.id` (**NOT NULL，无级联**)、`organization_id`(可空，**无级联**) |
| `project_member` | `ProjectMember` | `project_id`(CASCADE)、`user_id`(CASCADE)、`role`(默认 `member`)、`created_by` → `user.id` (**NOT NULL，无级联**)；唯一键 `(project_id, user_id)` |
| `project_outbound_target` | `ProjectOutboundTarget` | `project_id`(CASCADE)、`scheme`、`host`、`port`、`is_production`、`enabled`、`approved_by` → `user.id` (**NOT NULL，无级联**)；唯一键 `(project_id, scheme, host, port)` |
| `model_configuration` | `models/configuration.py::ModelConfiguration` | `domain_id`(unique)、`label`、`provider`、`api_base`、`api_key_encrypted`(**仅存密文，任何接口不得返回**)、`model_name`、`temperature`、`max_tokens`、`timeout`、`cost_per_1k_input/output`、`is_enabled`、`is_default`、`sort_order`、`created_by`(**可空，且没有 `ondelete` 动作**) |
| `environment` | `Environment` | `name`(unique)、`display_name`、`base_url`、`gateway_prefix`、`default_headers`(JSON)、`is_default`、`is_active`、`created_by`/`updated_by`(SET NULL)；索引 `(is_active, is_default)` |
| `notification` | `models/notification.py::Notification` | `user_id`(CASCADE)、`project_id`(CASCADE, 可空)、`organization_id`(CASCADE, 可空)、`event_type`、`title`、`body`、`payload`(JSON)、`is_read`、`read_at`、`created_at`；索引 `(user_id, is_read, created_at)` |

模型定义**集中**在 `app/models/`（`identity.py` / `project.py` / `configuration.py` / `notification.py`），
由 `app/models/__init__.py` 统一导出，`app/main.py` 顶层 `import app.models` 让 `Base.metadata` 完整。
**为什么集中**：Alembic 的基线迁移直接 `Base.metadata.create_all()`，元数据漏一张表就等于漏一张库表，
且不会有编译期报错。

### 6.2 外键行为（直接决定删除语义）

| 关系 | 约束 | 级联 |
|---|---|---|
| `organization.owner_id` → `user.id` | NOT NULL | **无** |
| `project.owner_id` → `user.id` | NOT NULL | **无** |
| `project.organization_id` → `organization.id` | 可空 | **无** |
| `project_member.created_by` → `user.id` | NOT NULL | **无** |
| `project_outbound_target.approved_by` → `user.id` | NOT NULL | **无** |
| `organization_member.organization_id/user_id` | NOT NULL | `ondelete="CASCADE"` |
| `project_member.project_id/user_id` | NOT NULL | `ondelete="CASCADE"` |
| `project_outbound_target.project_id` | NOT NULL | `ondelete="CASCADE"` |
| `notification.user_id/project_id/organization_id` | 部分可空 | `ondelete="CASCADE"` |
| `model_configuration.created_by` | 可空 | **无 `ondelete`**（`app/models/configuration.py` 里只写了 `ForeignKey("user.id")`）。这不是笔误，但意味着 `users/service.py::delete_user` **必须**先靠 `_reattach_audits` 把该列显式置 NULL 才能 `db.delete(user)`，否则外键会直接抛 500；若第二阶段打算真正放开「直接删用户」，请先给这条 FK 补 `ondelete="SET NULL"` |
| `environment.created_by/updated_by` | 可空 | `ondelete="SET NULL"` |

### 6.3 为什么 `project.owner_id` / `organization.owner_id` 这两个 NOT NULL 字段会破坏「直接删用户」

旧项目 `db.delete(user)` 会因 `project.owner_id` / `organization.owner_id` 的 NOT NULL + 无级联而直接抛 500。
新实现 `users/service.py::delete_user` 改成显式交接：

1. **拒绝两类删除**：不能删自己（`403`）、不能删管理员（`400`）。
2. **项目交接**：`_hand_over_project` 在 `project_member` 中按 ID 升序找下一个 `is_active=true` 的成员接管 `owner_id`；找不到就删项目（成员关系与出站目标由级联带走）。
3. **组织交接**：`_hand_over_organization` 同理找下一个激活成员；且把接管人的 `organization_member.role` 提升为 `owner`。
   找不到时**必须先删组织内的项目再删组织** —— 因为 `project.organization_id` 引用了 `organization.id` 却没有级联动作。
4. **审计外键改指**：`_reattach_audits` 把仍然存活的 `project_member.created_by` 与
   `project_outbound_target.approved_by` 改指所属项目的当前负责人；
   `model_configuration.created_by` 通过一次 `UPDATE ... SET created_by = NULL` 置空保留记录
   —— 注意这条列**没有数据库级 `ondelete="SET NULL"`**（见 6.2），所以这一步不是冗余，
   而是 `db.delete(user)` 能跑通的前提。
5. 最后才 `db.delete(user)`，`notification` / `project_member` / `organization_member` 由级联清理。

`test_06_persistence.py` 覆盖了「有后继者交接」「无后继者连带清理」「不能删管理员或本人」三种分支。

### 6.4 其它结构约定

- `user.username` 是 `unique` 但 **nullable** —— 允许历史数据里存在无用户名的账号行；
  服务层写入前一律 `strip()`，注册/建号要求 3–50 字符。
- `project.name` **全局唯一**（沿用旧库口径，不做组织内唯一），因此跨组织也不能重名，
  重名返回 409。
- `project_member.role` 的 `owner` / `admin` 是**虚拟角色**，不落库：负责人身份由 `project.owner_id` 推导。
  `ProjectMemberCreate.role` 用 `Literal["viewer","member","editor"]` 在 schema 层限制可写入值
  （`app/shared/roles.py::PROJECT_MEMBER_EDITABLE_ROLES` 声明了同一集合但**当前无调用方**，
  属于尚未接线的校验入口 —— 见 11 节）。
- `organization_member.agent_enabled` 与 `allowed_model_ids` 是**为智能体预留**的字段，
  第一阶段**没有任何消费方**（唯一读点是 `dashboard.service.overview_for_user` 统计
  `models_available`）—— **智能体能力未接入**。

---

## 7. 数据库与配置

### 7.1 Alembic 是唯一改表方式

- 表结构变更**只能**通过 `alembic/versions/` 下的迁移。
- 应用启动**不会**自动建表；`AUTO_CREATE_SCHEMA` 默认 `false`
  （`app/shared/config.py`），仅当显式设为 `true` 时 `lifespan` 才执行 `Base.metadata.create_all()`。
- 第一阶段只有一个迁移 `0001_initial_schema`，内容直接 `Base.metadata.create_all()` ——
  一次性把 9 张表按 ORM 元数据生成，保证约束/索引/命名与 ORM 一致。
  **后续变更不要再用 `create_all`，请写显式 `op.create_table` / `op.add_column`。**
- `alembic.ini` 的 `sqlalchemy.url` 固定写成 `driver://unused` 占位，
  真值一律来自环境变量 `DATABASE_URL`（`tests/conftest.py` 与 `scripts/seed_admin.py` 都用
  `config.set_main_option("sqlalchemy.url", ...)` 覆盖）。
- 启动顺序约定：`alembic stamp base` → `alembic upgrade head`。

**测试回归点**：`tests/test_07_schema_gate.py` 在**独立子进程**里探测
「`AUTO_CREATE_SCHEMA=false` 时启动不建表 / `=true` 时才建表」。
为什么用子进程：`Settings` 在导入时就读取环境变量，同一解释器内改 `os.environ` 不会生效。

### 7.2 `scripts/seed_admin.py`（完整 bootstrap）与 `app/scripts/seed_admin.py`

| 脚本 | 做什么 |
|---|---|
| `backend/scripts/seed_admin.py` | 建库（`--drop` 先删）→ Alembic `stamp base` + `upgrade head` → 写内置环境 → 写管理员 |
| `backend/app/scripts/seed_admin.py` | 只创建/确认管理员（含 `require_credentials` 长度校验：用户名 ≥3、密码 ≥10） |

共同的硬约束：**凭据必须由环境变量显式提供** `INIT_ADMIN_USERNAME` / `INIT_ADMIN_PASSWORD`，
脚本里不内置任何默认账号密码；未提供时打印提示并跳过。
**为什么**：仓库一旦包含固定管理员密码，clone 下来就是可登录实例。

幂等性：用户已存在则跳过创建、**不覆盖历史密码**；`ensure_personal_organization` 保证个人组织与
`owner` 成员行存在。内置环境按 `name` 去重插入 `dev / test / staging / prod` 四条
（仅第一条且无默认项时 `is_default=True`）。
`tests/test_01_schema_and_seed.py` 覆盖幂等与「不打印凭据」。

### 7.3 `.env` 与 `.env.example` 的差异

`backend/.env.example` **只含占位值**，且刻意把管理员凭据留空：

```ini
SECRET_KEY=change-me-to-a-long-random-string
INIT_ADMIN_USERNAME=
INIT_ADMIN_PASSWORD=
AUTO_CREATE_SCHEMA=false
```

- `SECRET_KEY` 缺失会导致**应用导入期直接 `RuntimeError`**（`config.py` 末尾硬检查），这是有意的快速失败。
- `DATABASE_URL` 在 `config.py` 里默认 `None`，不写死任何库地址；compose.yaml 与 `.env.example` 各持一份本地默认值。
- `MODEL_CONFIG_ENCRYPTION_KEY` 可留空，留空时由 `SECRET_KEY` 派生（`runtime_model_config_key()`）。
- `CORS_ORIGINS` 用**逗号分隔**而非 JSON 数组，由 `config.py` 里的
  `_CsvListEnvSource` / `_CsvListDotEnvSource` 在设置来源层拆分 —— 避免 pydantic-settings 按 JSON 解析失败。
- 真实 `.env` 已在 `.gitignore` 中。

### 7.4 `compose.yaml` 的作用与限制

只管**平台主库**：`postgres:16`、容器名 `testplatform-postgres`、端口 `5432:5432`、
数据卷 `postgres-data`、`pg_isready` 健康检查。文件头明确写了：
**「本地 PostgreSQL（仅平台主库）。被测目标数据库不在此文件管理。」**

> 这句提示**只写在 `compose.yaml` 里**；`backend/.env.example` 并没有对应说明（它只有一句
> 「内置环境地址，未配置时回退到示例域名」）。如果接手人依赖 `.env.example` 来理解
> 「平台主库 ≠ 被测目标数据库」，需要自己补一句注释。
>
> 另外提醒：`compose.yaml` 里的 `POSTGRES_USER` / `POSTGRES_PASSWORD` 是本机开发凭据
> （明文写在仓库里），本文按约定不复制它们的值；不要把这些值当成生产凭据，也不要再往
> 文档或示例文件里写真实密码。

**两个概念不要混成「二选一」**：

| | 平台主库 | 被测目标数据库 |
|---|---|---|
| 内容 | 用户、组织、项目、配置、环境、通知 | 被测系统自己的业务数据 |
| 由谁提供 | `compose.yaml`（本地） | 被测环境自己，平台**不托管** |
| 平台如何触达 | `DATABASE_URL` 直连 | 通过 `environment.base_url` + `project_outbound_target` 指向被测**服务**，平台不连被测库 |
| 是否互斥 | 不是 | 平台可以同时对接多个被测目标，两者共存；被测库由被测环境自己提供 |

第二阶段加「API 执行 / 慢 SQL 分析」时，若要连被测数据库，那是一个**新的、独立的**连接来源，
不要复用平台主库的 `DATABASE_URL`，也不要写进 `compose.yaml`。

---

## 8. 安全设计

| 主题 | 做法 | 代码位置 |
|---|---|---|
| 密钥不落日志 | `main.py` 启动日志只打 `DATABASE_URL.split("@")[-1]`（去凭据）；全代码库无 `print` 密钥；`seed_admin.py` 打印时只报用户名与 ID | `app/main.py::lifespan`、`tests/test_01_schema_and_seed.py::test_seed_admin_does_not_print_credentials` |
| 模型 API Key 加密存储 | Fernet：`MODEL_CONFIG_ENCRYPTION_KEY` 缺失时由 `SECRET_KEY` 派生 → `sha256` → `urlsafe_b64encode` 得 Fernet key；解密失败**返回空串而不是抛错**（密钥轮换后不炸接口） | `model_configuration/service.py::_fernet` |
| 只回掩码 | `response_for` 是唯一的响应构造函数，返回 `has_api_key` + `masked_api_key`（首 3 末 4，≤8 位全隐藏），**永不返回 `api_key_encrypted`** | 同上 |
| 编辑不传密钥 = 保留原值 | `update_configuration` 中 `api_key` 缺失或为空串都会被 pop，不覆盖已存密文 | 同上 |
| 启用但无密钥 → 400 | **新增**走 `create_configuration` 里的显式判断，文案是「启用状态的模型必须配置 API Key」（此时 `is_enabled` 已被折叠成 `bool(body.is_enabled and api_key)`，所以 `_validate_payload` 那条分支不会触发）；**编辑**才走 `_validate_payload` 的 `is_enabled and not has_api_key`，文案是「启用模型前必须填写 API Key」。两条文案不同但语义一致，都指向 400。为什么不做「悄悄存成停用」：会让管理员以为模型已生效，而执行链路永远选不到它 | 同上 |
| 停用却设默认 → 400 | `_validate_payload` 还有一条 `is_default and not is_enabled` → 「停用的模型不能设为默认模型」，新增与编辑共用；`set_default` 也单独校验一次 | 同上 |
| 令牌撤销 | `token_version` 递增，见 4.2 | `shared/auth.py` |
| 账号枚举防护 | 用户名不存在与密码错误返回**同一条** `bad_request("用户名或密码错误")`；删除用户后的令牌与令牌撤销共用 401 文案 | `users/service.py::authenticate`、`shared/auth.py::get_current_user` |
| 环境表含凭据 | `default_headers` 可能含凭据，因此 `/environments` 读写**全部**仅管理员；第二阶段给控制台加只读环境选择器时应新建仅回名称的接口 | `environment_configuration/router.py` |
| 管理员自锁防护 | 不能删自己（403）、不能删管理员（400）、不能改自己角色、不能停用自己、不能停用其他管理员 | `users/service.py::update_user` / `delete_user` |
| 通知非主数据 | `notify()` 失败只记 warning 并吞掉，不让业务回滚 | `shared/notify.py` |
| 速率限制 | 登录：IP 60 次/分钟、用户名 10 次/分钟；注册：IP 10 次/小时；进程内滑动窗口（`deque` + `popleft` 做单 key 过期）。**注意清扫是全量清空**：当距上次清扫 > 300s 且 key 数 > 5 万时，`_events` 与 `_limits` 被**整体 `clear()`**，而不是只回收过期 key —— 这意味着一次误判（例如把 5 万个不同 IP 打进缓存）会让后续所有登录在 300s 内不受限流约束 | `shared/rate_limit.py`（`_MAX_TRACKED_KEYS = 50_000`）+ `config.py` 的 `AUTH_*` 阈值 |
| 限流防伪造 | `_client_ip` 只取 `request.client.host`，**不信任转发头** | `shared/rate_limit.py` |
| JWT 算法混淆防护 | `jwt.decode(..., algorithms=[ALGORITHM])` 显式传算法列表 | `shared/auth.py` |
| bcrypt 72 字节截断 | SHA256 预处理 + 显式 `_truncate`，兼容旧 passlib 产物 | `shared/passwords.py` |
| CORS | 白名单来自 `CORS_ORIGINS`；`expose_headers=["X-Request-ID"]` 便于前端展示追踪 ID | `app/main.py` |
| 出站目标白名单 | `scheme` 仅 http/https；`host` 禁止含端口/方括号；生产目标强制 https；四元组唯一 | `projects/service.py::_normalize_target` |

**多进程部署注意**：`rate_limit.py` 是**进程内**滑动窗口，多 API 进程各自计数，
文件头已声明应在可信网关侧再叠加共享限制。

---

## 9. 可观测性与质量保障

### 9.1 日志与 request_id 关联

- 中间件 `attach_request_context`：`X-Request-ID` 合法（`[A-Za-z0-9._-]{8,128}`）则沿用，否则生成 `uuid4().hex`。
- 写入 `request.state.request_id` + `contextvars.request_id_context`；响应头回写 `X-Request-ID`。
- `RequestIdFilter` 把当前请求 ID（截前 8 位）注入每条日志：
  格式 `%(asctime)s %(levelname)s [%(request_id)s] %(name)s %(message)s`。
- 访问日志：`method / path / status / duration_ms`，未捕获异常额外记 `unhandled_error`。
- 错误信封里的 `request_id` 与响应头一致，**报障时贴 `request_id` 即可串起一次请求**。

`configure_logging()` 只在 root 没有 handler 时追加，避免与 uvicorn 的日志配置重复。

### 9.2 后端测试（51 个用例全部通过）

`backend/tests/`，共 7 个文件、**51 个用例**（`pytest --collect-only` 实测）：

| 文件 | 验收项（文件头自述） | 主题 |
|---|---|---|
| `test_01_schema_and_seed.py` | 1、2 | Alembic 从空库升到 head；seed 幂等；不打印凭据 |
| `test_02_auth_flow.py` | 3 | 注册/登录/当前用户/退出，个人组织自动创建 |
| `test_03_token_revocation.py` | 4 | 改密、停用（403）、改角色、改用户名、令牌过期 |
| `test_04_admin_authorization.py` | 5、6 | 非管理员不可读/写管理端点；分页契约；keyword 过滤；API Key 不明文回传；启用模型必须有关键 |
| `test_05_isolation.py` | 7 | 组织与项目边界隔离；残留跨组织成员行不可见 |
| `test_06_persistence.py` | 8、9 | 数据持久化；用户删除交接；看板去重；**未接入模块标记**；`/ready` 降级 |
| `test_07_schema_gate.py` | 10 | 应用启动不自动改表结构 |

隔离与夹具（`tests/conftest.py`）：

- 独立测试库 `testplatform_test`（可用 `TEST_DATABASE_NAME` 覆盖），**绝不复用开发库**；
  session 级 fixture 先 `pg_terminate_backend` 断开连接再 `DROP DATABASE` / `CREATE DATABASE`。
- 表结构由 Alembic `stamp base` → `upgrade head` 生成，测试**不**依赖应用启动期建表。
- 导入 app 之前固定环境变量：`AUTO_CREATE_SCHEMA=false`、测试专用 `SECRET_KEY`、
  三个 `AUTH_*` 限流阈值放到 1000000（避免测试互相触发 429）。
- `ApiClient` 助手缓存令牌，减少重复登录样板；管理员账号通过显式写库 + HTTP 登录获得，
  模拟「管理员由初始化命令创建」的真实前置条件。

**新增测试请沿用编号风格**：`test_08_xxx.py`，并复用 `conftest.py` 的 fixture。

### 9.3 前端质量门

- `npm run typecheck` = `tsc -b --noEmit`（`tsconfig.app.json` 开 `strict` + `noUnusedLocals` + `noUnusedParameters` + `noFallthroughCasesInSwitch`）。
- `npm run build` = `tsc -b && vite build`。
- 两者均已通过。CI 建议顺序：`typecheck` → `build` → 后端 `pytest`。

---

## 10. 扩展点设计（第二阶段必读）

### 10.1 新增一个业务模块的完整路径

以后新增「测试计划」模块为例：

**后端**
1. `mkdir -p app/features/test_plans/`，建 `__init__.py` / `router.py` / `service.py` / `schemas.py`。
   - `router.py`：`router = APIRouter(prefix="/test-plans", tags=["测试计划"])`，只声明参数与 `Depends`。
   - `service.py`：写业务与事务；判定权限用 `shared/roles.py`，不要自己在 service 里查表拼权限。
   - `schemas.py`：Pydantic 入参/响应，字段一律 `snake_case`。
2. 新表定义加在 `app/models/` 下对应文件，并在 `app/models/__init__.py` 导出。
3. 写**显式** Alembic 迁移 `alembic/versions/0002_xxx.py`（`revision = "0002"`, `down_revision = "0001"`），
   用 `op.create_table` / `op.add_column`，**不要**再调 `Base.metadata.create_all()`。
4. 注册路由：`app/main.py` 顶部 import，`create_app()` 里
   `application.include_router(test_plans_router, prefix=API_PREFIX)`。
   若前缀与既有 feature 冲突（例如需要 `/projects/{id}/plans` 这种嵌套），
   应挂在 `projects/router.py` 里而不是新开前缀 —— 因为路径参数解析由同一 router 顺序决定。
5. 测试：`tests/test_08_test_plans.py`，复用 `conftest.py` 夹具。

**前端**
6. `src/api/testPlans.ts`：`import { api } from './client'`，用 `api.get<T>` 等便捷方法；类型加到 `src/types/index.ts`。
7. 页面按视角放：`src/pages/console/TestPlans.tsx`（用户视角）或 `src/pages/admin/TestPlans.tsx`（平台视角）。
8. 在 `src/App.tsx` 对应分支下加 `<Route path="test-plans" ... />`，
   需要守卫的话复用 `RequireAdmin` / `RequireAuth`。
9. **缓存 key 约定**：组织级数据用 `['testPlans']`，项目级数据用 `['testPlans', projectId, ...]`。
   项目级前缀必须让 `ConsoleScopeProvider.setProjectId` 的 `invalidateQueries(['project'])` 能覆盖到 ——
   注意它当前只失效 `['project']`，若你的 key 首段不是 `project`，
   需要同时更新 `useConsoleScope.tsx` 的失效清单（**这是一个真实踩坑点**）。
10. 控制台页面若需要「当前项目」上下文，用 `useConsoleScope().currentProjectId`；
    作用域通过 **query 参数**传给后端，不要放请求头。

### 10.2 项目内未来能力的挂接位置

第一阶段的项目模型已经为后续能力留好了挂载点：

| 未来能力 | 挂哪 | 当前状态 |
|---|---|---|
| API 执行 / 用例执行 | 新增 `test_run` 表，`project_id` 外键 + `project_member` 权限判定（建议 `member` 及以上）；被测地址取自 `environment.base_url`，放行名单取自 `project_outbound_target` | **未接入** |
| 用例生成（AI） | 复用 `model_configuration`（`domain_id` 引用）+ `organization_member.allowed_model_ids` 做模型授权；执行身份来自 `project_member` | **未接入** |
| UI 自动化 | 同上，`project_outbound_target.scheme/host/port` 已含协议与端口校验 | **未接入** |
| 移动端控制 | 无挂载点，需新增设备/会话表 | **未接入** |
| 报告 / 缺陷 | 新增 `report` / `defect` 表挂 `project_id`；`dashboard.stats` 的 `reports` / `defects` 键已占位 | **未接入** |
| 数据工厂 | 新增任务表 + `project_outbound_target` 放行；注意与平台主库区分（见 7.4） | **未接入** |
| 慢 SQL 分析 / JVM 诊断 / 代码扫描 | 无挂载点；需要独立的数据源配置（不放进 `environment` 表） | **未接入** |
| 统一编排 | 无挂载点 | **未接入** |
| AI 智能体 | 字段已备好：`organization_member.agent_enabled` + `allowed_model_ids`；但**没有任何消费方** | **未接入** |

两个具体约定：

- **`project_outbound_target` 是项目作用域的目标服务白名单**（`scheme`/`host`/`port` 四元组唯一，
  生产目标强制 https，`approved_by` 记录审批人）。第二阶段做 API 执行或 UI 自动化时，
  执行前应校验目标是否在该项目的白名单内 —— 这个表的语义就是为它准备的。
  注意 `approved_by` 是 NOT NULL 且**无级联**，删除审批人时会被
  `users/service.py::_reattach_audits` 改指项目负责人，这条清理逻辑已经在跑。
- **`notification.event_type` 是开放字符串 + 目录**（`shared/notify.py::EVENT_TITLES` / `EVENT_LABELS`）。
  新增事件类型需要**同时**往这两个字典加中文标题与说明，否则前端拿不到中文文案。
  现有类型：`user.created` / `user.updated` / `user.password_changed` /
  `organization.member.invited` / `project.member.invited` / `project.owner_changed`。
  注意：目录中 `organization.member.invited`、`project.member.invited`、`project.owner_changed` 三个事件
  目前**没有任何调用方写入**（`notify()` 的唯一调用点是 `users/service.py::_emit`，只发出
  `user.created` / `user.updated` / `user.password_changed`）—— 属于目录已声明、写入未接入。
  成员 upsert 与负责人转移都不发通知。

### 10.3 看板如何如实标记未接入

`app/features/dashboard/service.py`：

**stats 中的占位约定** —— `StatCard(key, label, value, hint)`，
未接入项**一律 `value=0` + `hint="未接入"`**（常量 `NOT_MIGRATED_HINT = "未接入"`），
绝不产生随机或伪造数据：

| key | label | value | hint |
|---|---|---|---|
| `projects` | 可见项目 | 真实计数 | 当前用户可见范围 |
| `organizations` | 可见组织 | 真实计数 | 当前用户所属组织 |
| `my_projects` | 我参与的项目 | 真实计数 | 负责人或成员身份 |
| `unread_notifications` | 未读通知 | 真实计数 | 个人收件箱 |
| `models_available` | 可用模型配置 | 真实计数 | 组织授权且已启用 |
| `environments_available` | 可用环境 | 真实计数 | 已启用的执行环境 |
| `test_runs` | 测试执行 | **0** | **未接入** |
| `reports` | 测试报告 | **0** | **未接入** |
| `defects` | 缺陷 | **0** | **未接入** |

**扩展约定**：新增已实现能力时，直接把占位项的 `value` 换成真实查询即可，
`key` 不变（前端依赖 `key` 做展示分支），`hint` 改成口径说明。

**`/dashboard/ready` 的降级语义**（`readiness()`，**不谎报 ready**）：

| 依赖 | 条件 | 单项状态 | 整体状态 |
|---|---|---|---|
| `database` | `SELECT 1` 失败 | `down` | **`not_ready`**（立即返回，不查其它依赖） |
| `llm_configs` | 无启用模型 / 无默认模型 | `degraded` | `degraded` |
| `llm_configs` | 查询异常 | `unknown` | `degraded` |
| `environments` | 无启用环境 | `degraded` | `degraded`（仅当原本为 `ready` 时降级） |
| `environments` | 查询异常 | `unknown` | `degraded` |
| 全部正常 | —— | `up` | `ready` |

`database` 是唯一能压到 `not_ready` 的依赖 —— 数据库不可用时其它检查没有意义。

`tests/test_06_persistence.py` 有 `test_unconnected_modules_are_marked_not_connected`、
`test_readiness_reports_real_dependency_state`、`test_readiness_degrades_to_not_ready_when_database_is_unavailable`
三个回归用例锁住这套语义。**第二阶段别把这三个用例删了来"通过"验收。**

### 10.4 第一阶段刻意没有实现的东西

- **通知引擎**：旧项目有通知模板 / 渠道配置 / 订阅，第一阶段只保留**收件箱**（`notification` 表 + 已读状态）。
  `notifications/router.py` 文件头已注明这一点。
- **组织侧的智能体能力**：字段预留（`agent_enabled` / `allowed_model_ids`），无实现。
- **模型配置的"调用"**：`model_configuration` 只管连接参数与启停，没有任何执行/调用代码。
  `api_base`、`temperature`、`max_tokens` 等字段是为第二阶段调用层准备的。
- **环境配置的"执行"**：`environment` 只存路由参数，没有 HTTP 转发/代理实现。
- **看板**：只统计第一阶段已有的表，未接入能力一律占位（见 10.3）。

---

## 11. 待确认项

以下是写文档时在代码中无法完全确认、需要接手人核对的点：

1. **验收项编号**：本仓库测试文件头自述覆盖了验收项 1–10（`test_06` 覆盖 8、9）。
   若你的验收清单里第 9 项另有定义，请以清单为准 —— 文件头是自述，不是验收单本身。
2. **浏览器端到端流程**：本文只覆盖 `pytest`（51 通过）与前端 `typecheck`/`build`（通过）。
   浏览器实测结果未从代码仓库读取，需另行确认。
3. **`app/bootstrap/routes.py` 未被引用**：`app/main.py` 直接逐个 `include_router`，
   这个「顶层装配器」目前是死代码。若第二阶段希望集中装配，应在 `main.py` 改为
   `include_router(router, prefix=API_PREFIX)` 二选一，不要同时存在两套注册。
4. **`model-configs/providers` 无鉴权**：与模块文档字符串的「全部仅管理员」不一致（见 5.3 注）。
5. **未使用的错误码常量**：`ERR_USER_NOT_FOUND`、`ERR_ACCOUNT_DISABLED`（见 5.4）。
   前端目前靠**文案**判断账户被禁用，若要改成靠错误码，需要前后端一起改。
6. **两个 seed 脚本并存**：`scripts/seed_admin.py`（完整 bootstrap）与 `app/scripts/seed_admin.py`
   （仅管理员）功能重叠且长度校验规则不同（后者要求密码 ≥10）。是否需要合并待定。
7. **分页执行路径不统一**：`apply_page` 与各 service 内联 `offset/limit` 并存（见 5.2）。
8. **`notifications` 没有 `service.py`**：唯一把业务逻辑写在 `router.py` 里的模块
   （`_visible_in_scope` 直接调 `accessible_project_ids`）。新增通知相关逻辑时，
   建议先补 `service.py` 再扩展，否则会把可见性判定散落到更多路由里。
9. **Node 版本未钉住**：仓库无 `engines` / `.nvmrc`，本地实测 v24.21.0。CI 需显式指定。
10. **`user.username` 为 nullable**：唯一约束在 nullable 列上，PostgreSQL 允许多行 NULL。
    当前服务层写入前都强制 `strip()` 且注册要求非空，但没有数据库层 NOT NULL 约束 —— 属历史口径保留。
11. **`PROJECT_MEMBER_EDITABLE_ROLES` 无调用方**：该常量声明了项目成员可写入的角色集合，
    但仓库中没有任何一处引用它；实际约束由 `ProjectMemberCreate.role` 的 `Literal` 在 schema 层完成。
    两处口径目前一致，但改角色时容易漏改一侧。
12. **通知目录有 3 个事件无人写入**：`organization.member.invited`、`project.member.invited`、
    `project.owner_changed`（见 10.2）。前端下拉里会看到这三个中文选项，但永远不会收到对应通知。
13. **`invalidate_user_tokens` 的文档字符串与实际调用不符**：文档字符串列举了 4 种场景
    （改密、禁用、调角色、被移除），但仓库中只有 `change_password` 与 `update_user` 两处调用；
    「被管理员移除」实际靠删除用户行让令牌落到「用户不存在」分支失效。
    用户侧效果一致，但排查时不要被文档字符串误导。
14. **`/dashboard/projects` 的分页信封不完整**：`ProjectSummaryResponse` 只有 `items` 与 `total`，
    没有 `page` / `page_size`（见 5.2 例外说明）。控制台工作台目前只取前 5 条且不翻页，
    所以没暴露；一旦控制台要加「加载更多项目」，前端会按 `Paginated<T>` 期待这两个字段而拿到 `undefined`。
    建议第二阶段直接补齐字段，成本很低。
15. **`shared/dependencies.py::require_platform_admin` 是半成品**：它把 `user` 当普通参数，
    不含 `Depends(get_current_user)`，因此不能单独当守卫用；而且唯一 import 它的
    `model_configuration/router.py` 一次都没调用（实际用 `is_platform_admin` 内联判定）。
    目前仓库里真正被路由依赖的是 `shared/auth.py` 版本。见 2.3 的提示。
16. **`model_configuration.created_by` 缺 `ondelete`**：与 `environment.created_by/updated_by`
    （显式 `ondelete="SET NULL"`）不一致，删除用户全靠 `_reattach_audits` 先置 NULL 才不撞外键。
    见 6.2 —— 建议在下一个迁移里补齐，避免后续有人写「直接删用户」的路径时踩雷。

---

*文档基于第一阶段（Phase 1，已交付）代码撰写。凡标注「未接入」的能力均未实现，
请勿按已交付理解。*
