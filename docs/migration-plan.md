# 迁移计划：TestPilot → 测试开发平台

**阶段口径：第一阶段（Phase 1，已交付）/ 后续阶段（未交付）**

- 阅读对象：资深全栈工程师、项目评审人
- 事实来源：新项目 `/Users/a1/Desktop/ai-test-project`（可读可写）与旧项目 `/Users/a1/Desktop/test-projects`（只读参考）。本文每一条差异都来自实际读到的代码，并在文末「风险与后续行动」中标出未能从代码确认的点。
- 未执行过的验证项一律写「未验证」并给出预期结果，不写「通过」。
- 本文中不出现任何明文密钥、密码或 API Key。

---

## 1. 阶段划分与「未接入」边界

### 1.1 第一阶段（Phase 1，已交付）范围与验收点

第一阶段只做「人、组织、项目、配置、通知、看板」这一层的管理与鉴权骨架，不接任何执行类能力。

| 域 | 交付内容 | 后端入口 | 验收点 |
| --- | --- | --- | --- |
| 认证 | 注册、登录、登出、当前用户、改密、我的组织 | `app/features/users/auth.py` | `POST /api/v1/login` 返回 `access_token` + `expires_in` + `user` |
| 用户管理 | 管理员增删改查、关键字与启用状态过滤 | `app/features/users/admin.py` | 非管理员访问返回 403 `ERR_FORBIDDEN` |
| 组织 | 组织 CRUD、成员、模型授权、负责人转移 | `app/features/organizations/router.py` | 创建组织自动生成 `owner` 成员行 |
| 项目 | 项目 CRUD、成员、出站目标、负责人转移 | `app/features/projects/router.py` | viewer 角色写操作被拒 |
| 模型配置 | 平台级模型连接配置的 CRUD、默认项归一化 | `app/features/model_configuration/router.py` | 响应只含 `has_api_key` / `masked_api_key` |
| 环境配置 | 执行环境 CRUD、按名寻址、内置环境回退 | `app/features/environment_configuration/router.py` | 读写接口全部仅平台管理员可用 |
| 通知 | 个人收件箱、已读、未读角标、事件目录 | `app/features/notifications/router.py` | 新增 `notification` 表；由 `app/features/users/service.py::_emit` 在 3 个用户域动作处写入（`user.created` / `user.updated` / `user.password_changed`），见风险 R3 |
| 看板 | 个人总览、项目概况、依赖就绪、平台统计 | `app/features/dashboard/router.py` | 未迁移业务以 `value=0, hint="未接入"` 返回 |
| 基础设施 | 统一错误体、统一分页、JWT 撤销、请求 ID、限流 | `app/shared/` | 9 张表由 Alembic `0001` 建立 |

### 1.2 后续阶段（未交付）清单 —— 全部标记「未接入」

这些能力在旧项目里都有代码和页面，但**第一阶段完全没有迁移，也没有任何运行时入口**。文档与评审中不得把它们描述成「已实现」或「可用」。

| 能力 | 旧项目位置 | 第一阶段状态 | 计划接入点 |
| --- | --- | --- | --- |
| AI 智能体 | `test_project_back/app/agent/`、`test_project_front/src/views/agent/` | 未接入 | `app/features/agent/`（复用 `model_configuration` + `project_outbound_target`） |
| 用例管理（用例 CRUD、目录、XMind 导入导出） | `app/features/test_cases/`（含 `xmind_io.py`、`xmind_service.py`）、`views/testcase/TestCaseManagement.vue`、`views/test-design/` | 未接入 | `app/features/test_cases/`（与旧模块同名，注意不要误以为已迁移） |
| 用例生成 | `app/features/case_generation/`、`script_generation/` | 未接入 | `app/features/test_cases/` 或独立的生成子域 |
| API 执行 | `app/features/automation/`、`app/agent/api/execute.py` | 未接入 | `app/features/execution/`（消费 `environment.base_url`） |
| UI 自动化 | `app/features/visual_automation/` | 未接入 | `app/features/visual_automation/` |
| 移动端控制 | `app/features/mobile_automation/` | 未接入 | `app/features/mobile_automation/` |
| 数据工厂 | `app/features/data_factory/` | 未接入 | `app/features/data_factory/` |
| 慢 SQL 分析 | `app/features/slow_sql/`、`sql_log/` | 未接入 | `app/features/slow_sql/` |
| JVM 诊断 | `app/features/jvm_monitoring/` | 未接入 | `app/features/jvm_monitoring/` |
| 代码扫描 | `app/features/code_analysis/` | 未接入 | `app/features/code_analysis/` |
| 统一编排 | `app/agent/api/orchestration.py` | 未接入 | `app/features/orchestration/` |
| 测试报告 | `app/agent/api/reports.py`（`GET /reports`、`/reports/{id}`、`/reports/{id}/download`）、`app/agent/reporting/`、`views/report/` | 未接入 | 看板 `reports` 卡片（现为 `hint="未接入"`） |
| 缺陷管理 | `app/features/defects/`、`views/bug/` | 未接入 | 看板 `defects` 卡片（现为 `hint="未接入"`） |
| 可观测性 / 回收站 / 知识库 / 资产库 / 套件 | `observability/`、`recycle-bin/`、`knowledge/`、`assets/`、`suites/` | 未接入 | 随对应业务域一起迁移 |
| 覆盖率中心 / 数据库连接 / 测试设计器 | `views/coverage-center/CoverageCenter.vue`、`views/database/DatabaseConnections.vue`、`views/test-design/` | 未接入 | 分别随 API 执行、数据工厂、UI 自动化一起迁移 |
| 通知引擎（模板 / 渠道 / 发送 / 测试发送） | `app/features/notifications/api/router.py` 的 templates、configs、subscriptions、`/send`、`/test` | 未接入 | `app/shared/notify.py` 目前只负责「写入收件箱」，没有任何发送通道 |

### 1.3 两个必须分清的概念

**平台主库（PostgreSQL 16）和被测目标数据库不是一回事，也不是二选一。**

- 平台主库：只存平台自身的用户、组织、项目、配置、通知。本地由 `compose.yaml` 起一个 `postgres:16`（容器名 `testplatform-postgres`，端口 5432，库名 `testplatform_dev`），凭据在 `compose.yaml` 与 `.env` 中，本文不复制。
- 被测目标数据库：被测服务自己的库。平台通过 `environment.base_url` 指过去，**第一阶段不连接、不托管、不迁移**。`compose.yaml` 顶部注释已明确「仅平台主库」。
- 代码侧印证：`app/models/configuration.py` 的 `Environment.base_url` 只是字符串配置；第一阶段没有任何连接池指向它。

---

## 2. 旧→新迁移总对照表

> 旧项目前端 `baseURL` 为 `/api`，而 Vite 代理会把 `/api` 前缀**删掉**再转发，所以下表「旧 API」列写的是**后端真实收到的路径**。新项目不做删除，「新模块」列写的是对外完整路径。

| 旧页面 | 旧 API | 相关数据表 | 新模块 | 迁移方式 | 阶段 | 验收标准 |
| --- | --- | --- | --- | --- | --- | --- |
| `views/auth/Login.vue`、`Register.vue` | `POST /users/login`、`POST /users/register` | `user` | `app/features/users/auth.py` → `/api/v1/login`、`/api/v1/register`、`/api/v1/me`、`PATCH /api/v1/me`、`/api/v1/me/organizations`、`POST /api/v1/logout` | 路由统一挂 `/api/v1`；响应体新增 `expires_in`；注册即建个人组织，保证新账号立刻能建项目 | 第一阶段（Phase 1，已交付） | 登录返回 `expires_in=28800`；重复注册 409 `ERR_CONFLICT`「用户名已存在」 |
| `views/user/UserManagement.vue` | `GET/POST /users/`（`skip`/`limit`）、`GET/PUT/DELETE /users/{id}`、`PUT /users/me/password` | `user` | `app/features/users/admin.py` → `GET/POST /api/v1/users`、`GET/PATCH/DELETE /api/v1/users/{id}` | 分页改 `page`/`page_size`；改密从 `PUT /me/password` 收敛为 `PATCH /me`（请求体为 `PasswordChange`）；新增 `keyword`/`is_active` 过滤 | 第一阶段（Phase 1，已交付） | 非管理员 `GET /api/v1/users` → 403 |
| `views/project/OrganizationManagement.vue` | `GET/POST /organizations`、`PATCH` 无、`GET /{id}/members`、`GET /{id}/candidates`、`GET /{id}/models` | `organization`、`organization_member` | `app/features/organizations/router.py` | 列表从裸 `{items}` 改为 `{items,total,page,page_size}`；新增 `PATCH /{id}` 改名与 `POST /{id}/members/{mid}/upgrade` 转移负责人 | 第一阶段（Phase 1，已交付） | 新建组织后成员行 `role=owner`，`organization.owner_id` 指向创建者 |
| `views/project/OrganizationManagement.vue`（成员与模型授权抽屉） | `PUT /organizations/{id}/members/{userId}`（`MemberGrant`：`role` 仅 `member\|admin`、`agent_enabled`、`allowed_model_ids`） | `organization_member`（`agent_enabled`、`allowed_model_ids JSON`） | `app/features/organizations/service.py::upsert_member` | 幂等 upsert 固定 200；`role` 允许 `owner`；`agent_enabled=false` 时清空 `allowed_model_ids`；分配的模型必须存在且启用 | 第一阶段（Phase 1，已交付） | 同一成员重复 `PUT` 两次均 200，且表内无重复行 |
| `views/project/ProjectManagement.vue` | `GET/POST /project/`（`skip`/`limit`/`name`）、`GET/PUT/DELETE /project/{id}` | `project`、`project_member` | `app/features/projects/router.py` → `/api/v1/projects` | 路径复数化；分页改 `page`/`page_size`/`keyword`/`organization_id`；详情内联成员列表 | 第一阶段（Phase 1，已交付） | 可见项目列表随组织边界过滤；不可见项目详情 404「项目不存在」 |
| `views/project/ProjectManagement.vue`（成员抽屉） | `POST /project/{id}/members`（后端存在）；`GET /project/{id}/member-candidates`、`GET /project/people`（**只在旧前端 `src/api/project.js` 里有调用点，旧后端从未实现这两个路由**） | `project_member` | `app/features/projects/service.py` → `PUT/PATCH/DELETE /api/v1/projects/{id}/members/{mid}`、`POST /api/v1/projects/{id}/owner` | 增改合并为幂等 `PUT`；成员必须是项目所属组织的成员；负责人不需要也不得单独加入成员表 | 第一阶段（Phase 1，已交付） | viewer 成员调用成员管理接口 403 |
| `views/project/ProjectManagement.vue`（出站目标抽屉） | `GET/POST /project/{id}/outbound-targets`、`DELETE /project/{id}/outbound-targets/{targetId}`（**只在旧前端 `src/api/project.js` 里有调用点，旧后端从未实现这三个路由**；旧项目对 `project_outbound_target` 唯一的后端使用点是 `app/shared/outbound_policy.py` 的内部策略校验，没有任何 HTTP 端点） | `project_outbound_target` | `app/features/projects/router.py` → `GET/POST /api/v1/projects/{id}/targets`、`PATCH/DELETE /{id}/targets/{target_id}` | 旧项目等于「有页面、无接口」，新平台是**第一次真正接通这条链路**；路径随项目复数化；`scheme` 仅 http(s)、`host` 禁止含 `:`/`[`、`is_production=true` 必须 https | 第一阶段（Phase 1，已交付） | 表结构（含 `uq_project_outbound_target`）与旧项目逐列一致 |
| `views/settings/ModelSettings.vue` | `GET/POST /agent/model-configs`、`GET/PUT/DELETE /agent/model-configs/{id}`、`PUT /{id}/default`、`POST /{id}/test`、`POST /provider-models` | `model_configuration` | `app/features/model_configuration/router.py` → `GET /api/v1/model-configs/providers`、`GET/POST /api/v1/model-configs`、`GET/PATCH/DELETE /{id}`、`POST /{id}/set-default` | 从 `/agent/` 下迁出为一级模块；`/test` 与 `/provider-models` **不迁移（未接入，属模型调用链路）**；Fernet 密钥沿用 `SHA256(SECRET_KEY)` 派生（若设置了 `MODEL_CONFIG_ENCRYPTION_KEY` 则以其为材料，见 7.3）；更新由 `PUT` 改 `PATCH`；`/default` 改为 `/set-default` 且用 `POST` | 第一阶段（Phase 1，已交付） | 响应中不存在 `api_key_encrypted`；非管理员 403 |
| `views/settings/TargetServiceManagement.vue`（页面标题就是「环境配置」，另有配套 `views/settings/environmentConfig.js`） | `GET /agent/environments`、`POST /agent/environments`（upsert 语义，`is_default` 在请求体里）、`DELETE /agent/environments/{name}` | `environment` | `app/features/environment_configuration/router.py` → `GET/POST /api/v1/environments`、`GET/PATCH/DELETE /api/v1/environments/{name}`、`POST /{name}/set-default` | 从智能体模块迁出为一级模块（页面本身照旧保留，只是后端路由换了前缀）；**读写全部仅平台管理员**（旧项目读是登录即可，写限管理员）；默认项从请求体内的 `is_default` 拆成独立的 `POST /{name}/set-default`；表空时回退内置 `dev/test/staging/prod` | 第一阶段（Phase 1，已交付） | 非管理员 `GET /api/v1/environments` → 403 |
| `views/notifications/NotificationCenter.vue`（模板 / 渠道 / 订阅配置台） | `/notifications` 下的 templates、configs、subscriptions、`/send`、`/test`、`/channels`、`/events` | **旧项目没有个人通知表**，只有 `notification_template`、`notification_config`、`notification_subscription` | `app/features/notifications/router.py` + `app/models/notification.py`（**新增 `notification` 表**） | 只保留收件箱与已读；模板 / 渠道 / 发送通道属通知引擎，**未接入**；`/events` 改为从内置 `EVENT_LABELS` 出目录 | 第一阶段（Phase 1，已交付） | `GET /api/v1/notifications/summary` 返回 `unread_total` |
| `views/dashboard/Dashboard.vue` | `/dashboard` 前缀下的 6 个子端点：`GET /dashboard/status`（概况）、`/execution-trend`、`/risk`、`/recent-tasks`、`/defect-analysis`、`/expiring`（旧项目没有单一的 `GET /dashboard`） | 依赖测试执行、缺陷等表（旧项目专有：`ExecutionRecord`、`Bug`、`TestCase`、`ApiTestCase`） | `app/features/dashboard/router.py` → `/api/v1/dashboard/overview`、`/projects`、`/ready` | 重做为「当前用户可见范围」口径，响应带 `scope`；`test_runs`/`reports`/`defects` 三项 `value=0` 且 `hint="未接入"`；新增 `/ready` 做依赖就绪检查 | 第一阶段（Phase 1，已交付） | `/ready` 返回 `ready` / `degraded` / `not_ready` 真实状态，不恒定报 ready |
| `views/dashboard/Dashboard.vue`（平台部分） | `GET /dashboard`（平台口径） | `user`、`organization`、`project`、`model_configuration`、`environment` | `app/features/dashboard/router.py` → `GET /api/v1/dashboard/platform` | 独立端点 + 平台管理员门槛；统计全平台计数 | 第一阶段（Phase 1，已交付） | 非管理员 → 403「仅管理员可查看平台统计」 |

---

## 3. 字段与分页差异

| 项 | 旧 | 新 | 原因 |
| --- | --- | --- | --- |
| 分页参数 | `skip=0` + `limit`（用户/项目 `le 500`，模型 `le 200`，默认 10 / 100 / 50） | `page`（`ge=1`，默认 1）+ `page_size`（`ge=1`，`le=200`，默认 20）+ `keyword` | 旧项目每个接口各自实现偏移分页；新项目集中为 `app/shared/pagination.py`，页码比偏移对前端分页控件更直观 |
| 列表响应 | `{total, items}` | `{items, total, page, page_size}`（通知接口额外带 `unread_total`） | 前端 TanStack Query 需要 `page`/`page_size` 才能判断是否还有下一页 |
| 错误响应体 | `{"detail": "..."}` | `{"code", "message", "request_id"}` | 前端需要按 `code` 走分支，`request_id` 对应后端日志里的同一条链路 |
| 认证响应 | `{access_token, token_type, user}` | 额外返回 `expires_in`（秒） | 前端要显示会话剩余时长，否则只能自己猜过期时间 |
| JWT 声明 | `sub` / `exp` / `ver` | `sub` / `exp` / `ver`（一致） | 保留旧项目的撤销语义，前端无需改令牌解析 |
| 平台角色取值 | `admin` / `test` / `dev` | 一致 | — |
| 组织角色取值 | 入参 `role` 只允许 `member\|admin` | 允许 `owner` / `admin` / `member`，并额外返回虚拟 `platform_admin` | 旧接口无法直接授予负责人身份；新项目仍通过 `organization.owner_id` 表达负责人，虚拟角色由服务层推导、不落库 |
| 项目角色取值 | `viewer` / `member` / `editor` + 虚拟 `owner` / `admin` | 一致（`RANKS` 0/1/2/3/4） | — |
| 注册密码长度 | 最小 **12**，最大 100 | 最小 **6**，最大 100 | 旧的 12 位下限会让管理员分发的短初始密码在用户改密时被校验拦下（见 `AdminUserCreate` 注释，管理员建号同样改为 6） |
| 改密长度 | 旧密码 6–30、新密码 12–100 | 完全一致 | 无需变更 |
| 用户名 | 3–50 | 3–50，新增 `strip` 校验器 | 去掉首尾空白，避免「 admin 」与「admin」被视为两个账号 |
| 组织成员负责人行 | 旧 `PUT members` 时若目标是组织负责人会强制 `row.role = "owner"`（`row.role = "owner" if org.owner_id == member_id else body.role`） | 新不再强制回写 `owner`：`row.role = requested_role`，但组织负责人行**只允许** `owner`/`admin`，传 `member` 会被 403 拒绝（「组织负责人至少需要组织管理员角色；如需转移负责人，请使用转移接口」）；负责人身份仍以 `organization.owner_id` 为准 | 旧写法把负责人的成员行锁死在 `owner`，而 `MemberGrant.role` 只允许 `member\|admin`，想降级再转移会校验失败；新写法允许直接降级到 `admin`，但仍不允许降到 `member`（否则该组织在成员表里没有任何管理员） |
| 项目路径 | `/project`（单数） | `/projects`（复数） | REST 命名统一 |
| 出站目标路径 | `/project/{id}/outbound-targets`（仅存在于旧前端调用点，旧后端未实现） | `/projects/{id}/targets` | 跟随项目路径复数化，并补上旧项目缺的接口 |
| 模型配置更新方法 | `PUT /agent/model-configs/{id}` | `PATCH /api/v1/model-configs/{id}` | 配合 `body.model_dump(exclude_unset=True)` 的局部更新语义 |
| 模型配置寻址 | 更新/默认用数字 `config_id` | 一致（`set-default` 同样用 `config_id`） | — |
| 环境寻址 | 按环境名（`{name}`） | 一致 | 执行链路本来就靠名称选环境 |
| `environment.name` 长度 | `String(50)` | `String(50)`（刻意保留） | `name` 会被写进执行记录等列，长度必须一致 |

---

## 4. 状态码差异

| 场景 | 旧 | 新 | 原因 |
| --- | --- | --- | --- |
| 重复注册 | 400「该用户名已存在」 | **409** `ERR_CONFLICT`「用户名已存在」 | 用户名冲突属于资源冲突，409 语义明确，前端可直接定位到表单字段 |
| 管理员建号撞名 | 400「该用户名已存在」 | **409**「用户名已存在」 | 同上，统一冲突口径 |
| 管理员改名撞名 | 400「该用户名已存在」 | **409**「用户名已存在」 | 同上 |
| 「用户名已存在」类冲突整体 | 旧 auth 路由内 **5 处** 400（注册、管理员建号、管理员建号的唯一约束兜底、管理员改名、以及改名冲突分支） | 全部归一到 **409** | 同一业务语义必须同一状态码，否则前端要写五套判断（见风险 R2） |
| 用户不存在（按 ID 查） | 404「用户不存在」 | 404 | 语义一致，保留 |
| 令牌过期 / 版本不一致 / 用户已删除 | 401，但**用户已删除返回「用户不存在」**，其余返回「登录失效，请重新登录」 | 全部 401，文案统一为「登录失效，请重新登录」 | 避免攻击者通过 401 文案差异枚举某个 `sub` 是否存在过（见 `app/shared/auth.py` 注释） |
| 缺少 `Authorization` 头 / 非 Bearer | 401（OAuth2PasswordBearer 默认英文 `Not authenticated`） | 401「登录失效，请重新登录」 | 与上一行同一原因；归一化在 `app/shared/errors.py` 的 `HTTPException` handler 里完成 |
| 账户被禁用 | 403「该账户已被禁用」 | 403「该账户已被禁用」（一致） | 前端要靠这个 403 区分「被禁用」和「令牌过期」，不能一起归一 |
| 启用模型但未填 API Key | create 与 update 均返回 400，文案同为「启用模型前必须填写 API Key」 | 同为 400，但文案分两条：create 是「启用状态的模型必须配置 API Key」，update 走 `_validate_payload` 仍是「启用模型前必须填写 API Key」 | 旧代码在 create 路径上已有该校验，实际不会静默落库；新平台**同样先拒绝、不会静默收敛**。`create_configuration` 里的 `is_enabled = bool(body.is_enabled and api_key)` 看似是兜底收敛，但前置的 `if body.is_enabled and not api_key: raise bad_request(...)` 已经拦下这种情况，所以这行实际是空操作，前端不要依赖「提交后被改回停用」的行为 |
| 默认模型被删 | 旧无保护，删除后重新归一化默认项 | 400「默认模型不能删除，请先指定新的默认模型」 | 删除唯一默认项会让调用链路失去兜底 |
| 删除用户 | `DELETE /users/{id}` 直接 `db.delete(user)`，无负责人移交；只禁止删除自己，**允许删除其他管理员** | 先移交项目与组织负责人（有其它激活成员则转交，没有则连带清理项目/组织），再把存活的 `project_member.created_by`、`project_outbound_target.approved_by` 重挂到项目 owner、清空 `model_configuration.created_by`；并新增禁止删除管理员账户 | 旧逻辑在删除「负责项目/组织的用户」时可能触发外键失败或留下孤儿引用（旧代码没有任何移交）；「不能删管理员」是防止把平台管理端删空 |
| 成员新增 / 改角色 | `POST /project/{id}/members`（201）本身就是 upsert：已有成员行时只改 `role`，**不会**对重复成员返回 409；只有「把项目 owner 添加为成员」返回 409「项目负责人无需重复添加为成员」 | `PUT /{id}/members/{mid}` 幂等，**固定 200**；「把项目 owner 添加为成员」改为 400「项目负责人不需要单独添加为成员」 | 新平台把「不能把负责人塞进成员表」这类业务冲突从 409 归到 400，与组织侧的口径保持一致；upsert 语义两侧本来就一致，不需要前端改重试逻辑 |
| 成员 ID 与请求体不一致 | 422「成员 ID 不一致」——**只有组织侧**（`project/api/organization.py::put_member`）有这个校验；旧项目成员接口（`POST /project/{id}/members`）路径上没有 ID，根本没有这项检查 | 组织：400；项目：404 | 新项目不再走 pydantic 层报 422，改为业务校验；两者的差异本身也应在后续统一（见风险 R7） |
| 项目 / 组织不存在或无权访问 | 404「项目不存在或无权访问」 | 404「项目不存在」 | 隐藏资源存在性，不区分「没有」和「没有权限」 |
| 环境不存在 | 404「环境不存在」 | **400**「环境不存在」 | 新 `get_or_404` 复用了 `bad_request`，与「404 隐藏存在性」的统一原则不一致（见风险 R7） |
| 环境名非法 | 422 | **400** | 旧服务层抛 `HTTPException(422)`，新改为业务 `bad_request` |

---

## 5. `/api` 前缀处理差异

### 5.1 旧项目：代理层删前缀

```js
// test_project_front/vite.config.js
'/api': {
  target: 'http://127.0.0.1:8888',
  changeOrigin: true,
  rewrite: (path) => path.replace(/^\/api/, ''),  // 去掉 /api 前缀再发给后端
}
```

前端 `axios` 的 `baseURL` 是 `/api`，所以浏览器请求 `/api/users/login`，经 Vite 去掉 `/api` 后，后端收到的是 `/users/login` —— 旧后端的路由也确实是 `/users`、`/project`、`/organizations`、`/agent/...`，不带任何前缀。

### 5.2 新项目：代理层保留前缀

```ts
// frontend/vite.config.ts
'/api': {
  target: process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8001',
  changeOrigin: true,
  // 刻意不写 rewrite
}
```

```ts
// frontend/src/api/client.ts
export const API_BASE = '/api/v1';
```

后端在 `app/main.py` 里 `API_PREFIX = "/api/v1"`，所有 router 都以该前缀挂载，因此浏览器请求 `/api/v1/login` 时后端收到的还是 `/api/v1/login`。

### 5.3 为什么不再 rewrite

后端的真实路径**已经带** `/api/v1`。如果代理层继续删掉 `/api`，请求会变成 `/v1/login`，直接 404 —— 这是一个纯配置错误，而不是业务差异。保留前缀的额外好处是：Swagger（`/docs`）里生成的路径可以直接粘到 `curl` 或 Postman 里跑，不需要调用方自己补前缀。

### 5.4 对不同调用方的影响

| 调用方 | 旧项目 | 新项目 |
| --- | --- | --- |
| 浏览器（Vite dev） | 可用（代理承担了差异） | 可用（代理承担差异的方式不同） |
| 生产 Nginx | 需要 `location /api/ { rewrite ^/api/(.*)$ /$1 break; proxy_pass http://backend; }` | `location /api/ { proxy_pass http://backend; }` 即可，不需要 rewrite |
| API 客户端 / SDK / 服务互调 | 必须自己补 `/api` 前缀，否则打不到 8888 上不带前缀的路由 | 文档地址 `/api/v1/openapi.json` 复制即用 |
| 旧前端代码直接接新后端 | — | **`baseURL: '/api'` + 旧路径会 404**：请求会被保留前缀转发成 `/api/users/login`，新后端没有这个路由 |

最后一条是本次迁移最容易踩的坑：新项目的前端必须用 `API_BASE = '/api/v1'`，不能沿用旧的 `/api` 拼旧路径。

---

## 6. 认证与令牌迁移

### 6.1 令牌结构

新项目沿用旧项目的声明：

```python
{"sub": str(user.id), "exp": now + ACCESS_TOKEN_EXPIRE_MINUTES, "ver": user.token_version}
```

`HS256`，`ACCESS_TOKEN_EXPIRE_MINUTES = 480`（即 8 小时，`expires_in = 28800` 秒）。解码时显式传入 `algorithms=[ALGORITHM]`，避免算法混淆或把算法名误当成 audience。

### 6.2 `token_version` 递增触发点

新项目在 `app/shared/auth.py::invalidate_user_tokens` 与 `app/features/users/service.py::update_user` 里覆盖：

| 触发点 | 是否触发 |
| --- | --- |
| 修改密码 | 是 |
| 账户被禁用 / 重新启用（`is_active` 变更） | 是 |
| 平台角色变更 | 是 |
| 用户名变更 | 是（旧项目只有角色与启用状态变更触发） |
| 被管理员删除 | 是（用户行本身消失，令牌自然失效） |
| 组织内 / 项目内角色变更 | 否（这些角色不影响令牌，属资源级权限） |

### 6.3 旧令牌在新系统一律不可用

- 新项目的 `SECRET_KEY` 必须由环境变量显式提供，缺失时 `app/shared/config.py` 在导入阶段直接 `RuntimeError`，不再有任何默认值；与旧项目不是同一个密钥，因此旧签名的 `HS256` 无法通过校验。
- 即便密钥巧合相同，旧库的 `user.id` 在新库里不一定存在，`get_current_user` 也会返回同一个 401。

**结论：迁移日必须全员重新登录，不需要（也不应该）做令牌迁移。**

### 6.4 401 的完整场景清单

| 场景 | 状态码 | 文案 |
| --- | --- | --- |
| 令牌过期 | 401 | 登录失效，请重新登录 |
| `token_version` 不一致（改密 / 禁用 / 改角色 / 改用户名 / 被删除） | 401 | 登录失效，请重新登录 |
| `sub` 指向已删除用户 | 401 | 登录失效，请重新登录 |
| 缺少 `Authorization` 头，或不是 Bearer 格式 | 401 | 登录失效，请重新登录 |
| 令牌解析失败（`PyJWTError` / `TypeError` / `ValueError`） | 401 | 登录失效，请重新登录 |
| `ver` 字段不是整数 | 401 | 登录失效，请重新登录 |
| 账户被禁用（令牌本身有效） | **403** | 该账户已被禁用 |

前六种全部同文案，是为了不让调用方通过错误差异推断用户是否存在。

### 6.5 前端如何处理 401 / 403

新项目（React，`frontend/src/api/client.ts`）：

```ts
const isAccountDisabled = status === 403 && body?.message === '该账户已被禁用';
if (status === 401 || isAccountDisabled) {
  tokenStore.clear();
  onAuthExpired?.();   // 由 AuthProvider 注册，跳转登录页
}
```

旧项目（Vue，`src/utils/request.js`）：

```js
if (error.response?.status === 401) { clearAuth(); window.dispatchEvent(new CustomEvent('auth-expired', {...})); }
if (error.response?.status === 403 && error.response?.data?.detail === '该账户已被禁用') { ... }
```

行为意图一致（401 清登录态并跳登录；403 + 禁用文案同样清登录态），但有两处必须跟着改：

1. **错误体字段变了**：旧代码读 `data.detail`，新后端返回 `data.message`。沿用旧写法会让「该账户已被禁用」的分支永远不触发，用户被禁用后只会看到一条普通 403。
2. **错误码通道变了**：新项目返回 `code`，前端若要区分「用户名已存在」（409）与其他失败，应读 `body.code === 'ERR_CONFLICT'`。

另需说明：旧前端的请求重试与请求取消两块能力在新项目里**都没有移植**，属未接入：

- 重试：`RETRYABLE_STATUS_CODES = {429,502,503,504}`、`MAX_RETRIES = 3`、`RETRY_DELAYS = [1000, 2000, 4000]` 指数退避、`NON_RETRYABLE_STATUS_CODES = {400,401,403}`、`NON_RETRYABLE_BUSINESS_CODE_PREFIXES = ['DATA_TEMPLATE_']`，并且只重试幂等方法（`IDEMPOTENT_METHODS = get/head/options`）。
- 取消：`createRequestSignal` / `useRequestAbort` 也是**旧前端**（`src/utils/request.js`）的工具，供 `views/slow-sql/SlowSqlAnalysis.vue` 等页面使用；新项目 `src/` 下搜索不到任何 `AbortController` / `signal`，即连请求取消本身也没有。新前端唯一的请求级控制是 `axios` 的 `timeout: 30000`。

---

## 7. 数据库迁移策略

### 7.1 Alembic 基线与结构变更纪律

- `alembic/versions/0001_initial_schema.py`：`revision = "0001"`、`down_revision = None`，`upgrade()` 直接 `Base.metadata.create_all(bind=op.get_bind())`，`downgrade()` 为 `drop_all()`。
- 一次性建 9 张表：`user`、`organization`、`organization_member`、`project`、`project_member`、`project_outbound_target`、`model_configuration`、`environment`、`notification`。
- 迁移产物从 ORM 元数据生成，因此 Alembic 与 ORM 不会在索引、约束、命名上漂移；**后续所有结构变更必须追加 `0002+` 的显式 `op` 迁移，不允许改 `0001`。**
- 启动期不自动建表：`AUTO_CREATE_SCHEMA` 默认 `false`，`app/main.py` 的 `lifespan` 仅在它为 `true` 时 `create_all`（供本地首次调试）。生产链路只认 Alembic。

### 7.2 库的分工

| 库 | 用途 | 谁维护 |
| --- | --- | --- |
| `testplatform_dev` | 开发 / 手工联调 | `compose.yaml`（`postgres:16`，容器 `testplatform-postgres`，5432） |
| `testplatform_test` | pytest 专用 | `backend/tests/conftest.py` 每个会话重建，**绝不复用 `testplatform_dev`** |
| 被测目标库 | 被测服务自有 | 平台不连接、不托管（见 1.3） |

### 7.3 旧数据导入（未接入 / 待实施）

**第一阶段没有数据搬迁脚本，也没有做过任何数据导入。** 以下是可行的思路，落地前需另行评审：

1. **表结构对齐度足够高**：`app/models/identity.py` 与 `app/models/project.py` 的表名、字段名、约束名刻意沿用旧项目（`uq_organization_member_user`、`uq_project_member_project_user`、`uq_project_outbound_target` 等）。因此旧库的 `user`、`organization`、`organization_member`、`project`、`project_member`、`project_outbound_target`、`model_configuration`、`environment` 这 8 张表按列名即可写入，不需要列映射脚本。`notification` 是新表，旧项目无对应数据。
2. **账号密码不建议搬**：新项目用「SHA256 前处理 + bcrypt（12 轮，72 字节截断）」替换 passlib 的 `bcrypt_sha256`；`app/shared/passwords.py::verify_password` 会先试前处理后的哈希、再退回原始 bcrypt。旧库里形如标准 `$2b$` 的哈希理论上可验，但 passlib 特有的前缀格式不行。**待确认**：旧库实际哈希格式需要抽样确认后再决定。建议做法是新库重新建号 + 强制首次登录改密，只搬组织结构与项目关系。
3. **模型 API Key 依赖密钥**：`app/features/model_configuration/service.py::_fernet()` 的材料是 `runtime_model_config_key()` —— 即 `MODEL_CONFIG_ENCRYPTION_KEY`（若设置）否则 `SECRET_KEY`，再由 `sha256(...)` 派生成 Fernet key。**判断历史密文能否解密，看的是这两个变量里的哪一个与旧环境相同，不只是 `SECRET_KEY`**；若新环境设置了 `MODEL_CONFIG_ENCRYPTION_KEY` 而旧环境没有，即使 `SECRET_KEY` 一致也解不开。解不开时 `decrypt_api_key` 捕获 `InvalidToken` 后返回空串，`has_api_key` 变成 `false`、`masked_api_key` 变成空串，**必须重新录入 API Key，且不会有任何报错或告警提示**。
4. **验证步骤**：迁移后 `alembic current` 应为 `0001`；跑一次完整 pytest（作用于 `testplatform_test`）；抽查 `GET /api/v1/users?page=1` 的分页总数、组织数、项目数与旧库一致；对每个被导入的组织负责人抽验 `organization.owner_id` 与 `organization_member.role` 一致。

---

## 8. 验收矩阵

验证环境：本地 Postgres 16，经 `127.0.0.1:5432` 访问，实测由 `compose.yaml` 的容器 `testplatform-postgres`（`postgres:16`）提供；pytest 使用 `testplatform_test`；`test_07` 另用 `testplatform_gate` / `testplatform_gate_create` 两个一次性临时库并在用例末尾删除。所有「已验证」项均为本次实际执行的结果。

| 验收项 | 验证方式 | 结果 |
| --- | --- | --- |
| 1. Alembic `upgrade head` 建立 9 张表 | `.venv/bin/python scripts/seed_admin.py --drop`（空库），或 `alembic upgrade head` + `alembic current`；对应 `tests/test_01_schema_and_seed.py`（其 `EXPECTED_TABLES` 为 9 表集合） | **已验证**：空库执行输出 `Running upgrade -> 0001`、`迁移完成，当前版本：0001` |
| 2. 管理员种子幂等 | 连跑两次 `.venv/bin/python -m app.scripts.seed_admin` | **已验证**：第二次输出「管理员 admin 已存在，跳过创建（密码保持不变），id=1，role=admin」，账号行未被覆盖 |
| 3. 注册 / 登录 / 登出 / me | `tests/test_02_auth_flow.py` | **已验证**：`pytest -q` 全量 52 passed，其中含该文件全部用例 |
| 4. 令牌撤销与账户禁用 | `tests/test_03_token_revocation.py` | **已验证**：同上，52 passed |
| 5. 非管理员被挡在管理接口之外 | `tests/test_04_admin_authorization.py` | **已验证**：同上，52 passed |
| 6. 跨组织 / 跨项目隔离 | `tests/test_05_isolation.py` | **已验证**：同上，52 passed |
| 7. 只读成员（viewer）不能写 | `tests/test_05_isolation.py` | **已验证**：同上，52 passed |
| 8. 真实持久化（重启进程后数据仍在） | `tests/test_06_persistence.py` | **已验证**：同上，52 passed |
| 9. 前端刷新恢复登录态 / 组织切换 / 项目切换 / 登录过期跳转 | 需人工浏览器验证；`tests/test_07_schema_gate.py` 只覆盖「启动不自动建表」这一门禁，不含浏览器交互 | **未验证**。预期：F5 后 `AuthProvider.refresh` 用本地令牌调 `/me` 恢复用户态；切换组织后项目列表按组织过滤；登出或收到 401 / 403「该账户已被禁用」后清登录态并跳转登录页 |
| 10. TypeScript 类型检查 + 构建 + 关键链路 | `cd frontend && npm run typecheck`（`tsc -b --noEmit`）与 `vite build` | **已验证**：typecheck 零错误；`vite build` 成功产出（1 个 JS bundle 1,303.72 kB / gzip 411.32 kB，仅有 chunk 大于 500 kB 的告警）。浏览器端关键链路本身归入第 9 项，**未验证** |

后端整体结果：`pytest -q` → **52 passed, 6 warnings in 39.85s**（告警来自第三方库的弃用提示与测试用短密钥，不影响结果）。按文件拆开是 `test_01` 4 + `test_02` 8 + `test_03` 8 + `test_04` 14 + `test_05` 6 + `test_06` 10 + `test_07` 2 = 52；`test_04` 的两个用例按 `ADMIN_READ_ENDPOINTS`（4 个端点）参数化后各展开为 4 项，所以该文件从 8 个函数变成 14 个用例。`conftest.py` 里的 `test_database` 是夹具（fixture），不计入用例数。耗时随机器负载浮动，用例数才是可核对的口径。

---

## 9. 完成 / 未完成 / 未来

### 9.1 已完成（第一阶段 Phase 1，已交付）

1. 9 张表由 Alembic `0001` 建立，启动期不再自动改表结构
2. 注册 / 登录 / 登出 / 当前用户 / 改密 / 我的组织 全套认证接口
3. 注册即建个人组织，新账号可直接创建项目
4. 管理员用户管理（含关键字与启用状态过滤、改名、禁用、删除）
5. 删除用户时的项目与组织负责人移交，以及审计引用重挂
6. 组织 CRUD + 成员 + 模型授权 + 负责人转移
7. 项目 CRUD + 成员 + 出站目标 + 负责人转移
8. 模型配置 CRUD，响应白名单（只暴露 `has_api_key` / `masked_api_key`）
9. 执行环境 CRUD，读写全部仅平台管理员，表空时回退内置环境
10. 个人通知收件箱 + 已读状态 + 未读角标 + 事件目录
11. 看板（真实计数 + `未接入` 占位）+ 平台统计 + 依赖就绪检查
12. 统一错误体 `{code, message, request_id}` 与 8 个实际会返回的错误码（`app/shared/errors.py` 里还定义了 `ERR_USER_NOT_FOUND`、`ERR_ACCOUNT_DISABLED` 两个常量，但没有任何调用点在用——「账户被禁用」走的是 403 + `ERR_FORBIDDEN`，`get_or_404` 走的是 404 + `ERR_NOT_FOUND`；这两个常量是死代码，前端不要依赖它们）
13. 统一分页 `{items, total, page, page_size}`
14. JWT 撤销（`token_version`）与 401 文案归一（防用户名枚举）
15. 请求 ID 中间件、登录/注册限流、bcrypt 密码哈希
16. 前端 React 18 + TS strict + antd 5 + TanStack Query 骨架与 13 个页面（6 个管理端 + 2 个认证 + 5 个控制台）
17. 代理不再 rewrite，前后端路径一致
18. 52 个后端测试全部通过

### 9.2 未完成（已识别、第一阶段不做）

1. 旧数据导入脚本（见 7.3，未接入 / 待实施）
2. `environment` 对普通用户的只读端点（现在读写都是管理员，控制台暂无环境选择器）
3. 前端请求重试与请求取消（旧 Vue 端有，新端未移植）
4. `model-configs` 的连接测试与供应商模型拉取（`/test`、`/provider-models` 未迁移）
5. `environment` 与 `model-configs` 的「不存在」状态码统一（现为 400，见风险 R7）
6. `notification` 只有 3 个写入触发点且全在用户域（`user.created` / `user.updated` / `user.password_changed`，见风险 R3）；组织与项目侧的成员变更、负责人转移、自助注册均无触发点
7. `test_runs` / `reports` / `defects` 三块统计的真实数据源
8. `organization_member` 无 `updated_at` 列，成员变更记录无法追溯
9. 前端 chunk 拆分（当前单 bundle 超过 500 kB 告警阈值）
10. 浏览器端 E2E 覆盖（验收矩阵第 9 项未验证）

### 9.3 未来（后续阶段，未交付，全部标记「未接入」）

1. AI 智能体（未接入）—— 接入点：`app/features/agent/`，复用 `model_configuration` 与 `project_outbound_target`
2. 用例管理（旧 `app/features/test_cases/`，含 XMind 导入导出）与用例生成 / 脚本生成（旧 `case_generation/`、`script_generation/`）（未接入）—— 接入点：`app/features/test_cases/`
3. API 执行（未接入）—— 接入点：`app/features/execution/`，消费 `environment.base_url` 与 `default_headers`
4. UI 自动化（未接入）—— 接入点：`app/features/visual_automation/`
5. 移动端控制（未接入）—— 接入点：`app/features/mobile_automation/`
6. 数据工厂（未接入）—— 接入点：`app/features/data_factory/`
7. 慢 SQL 分析与 SQL 日志（未接入）—— 接入点：`app/features/slow_sql/`
8. JVM 诊断（未接入）—— 接入点：`app/features/jvm_monitoring/`
9. 代码扫描（未接入）—— 接入点：`app/features/code_analysis/`
10. 统一编排（未接入）—— 接入点：`app/features/orchestration/`
11. 通知引擎（模板 / 渠道 / 发送 / 测试发送，未接入）—— 接入点：`app/shared/notify.py` 目前只写收件箱，需要在其上加通道分发层
12. 测试报告与缺陷（未接入）—— 接入点：看板 `reports` / `defects` 两张卡片已留好 `hint="未接入"` 的占位
13. 旧资产库 / 知识库 / 套件 / 可观测性 / 回收站（未接入）—— 随对应业务域迁移

---

## 10. 风险与后续行动

| 编号 | 风险 | 具体位置 | 建议行动 |
| --- | --- | --- | --- |
| R1 | **环境配置的「不存在」与「校验失败」都返回 400**，与「404 隐藏资源存在性」的统一原则相冲突，前端无法区分「环境名打错」和「参数非法」 | `app/features/environment_configuration/service.py::get_or_404`（`bad_request("环境不存在")`）；同类问题在 `app/features/model_configuration/service.py::get_or_404` | 统一改为 `not_found(...)`，并在 404 前保持权限判断顺序不变（先判权限再查资源），避免通过 404 探测他人可见性 |
| R2 | **新项目源注释与实际旧行为不符**：`app/features/users/auth.py` 注册处注释写「旧项目在这里返回 404 隐藏用户名占用情况」，但旧项目 `test_project_back/app/features/auth/api/router.py` 的全部 5 处重复用户名分支返回的都是 400，404 只用于「用户不存在」 | `backend/app/features/users/auth.py` 注册分支注释；对照 `test_project_back/app/features/auth/api/router.py` | 修注释为「旧项目返回 400」。行为本身（改为 409）是正确的，但注释会误导后续评审 |
| R3 | **`notification` 的写入触发点只有 3 个，且全在用户域**：`app/features/users/service.py` 的 `_emit()` 被 `create_by_admin`（`user.created`）、`update_user` 的角色/启用状态/用户名变更（`user.updated`）、`change_password`（`user.password_changed`）调用；`_emit` → `app/shared/notify.py::notify()` → 写收件箱。组织成员变更、项目成员变更、负责人转移、环境/模型配置变更、**自助注册**（`app/features/users/auth.py::register_user` 没有调用 `_emit`）都没有触发点，所以只自助注册、从不改自己的账号的用户收件箱就是空的 | `app/features/users/service.py::_emit` 及其 3 个调用点；`app/shared/notify.py`；`tests/test_06_persistence.py::test_notifications_are_persisted_and_scoped` 已覆盖「改名产生一条 `user.updated`」 | 在组织/项目成员变更、负责人转移等既有动作处补挂 `notify()`；自助注册是否也要发一条欢迎通知需要产品确认（`EVENT_TITLES` 里已有 `user.created` 的文案，说明这是预期事件，但目前只有管理员建号会触发）。另外 `EVENT_TITLES` / `EVENT_LABELS` 共登记 6 个事件，其中 `organization.member.invited`、`project.member.invited`、`project.owner_changed` 3 个**从未被写入**，但 `/api/v1/notifications/events` 会把它们如实返回给前端做事件目录，前端会看到永远不会出现的条目 |
| R4 | **模型 API Key 在密钥轮换后静默失效**：`decrypt_api_key` 捕获 `InvalidToken` 后返回空串，`has_api_key` 直接变 `false`，没有任何告警或日志 | `app/features/model_configuration/service.py::_fernet` / `decrypt_api_key` | 密钥轮换必须配套一次批量重录流程；建议解密失败时打一条 warning 日志，避免管理员以为模型仍然可用 |
| R5 | **跨组织可见性比旧项目更严格**：旧项目 `project/api/router.py::_get_accessible_project` 忽略组织边界（只看是否项目成员或负责人），而 `project/application/access.py::accessible_project_ids` 是强制组织边界的；新项目 `app/shared/roles.py` 采用的是强制版本 | 新项目 `app/shared/roles.py::project_role_for` / `accessible_project_ids`；旧 `test_project_back/app/features/project/application/access.py` | 迁移前导出「项目绑定了组织、但用户在组织外仍有 project_member 行」的记录清单，逐条确认这些人在新平台是否应失去访问权 |
| R6 | **迁移日旧令牌全部失效且没有过渡期**：`SECRET_KEY` 由环境变量强制提供、旧默认值被移除，旧签名无法通过校验 | `app/shared/config.py`（缺失即 `RuntimeError`）；`app/shared/auth.py::get_current_user` | 迁移公告中明确「所有用户需重新登录」；确认没有任何后台任务或服务间调用硬编码了旧令牌 |
| R7 | **状态码口径尚未完全收敛**：成员 ID 不一致在组织侧是 400、项目侧是 404；环境名非法从 422 变成 400 | `app/features/organizations/router.py::put_member` 与 `app/features/projects/router.py::upsert_member` | 在后续阶段统一为「ID 不一致 → 400，业务对象不存在 → 404，请求体非法 → 422」三档，并写进接口约定文档 |
| R8 | **前端单 bundle 超过告警阈值**（1,303.72 kB / gzip 411.32 kB），首屏加载成本偏高 | `frontend/vite.config.ts`（未配置 `manualChunks`）；旧 Vue 端有 echarts/element-plus 分包 | 引入 `manualChunks` 或按路由做动态 `import()`，把 antd 与图表类依赖拆包 |
| R9 | **`AUTO_CREATE_SCHEMA` 一旦误开就会在启动时改生产表结构**，与「结构变更只走 Alembic」的纪律冲突 | `app/main.py` 的 `lifespan`；`app/shared/config.py::AUTO_CREATE_SCHEMA` | 在部署清单中把该变量固定为 `false`，并在 CI 中校验；或从 `lifespan` 中移除该分支，只保留在种子脚本里 |
| R10 | **`/api` 前缀变更是最容易漏改的一处**：旧前端任何沿用 `baseURL: '/api'` + 旧路径的调用方接上新后端都会 404（请求被保留前缀转发） | `frontend/src/api/client.ts::API_BASE`；对照 `test_project_front/vite.config.js` 的 `rewrite` | 迁移检查单中把「后端真实路径必须带 `/api/v1`」列为第一项；对外部调用方发布新旧路径对照表 |
| R11 | **旧账号密码无法确定能否直接复用**：新项目同时接受 SHA256 前处理哈希与原始 bcrypt，但 passlib 特有的前缀格式不在其列 | `app/shared/passwords.py::verify_password` | 迁移前抽样检查旧库 `hashed_password` 的实际格式，再决定「搬账号」还是「重建账号 + 首次登录强制改密」（建议后者，见 7.3） |
| R12 | **验收矩阵第 9 项（浏览器端 E2E）仍未验证**，登录态刷新恢复、组织/项目切换、过期跳转都只靠代码走读 | `frontend/src/hooks/useAuth.tsx`、`frontend/src/api/client.ts`、`frontend/src/layouts/ConsoleLayout.tsx` | 在浏览器里手工跑一遍并在本文回填结果；条件成熟后补 Playwright 用例 |

---

## 附：本文结论的验证环境

- 后端测试：`pytest -q`，52 passed / 6 warnings / 39.85s，作用于 `testplatform_test`
- 迁移与种子：一次性临时库，执行 `scripts/seed_admin.py --drop` 与两次 `python -m app.scripts.seed_admin`，验证完成后已删除
- 前端：`npm run typecheck` 零错误；`vite build` 成功
- 未涉及：`testplatform_dev` 未被本次验证写入；被测目标数据库未被连接
