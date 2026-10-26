---
name: develop-this-project
description: "在本项目（ai-test-project）中做开发任务时使用：启动/停止前后端、跑测试、做 Alembic 迁移、加 feature、加页面、加 API、查 API、看配置、常见故障排查。项目特定事实与命令。**在本项目协作中，所有对话回复必须使用中文。**"
---

# 项目开发指引（ai-test-project）

## ⚠️ 必读规则

**1. 所有回复必须使用中文**

在本项目中与用户 / 团队对话的一切文字产出——Claude 助手回复、代码评审意见、commit message、PR 描述、issue 讨论、错误消息文案、UI 文案、日志里带业务含义的字符串——**统一使用中文**。

例外（保持英文的场景）：
- 标识符、类型名、函数名、变量名、模块路径、API 字段名（`snake_case` / `camelCase`）
- 第三方库、框架、命令、URL、错误码、HTTP 状态码的原始英文/技术名（如 `FastAPI`、`uvicorn`、`pip install`、`404 Not Found`）
- 通用代码约定：`type: ignore`、`noqa`、`TODO`、`FIXME`、`XXX`
- 引用第三方文档原文

**判断标准：如果这句话是给「人」看的解释/描述，用中文；如果是「机器」读的符号/标识符，用英文。**

**2. 每次工作开始前必须完整阅读本文档**

不是扫一眼，是从头到尾读。特别是：
- 本节（必读规则）
- §3–§5（环境、启动、测试）
- §6.4 后端红线
- §7.4 前端常见坑
- §8 API 速查
- §11 故障排查
- §12 Git 分支与提交流程（每次动手前按它开分支，完工按它提交推送）

**3. 另外必须读 [docs/coding-conventions.md](../../../docs/coding-conventions.md)**

里面是中文注释强制要求、架构不变量、17 条红线、变更流程。本文只写日常操作；规则性/结构性内容一律指向 `coding-conventions.md`。

**4. Git 开发必须走功能分支（详见 §12）**

当前主线是 **`develop`**。每个功能 / 任务：**先 `git checkout develop && git pull --ff-only origin develop` 同步最新主线，再按当前功能拉一个 `feature/<功能名>` 新分支开发；开发完毕后在该分支提交并推送。** 禁止直接在 `develop` / `main` 上改代码、直接 commit。

---

## 1. 项目一句话

测试开发平台 monorepo。**后端** FastAPI + PostgreSQL 16 + SQLAlchemy 2.0 + Alembic 1.20；**前端** React 18.3 + TypeScript 5.6 + Vite 5.4 + antd 5.21 + @tanstack/react-query 5.59。全栈 Python 3.11+ / Node 20+，本地开发端口 8001（后端）+ 5173（前端）。

---

## 2. 目录速览

```
backend/
  app/
    main.py                      # create_app；路由只在这里 include_router
    shared/                      # config, database, auth, roles, errors, pagination,
                                 #   notify, rate_limit, passwords, dependencies, request_context
                                 #   Base 只在 database.py 定义
    models/                      # 0001 基线表：identity, project, configuration, notification
    features/                    # 每个 feature 一个目录，service 一律放 services/<name>_service.py
                                 #   users, organizations, projects, captcha, defects,
                                 #   model_configuration, environment_configuration, dashboard,
                                 #   notifications, api_catalog, business, test_management,
                                 #   reports, agent, test_data, tasks
  scripts/                       # seed_admin.py、e2e_smoke.sh（唯一入口）
  alembic/                       # 迁移（当前 head = 0015）
  tests/                         # pytest：test_01 … test_20，另有 test_api_catalog.py
frontend/
  src/
    api/                         # 18 个文件：client + auth/captcha/users/organizations/
                                 #   projects/modelConfigs/environments/dashboard/notifications/
                                 #   notificationChannels/defects/apiCatalog/business/
                                 #   testManagement/reports/agent/testData
    pages/console/               # 控制台页面都是目录 + index.tsx
    pages/admin/                 # 管理端仍是单文件
    pages/auth/
    components/ hooks/ layouts/ types/
```

**API 前缀**：所有端点挂 `/api/v1/*`。Vite dev 代理**不 rewrite**，前缀原样透传。

---

## 3. 环境准备（一次性）

```bash
# 后端
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # 已有 .env 就跳过
export SECRET_KEY=$(python3.11 -c 'import secrets; print(secrets.token_urlsafe(32))')
psql -h 127.0.0.1 -U root -d postgres -c 'DROP DATABASE IF EXISTS testplatform;'
psql -h 127.0.0.1 -U root -d postgres -c 'DROP DATABASE IF EXISTS testplatform_test;'
psql -h 127.0.0.1 -U root -d postgres -c 'CREATE DATABASE testplatform OWNER root;'
psql -h 127.0.0.1 -U root -d postgres -c 'CREATE DATABASE testplatform_test OWNER root;'
.venv/bin/python -m alembic stamp base
.venv/bin/python -m alembic upgrade head
python scripts/seed_admin.py

# 前端
cd ../frontend
npm install
```

生产 `DATABASE_URL` 必须带 `?options=-csearch_path%3D__schema__`（`AUTO_CREATE_SCHEMA` 会据此建 schema 并建表）。

---

## 4. 日常启动 / 停止

```bash
# 终端 A：后端
cd backend && source .venv/bin/activate
export SECRET_KEY=<...>
.venv/bin/uvicorn app.main:app --reload --port 8001

# 终端 B：前端
cd frontend
npm run dev                     # Vite，:5173

# 浏览器（Swagger / Health 走后端 8001；业务 API 走前端 5173）
http://localhost:8001/docs              # Swagger UI（后端）
http://localhost:8001/healthz           # 根路径健康检查（**不带 /api/v1 前缀**），返回 {"status":"ok"}
http://localhost:8001/api/v1/dashboard/ready  # 唯一 readiness 端点，需登录（无 token 返 401）
```

访问 `localhost:5173`（前端）→ Vite 代理 `/api` 到 `127.0.0.1:8001`。联调别端口可：`VITE_API_PROXY_TARGET=http://127.0.0.1:8002 npm run dev`。

**注意**：`/healthz` 和 `/health` 在根路径注册（`@application.get("/healthz", ...)`），**没有**走 `API_PREFIX = "/api/v1"`。这是历史遗留——`/api/v1/healthz` 会 404。

---

## 5. 跑测试

```bash
cd backend
.venv/bin/python -m pytest tests/ -q                 # 全量
.venv/bin/python -m pytest tests/test_08_defects.py -q
.venv/bin/python -m pytest tests/test_08_defects.py::test_xxx -q
```

- 测试**不依赖生产数据**，用独立的 `testplatform_test` 数据库
- `conftest.py` 里 `ApiClient.register()` 会自动 seed 验证码（`_STORAGE[cid] = ...`），业务代码不用管
- 断言 Alembic head：`assert head == "0015"`（`test_01`、`test_10`、`test_18`、`test_22`、`test_29`、`test_30`、`test_32`；新增迁移后同步全部 head 断言）

---

## 6. 后端开发速查

### 6.1 加一个 feature

目录一律按这个来，不再使用根上的 `service.py`：

- 必有：`app/features/<name>/{__init__,schemas,router}.py` + `services/<name>_service.py` + `services/__init__.py`
- 有自己的表：再加 `models/`。0002 及以后的表放这里，**不要**放进 `app/models/`
- 需要时再加 `parsers/`、`providers/`、`runtime/`、`executors/`。没有实现就不要建空目录
- 路由只登记 `app/main.py` 的 `include_router(..., prefix=API_PREFIX)`

- **schemas.py**：Pydantic v2，字段全 snake_case
- **services/<name>_service.py**：`class XxxService:` 类方法，**service 层负责 commit**（router 不 commit）
- **router.py**：`@router.get("/xxx", response_model=...)`，不写库事务

**新增后必须做的三件事**（漏一个 = 迁移/路由静默失败）：
1. 建 feature-local 表：`app/features/<name>/models/`，由 `alembic/versions/000X_*.py` 显式 `op.create_table` 建。**不要**把新模型加进 `app/models/__init__.py`（原因见下）
2. 在 `app/main.py` `create_app()` 里 `include_router(..., prefix=API_PREFIX)`（`API_PREFIX = "/api/v1"`）
3. 新迁移的 `down_revision` 接当前 head，并同步 `backend/tests` 里断言的 `alembic head`

**❌ 绝对不要**把新表 import 进 `app/models/__init__.py`：0001 的 `Base.metadata.create_all` 会认识这张表，与 0002+ 的 `op.create_table` 建表冲突。当前设计是"0001 用 create_all 建基线表，0002+ 用显式 `op.create_table`"（见 [docs/coding-conventions.md](../../../docs/coding-conventions.md) §17 红线 17 与 FAQ）。

### 6.2 数据库迁移

```bash
# 生成新 revision
.venv/bin/python -m alembic revision --autogenerate -m "描述"
# 执行 / 回滚 / 状态
.venv/bin/python -m alembic upgrade head
.venv/bin/python -m alembic downgrade -1
.venv/bin/python -m alembic current

# 空库初始化（stamp + upgrade）
.venv/bin/python -m alembic stamp base
.venv/bin/python -m alembic upgrade head
```

- head 当前是 `0015`：0001 基线 → 0002 bug → 0003 接口管理 → 0004 业务表 → 0005 业务执行 → 0006 测试管理 → 0007 Agent → 0008 报告与通知 → 0009 测试数据中心 → 0010 Mock → 0011 Security → 0012 Web UI → 0013 ZAP 安全扫描 → 0014 Web UI 智能体二期 → 0015 统一任务与持久化调度。新增迁移接实际 head，并同步所有 head 断言
- `--database-url` 可覆盖 `settings.DATABASE_URL`，别硬编码
- 空库必须先 `stamp base` 再 `upgrade head`，否则 Alembic 认不出库

### 6.3 常用脚本

```bash
# 初始化管理员（唯一入口）
python scripts/seed_admin.py --database-url "$DB" --username u --password p

# 端到端冒烟
bash scripts/e2e_smoke.sh
```

### 6.4 必须遵守的红线（详见 coding-conventions.md §2.4）

- **只有 `app/shared/database.py` 里定义 `Base = declarative_base()`**。加新模型时 `from app.shared.database import Base`
- **Alembic `env.py` 必须 import `app.models`**，否则 Alembic 看不到基线表
- **新表不加进 `app/models/__init__.py`**：feature-local 模型靠显式 `000X` 迁移建表；进了 `__init__.py` 会让 `create_all` 也建一遍，与 `op.create_table` 冲突
- **`SessionLocal` 三个参数不能改**：`autocommit=False, autoflush=False, expire_on_commit=False`
- **`notify()` 是 no-throw**，内部 swallow 失败不阻塞主流程
- **跨资源越权统一返 404**（不返 403，避免暴露资源存在性）
- **测试数据库是 `testplatform_test`**，别把测试跑到 `testplatform`
- **验证码字符集**排除 `0/O/1/I/l`（防混淆），**每个字符单独旋转**，**成功即失效**（用后即删）
- **`seed_admin` 输出不能泄露密码 / secret**，只能给 username 与初始密码

---

## 7. 前端开发速查

### 7.1 加一个页面（四步）

以"回归测试"为例，完整流程：

**Step 1** — `src/api/regressions.ts`（新建）：

```ts
import { api } from './client';
import type { Regression, RegressionListQuery, Paginated } from '@/types';

export interface RegressionCreate {
  name: string;
  project_id: number;
}
export interface RegressionUpdate {
  name?: string;
  project_id?: number;
}

export const regressionsApi = {
  list: (p: RegressionListQuery) => api.get<Paginated<Regression>>('/regressions', { params: p }),
  get: (id: number) => api.get<Regression>(`/regressions/${id}`),
  create: (body: RegressionCreate) => api.post<Regression>('/regressions', body),
  update: (id: number, body: RegressionUpdate) => api.put<Regression>(`/regressions/${id}`, body),
  remove: (id: number) => api.delete<void>(`/regressions/${id}`),
};
```

**Step 2** — `src/types/index.ts` 加 `Regression` + `RegressionListQuery` interface

**Step 3** — `src/pages/console/Regressions/index.tsx` 新建（仿 [Defects/index.tsx](../../../frontend/src/pages/console/Defects/index.tsx)）：`export function ConsoleRegressionsPage()`。控制台页面用目录，管理端页面继续用单文件。

**Step 4** — 编辑 [App.tsx](../../../frontend/src/App.tsx) 加 `<Route path="regressions" element={<ConsoleRegressionsPage />} />` + 编辑 [ConsoleLayout.tsx](../../../frontend/src/layouts/ConsoleLayout.tsx) 加 `MENU_ITEMS` 和 `ROUTE_TITLES`（**key 必须等于 `/console/regressions`**，用于菜单高亮）

**完成校验**：`npm run typecheck && npm run build`

### 7.2 页面样板骨架（照抄 [Defects/index.tsx](../../../frontend/src/pages/console/Defects/index.tsx)）

```tsx
export function ConsoleXxxPage() {
  const { message, modal } = App.useApp();          // 别用 antd 静态 message.xxx
  const queryClient = useQueryClient();
  const { currentOrgId } = useConsoleScope();

  const [pagination, setPagination] = useState({ page: 1, page_size: 10 });
  const [keyword, setKeyword] = useState('');
  const [modalState, setModalState] = useState<{mode:'create'} | {mode:'edit'; row: Xxx} | null>(null);
  const [formKey, setFormKey] = useState(0);        // 每次弹窗开 +1 强制重建 Form

  const query = useMemo(() => ({ page: pagination.page, page_size: pagination.page_size, keyword }),
                        [pagination, keyword]);
  const listQuery = useQuery({ queryKey: ['xxx', query], queryFn: () => xxxApi.list(query) });

  const createMutation = useMutation({
    mutationFn: (body: XxxCreate) => xxxApi.create(body),
    onSuccess: () => {
      message.success('已创建');
      queryClient.invalidateQueries({ queryKey: ['xxx'] });  // 前缀固定，不带 query
      setModalState(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });

  if (listQuery.isPending) return <LoadingState />;
  if (listQuery.isError)   return <PageContainer><ErrorState error={listQuery.error} onRetry={listQuery.refetch} /></PageContainer>;

  return (
    <PageContainer>
      {/* 顶部工具栏：所有过滤改动都要 setPagination(p => ({...p, page:1})) */}
      <ResourceTable
        rowKey={r => r.id}
        columns={[...]}
        dataSource={listQuery.data!.items}
        total={listQuery.data!.total}
        pagination={pagination}
        onPaginationChange={setPagination}
        loading={listQuery.isFetching}
      />
      <Modal open={modalState != null} onOk={...} destroyOnClose>
        <Form<XxxFormValues> key={formKey} form={bugForm} layout="vertical" ...>
          ...
        </Form>
      </Modal>
    </PageContainer>
  );
}
```

### 7.3 QueryKey 命名（ConsoleScopeProvider 靠前缀批量失效）

`useQuery({queryKey: ...})` 必须遵守这套约定，否则切组织/项目后 UI 会卡在旧数据上：

- `['organizations']`             —— 全局，不随 scope 变
- `['projects', { orgId: x }]`    —— 切组织失效
- `['project', id, ...]`          —— 单项目相关，切项目失效
- `['bugs', query]`               —— 切组织 + 切项目都失效
- `['dashboard']` `['notifications']` `['xxx', query]`

`invalidateQueries` **用固定前缀**（不带具体 query），因为要刷所有过滤条件下的列表。

### 7.4 常见坑

- **`@/` alias 硬性**：所有 `src/` 内 import 用 `@/xxx`，不用 `../`
- **client baseURL 已含 `/api/v1`**：写 `api.get('/bugs')` 不是 `api.get('/api/v1/bugs')`
- **Vite 代理不 rewrite**：前端调 `/api/v1/xxx` 原样转发，后端必须挂 `/api/v1`
- **tokenStore 存的是 `{token}` 对象**（JSON.stringify 后）：清 localStorage 用 `tokenStore.clear()`（会同时清 `access_token` 和 `user`），别直接 `removeItem`
- **client.ts 不直接 import router**：401 跳转靠 `registerAuthExpiredHandler(handler)` 回调，由 AuthProvider 注册；改登出跳转 → 改 [App.tsx](../../../frontend/src/App.tsx) 里 `AuthShell` 的 `onAuthExpired`
- **message / modal 必须用 `App.useApp()`**：不要用 antd 静态 `message.xxx`（脱离 ConfigProvider，主题不生效）
- **Modal 内 Form 用 `key={formKey}` 强制重建**：不要用 `bugForm.resetFields()`，key 更干净，能同步清掉 antd 内部的 validate status
- **useQuery enabled 控制惰性请求**：弹窗内数据 `enabled: modalState != null`，避免挂载就请求
- **types/index.ts 是唯一契约**：后端字段变化必须同步；每个字段跟 `// 注释`
- **没有 ESLint / Prettier**：靠 `npm run typecheck`（`tsc -b --noEmit`）+ 人工约定，别装 ESLint 假装
- **useAuth().ready 语义**：`!ready` 时守卫全部只转圈，不判权限
- **BugStatus 是中文枚举**：`'待确认' | '处理中' | '已修复' | '已关闭' | '已拒绝'`，别本地化

---

## 8. API 速查

Base URL：`/api/v1/*`（相对前端代理路径；完整 URL `http://localhost:8001/api/v1/...`）

**统一错误体**：`{code, message, request_id}`；`request_id` 由 middleware 注入 `X-Request-ID`，排查时用它 grep 日志。

| 模块 | 端点 |
|---|---|
| Auth | `POST /auth/login` · `POST /auth/register` · `GET /auth/me` |
| Me | `GET /me` · `PATCH /me`（改密，会 invalidate 现有 token）· `GET /me/organizations` · `POST /logout`（204 无 body；服务端无 token 会话，只清本地）|
| Defects | `GET/POST /bugs`（`project_id` 走 query param 跨项目过滤，**没有** `GET /projects/{id}/bugs` 嵌套路由）· `GET/PUT/DELETE /bugs/{bug_id}` |
| Projects | `GET/POST /projects` · `GET/PATCH/DELETE /projects/{project_id}` · `POST /projects/{project_id}/owner`（转移负责人）· `GET /projects/{project_id}/members` · `PUT/PATCH/DELETE /projects/{project_id}/members/{member_id}` · `GET/POST /projects/{project_id}/targets`（**不是 outbound-targets**）· `PATCH/DELETE /projects/{project_id}/targets/{target_id}` |
| Users | `GET/POST /users` · `GET/PATCH/DELETE /users/{user_id}` · `PATCH /users/{user_id}/password` |
| Organizations | `GET/POST /organizations` · `GET/PATCH/DELETE /organizations/{organization_id}` · `POST /organizations/{organization_id}/members` · `PATCH .../members/{user_id}` |
| ModelConfigs | `GET /model-configs/providers` · `GET/POST /model-configs` · `GET/PATCH/DELETE /model-configs/{config_id}` · `POST /model-configs/{config_id}/set-default`（**不是** PATCH `.../default`；**没有** `/validate` 端点）|
| Environments | `GET/POST /environments` · `GET/PATCH/DELETE /environments/{name}`（**按 name 定位，不是 id**）· `POST /environments/{name}/set-default`（**没有** upsert 语义；删除默认环境会 400 拒绝）· **没有** `/headers` 子路由（headers 走 create/update schema）|
| Dashboard | `GET /dashboard/overview`（**不是 `/summary`**）· `GET /dashboard/projects` · `GET /dashboard/ready`（**唯一 readiness 端点**，需登录）· `GET /dashboard/platform`（仅平台管理员）|
| Captcha | `GET /captcha` |
| ApiCatalog（接口管理，23 个端点）| 见 **8.1** |
| Business（业务场景，47 个端点）| 见 **8.2** |
| TestManagement（测试资产 / 套件 / 计划 / 执行）| 见 **8.3** |
| Reports | 见 **8.4** |
| Agent | 见 **8.4** |
| Notifications | 见 **8.4** |
| TestData（Fixture / Provider / Pool / 目标库）| 见 **8.5** |
| Health | `GET /healthz`（**根路径，不带 `/api/v1` 前缀**）· `GET /health`（同样根路径）· 均返回 `{"status":"ok"}` |

**路径参数命名约定**：全项目 `{xxx_id}` 后缀（`bug_id` / `project_id` / `member_id` / `target_id` / `organization_id` / `config_id` / `user_id`），**不是** `{id}`。

---

### 8.1 接口管理 ApiCatalog（23 端点，全部在 `/api/v1` 下）

**模块树（5）**
- `GET /projects/{project_id}/api-modules` · `POST /projects/{project_id}/api-modules`
- `PATCH /api-modules/{module_id}` · `PATCH /api-modules/{module_id}/move` · `DELETE /api-modules/{module_id}`

**接口（6）**
- `GET /projects/{project_id}/apis` · `POST /projects/{project_id}/apis`
- `GET /apis/{api_id}` · `PATCH /apis/{api_id}` · `DELETE /apis/{api_id}` · `PATCH /apis/{api_id}/move`

**请求 / 响应（4）**
- `GET /apis/{api_id}/request` · `PUT /apis/{api_id}/request`（**整体替换**参数+body）
- `GET /apis/{api_id}/responses` · `PUT /apis/{api_id}/responses`（**整体替换**）

**关联（3）**
- `GET /apis/{api_id}/relations` · `POST /apis/{api_id}/relations` · `DELETE /api-relations/{relation_id}`

**历史 / 导入 / 调试（5）**
- `GET /apis/{api_id}/history`（变更记录）
- `POST /projects/{project_id}/apis/import/preview` · `POST /projects/{project_id}/apis/import/confirm` · `GET /projects/{project_id}/api-import-records`
- `POST /apis/{api_id}/debug` —— **仅平台管理员**，且强制校验项目出站目标白名单（scheme/host/port 命中才放行）；默认项目没配 outbound target 时 admin 也会被拒

**注意**：`/apis/{api_id}`、`/api-modules/{module_id}`、`/api-relations/{relation_id}` **不带项目路径前缀**，靠 id 定位后在服务层校验项目可见性。权限：读 viewer+、写 member+、调试 platform admin；不可见项目统一 404 隐藏存在性。

### 8.2 业务场景 Business（47 端点）

**业务域（5）**：`GET|POST /projects/{project_id}/business-domains` · `GET|PATCH|DELETE /business-domains/{domain_id}`

**业务流程（6）**：`GET|POST /projects/{project_id}/business-flows` · `GET /business-flows/{flow_id}` · `GET /business-flows/{flow_id}/detail` · `PATCH|DELETE /business-flows/{flow_id}`

**流程内动作（5）**：`GET|POST /business-flows/{flow_id}/actions` · `PATCH|DELETE /business-actions/{action_id}` · `PATCH /business-flows/{flow_id}/actions/reorder`

**动作子资源（17）**
- 前置条件：`GET|POST /business-actions/{action_id}/preconditions` · `PATCH|DELETE /business-preconditions/{precondition_id}`
- 变量：`GET|POST /business-actions/{action_id}/variables` · `PATCH|DELETE /business-variables/{variable_id}`
- 状态：`GET|POST /business-actions/{action_id}/states` · `PATCH|DELETE /business-states/{state_id}`
- 接口绑定：`GET|POST /business-actions/{action_id}/bindings` · `GET|PATCH|DELETE /business-bindings/{binding_id}`
- 绑定映射：`GET|POST /business-bindings/{binding_id}/mappings` · `PATCH|DELETE /business-api-mappings/{mapping_id}`

**流程变量引用（3）**：`GET|POST /business-flows/{flow_id}/variable-refs` · `DELETE /business-variable-refs/{ref_id}`

**规则（4）**：`GET|POST /projects/{project_id}/business-rules` · `PATCH|DELETE /business-rules/{rule_id}`

**执行（3，0005 已入库）**：`POST /business-flows/{flow_id}/execute` · `GET /business-executions/{execution_id}` · `GET /business-executions/{execution_id}/actions`

### 8.3 测试管理

单路由、无自身前缀。列表走 `/projects/{project_id}/test-*`，详情走资源 id。读 viewer+，写 member+。

- 策略 / 测试点 / 用例 / 套件 / 计划：各自 `GET|POST /projects/{project_id}/test-(strategies|points|cases|suites|plans)`，以及 `GET|PATCH|DELETE /test-*/{id}`
- 用例子资源：`/test-cases/{case_id}/(preconditions|data|fixtures|steps|assertions)`。`fixtures` 是整体 `PUT` 替换
- 套件用例、计划套件：`/test-suites/{suite_id}/cases`、`/test-plans/{plan_id}/suites`
- 执行：`POST /test-plans/{plan_id}/runs` · `GET /projects/{project_id}/test-runs` · `GET /test-runs/{run_id}` · `GET /test-runs/{run_id}/cases`

### 8.4 报告、Agent、通知

- 报告：`POST /test-runs/{run_id}/report` · `GET /projects/{project_id}/reports` · `GET|DELETE /reports/{report_id}` · `POST /reports/{report_id}/regenerate-ai-summary`
- Agent：`GET|POST /projects/{project_id}/agent/sessions` · `GET|DELETE /agent/sessions/{session_id}` · `GET /agent/sessions/{session_id}/workspace` · `POST /agent/sessions/{session_id}/messages`
- 站内通知：`GET /notifications` · `GET /notifications/summary` · `GET /notifications/events` · `POST /notifications/{notification_id}/read` · `POST /notifications/read-all` · `DELETE /notifications/{notification_id}`
- 飞书渠道：`/projects/{project_id}/notification-channels` 与 `/notification-channels/{channel_id}`（含测试发送）

### 8.5 测试数据中心

Fixture、数据资产、Provider、数据池、目标库连接都挂在 `/api/v1` 下，列表走项目前缀，详情走资源 id。

- Fixture：`/projects/{project_id}/fixtures` · `/fixtures/{fixture_id}`（含 steps、outputs、dependencies、generate、cleanup）
- 资产：`/projects/{project_id}/test-data-assets` · `/test-data-assets/{asset_id}`
- Provider：`/projects/{project_id}/data-providers` · `/data-providers/{provider_id}`（enable / disable / test）
- 数据池：`/projects/{project_id}/data-pools` · `/data-pools/{pool_id}/items` · `/data-pool-items/{item_id}`
- 目标库：`/projects/{project_id}/target-databases` · `/target-databases/{connection_id}`（含 ping 与写策略）。生产环境名禁止写库

变量只由测试数据运行时解析：`${env.*}`、`${data.*}`、`${runtime.*}`、`${fixture.KEY.name}`、`${faker.*}`。Agent 不建 Fixture，也不直接执行 SQL。

## 9. 配置速查

### 9.1 环境变量（后端 `backend/.env`）

| Key | 示例 / 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://root:fangzhou123@127.0.0.1:5432/testplatform?options=-csearch_path%3Dtestplatform` | **必需**，注意 URL 编码 |
| `SECRET_KEY` | `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` | **必需**；import 时就 `RuntimeError`，别留占位符 |
| `JWT_ACCESS_TOKEN_EXPIRE_DAYS` | `7` | |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 逗号分隔，**不是** JSON |
| `AUTO_CREATE_SCHEMA` | `False` | 配合 `?options=-csearch_path%3D...` 建 schema |

后端只有 `.env` / `.env.example` 两套；开发默认走 `.env.example`。`.venv` 不进 git。

### 9.2 密码规则（`app/features/users/schemas.py`）

- **注册**：6–100 字符
- **管理员设定的初始密码**：6–100 字符
- **修改密码 old**：6–30 字符
- **修改密码 new**：12–100 字符
- **登录**：接受 1–100（业务层 `SERVICE.validate_password` 会拦）

### 9.3 限流（`app/shared/config.py`，`rate_limit.py` 只做调度）

- **登录**：`AUTH_LOGIN_IP_LIMIT_PER_MINUTE=60`（每分钟同 IP 60 次）+ `AUTH_LOGIN_USERNAME_LIMIT_PER_MINUTE=10`（每分钟同 username 10 次）
- **注册**：`AUTH_REGISTER_IP_LIMIT_PER_HOUR=10`（**每小时**同 IP 10 次；不是每分钟！）
- **验证码签发**：`AUTH_CAPTCHA_IP_LIMIT_PER_MINUTE=30`（每分钟同 IP 30 次）
- 超限统一返 429；测试里 `conftest.py` 已 override 这些阈值

### 9.4 验证码（`app/shared/config.py`）

- `CAPTCHA_TTL_SECONDS=300` · `CAPTCHA_LENGTH=5` · `CAPTCHA_IMAGE_WIDTH=120` · `CAPTCHA_IMAGE_HEIGHT=40`
- **字符集排除** `0/O/1/I/l`
- **存储**：进程内 `dict` + `threading.Lock`，一次性（用后即删），**单进程部署**
- 多 worker / 多实例必须换 Redis，本模块不处理分布式

### 9.5 测试配置

- 数据库：`testplatform_test`（`OWNER root`，root / `fangzhou123`）
- `SECRET_KEY` 必须显式 export
- `conftest.py` 里已 override rate limit，测试不撞限流

---

## 10. 运维命令速查

```bash
# 健康检查（注意：/healthz 和 /health 在根路径，不带 /api/v1）
curl http://localhost:8001/healthz            # → {"status":"ok"}
curl http://localhost:8001/health             # → {"status":"ok"}
curl -H "Authorization: Bearer <token>" http://localhost:8001/api/v1/dashboard/ready  # 需登录

# 查看 alembic 状态
.venv/bin/python -m alembic current
.venv/bin/python -m alembic history | head -20

# 备份数据库
pg_dump -h 127.0.0.1 -U root -d testplatform > /tmp/testplatform.sql

# 生成新 SECRET_KEY（生产）
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'

# 前端构建
cd frontend && npm run build         # 输出到 dist
cd frontend && npm run preview       # 预览 dist 产物
```

---

## 11. 故障排查（症状 → 解）

| 症状 | 解 |
|---|---|
| `RuntimeError: 请设置 SECRET_KEY 环境变量` | `export SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')` 后重启 |
| 500「password cannot be longer than 72 bytes」 | bcrypt 限制；缩短密码或改密码策略；不能绕过 |
| 500「关系 xxx 不存在」 | 跑 `.venv/bin/python -m alembic upgrade head` |
| `OperationalError: relation "pg_backend_pid" does not exist` | 查连接串 `?options=-csearch_path=...`；或去掉 `pg_backend_pid` exclude 列 |
| 403「你没有权限」 | 检查登录用户角色；管理员用 `/admin/*`，普通用户用 `/console/*` |
| 429「过于频繁」 | 登录 IP 60/min、同用户名 10/min；注册同 IP 10/小时；验证码 30/min。等窗口过去或换 IP |
| 400「验证码错误或已过期」 | 验证码一次性、300s 过期；点图片刷新 |
| `Cannot add a child` 循环导入 | `app.features.xxx` 之间**必须 lazy import**；service 层用 `from app.features...` |
| Alembic 看不到 0001 基线表 | `app/models/__init__.py` 没 import 该模型，或 `env.py` 没 import `app.models`。0002 及以后的表不要加进 `__init__.py`，靠对应迁移的 `op.create_table` |
| 空库 `alembic upgrade` 报 head 冲突 | 先 `alembic stamp base` 再 `upgrade head` |
| 登录失败无响应 | 前端 `getErrorMessage(e, '登录失败')`；后端返 401 |
| `npm install` 卡住 | 换 registry 或清 cache：`npm cache clean --force && npm install` |
| Vite 报错代理连不上后端 | 后端没启动；或 `VITE_API_PROXY_TARGET` 写错端口 |

---

## 12. Git 分支与提交流程

### 12.1 分支模型

| 分支 | 角色 | 改法 |
|---|---|---|
| `develop` | **日常开发主线**。所有功能都从它拉分支，所有完成的功能都并回它 | 只接收合并，**禁止在其上直接提交代码** |
| `main` | 发布分支，从 `develop` 合并，保持可部署 | 只有明确要发布时才动 |

远程 `origin` = `https://github.com/Jason-Guillaume/AI-Test-Project.git`。`.git/config` 里**只存干净 URL，不要把 token 写进去**（需要凭据时走 §12.3 的内联 URL）。

### 12.2 开始一个新功能：先同步 develop，再拉功能分支

```bash
git checkout develop
git pull --ff-only origin develop          # 拿到"最新的 develop"，不做 merge commit
git checkout -b feature/<功能短名>          # 按当前功能拉一个全新分支
```

分支命名 `feature/<短横线英文短名>`——见功能，不见人名、不见日期：

- `feature/api-catalog` · `feature/business-executor` · `feature/regression-suite`
- 修 bug 用 `fix/<短名>`；纯技术债用 `chore/<短名>`
- **不要**用 `dev` / `test` / `xxx` / `111` / 人名 / 日期

**一个分支只装一个功能。** 手上还有无关未提交改动时，先提交或 `git stash`，别混着拉分支——否则后面 `git status` 分不清哪些文件属于这次提交。

### 12.3 开发完毕：提交 → 推送

```bash
git status --porcelain                  # 逐行核对：只应有本次功能的改动
git add <本次功能的文件>                  # 不要 git add . 一把梭
git commit -F .git/COMMIT_MSG.txt        # 消息写成文件再 -F（见下）
git push -u origin feature/<功能短名>     # -u 建立上游关联
```

commit message：中文描述变更意图（对齐 coding-conventions §1.1.1），**结尾必须保留署名行**：

```
feat: 接口管理（API Catalog）模块 + 框架首次入库

<body：做了什么、为什么、怎么验证>

Co-Authored-By: Claude Code <noreply@anthropic.com>
```

`git commit -m "中文长消息"` 容易在参数传递上出问题（超时 / 被拦），**统一写成文件用 `-F`**：先把消息写到 `.git/COMMIT_MSG.txt`（在 `.git` 内，不会被提交），提交后删掉。

推送被拒或需要凭据时，用**内联 URL**（不落 config、不落 keychain）：

```bash
git push https://github.com/Jason-Guillaume:<token>@github.com/Jason-Guillaume/AI-Test-Project.git feature/<功能短名>
```

要推的 token 需要 **Contents: Read and write**（classic 即勾 `repo`）。只读 token 的典型症状：`git-upload-pack` 返回 200（能拉）但 `git-receive-pack` 返回 403（推不了）——那是权限不够，**不是**网络 / 代理问题；若连 `GET /user` 都 401，则是 token 无效或已撤销。

### 12.4 合回 develop

```bash
git checkout develop
git pull --ff-only origin develop
git merge --no-ff feature/<功能短名>      # 保留功能分支历史
git push origin develop
```

合并前先 `git pull --rebase origin develop` 把功能分支追平主线，避免落后导致冲突堆积。

### 12.5 分支红线

- **禁止**在 `develop` / `main` 上直接写代码或直接 commit
- **禁止** `git push --force` 到 `develop` / `main`；被拒时先 rebase 再推
- **禁止** `git add .` / `git add -A` 一把梭——本仓库工作树里常年有其他未提交改动，一把梭会把别人的功能一起提交
- **禁止**把 token / 密码 / `.env` / `.claude/settings.local.json` 写进提交或 `.git/config`
- `.env`、`tmp*.txt`、`.venv/`、`node_modules/`、`dist/` 必须始终保持未跟踪（`.gitignore` 已覆盖）
- 迁移文件与功能**同一个 commit**：`alembic/versions/000X_*.py` + 对应模型 + 测试一起走，不要拆成「先代码后迁移」
- 提交前确认 `backend/tests` 里断言的 `alembic head` 与 `alembic/versions/` 最新 revision 一致（改 head 要同步改断言）

## 13. 提交前自检清单

跑一遍这几个才算「改完」：

- [ ] 当前在 `feature/*` / `fix/*` / `chore/*` 功能分支上，**不是** `develop` / `main`（§12）
- [ ] `git status --porcelain` 逐行看过，只包含本次功能的文件（迁移 + 模型 + 测试在同一批）
- [ ] `cd backend && .venv/bin/python -m pytest tests/ -q` 全绿
- [ ] `cd frontend && npm run typecheck && npm run build` 全绿
- [ ] 新增 feature 已同步：`main.py` 注册路由 + `000X` 迁移（`down_revision` 接当前 head）与 `backend/tests` 的 head 断言；新表**没有**加进 `app/models/__init__.py`
- [ ] 新增页面三件套（`types/index.ts` + `App.tsx` 路由 + `ConsoleLayout.tsx` 菜单）都同步了
- [ ] 所有新文件顶部有模块级中文 docstring；每个函数 / 关键节点都有中文注释（见 [coding-conventions.md](../../../docs/coding-conventions.md) §1.2）
- [ ] 没有触碰 coding-conventions §2.4 里的 17 条红线
- [ ] commit message 用中文描述变更意图（对齐 §1.1.1），并带 `Co-Authored-By: Claude Code <noreply@anthropic.com>` 署名行
- [ ] 已 `git push -u origin <功能分支>`；功能完成并已并回 `develop` 且推送（§12.4）

## 14. 交叉引用

- [docs/coding-conventions.md](../../../docs/coding-conventions.md) — 中文注释规则、架构不变量、17 条红线、变更流程（**必读**）
- [docs/development.md](../../../docs/development.md) — 本轮开发日志：交付了什么、验证了什么、什么还没做
- [docs/target-architecture.md](../../../docs/target-architecture.md) — 目标架构与演进方向
- [docs/migration-plan.md](../../../docs/migration-plan.md) — 从旧项目迁移的路径
- [docs/current-system-analysis.md](../../../docs/current-system-analysis.md) — 现状分析

**版本**：v1.5（2026-10-23）——对齐 Web UI 智能体二期。该版本交付时 Alembic head 为 `0014`；当前仓库已推进至 `0015`。变更 head 后同步更新本文 §2、§5、§6.2 及全部对应测试断言。

**v1.4 → v1.5 变更**：
- 0014 创建两张表：web_agent_session（受控浏览器会话）、web_agent_step（步骤提案/结果，加密落库）。会话与步数预算上限分别为 2 与 100。
- Agent 主图新增 web 节点组与循环边：observe→decide→act→observe，`web_step_review` 为新增 `interrupt_before` 暂停点；人工只经 confirm_web_step 执行单步。
- 意图枚举新增 `INTERACTIVE_WEB_AUTHORING`（intent.md 升到 TEST_INTENT_PROMPT_V2）；该意图必须由 intent.py 把「Web 受控会话绑定」信号写进 user content，否则模型无依据可选。

**v1.3 → v1.4 变更**：

- §2 去掉已删除的 `app/scripts` 与 `app/bootstrap`；feature 补到 test_data；前端 API 改为 18 个文件；控制台页面统一为目录
- §5 / §6.2 head 从 `0004` 改为 `0009`，并写明 0005–0009 各管什么
- §6.1 目录标准改为一律 `services/<name>_service.py`，路由只登记 `main.py`
- §7.1 新页面示例改为 `pages/console/<Name>/index.tsx`
- §8 补测试管理、报告、Agent、通知、测试数据；业务执行端点改为已入库
- §11 限流数字与 §9.3 对齐；「看不到新表」不再要求把 0002+ 模型加进 `app/models/__init__.py`

**v1.2 → v1.3 变更**：

- 必读规则新增第 4 条：git 开发必须走功能分支
- 新增 §12：`develop` 为主线、`feature/<功能名>` 分支模型、同步 develop → 拉分支 → 提交推送 → 合回四步流程、分支红线
- §13 自检清单新增：当前分支检查、`git status --porcelain` 逐行核对、署名行、推送与合并回 `develop`
- 版本说明里的 head 从 `0002` 更正为 `0004`；原「§5.2」更正为「§5」（§5 无子节）
- 新增 §8.1 / §8.2：ApiCatalog 23 个端点、Business 47 个端点全量清单（§8 原本只覆盖到 Defects/Projects 等 11 个模块，两个新模块没有端点表）
- §6.1 修正「新增表注册」错误：原文要求把新模型加进 `app/models/__init__.py`，与 coding-conventions 红线 17 / FAQ 直接冲突（会让 `create_all` 与 `op.create_table` 建表冲突）；改为 feature-local 表 + 显式 `000X` 迁移，并把「新迁移接 head + 同步测试断言」补为第四条
- §6.4 补同款红线；§6.1 补大 feature 的 `models/` + `services/` + `parsers/` 分层结构
- §2 目录速览补 `api_catalog`、`business`；api/ 「12 个 client」更正为 13 个文件；console 页面「6」更正为 8

**v1.0 → v1.1 修正**（Ultracode 验证发现的原稿错误，均已改正）：

- §8 Auth：`DELETE /logout` → `POST /logout`（204）
- §8 Defects：删除 `GET /projects/{id}/bugs`（不存在）；`project_id` 走 query param
- §8 Projects：`outbound-targets` → `targets`；补全 owner transfer / members PUT+PATCH+DELETE
- §8 ModelConfigs：删除 `POST /model-configs/validate`（不存在）；`PATCH /model-configs/{id}/default` → `POST /model-configs/{config_id}/set-default`
- §8 Environments：`/{id}` → `/{name}`；无 upsert；无 `/headers` 子路由
- §8 Dashboard：`/summary` → `/overview`；补 `/ready` 和 `/platform`
- §8 Health：`/healthz` 与 `/health` 在**根路径**（不带 `/api/v1`），不是 `/api/v1/healthz`
- §9.3 限流：登录 5/min → 60/min（IP）+ 10/min（username）；注册 3/min → 10/**小时**；数字来自 `config.py`
- §4 启动步骤：`/api/v1/healthz` → `/healthz`（根路径）
- 路径参数命名约定统一为 `{xxx_id}` 后缀


## 15. Web UI Automation Phase 1（2026-10-19）

- 入口：`/console/web-ui`；实现：`backend/app/features/web_ui/`、`frontend/src/pages/console/WebUI/`。
- 用例及步骤继续使用 `TestCase` / `TestStep`，`target_type=WEB`；`web_case` 只保存浏览器扩展配置与确认指纹，不另建执行体系。
- 调试与计划都经过 `RunService` → Fixture / Mock 生命周期 → `TestCaseExecutor` → Playwright → `CaseExecution` → 原有报告。
- 只允许 NAVIGATE / CLICK / FILL / SELECT / UPLOAD / WAIT / ASSERT。不得执行用户或 LLM 原始 Python/JavaScript。
- 定位优先 TEST_ID / ROLE / LABEL / TEXT，CSS / XPath 仅显式兜底；新页面对象必须提供稳定元素 key。
- 账号、Cookie、LocalStorage/JWT、人工扫码后导入的 storage_state 加密存储。敏感填入值必须引用变量，例如 `${data.auth_password}`。
- 用例、页面元素或认证配置修改后必须重新人工确认；Agent 只能生成未确认草稿。执行器再次验证指纹，通用测试计划也不能绕过确认。
- 每次执行独立 Chromium 进程和 BrowserContext；进程内 Web 专属并发上限 2，不连接用户浏览器或 ZAP 会话。
- 只允许项目已授权的 scheme/host/port；拦截页面、子资源与重定向，禁用 Service Worker 和 WebSocket，冻结执行 DNS。
- 0012 创建四张扩展表：web_page_object、web_auth_profile、web_case、web_artifact；0013 建 ZAP 扫描表；0014 建 web_agent_session / web_agent_step。迁移保持 seed_admin 重复初始化幂等。后续迁移接实际最新 head。
- 浏览器安装：`cd backend && .venv/bin/python -m playwright install chromium`。
- 定向验证：`cd backend && .venv/bin/python -m pytest tests/test_30_web_ui.py tests/test_31_web_ui_console.py -q`。
- 头版本断言已扩展到 test_22 与 test_30；不要只按旧 test_01 / test_10 / test_18 清单更新。
- 飞书真实租户扫码与外部真实 LLM 属于需要账号/配置的集成验证；一期提供人工完成登录后的 state 导入和平台模型生成入口，不虚报外部服务已验收。
- 交付报告：`docs/web-ui-automation-phase1-delivery-report.md`。
