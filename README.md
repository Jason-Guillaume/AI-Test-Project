# 测试开发平台 · 阶段一（统一身份与权限 + 平台基础台）

旧项目（`~/Desktop/test-projects`）的重构落地。**旧项目只作分析参考，从未被修改**；
本仓库是新项目，所有代码、迁移与文档都在这里。

阶段一交付的是「身份、权限、组织/项目骨架、看板与就绪检查」这套底座，
以及后续测试业务能力（AI 用例、接口执行、UI 自动化……）接入所需的明确扩展点。
**尚未接入的业务能力全部标记「未接入」，不做假数据、不假装可用。**

---

## 1. 目录结构

```
ai-test-project/
├── backend/                     FastAPI 后端
│   ├── app/
│   │   ├── main.py              应用装配（无启动期建表、无内置种子）
│   │   ├── shared/              配置 / 数据库 / 错误信封 / 角色 / 认证依赖 / 分页
│   │   └── features/            users · organizations · projects · environment_configuration
│   │                            model_configuration · dashboard · notifications
│   ├── alembic/                 唯一合法的表结构来源
│   ├── scripts/seed_admin.py    初始化命令（建库 + 迁移 + 管理员 + 内置环境）
│   ├── scripts/e2e_smoke.sh     端到端冒烟（13 组，118 项断言）
│   └── tests/                   pytest（隔离库 testplatform_test）
├── frontend/                    React 18 + TS 5.6 + Vite 5 + antd 5
│   └── src/
│       ├── App.tsx              单应用双入口的路由表（共享登录态与权限上下文）
│       ├── layouts/             AdminLayout.tsx · ConsoleLayout.tsx
│       ├── pages/
│       │   ├── auth/            登录 / 注册
│       │   ├── admin/           /admin/*  平台管理端
│       │   └── console/         /console/* 用户控制台
│       └── api/ components/ hooks/ types/    请求客户端 · 基础组件 · hooks · 类型
├── docs/
│   ├── current-system-analysis.md   旧项目现状分析（逐模块、逐端点）
│   ├── target-architecture.md       目标架构与阶段一设计
│   └── migration-plan.md            旧→新 API 映射、字段与状态码差异
├── compose.yaml                 本地 PostgreSQL（仅平台主库）
└── README.md
```

技术栈（实际安装版本）：Python 3.14 / FastAPI 0.141.1 / SQLAlchemy 2.0.54 / Alembic 1.20.0 /
psycopg 3.3.6 / PyJWT 2.15.1 / bcrypt 4.3.0 / pydantic 2.14 / uvicorn 0.53.0；
React 18.3 / TypeScript 5.6（strict）/ Vite 5.4 / antd 5.21 / @tanstack/react-query 5.59 /
react-router-dom 6.26 / dayjs。

依赖来源只有一处：后端是 `backend/requirements.txt`（**没有** `pyproject.toml`，所以装依赖用
`pip install -r requirements.txt`，不能用 `pip install -e .`）；前端是 `frontend/package-lock.json`
（npm 锁文件，用 `npm install`，不要换成 pnpm）。

端口约定：PostgreSQL `5432`、后端 `8001`、前端 dev `5173`。

---

## 2. 快速开始

```bash
# 0) 起库（首次；数据落在 compose 卷 postgres-data 里）
docker compose up -d postgres
docker compose ps                                   # 等 healthcheck 变 healthy

# 1) 后端依赖（backend/ 只有 requirements.txt，没有 pyproject.toml，不要 pip install -e .）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

# 2) 配置（仓库里只有不带凭据的样例）
cp .env.example .env
#   编辑 .env：DATABASE_URL 指向你的库、SECRET_KEY 换成足够长的随机串
#   SECRET_KEY 生成：python -c "import secrets;print(secrets.token_urlsafe(48))"

# 3) 初始化数据库 + 首个管理员（凭据只走环境变量，不在 .env、不内置默认值）
INIT_ADMIN_USERNAME=admin \
INIT_ADMIN_PASSWORD="$(python -c 'import secrets;print(secrets.token_urlsafe(18))')" \
  .venv/bin/python scripts/seed_admin.py

# 4) 起后端（注意：本项目不自动建表，表结构一律来自 Alembic）
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8001

# 5) 起前端（另一个终端）
cd ../frontend && npm install && npm run dev        # http://localhost:5173
```

浏览器打开 `http://localhost:5173/` 用第 3 步的账号登录；平台管理端在 `/admin/*`，
用户控制台在 `/console/*`。两个入口共用同一套登录态与权限上下文。

---

## 3. 凭据与安全约定

| 约定 | 落地方式 |
|---|---|
| 不内置固定管理员密码 | `scripts/seed_admin.py` 只读 `INIT_ADMIN_USERNAME` / `INIT_ADMIN_PASSWORD`；未提供就跳过并打印说明，不猜、不生成、不写死 |
| 不复制旧 `.env` / 密钥 / 日志 | 仓库只提交 `.env.example`；`.env` 在 `.gitignore` 里 |
| 配置编辑不读原值 | 模型配置接口永不回传 `api_key`，只回 `has_api_key` 与 `masked_api_key`；改配置时留空即保留原密钥，不必先读出来 |
| 启用中的模型必须有密钥 | `is_enabled=true` 且无密钥 → `400`（前端表单同样拦截） |
| 权限以服务端为准 | 前端隐藏按钮只是体验；每个写端点都在服务层做角色判定，冒烟脚本用直接 HTTP 请求验证过越权写 |
| 令牌可吊销 | 用户表有 `token_version`，写进 JWT；改密码、停用、改角色、组织/项目成员变更都会递增它，旧令牌立刻失效 |
| 不把随机数据当真实统计 | 看板只统计真实落库的行；未接入的能力返回 `hint="未接入"`，不返回伪造的 0 值趋势 |

---

## 4. 数据库与迁移

- **表结构唯一来源是 Alembic。** 应用启动时不建表（`AUTO_CREATE_SCHEMA=false` 是默认值）。
- 首次初始化 / 升级：

  ```bash
  cd backend
  .venv/bin/python -m alembic upgrade head          # 只升级
  .venv/bin/python scripts/seed_admin.py            # 建库 + 升级 + 种子
  .venv/bin/python scripts/seed_admin.py --drop     # 先删库再重建（仅本地）
  .venv/bin/python scripts/seed_admin.py --database-url 'postgresql+psycopg://...'   # 指定库
  ```

- 管理员初始化**幂等**：账号已存在则跳过（**绝不覆盖历史密码**）；内置环境按名称去重。
- 本地数据库隔离，互不污染：

  | 库 | 用途 |
  |---|---|
  | `testplatform_dev` | 开发库（compose 建，`.env` 指向它） |
  | `testplatform_test` | pytest 会话库，每次会话开始前强制重建 |
  | `testplatform_e2e` | 冒烟脚本库，脚本退出时删除 |

  旧项目自己的 `testproject` / `testproject_dev` 从未被本项目碰过。

- 当前基线 10 张表：`user`、`organization`、`organization_member`、`project`、
  `project_member`、`project_outbound_target`、`model_configuration`、`environment`、
  `notification`、`alembic_version`。

---

## 5. 验证

三条命令，本地均已跑通：

```bash
# 后端单测（隔离库 testplatform_test）
cd backend && .venv/bin/python -m pytest -q tests/
#   52 passed, 6 warnings in 39.63s

# 前端类型检查 + 生产构建
cd frontend && npm run typecheck && npm run build
#   exit 0（1 条 antd 体积提示，非错误）

# 端到端冒烟（隔离库 testplatform_e2e，退出即删除）
cd backend
INIT_ADMIN_USERNAME=e2e-admin INIT_ADMIN_PASSWORD='E2E-Password-456' \
  bash scripts/e2e_smoke.sh \
    --database-url 'postgresql+psycopg://root:fangzhou123@127.0.0.1:5432/testplatform_e2e' \
    --port 8001 --frontend-url http://localhost:5173
#   == 结果：118 通过，0 失败 ==
```

6 条 warning 都是无害的：Starlette `TestClient` 弃用、`HTTP_422_UNPROCESSABLE_ENTITY`
弃用、以及一处**故意**用 12 字节密钥触发的 `InsecureKeyLengthWarning`
（用来验证「密钥过短会被 PyJWT 警告」的行为）。

`e2e_smoke.sh` 从空库开始走完 13 组：建库+迁移+种子、幂等重跑、起服务、
注册/登录/me/401/退出、非管理员访问管理端、管理员分页与搜索、组织与项目跨组织隔离、
只读成员不可写、令牌吊销与停用、看板与就绪与「未接入」、模型密钥不泄露、
**逐表行数与 API 写入对账**、Vite SPA 回退与代理前缀。脚本不内置任何账号密码，
输出全程掩码，退出时删除测试库。

---

## 6. API 迁移映射（要点）

完整逐端点映射、字段差异与状态码对照见 [docs/migration-plan.md](docs/migration-plan.md)，
旧项目现状见 [docs/current-system-analysis.md](docs/current-system-analysis.md)。
下表是必须在改造前端时知道的几条结构性差异，均已对照旧代码核实：

| 项 | 旧项目 | 新项目 |
|---|---|---|
| URL 前缀 | 后端路由挂在根路径（`POST /users/login`）；`/api` 只是前端约定，Vite 代理 `rewrite: path.replace(/^\/api/,'')` 把它剥掉 | 后端真实版本前缀 `/api/v1`；前端 `baseURL: '/api/v1'`；Vite 代理**不 rewrite** |
| 登录 | `POST /users/login` | `POST /api/v1/login` |
| Swagger 登录按钮 | `OAuth2PasswordBearer(tokenUrl="/users/login")` | `tokenUrl="/api/v1/login"`（`/docs` 页的 Authenticate 按钮可直接用） |
| 注册 | `POST /users/register` | `POST /api/v1/register`（注册即建个人组织，规则与旧项目一致） |
| 改密 | `PUT /users/me/password` | `PATCH /api/v1/me`，body `{old_password, new_password}` |
| 用户列表 | `GET /users/` → `{total, items}`；分页 `skip`/`limit`（`limit ≤ 500`，默认 10）；无关键字 | `GET /api/v1/users` → `{items, total, page, page_size}`；`page`(≥1)/`page_size`(1..200，默认 20)/`keyword` |
| 分页信封 | `{total, items}`，偏移量分页 | `{items, total, page, page_size}`，页码分页，全平台统一 |
| 错误信封 | 直接抛 HTTPException，各端点各写各的 | 统一 `{code, message, request_id}`；`ERR_TOKEN_EXPIRED`/`ERR_FORBIDDEN`/`ERR_NOT_FOUND`/`ERR_VALIDATION`/`ERR_CONFLICT`/`ERR_BAD_REQUEST`/`ERR_RATE_LIMITED`/`ERR_INTERNAL` |
| 401 文案 | 因端点而异 | 统一「登录失效，请重新登录」+ `WWW-Authenticate: Bearer`，防用户名枚举（错误密码与未知用户名同一个响应） |
| 用户名重复 | `400`「该用户名已存在」 | `409`「用户名已存在」 |
| 删除自己 | `400`「不能删除自己的账户」 | `403` |
| 管理员自保护 | **没有**：旧接口可以删除任一非本人的管理员 | `400`「不能删除管理员账户」/「不能停用管理员账户」，自己则报「不能删除/停用自己的账户」 |
| 令牌吊销 | 无 | `token_version` 写入 JWT `ver` 声明，失效即拒 |
| 退出登录 | 前端删本地态 | `POST /api/v1/logout` → `204`；服务端无会话表，令牌仍有效到过期 |
| 跨组织访问 | **有真实漏洞**：旧 `_get_accessible_project`（`app/features/project/api/router.py:41`）只判
  `owner_id` 与 `ProjectMember` 是否存在，**完全不看 `project.organization_id`**——组织边界只在列表查询和角色计算路径上判。
  结果：只要某条 `project_member` 行落在别人组织的项目上，跨组织用户就能按 ID 读写该项目 | 先判组织边界再判项目身份；不可见资源一律 `404` 隐藏存在性；遗留成员行不放行（有回归用例） |

一个容易踩的坑：**旧前端的 `/api` 前缀在代理层就被剥掉了，新后端不会收到它。**
新项目反过来——`/api/v1` 是真实路径前缀，代理原样转发。冒烟脚本第 13 组专门断言了
「经代理与直连后端同码（401/401）」，就是为了防止有人误加 rewrite。

---

## 7. 权限模型（三层，不合并）

按旧项目约定保留三层独立角色，**没有压成一个全局 role**：

- **平台角色**（`user.role`）：`admin` / `test` / `dev`。只有 `admin` 能进平台管理端。
- **组织成员角色**：`owner` / `admin` / `member`；平台管理员额外获得虚拟角色 `platform_admin`。
- **项目成员角色**：`viewer` / `member` / `editor`；项目负责人额外获得虚拟 `owner` / `admin`。
  等级 `0 < 1 < 2 < 3 < 4`，判定统一走 `has_project_role()`。

服务端强制点：

- 所有写端点在服务层判角色，前端隐藏按钮不构成授权。
- 项目可见性 = 组织边界 **且** 项目身份：组织普通成员只看到被分配的项目，
  组织负责人/管理员看到本组织全部项目。
- 越权读到不存在的资源返回 `404` 而非 `403`，不泄露存在性。
- 数据库里遗留的「不属于当前组织」的成员行不会越权放行（有专门回归用例）。

---

## 8. 阶段一验收清单

| # | 验收项 | 验证方式 | 状态 |
|---|---|---|---|
| 1 | Alembic 在隔离 PostgreSQL 上从空库升到 head，生成约定表 | `tests/test_01_schema_and_seed.py` + `tests/test_07_schema_gate.py`（表结构门禁） | ✅ 通过 |
| 2 | 管理员初始化可重复执行、不内置密码、不覆盖历史密码 | 同上 + 冒烟第 1–2 组 | ✅ 通过 |
| 3 | 注册 / 登录 / me / 退出 / 401 统一文案与错误码 | `tests/test_02_auth_flow.py` + 冒烟第 4 组 | ✅ 通过 |
| 4 | 禁用 / 改密 / 改角色后的令牌行为 | `tests/test_03_token_revocation.py` + 冒烟第 9 组 | ✅ 通过 |
| 5 | 非管理员不能调用平台管理端点 | `tests/test_04_admin_authorization.py` + 冒烟第 5 组 | ✅ 通过 |
| 6 | 无跨组织、跨项目访问 | `tests/test_05_isolation.py` + 冒烟第 7 组 | ✅ 通过 |
| 7 | 只读成员无法通过直接请求修改数据 | 冒烟第 8 组（改项目/改成员/删项目/转负责人全 403） | ✅ 通过 |
| 8 | 数据真实持久化（不是内存态） | `tests/test_06_persistence.py` + 冒烟第 12 组逐表行数对账 | ✅ 通过 |
| 9 | refresh / 组织切换 / 项目切换 / 登录过期行为 | 后端令牌与成员接口 + 冒烟第 7、9 组 | ✅ 通过 |
| 10 | TS 类型检查 + 前端构建 + 关键 E2E 流 | `npm run typecheck && npm run build`（exit 0）+ 冒烟第 13 组 | ✅ 通过 |

**第 10 项的边界要说清楚**：前端「浏览器逐页点选」流程**未用浏览器自动化验证（未验证）**。
冒烟脚本验证的是 HTTP 层面——Vite dev server 的 SPA 回退（`/admin/users`、`/console` 返回 200）、
代理前缀不被剥离、401 经代理仍是统一信封。要补这一项，预期结果是：

```bash
cd frontend && npm install && npx playwright install chromium
# 期望：登录页 → 用管理员账号登录 → 跳转 /admin/dashboard → 用户管理可分页/搜索/禁用，
#       用普通账号登录 → 只看到 /console，访问 /admin/users 被拒并跳回控制台。
```

---

## 9. 未接入清单（明确标记，不做假实现）

以下能力**阶段一没有实现**，接口返回 `hint="未接入"`，前端展示「未接入」而不是 0 值或空表：

AI 智能体编排 · 用例自动生成 · API 用例执行 · UI 自动化执行 · 移动端自动化 ·
数据工厂 · 慢 SQL 分析 · JVM 诊断 · 代码扫描 · 统一编排调度。

看板里的 `test_runs` / `reports` / `defects` 三个统计位都带 `hint="未接入"` 且 `value=0`；
已接入的 `projects` 统计位不会带这个标记。就绪检查在「数据库连不上 / 无启用模型 / 无可用环境」
时返回 `not_ready` 或 `degraded`，不谎报 ready。查询失败显示错误或降级状态，不伪装成零。

后续扩展点已经留好：`app/features/` 下按业务能力分包，
`project_outbound_target`（被测目标连接）、`environment`（环境与网关前缀）、
`model_configuration`（模型域配置）三张表就是接入测试执行链路时的连接与配置底座。
**平台主库与被测目标数据库是两回事**——平台用 PostgreSQL 不意味着将来不能连 MySQL 等目标库。

---

## 10. 已知事项与本次交付中的两次失误（如实记录）

1. **`--database-url` 曾被静默忽略，导致种子数据写错库。**
   `app/shared/database.py` 在首次导入时就用 `settings.DATABASE_URL` 建好 engine，
   而 `seed_admin.py` 原本在导入 `app.shared.config` **之后**才覆盖环境变量，
   结果「迁移打到目标库、种子数据写进 `.env` 里的库」。
   修法：命令行覆盖必须发生在任何 `app` 导入之前。
   已加回归用例 `test_seed_admin_targets_the_database_named_on_the_command_line`
   —— 该用例在修法前失败、修法后通过，且它把失败现场锁在隔离测试库上，不会再碰开发库。

2. **开发库 `testplatform_dev` 曾被误删并重建。**
   执行 `VAR='...' python seed_admin.py --database-url "$VAR" --drop` 时，
   shell 前缀赋值 `VAR=x cmd "$VAR"` 的 `$VAR` 是在赋值生效**之前**展开的，
   于是 `--database-url ""` 为空而 falsy，`--drop` 落到了 `.env` 的开发库上。
   库已用干净参数重建并恢复到「1 个管理员 + 1 个个人组织 + 4 条内置环境、
   0 项目 / 0 模型」的初始状态。
   同类教训已固化到脚本里：`e2e_smoke.sh` 的连接串改走环境变量而不是 argv，
   清理失败必须打印出来，不再静默。

3. **遗留脚本**：`backend/app/scripts/seed_admin.py` 是迁移初期的旧式入口，已不被引用，
   初始化请用 `backend/scripts/seed_admin.py`。

4. **`compose.yaml` 里的 `root` / `fangzhou123` 是单机开发默认值**（监听 127.0.0.1、
   数据在 compose 卷里）。只要 5432 会暴露给局域网或共享机器，先改它并同步 `backend/.env`。

5. **`/healthz` 不带版本前缀**，是部署探活用的；`/readyz`、`/status`、`/ping` 都不存在。
   API 文档在 `/docs`、`/redoc`、`/openapi.json`。
# AI-Test-Project
# AI-Test-Project
# AI-Test-Project
