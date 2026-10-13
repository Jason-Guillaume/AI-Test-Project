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

**3. 另外必须读 [docs/coding-conventions.md](../../../docs/coding-conventions.md)**

里面是中文注释强制要求、架构不变量、17 条红线、变更流程。本文只写日常操作；规则性/结构性内容一律指向 `coding-conventions.md`。

---

## 1. 项目一句话

测试开发平台 monorepo。**后端** FastAPI + PostgreSQL 16 + SQLAlchemy 2.0 + Alembic 1.20；**前端** React 18.3 + TypeScript 5.6 + Vite 5.4 + antd 5.21 + @tanstack/react-query 5.59。全栈 Python 3.11+ / Node 20+，本地开发端口 8001（后端）+ 5173（前端）。

---

## 2. 目录速览

```
backend/
  app/
    main.py                      # create_app 入口
    shared/                      # config, database, auth, roles, errors, pagination,
                                 #   notify, rate_limit, passwords, dependencies, request_context
    models/                      # user, organization, project, bug (+ Base 只做再导出)
    features/                    # 每个 feature 一个目录：users, organizations, projects,
                                 #   model_configuration, environment_configuration, dashboard,
                                 #   notifications, captcha, defects
    scripts/                     # ⚠️ legacy，勿新增
  scripts/                       # 顶层脚本（seed_admin.py、e2e_smoke.sh）
  alembic/                       # 迁移（当前 head = 0002）
  tests/                         # pytest 套件
frontend/
  src/
    api/                         # 12 个 client（auth/captcha/users/orgs/projects/modelConfigs/
                                 #   envs/dashboard/notifications/defects/client）
    pages/{console,admin,auth}/  # 6 admin + 6 console + 2 auth
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
.venv/bin/python -m app.scripts.seed_admin        # 或顶层 backend/scripts/seed_admin.py

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
- 断言 Alembic head：`assert head == "0002"`

---

## 6. 后端开发速查

### 6.1 加一个 feature

标准 4 文件：`app/features/<name>/{__init__,schemas,service,router}.py`

- **schemas.py**：Pydantic v2，字段全 snake_case
- **service.py**：`class XxxService:` 类方法，**service 层负责 commit**（router 不 commit）
- **router.py**：`@router.get("/xxx", response_model=...)`，不写库事务

**新增后必须做的三件事**（漏一个 = 迁移/路由静默失败）：
1. 在 `app/models/__init__.py` 加 `from app.models.<name> import Model`（否则 Alembic 看不到）
2. 在 `app/main.py` `create_app()` 里 `include_router(..., prefix=API_PREFIX)`（`API_PREFIX = "/api/v1"`）
3. 在 `app/bootstrap/routes.py` 同步登记（虽未被运行期引用，但 docstring 声明是装配点，保持同步）

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

- head 当前是 `0002`（bug 表）；改测试断言记得跟着改
- `--database-url` 可覆盖 `settings.DATABASE_URL`，别硬编码
- 空库必须先 `stamp base` 再 `upgrade head`，否则 Alembic 认不出库

### 6.3 常用脚本

```bash
# 冒烟脚本（顶层 scripts/ 优先；app/scripts/ 是 legacy）
.venv/bin/python -m app.scripts.seed_admin            # legacy
python scripts/seed_admin.py --database-url "$DB" --username u --password p

# 端到端冒烟
bash scripts/e2e_smoke.sh
```

### 6.4 必须遵守的红线（详见 coding-conventions.md §2.4）

- **只有 `app/shared/database.py` 里定义 `Base = declarative_base()`**，`app/models/base.py` 只做再导出——加新模型时 `from app.models.base import Base` 即可
- **Alembic `env.py` 必须 import `app.models`**，否则 Alembic 看不到表
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

**Step 3** — `src/pages/console/Regressions.tsx` 新建（仿 [Defects.tsx](../../../frontend/src/pages/console/Defects.tsx)）：`export function ConsoleRegressionsPage()`

**Step 4** — 编辑 [App.tsx](../../../frontend/src/App.tsx) 加 `<Route path="regressions" element={<ConsoleRegressionsPage />} />` + 编辑 [ConsoleLayout.tsx](../../../frontend/src/layouts/ConsoleLayout.tsx) 加 `MENU_ITEMS` 和 `ROUTE_TITLES`（**key 必须等于 `/console/regressions`**，用于菜单高亮）

**完成校验**：`npm run typecheck && npm run build`

### 7.2 页面样板骨架（照抄 [Defects.tsx](../../../frontend/src/pages/console/Defects.tsx)）

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
| Health | `GET /healthz`（**根路径，不带 `/api/v1` 前缀**）· `GET /health`（同样根路径）· 均返回 `{"status":"ok"}` |

**路径参数命名约定**：全项目 `{xxx_id}` 后缀（`bug_id` / `project_id` / `member_id` / `target_id` / `organization_id` / `config_id` / `user_id`），**不是** `{id}`。

---

## 9. 配置速查

### 9.1 环境变量（后端 `backend/.env`）

| Key | 示例 / 默认 | 说明 |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://root:fangzhou123@127.0.0.1:5432/testplatform?options=-csearch_path%3Dtestplatform` | **必需**，注意 URL 编码 |
| `SECRET_KEY` | `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` | **必需**；import 时就 `RuntimeError`，别留占位符 |
| `JWT_ACCESS_TOKEN_EXPIRE_DAYS` | `7` | |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 逗号分隔，**不是** JSON |
| `AUTO_CREATE_SCHEMA` | `True` | 配合 `?options=-csearch_path%3D...` 建 schema |

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
| 429「过于频繁」 | 登录 ≤5/min · 注册 ≤3/min · captcha ≤30/min；等一分钟或换 IP |
| 400「验证码错误或已过期」 | 验证码一次性、300s 过期；点图片刷新 |
| `Cannot add a child` 循环导入 | `app.features.xxx` 之间**必须 lazy import**；service 层用 `from app.features...` |
| Alembic 看不到新表 | `app/models/__init__.py` 没 import；Alembic `env.py` 没 import `app.models` |
| 空库 `alembic upgrade` 报 head 冲突 | 先 `alembic stamp base` 再 `upgrade head` |
| 登录失败无响应 | 前端 `getErrorMessage(e, '登录失败')`；后端返 401 |
| `npm install` 卡住 | 换 registry 或清 cache：`npm cache clean --force && npm install` |
| Vite 报错代理连不上后端 | 后端没启动；或 `VITE_API_PROXY_TARGET` 写错端口 |

---

## 12. 提交前自检清单

跑一遍这几个才算「改完」：

- [ ] `cd backend && .venv/bin/python -m pytest tests/ -q` 全绿
- [ ] `cd frontend && npm run typecheck && npm run build` 全绿
- [ ] 新增 feature 三件套（`models/__init__.py` + `main.py` + `bootstrap/routes.py`）都同步了
- [ ] 新增页面三件套（`types/index.ts` + `App.tsx` 路由 + `ConsoleLayout.tsx` 菜单）都同步了
- [ ] 所有新文件顶部有模块级中文 docstring；每个函数 / 关键节点都有中文注释（见 [coding-conventions.md](../../../docs/coding-conventions.md) §1.2）
- [ ] 没有触碰 coding-conventions §2.4 里的 17 条红线
- [ ] commit message 用中文描述变更意图（对齐 §1.1.1）

## 13. 交叉引用

- [docs/coding-conventions.md](../../../docs/coding-conventions.md) — 中文注释规则、架构不变量、17 条红线、变更流程（**必读**）
- [docs/development.md](../../../docs/development.md) — 本轮开发日志：交付了什么、验证了什么、什么还没做
- [docs/target-architecture.md](../../../docs/target-architecture.md) — 目标架构与演进方向
- [docs/migration-plan.md](../../../docs/migration-plan.md) — 从旧项目迁移的路径
- [docs/current-system-analysis.md](../../../docs/current-system-analysis.md) — 现状分析

**版本**：v1.2（2026-10-12）——与 Alembic head `0002` 对齐。Alembic head 变更后同步更新本 skill 的 §5.2 与 §6.2。

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
