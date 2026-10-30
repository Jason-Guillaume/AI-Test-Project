# 编码约定与架构约束

> **⚠️ 每次工作开始前必读本文档**：任何人在开始任何一次编码 / 排错 / 评审工作前，都必须**从头到尾读完**这一篇。不读完不动手。
>
> **本文档性质**：本仓库的**强制性**规范。新增/修改任何文件之前必须先读这一篇；违反任意「强制规则」或「不可修改的红线」都会导致 PR 被拒。
>
> **本文档范围**：只描述**当前代码库实际存在**的规则，不描述「将来可能会有的做法」。任何与仓库代码不一致的地方以代码为准，并应在同一个 PR 里同步修文档。

---

## 目录

1. [强制规则](#1-强制规则)
   - 1.1 通用工作规范（中文回复 + 必读本文档）
   - 1.2 中文注释：每个新文件、每个函数、每个关键节点
   - 1.3 提交前自检清单
2. [后端架构](#2-后端架构)
   - 2.1 目录结构
   - 2.2 分层规则
   - 2.3 事务约定
   - 2.4 关键不变量（不可修改）
3. [前端架构](#3-前端架构)
   - 3.1 目录结构
   - 3.2 数据流
   - 3.3 API 客户端约定
   - 3.4 Hook / Provider 模式
   - 3.5 页面组件规范
4. [技术栈（版本锁定）](#4-技术栈版本锁定)
   - 4.1 后端依赖
   - 4.2 前端依赖
   - 4.3 版本更新策略
5. [注释风格示例（复制即通过）](#5-注释风格示例复制即通过)
6. [反例（一眼看出）](#6-反例一眼看出)
7. [提变更流程](#7-提变更流程)

---

## 1. 强制规则

### 1.1 通用工作规范

**这两条是**每次工作**开始前**都要遵守的沟通与工作纪律，与 §1.2（代码注释）并列，都是硬约束。**

> **1.1.1 每次回复使用中文**
>
> 与本项目协作的**所有对话**（含但不限于：Claude 助手回复、代码评审意见、commit message、PR 描述、issue 讨论、错误消息文案、UI 文案、日志里带业务含义的字符串）**统一用中文**。
>
> 例外（保持英文的场景）：
> - 标识符、类型名、函数名、变量名、模块路径、API 字段名（按各语言惯例：Python `snake_case`，TS `camelCase` 或对齐后端 `snake_case`）
> - 第三方库、框架、命令、URL、错误码、HTTP 状态码的原始英文/技术名
> - `type: ignore`、`noqa`、`TODO`、`FIXME`、`XXX` 等通用代码约定
> - 引用第三方文档的原文
>
> 判断标准：**如果这句话是给「人」看的解释/描述，用中文；如果是「机器」读的符号/标识符，用英文**。
>
> **1.1.2 每次工作开始前必须读取本文档**
>
> 每次接手任何一件编码 / 排错 / 评审 / 文档任务前，**都必须完整阅读一遍本文档**——不是扫一眼，是从头到尾读。**特别是**：
> - §1.1（本节，通用工作规范）
> - §1.2（中文注释要求）
> - §2.4（16 条不可修改的红线）
> - §3（前端架构）
> - §7（提变更流程）
>
> **AI 助手也必须遵守这一条**：任何 Claude / 其他 AI 助手在本次会话里第一次动手前，都要读一遍本文档。读完后如果发现自己已经知道答案，也要先读一遍——**读一遍的代价远低于违反某条红线的代价**。
>
> **触发场景**：
> - 新建一个文件
> - 修改任何现有文件
> - 修 bug、加功能
> - 回答"这个怎么写"、"这样改对不对"、"这个报错怎么办"这类问题
> - Review 别人的 PR
>
> **不触发的场景**：
> - 只读代码、不做修改
> - 只回答问题、不改代码
> - 只解释某个概念、不涉及本仓库

### 1.2 中文注释：每个新文件、每个函数、每个关键节点

**规则原文（不可豁免）**：

> 1. 每次编写一个新的文件，都必须在文件**开头**加中文模块/文件注释，说明**该文件做什么、对外暴露什么、和哪些模块协作、已知限制**。
> 2. 每一个函数（Python `def` / TypeScript `function` / `export const xxx = () =>` / React Hook）**必须有中文 docstring 或 `/** ... */` 注释**，说明**做什么、什么时候被调用、副作用、错误处理**。
> 3. 每一个**关键节点**（权限判定、事务边界、外部 IO、加密/鉴权、缓存失效、分页、限流、降级/回退、错误归一化、状态切换）都必须有一行中文**内联注释**说明**为什么**这样写，而不是**做了什么**（做了什么代码本身已经说清）。

**为什么是中文**：本仓库的主要读者是中文工程师；中文注释比英文更贴近业务语义（"报告人 / 处理人 / 可见性" 这类概念用英文翻译会丢失精度）。所有 docstring、内联注释、错误消息文案（用户可见）**统一用中文**；标识符、类型名、模块路径、API 字段名仍按各语言惯例用英文 `snake_case`（Python）或 `camelCase`/`snake_case`（TS，见 §3.3）。

**注释的密度基线**：参考 [backend/app/features/defects/services/defect_service.py](../backend/app/features/defects/services/defect_service.py)、[frontend/src/pages/console/Defects.tsx](../frontend/src/pages/console/Defects.tsx)。这些文件的注释密度就是本仓库的合格下限。

**例外（允许无注释的场景）**：
- 一行 `__init__.py` 只写 `# noqa: F401` 且无其他内容的文件
- 类型别名（`type X = int` / `type Y = string`）且含义自明
- `__all__` 列表
- 一行且语义自明的 re-export（`from .foo import Bar`）

**"关键节点"的定义**（不穷举，遇到不确定的按此清单判断）：
- 权限判定：`if not has_x_role(...)`、`if user.role != "admin"`
- 事务边界：`db.commit()`、`db.flush()`、`db.rollback()`、`session.begin()`
- 外部 IO：HTTP 请求、文件读写、图片渲染、加密/哈希
- 鉴权与安全：JWT 签发/校验、密码校验、限流触发
- 缓存失效：`queryClient.invalidateQueries`、`session.expire`
- 分页：`order_by(None)`、`in_(...) or [-1]`、`page_size` 兜底
- 降级/回退：`except Exception` 后 `return None`、默认值 fallback
- 错误归一化：所有 401 统一文案、跨资源 404 隐藏、`ERR_*` code 映射
- 状态切换：mutation 前后状态、弹窗开关、tab 切换
- 数据写入前的一次性动作（如 `_STORAGE.pop` 一次性消费语义）

**关键节点注释模板**：
```python
# <一句话原因>：为什么在这里做这件事，如果不做会怎样。
if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
    raise not_found("项目不存在")
```
```typescript
// <一句话原因>
queryClient.invalidateQueries({ queryKey: ['bugs'] }); // 组织切换后可能命中新的项目集合
```

### 1.3 提交前自检清单

**每次提交新代码前逐条勾选**，一条不过就别提交：

**通用检查**
- [ ] 本次回复 / 提交消息 / PR 描述都是**中文**（§1.1.1）
- [ ] 已经完整读过本文档一遍（§1.1.2）

**注释检查**
- [ ] 新文件的顶部有中文模块 docstring / 文件头注释（说明做什么、暴露什么、和谁协作、已知限制）
- [ ] 每个新函数有中文 docstring（说明做什么、参数、返回、错误、副作用）
- [ ] 每个关键节点有一行中文内联注释，说明**为什么**（不是**做了什么**）
- [ ] 用户可见的错误消息、按钮文字、菜单标签都是中文
- [ ] 与仓库现有注释密度对齐（不出现"某个新文件比其他文件明显更少注释"）

**架构检查**
- [ ] 新代码放在正确的 feature 目录，没有横跨 feature 引入依赖
- [ ] 新路由走 `include_router(prefix=API_PREFIX)`（后端）或 `/console` 子路由（前端）
- [ ] 新 ORM 表**没有**被加进 `app/core/models/__init__.py`（除非属于九张核心基线表）
- [ ] 错误响应通过 `app.core.http.errors` 的 helper 抛（`bad_request` / `conflict` / `not_found` / `forbidden`）
- [ ] 权限用 `has_project_role(role, required)`，不直接比较字符串
- [ ] 可见性用 `accessible_project_ids`，不用 `IN ALL()`
- [ ] 事务在 service 层 commit，router 层不 commit
- [ ] 前端 API 客户端只走 `src/shared/api/client.ts` 的 `api` 实例，不自己 new `axios`
- [ ] 前端 queryKey 命名与后端字段对齐（snake_case）

**红线检查**
- [ ] **没有**修改 §2.4 / §3.2 列出的关键不变量
- [ ] **没有**修改 §4 列出的技术栈版本
- [ ] **没有**引入 §4.3 未列出的新框架或运行时
- [ ] **没有**把未验证的能力标成"已接入"
- [ ] 敏感值（密钥、密码）没有写进日志或错误消息

---

## 2. 后端架构

### 2.1 目录结构

```
backend/
├── app/
│   ├── main.py                      # 唯一应用装配入口
│   ├── agents/                      # Agent 定义、组装、提示词与工作流
│   │   ├── browser_authoring/       # 探索会话、步骤留痕与 Web 草稿候选生成
│   │   ├── models/                  # Agent/探索会话的唯一 ORM 定义
│   │   ├── services/                # Agent 配置、决策与跨能力引用
│   │   ├── assembly/                # 依赖解析、运行快照与上下文组装
│   │   └── workflows/legacy/        # 现有图、状态与节点；节点 key/暂停点稳定
│   ├── orchestration/               # 任务及跨域应用用例编排
│   │   └── tasks/                   # 任务状态、命令、租约、回执与处理器
│   ├── execution/                   # 共用技术执行运行时
│   │   ├── browser/                 # 唯一 Playwright 执行器、观察器、策略与会话注册表
│   │   ├── http/                    # 受出站策略约束的共享 HTTP 请求执行
│   │   └── templates/               # 不读取业务数据的模板解析与上下文契约
│   ├── platform/                    # 用户、组织、项目、环境、通知与治理等平台能力
│   ├── features/                    # 正式业务资产、规则、权限和事务
│   │   ├── api_catalog/             # 接口目录、解析器与调试
│   │   ├── business/                # 被测业务建模与执行
│   │   ├── mocking/                 # Mock 资产、运行、上下文及留痕
│   │   ├── test_management/         # 测试资产、运行与结果
│   │   ├── test_data/               # Fixture、Provider、运行时与数据安全
│   │   ├── web_testing/             # 正式 Web 用例、认证、确认与执行适配
│   │   └── ...                      # 其他业务域
│   ├── tools/                       # 稳定工具 key、注册、授权与薄适配器
│   │   └── builtin/                 # 按 api_catalog、business、mocking 等分域
│   ├── llm/                         # 模型 Provider、调用契约与通用追踪
│   ├── skills/                      # Skill 定义、版本、文件树与渲染
│   ├── mcp/                         # MCP 服务、发现、审批与协议调用
│   └── core/                        # 唯一基础原语与九张平台核心 ORM 表
├── alembic/                         # 数据库迁移；本次目录整理不新增迁移
├── scripts/                         # 运维与模型发现脚本
└── tests/                           # pytest 用例
```

当前代码尚无 `app/knowledge/`；知识库按重构文档中的 K 阶段单独开发，不提前创建空目录或占位实现。

**Feature 目录的内部规范**：

每个 `app/features/<name>/` 按需包含以下结构：
- `__init__.py` — 模块 docstring，声明领域范围
- `router.py` — 默认路由入口；多组路由可拆成同级模块，由 `app/main.py` 统一装配
- `schemas.py` — Pydantic 请求与响应模型；规模较大时可拆分子模块
- `services/` — 业务规则与事务边界；一个服务也使用复数目录，按资源拆分
- `models/` — 该 Feature 独占的 ORM 模型；新领域模型不放入 `app/core/models/`
- 可选 `executors/`、`providers/`、`runtime/`、`security/`、`parsers/` 等 — 仅在对应职责确实存在时创建

其他 Feature 如需调用某个 Service，应从该 Feature 的 `services/__init__.py` 导入公开入口；内部实现放在
`services/<resource>_service.py`，不要求每个 Feature 预建空文件。

`app/core/models/` 只定义平台核心模型。Feature 或其他能力包的 ORM 模型不能在此重复定义；由所属
`features/`、`agents/`、`skills/`、`mcp/` 或 `tools/` 包持有唯一类定义，并由显式 Alembic 迁移建表。
`app.models` 和 `app.shared` 旧路径兼容文件已清理；新代码与历史迁移调用方统一使用规范路径，如
`app.core.models`、`app.core.database`、`app.core.security`、`app.core.http`。历史迁移源码不为了兼容文件而保留第二套入口。
目录迁移不改变表名、外键或历史数据，没有结构变化时不新增迁移。

**Feature 之间的依赖规则**：
- feature 之间不能依赖对方的私有实现或 `_` 开头的模块
- 跨 feature/能力的业务调用通过对方明确的公开 service contract；平台基础原语放在 `core/`，共享 HTTP/模板执行能力放在 `execution/`，模型调用与追踪放在 `llm/`
- `agents/` 可以组合 `skills/`、`mcp/` 与 `tools/`；`agents/browser_authoring/` 持有探索会话服务和模型候选生成，正式 Web 资产保存仍归 `features/web_testing/`
- `execution/browser/` 只持有浏览器契约与进程资源，不查询业务 ORM；目标白名单由 Web 服务构造后注入，空闲回收后的会话状态通过 Web 服务回调持久化
- `tools/`、`skills/`、`mcp/` 不反向依赖 Agent 图、任务 Worker 或治理聚合服务；工具 key 与目录名是不同兼容面
- ORM 模型归属唯一；确需跨域只读查询时，显式导入所属包的模型，不复制模型定义
- 尚未实现的知识库不创建空目录或占位服务；规划路径见 Agent 集群重构文档中的 K 阶段

### 2.2 分层规则

```
        ┌─────────────────────────────────────────┐
        │  HTTP request                            │
        └──────────────┬──────────────────────────┘
                       ▼
        ┌─────────────────────────────────────────┐
        │  中间件（CORS → request_context →        │
        │  exception_handlers → router）           │
        └──────────────┬──────────────────────────┘
                       ▼
        ┌─────────────────────────────────────────┐
        │  router.py                               │
        │  - Depends(get_db, get_current_user)     │
        │  - 解析 Query / Path / Body              │
        │  - 调 service.xxx(db, body, ...)         │
        │  - 返回 response_model                    │
        │  ✗ 不做权限判定                           │
        │  ✗ 不 commit / flush                      │
        │  ✗ 不拼 SQL                              │
        └──────────────┬──────────────────────────┘
                       ▼
        ┌─────────────────────────────────────────┐
        │  services/<resource>_service.py          │
        │  - 权限判定（has_project_role 等）       │
        │  - 业务规则                              │
        │  - 事务边界：flush / commit / rollback   │
        │  - 通知写入（notify）                    │
        │  - 抛出 typed exception（not_found 等）  │
        └──────────────┬──────────────────────────┘
                       ▼
        ┌─────────────────────────────────────────┐
        │  SQLAlchemy ORM (models)                 │
        └─────────────────────────────────────────┘
```

**Router 层不允许做的事**：
- 权限判定（一律通过 service 的 helper，或调 `accessible_project_ids`）
- `db.commit()` / `db.flush()`（notify 内部除外，那是通用能力）
- 直接抛 `HTTPException`（一律通过 `app.core.http.errors` 的 helper）
- 拼 SQL 字符串（一律用 ORM）

**Service 层必须做的事**：
- 所有权限判定
- 所有事务边界（`commit` 由 service 层负责）
- 所有业务规则校验
- 通知写入（用 `notify()`，内部吞异常）
- 抛出 typed exception，由 exception_handlers 统一格式化

### 2.3 事务约定

**SessionLocal 的三个 flag**（[app/core/database/session.py:34](../backend/app/core/database/session.py)）：
```python
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
```

含义：
- `autocommit=False`：显式 commit，不会偷偷自动提交
- `autoflush=False`：写入不自动 flush，需要时手工 flush
- `expire_on_commit=False`：commit 之后对象属性不失效，便于提交后直接回读字段

**service 层的事务模板**：

```python
def create_xxx(self, db: Session, body: XxxCreate, *, actor: User) -> XxxResponse:
    # 权限判定（越权与不存在共用 404）
    if not has_project_role(...):
        raise not_found("...")

    row = Xxx(...)
    db.add(row)
    db.flush()              # 如果需要 ID（如通知、外键回填）
    notify(db, ..., ...)    # 通知写库（吞异常）
    db.commit()             # 事务提交
    db.refresh(row)         # 拿最新值
    return response(row)
```

**"事务内 notify 但不阻断"的实现**：`notify()` 内部 `try/except Exception` 后 `logger.warning` 返回 `None`。业务代码不需要判断返回值。

### 2.4 关键不变量（不可修改）

**下面 16 条是硬红线**。**改动其中任何一条都需要在 PR 里说明理由、更新本文档、并跑完整测试。**

| # | 分类 | 不变量 | 违反后果 |
|---|---|---|---|
| 1 | roles | 三层角色模型：platform 三档（admin/test/dev）/ org 三档（owner/admin/member）/ project 五档（viewer/member/editor/owner/admin），其中 project 的 `admin` 仅在平台管理员判定时派生、从不落库；成员表只允许分配 viewer/member/editor | 权限模型崩塌 |
| 2 | roles | `accessible_project_ids` 用两次 `.filter()` 叠加"组织边界 + 项目内身份"；平台管理员返回 `None` 表示不过滤 | 跨组织数据泄漏 |
| 3 | roles | `has_project_role` 先归一化 `strip().lower()`，不在 rank 集合内的角色一律降级为 viewer；不按字面值放行 | 脏数据提权 |
| 4 | errors | 错误信封固定 `{code, message, request_id}` 三键；`code` 从 `ERR_*` 常量池选 | 前端错误分流失效 |
| 5 | auth | 所有 401 共用同一文案 `"登录失效，请重新登录"`；用户禁用走 403 `"该账户已被禁用"` | 用户/令牌枚举风险 |
| 6 | errors | 跨资源越权一律 404，不用 403（`get_accessible_or_404` / `not_found(...)`） | 通过错误码差异推断他人项目 |
| 7 | auth | JWT claims 固定三键 `sub` / `exp` / `ver`，不新增 | 破坏 `get_current_user` 解析契约 |
| 8 | auth | `token_version` 即时撤销：改密码/禁账户/调平台角色/移除用户时递增；`invalidate_user_tokens` 只改内存不 commit，由调用方同事务提交 | 撤销不生效 |
| 9 | auth | `jwt.decode` 必须传 `algorithms=[ALGORITHM]` 白名单，捕获 `PyJWTError / TypeError / ValueError` | 算法混淆风险 |
| 10 | notify | `notify()` 内部 `try/except Exception` 吞异常返回 None，绝不向上抛；`payload={"actor", "detail": detail or {}}`；`is_read=False` | 主事务回滚 |
| 11 | pagination | 分页参数集中在 `page_params`（`page ge=1`, `page_size ge=1 le=200`）；响应固定 `{items, total, page, page_size}`；count 前 `order_by(None)` | 分页数据不一致 |
| 12 | db | `SessionLocal` 三个 flag 固定：`autocommit=False, autoflush=False, expire_on_commit=False` | commit-后读契约破坏 |
| 13 | routes | `API_PREFIX = "/api/v1"` 单前缀；所有 feature router 都走 `include_router(prefix=API_PREFIX)`；装配顺序：CORS → request_context → exception_handlers → routers | 版本管理 / 错误信封失效 |
| 14 | config | `AUTO_CREATE_SCHEMA` 默认 `False`；启动不 create_all；结构变更全部走 Alembic | 与迁移脚本双写冲突 |
| 15 | rate_limit | 限流键固定三种：`login:ip:{ip}` / `login:user:{username}` / `register:{ip}`；只用 `request.client.host`，不信任 X-Forwarded-For；滑动窗口 + 50k key 上限 + 300s 清扫 | 限流被伪造绕过 / 内存泄漏 |
| 16 | migrations | `0001_initial_schema.py` 用 `Base.metadata.create_all` 建基线（只在空库上跑）；`0002+` 必须走显式 `op.create_table/op.add_column`；`seed_admin.py` 每次 `stamp base` + `upgrade head`（幂等） | 迁移链断裂 |

**证据路径**（每条都能定位到具体代码）：
1. `app/core/security/roles.py:16-22, 31-36, 45-65`
2. `app/core/security/roles.py:212-250`
3. `app/core/security/roles.py:162-172`
4. `app/core/http/errors.py:32, 40-48, 225-240`
5. `app/core/http/errors.py:225, 374-378` + `app/core/security/auth.py:32, 108-112`
6. `app/features/projects/services/project_service.py:83-90`（`get_accessible_or_404` 定义）+ `app/features/projects/router.py:153, 177, 189, 202, 216, 238, 255, 270`（路由层调用点）+ `:315-316, 330-331`（出站目标交叉校验）
7. `app/core/security/auth.py:35-58`
8. `app/core/security/auth.py:62-68, 108-113`
9. `app/core/security/auth.py:112`
10. `app/core/notifications/notify.py:58-93`
11. `app/core/http/pagination.py:20-25, 47-65`
12. `app/core/database/session.py:34`
13. `app/main.py:49-50, 102-109, 111-133, 135-136, 162-172`
14. `app/main.py:71-85`
15. `app/core/http/rate_limit.py:24-29, 52-82, 88-90`
16. `alembic/versions/0001_initial_schema.py:22-26, 29-38` + `backend/scripts/seed_admin.py`

---

## 3. 前端架构

### 3.1 目录结构

```
frontend/src/
├── app/                         # 应用装配、路由、全局 Provider 与布局
│   ├── App.tsx                  # 懒加载路由表；治理别名仍映射同一治理页
│   ├── providers/               # AuthProvider、ConsoleScopeProvider、AppProviders
│   ├── router/                  # RouteGuards、错误边界与错误页
│   └── layouts/                 # AdminLayout、ConsoleLayout
├── features/                    # 业务域对外 API、合同与域内 UI/逻辑
│   └── <domain>/                # api/、contracts.ts、components/、hooks/、lib/
├── pages/                       # 路由页面；复杂页面可拆成同目录子组件
│   ├── auth/
│   ├── admin/
│   └── console/
├── shared/                      # 不依赖业务域的基础能力
│   ├── api/                     # Axios client、通用分页与基础合同
│   ├── lib/                     # 通用格式化、安全跳转、选项等纯函数
│   ├── session/                 # 会话代次与生命周期
│   ├── theme/                   # antd 主题配置
│   └── ui/                      # 通用展示组件
├── widgets/                     # 跨页面组合组件，如执行详情和任务助手
└── styles/                      # 全局基础、工作区、管理端、认证与响应式样式
```

依赖方向：`app → pages/widgets/features/shared`；`pages → widgets/features/shared`；`features → shared`。
`shared` 不依赖 `features`，feature 不直接导入其他 feature 的页面私有实现；跨域组合由 pages/widgets 通过公开 API 和 contracts 完成。
全局身份/项目作用域装配位于 `app/providers`，领域能力留在 `features/<domain>`。

### 3.2 数据流

**页面加载顺序**：
```
main.tsx (mount)
  └─ <StrictMode>
     └─ <AppProviders>                    # QueryClientProvider + antd App
        └─ <App />                        # BrowserRouter
           └─ <AuthShell>                 # AuthProvider + onAuthExpired
              └─ <AppRoutes>
                 └─ <RequireAuth>         # /console/*
                    └─ <ConsoleScopeProvider>  # 组织/项目作用域
                       └─ <ConsoleLayout>     # 顶部选择器
                          └─ <Outlet /> → 具体页面
```

**API 请求路径**：
```
页面 useQuery / useMutation
  └─ src/features/<domain>/api/*.ts（领域 API）
     └─ src/shared/api/client.ts 的 axios 实例（baseURL='/api/v1'）
        ├─ 浏览器会话：自动附带 HttpOnly Cookie；兼容旧 Bearer 客户端
        └─ 响应拦截器：
           ├─ 真实 401 / 账户禁用 → 一次 session transition，清理旧缓存并跳 /login
           ├─ 普通 403、登录接口 401、过期代次响应 → 保留当前页面错误语义或取消结果
           └─ 其他错误 → Promise.reject
     └─ vite.config.ts 代理（dev only）：/api → http://127.0.0.1:8001
```

**QueryKey 与缓存边界**：当前查询声明由路由页与领域组件持有，项目资源 key 必须显式包含资源所属的 `projectId`，过滤和分页参数必须进入 key；不能以顶栏项目变化覆盖正在打开的深链资源。身份转换会通过统一 session lifecycle 取消在途查询并清空 React Query query/mutation cache。新建领域查询时，应在 feature 内集中定义 key factory 并让查询、失效复用同一工厂；不要新增全局模糊扫描失效。

**作用域变化**（[ConsoleScopeProvider.tsx](../frontend/src/app/providers/ConsoleScopeProvider.tsx)）：
- 仅恢复与当前用户绑定且正整数的已保存组织/项目 ID；损坏或不可用的 `localStorage` 安全回退。
- 项目切换后重新查询项目资源；资源所属项目从资源合同或路由参数读取，不借用顶栏的当前项目。
- 用户身份变化、登出或令牌失效由统一会话生命周期清空用户态和 query/mutation cache；项目授权列表刷新后会清理已撤权的当前项目。

### 3.3 API 客户端约定

**axios 实例（[src/shared/api/client.ts](../frontend/src/shared/api/client.ts)）**：
- `API_BASE = '/api/v1'` — 唯一前缀，不允许在业务代码里改
- `axios.create({ baseURL: API_BASE, timeout: 30000 })` — 30s 超时
- 浏览器认证使用 HttpOnly Cookie；写请求校验 CORS 白名单 Origin
- 内存 `tokenStore` 仅兼容尚未迁移的 Bearer 调用方，不持久化令牌
- 会话生命周期：只将真正的 401/账户禁用响应转换为一次会话失效；普通 403、登录表单错误及其他 API 错误保持原页面错误语义。
- 身份切换推进 session generation；迟到查询/变更响应不得恢复旧用户状态，读请求在切换时取消。浏览器 Cookie 由服务端管理。

**领域 API 模块**（示例：[features/defects/api/defects.ts](../frontend/src/features/defects/api/defects.ts)）：

```typescript
import { api } from '@/shared/api/client';
import type { Paginated } from '@/shared/api/contracts';
import type { Bug, BugListQuery, BugCreate, BugUpdate } from '../contracts';

export const bugsApi = {
  list: (params: BugListQuery) => api.get<Paginated<Bug>>('/bugs', { params }),
  create: (body: BugCreate) => api.post<Bug>('/bugs', body),
  update: (id: number, body: BugUpdate) => api.put<Bug>(`/bugs/${id}`, body),
  remove: (id: number) => api.delete<void>(`/bugs/${id}`),
};
```

请求/响应 DTO 放在所属 feature 的 `contracts.ts`；API 文件只封装 HTTP 调用，不做业务判断。
跨域输入/输出通过公开 feature contract 引用，通用分页等无业务语义的合同归 `shared/api/contracts.ts`。

**wire 字段**：**必须严格 snake_case**（与后端 Pydantic 模型保持一致）。**不要**在 API 客户端层做 snake_case ↔ camelCase 转换，前端业务代码里字段名就是 snake_case（除了 TS 保留字或特殊语义）。

### 3.4 Hook / Provider 模式

**全局装配**（[app/providers](../frontend/src/app/providers/)）：

| Provider / Hook | 提供什么 | 责任 | 使用位置 |
|---|---|---|---|
| `AuthProvider` / `useAuth` | 用户、就绪状态、登录/注册/退出 | `/me` 恢复、会话代次、用户态和缓存清理 | `app/App.tsx` 的路由外壳 |
| `ConsoleScopeProvider` / `useConsoleScope` | 当前组织/项目选择 | 安全恢复作用域、权限刷新和切换处理 | `/console` 子树 |
| `AppProviders` | React Query 与 antd App | 全局客户端与消息上下文 | `main.tsx` |

领域查询和 mutation 放在 feature 内的 hook/controller 或页面组合中。每个 hook 都用中文说明是否发请求、错误怎么处理、何时调用。传递 React Query `signal` 给 Axios；身份转换时要取消在途读请求，并在过期回调里检查 generation。普通 API 错误要继续交给页面错误态或 mutation 提示处理。

### 3.5 页面组件规范

**页面组件标准结构**（以 [pages/console/Defects/index.tsx](../frontend/src/pages/console/Defects/index.tsx) 为参考）：

```tsx
// <页面名>。
// 本模块导出 XxxPage，由路由 /console/xxx 挂载。
//
// 功能：
//   - 列表：<支持哪些过滤>；
//   - 新建：<表单字段>；
//   - 编辑：<与新建的差别>；
//   - 删除：<二次确认方式>。
//
// 权限（服务端为准，前端隐藏只是辅助）：
//   - <列出各操作的权限要求>。
//
// 未接入（明确标记，不虚报）：<列出本期未做的能力>。
import { ... } from '...';

// 常量（如状态、严重度、颜色映射）
const STATUS_COLOR: Record<XxxStatus, string> = { ... };

// 表单值接口
interface XxxFormValues { ... }

/**
 * Xxx 页面。
 *
 * 会发请求：
 *   - useQuery ['xxx', query] 拉列表；
 *   - ...
 * mutation：create / update / remove，成功后 invalidate ['xxx']。
 * 失败呈现：列表失败整页 ErrorState；mutation 失败 message.error 折叠展示。
 */
export function XxxPage() {
  // ... 分页 / 过滤 state
  // ... useQuery / useMutation
  // ... 加载中 / 失败 / 空态三态处理
  // ... return <PageContainer> ... </PageContainer>
}
```

**三态强制要求**：
- 加载中：`if (listQuery.isPending) return <LoadingState />`
- 失败：`if (listQuery.isError) return <PageContainer><ErrorState error={...} onRetry={...} /></PageContainer>`
- 空：`ResourceTable` 内建空态

**Mutation 错误处理**：`onError: (e) => message.error(getErrorMessage(e, '默认文案'))`

**禁止在页面里做的事**：
- 直接 `new axios` 或 `fetch`；请求统一走领域 API 与 `src/shared/api/client.ts`
- 在页面里做权限判定后隐藏按钮——**服务端鉴权为准**（前端只是 UX 提示）
- 手工管理 `tokenStore` / `userStore`（通过 `useAuth`）

---

## 4. 技术栈（版本锁定）

**版本变更原则**：默认**不升级**。升级需在 PR 中说明理由（安全漏洞 / 阻塞 bug / 依赖 EOL），并跑完整测试。

### 4.1 后端依赖（[backend/requirements.txt](../backend/requirements.txt)）

**运行时**：
| 包 | 版本 | 说明 |
|---|---|---|
| fastapi | `==0.141.1` | Web 框架 |
| starlette | `>=0.49,<0.51` | FastAPI 0.141.1 需要 0.49/0.50 线，锁定 |
| uvicorn[standard] | `==0.53.0` | ASGI 服务器 |
| sqlalchemy | `>=2.0,<2.1` | ORM（legacy `Column(...)` 风格） |
| alembic | `==1.20.0` | 数据库迁移 |
| psycopg[binary] | `>=3.3,<4` | PostgreSQL 驱动 |
| pydantic | `>=2.10,<3` | 数据模型 v2 |
| pydantic-settings | `>=2.9,<3` | 配置加载 |
| python-dotenv | `>=1.0` | 加载 .env |
| python-multipart | `>=0.0.9` | form-data 解析 |
| PyJWT | `>=2.9,<3` | JWT |
| bcrypt | `>=4.2,<5` | 密码哈希 |
| cryptography | `>=43,<51` | Fernet 加密 |

**测试**：
| 包 | 版本 |
|---|---|
| pytest | `>=8.0,<10` |
| httpx | `>=0.27,<1` |

**Python 版本**：`>=3.11`（当前开发环境 3.14.5）

### 4.2 前端依赖（[frontend/package.json](../frontend/package.json)）

| 包 | 版本 | 说明 |
|---|---|---|
| react / react-dom | `^18.3.1` | UI 框架 |
| typescript | `^5.6.3` | 类型 |
| vite | `^5.4.10` | 构建工具 |
| @vitejs/plugin-react | `^4.3.3` | React 插件 |
| antd | `^5.21.6` | UI 组件库 |
| @ant-design/icons | `5.6.1` | 直接使用的图标包，锁定现有解析版本 |
| @tanstack/react-query | `^5.59.16` | 服务端状态 |
| axios | `^1.7.7` | HTTP 客户端 |
| react-router-dom | `^6.26.2` | 路由 |
| dayjs | `^1.11.13` | 日期（中文 locale 在 main.tsx 加载） |
| @types/react | `^18.3.12` | |
| @types/react-dom | `^18.3.1` | |
| @types/node | `^22.20.5` | |
| eslint | `^10.8.0` | 前端静态检查 |
| @eslint/js | `^9.39.5` | ESLint JavaScript 基础规则 |
| typescript-eslint | `^8.64.0` | TypeScript ESLint 规则 |
| eslint-plugin-react-hooks | `^7.1.1` | Hook 调用与依赖检查 |

**Vite 配置关键项**（[vite.config.ts](../frontend/vite.config.ts)）：
- `server.port = 5173`, `server.host = '127.0.0.1'`（开发服务器仅本机监听）
- `proxy['/api'] → process.env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8001'`（**不改写路径**）
- `resolve.alias['@'] → ./src`
- `build.outDir = 'dist'`, `build.sourcemap = false`

**TypeScript**：`tsconfig.json` 是 solution root，实际配置在 `tsconfig.app.json` / `tsconfig.node.json`。

### 4.3 版本更新策略

**允许的更新类型**（按优先级）：
1. **安全补丁**（同 major 内的 hotfix）：可以在 PR 里直接升级，跑完整测试
2. **Bug 修复升级**（同 major 内 minor）：需要说明修复的 bug 和影响
3. **Minor 升级**（同 major 内 minor）：默认允许，但需要跑完整测试
4. **Major 升级**：默认拒绝。需要 issue 讨论 + 完整迁移计划 + 跑完整测试

**禁止的行为**：
- 引入未在本文档列出的**新框架**（React/Vue/Svelte/Next/Nuxt/NestJS 等）
- 引入未在本文档列出的**新 ORM / DB 驱动**
- 引入未在本文档列出的**新测试框架**（当前只用 pytest）
- 引入未在本文档列出的**新 UI 库**（当前只用 antd + @ant-design/icons）
- 修改 `tsconfig.json` 为**非 strict**（当前是 strict mode）

**"未接入"的标记**：如果当前代码库某个能力没做（如通知渠道推送、回归关联），必须在**相关模块的 docstring** 里明确标记「未接入，属后续阶段」，不允许在文档或注释里模糊描述。参考 [backend/app/features/defects/__init__.py](../backend/app/features/defects/__init__.py) 和 [backend/app/features/defects/services/defect_service.py](../backend/app/features/defects/services/defect_service.py) 的写法。

---

## 5. 注释风格示例（复制即通过）

### 5.1 模块 docstring（Python 文件顶部）

**示例 1 — 应用工厂**（[backend/app/main.py](../backend/app/main.py)）：
```python
"""FastAPI 应用工厂。

运行时能力与旧项目对齐：请求 ID 中间件、CORS、统一异常处理、`/api/v1` 版本前缀。
新增约束：应用启动不自动变更表结构，全部结构变更走 Alembic；
仅在 ``AUTO_CREATE_SCHEMA=true`` 时允许启动期 create_all（限本地首次调试）。

启动方式（开发）：
    uvicorn app.main:app --reload --port 8000

本模块被 gunicorn / uvicorn 通过 `app.main:app` 加载；`lifespan` 负责启动期
副作用（日志、连接探测），`create_app` 负责中间件、异常映射与路由装配。
"""
```

**示例 2 — 服务层**（[backend/app/features/defects/services/defect_service.py](../backend/app/features/defects/services/defect_service.py)）：
```python
"""缺陷服务层。

路由层只做参数、认证与响应映射；所有业务、权限与事务集中在这里。

权限模型（对齐旧项目 ROLE_MEMBER 语义）：
- 读：对该 project 有可见性即可（viewer+ 或 platform admin）
- 写（增/改/删）：至少 project member；对齐 has_project_role(role, "member")
- 越权与不存在共用 404，避免泄露他人缺陷的存在性

事务约定：service 层负责 commit；router 层不 commit。

回归关联、通知渠道推送、趋势统计等能力未接入，属后续阶段。
"""
```

### 5.2 函数 docstring

**Python（有参数）**：
```python
def register_user(body: UserCreate, request: Request, db: Session = Depends(get_db)):
    """自助注册：创建账号与个人组织，并直接签发访问令牌。

    Args:
        body: 用户名与密码。
        request: 用于取客户端地址做限流。
        db: 数据库会话。
    Returns:
        TokenResponse：含 access_token 与用户信息，前端写入后直接进入控制台。
    """
```

**Python（说明复杂权限语义）**：
```python
def accessible_project_ids(db: Session, user: User) -> list[int] | None:
    """返回用户可见的项目 ID 列表；平台管理员返回 None 表示不过滤。

    口径与旧项目 ``accessible_project_ids`` 一致，两个条件叠加：
    1. 组织边界：项目未绑定组织，或绑定的是用户所在的组织
    2. 项目内身份：项目 owner、项目成员、或项目所属组织的 owner/admin

    也就是说组织里的普通成员只能看到自己被分配（或自己负责）的项目，
    不会因为「在同一个组织」就自动看到组织内全部项目；而组织 owner/admin
    可以看到本组织的全部项目。历史残留的跨组织项目成员行不会生效。
    """
```

**TypeScript（Hook / 组件）**：
```typescript
/**
 * 认证 Provider：持有登录态，并负责刷新页面后的登录态恢复。
 *
 * 会发请求：挂载时若无令牌则直接置 ready；有令牌则调用 /me 恢复用户。
 * 失败呈现：/me 失败即清除令牌并置 user 为 null，由路由守卫跳转登录页，
 * 而不是在此处抛错或展示错误页。
 *
 * @param props.children 被保护的路由子树
 * @param props.onAuthExpired 令牌失效/账户禁用时的回调，用于跳转登录页
 */
export function AuthProvider({ children, onAuthExpired }: Props) { ... }
```

### 5.3 内联注释（关键节点）

**权限判定**：
```python
def _get_project_or_404(self, db: Session, project_id: int, user: User) -> Project:
    """取项目并校验可见性；不可见与不存在共用 404。"""
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("项目不存在")
    # 权限判定：至少 viewer；否则统一 404 隐藏项目存在性。
    if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
        raise not_found("项目不存在")
    return project
```

**注册限流前置**：
```python
    enforce_auth_rate_limit(request, "register")  # 限流：按「注册」桶计数
```

**跨项目越权防护**：
```python
    row = db.get(ProjectOutboundTarget, target_id)
    # 跨项目越权防护：目标必须确实属于路径上的项目，否则按不存在处理。
    if row is None or row.project_id != project.id:
        raise not_found("出站目标不存在")
```

**事务边界**：
```python
    user = User(username=username, hashed_password=hash_password(body.password))
    db.add(user)
    db.flush()  # 先把用户落库拿到 ID，个人组织创建需要引用它
    ensure_personal_organization(db, user)  # 注册即拥有个人组织（含 owner 成员行）
    db.commit()  # 事务提交：用户与个人组织必须同时成功
    db.refresh(user)
```

**一次性消费语义**：
```python
        # exclude_unset 保证「未提交」与「提交为 None」语义不同：后者才清空处理人。
        data = body.model_dump(exclude_unset=True)
        if not data:
            return bug
```

**分页边界**：
```python
        if visible_ids is not None:
            # 非平台管理员：先把可见集合限定住，空集合用 [-1] 占位避免 IN () 退化成全表。
            if project_id is not None:
                if project_id not in visible_ids:
                    return [], 0
                query = query.filter(Bug.project_id == project_id)
            else:
                query = query.filter(Bug.project_id.in_(visible_ids or [-1]))
```

**敏感值防泄漏**：
```python
    configure_logging()
    # 只打印数据库 URL 的 host 部分（@ 之后），避免把用户名/密码泄漏到日志
    logger.info(
        "启动 %s v%s（数据库：%s）",
        settings.PROJECT_NAME,
        settings.VERSION,
        settings.DATABASE_URL.split("@")[-1] if settings.DATABASE_URL else "未配置",
    )
```

**前端 mutation 错误处理**：
```typescript
  const createMutation = useMutation({
    mutationFn: (body: BugCreate) => bugsApi.create(body),
    onSuccess: () => {
      message.success('缺陷已创建');
      queryClient.invalidateQueries({ queryKey: ['bugs'] });
      setModalState(null);
    },
    onError: (e) => message.error(getErrorMessage(e, '创建失败')),
  });
```

**前端作用域切换缓存失效**：
```typescript
  const setOrgId = useCallback((id: number | null) => {
    setOrgIdState(id);
    if (id == null) localStorage.removeItem(ORG_KEY);
    else localStorage.setItem(ORG_KEY, String(id));
    // 组织切换会让项目列表与项目级数据全部失效；缺陷列表按当前作用域过滤，
    // 组织切换后可能命中新的项目集合，也一起刷新。
    queryClient.invalidateQueries({ queryKey: ['projects'] });
    queryClient.invalidateQueries({ queryKey: ['dashboard'] });
    queryClient.invalidateQueries({ queryKey: ['bugs'] });
  }, [queryClient]);
```

### 5.4 "未接入"标记

**必须写在模块 docstring 里**，让下一个改代码的人一眼看到边界：
```python
"""缺陷服务层。
...
回归关联、通知渠道推送、趋势统计等能力未接入，属后续阶段。
"""
```
```typescript
// 缺陷管理（用户视角）。
// ...
// 未接入（明确标记，不虚报）：回归关联、趋势看板、修复时长统计。
```

---

## 6. 反例（一眼看出）

**❌ 错误 1：新文件没有模块 docstring**
```python
# backend/app/features/foo/services/foo_service.py  ← 错！文件顶部没有 docstring
"""（空）"""

def create_foo(db, body):
    ...
```

**❌ 错误 2：函数没有 docstring**
```python
def do_something(db, x, y):  # 错！没有 docstring
    return db.query(...)
```

**❌ 错误 3：router 层 commit**
```python
@router.post("/foo")
def create_foo(db, body):  # 错！router 层不允许 commit
    row = Foo(**body)
    db.add(row)
    db.commit()  # ❌ 违反分层规则
    return row
```

**❌ 错误 4：直接抛 HTTPException**
```python
@router.get("/foo/{id}")
def get_foo(id, db):  # 错！不用 not_found helper
    if not db.get(Foo, id):
        raise HTTPException(404, "not found")  # ❌ 违反错误信封契约
```

**❌ 错误 5：字符串直接比较权限**
```python
if project.role == "member":  # 错！不做归一化，脏数据提权
    allow_edit()
```
应该用 `has_project_role(project_role_for(db, project, user), PROJECT_ROLE_MEMBER)`。

**❌ 错误 6：跨资源 403**
```python
if row.project_id != project.id:
    raise forbidden("no permission")  # 错！泄露项目存在性
```
应该 `raise not_found("...")`。

**❌ 错误 7：不安全的 JWT 校验**
```python
payload = jwt.decode(token, settings.SECRET_KEY)  # 错！没有 algorithms 白名单
```
应该 `jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])`。

**❌ 错误 8：把 Bug 加进 `app/core/models/__init__.py`**
```python
# app/core/models/__init__.py
from .bug import Bug  # 错！0001 的 create_all 会与 0002 的 op.create_table 冲突
```
`core/models/__init__.py` 只注册 0001 覆盖的九张基线表；后续新增表留在各自能力包的 `models/` 下，由 Alembic 当前装配显式发现。模型只从其规范所属包导入，不提供 `app.models` 旧路径转发。

**❌ 错误 9：前端页面直接 new axios**
```typescript
const response = await axios.get('/bugs');  // 错！必须走 src/features/defects/api/defects.ts 的 bugsApi
```

**❌ 错误 10：前端页面里做权限判定隐藏按钮**
```tsx
{user.role === 'admin' && <Button>删除</Button>}  // 错！服务端是最终防线
```
允许做但**不能是唯一防线**——服务端必须独立校验。前端只是 UX。

**❌ 错误 11：把 mock 数据当真实数据**
```python
return {"items": [{"name": "示例"}], "total": 1}  # 错！查询失败要报错
```
应该 `raise not_found(...)` 或显示错误态。

---

## 7. 提变更流程

### 7.1 常规改动

1. **读本文档**，特别是 §1.1（通用工作规范：中文回复 + 必读本文档）、§1.2（注释要求）、§2.4 / §3（架构不变量）
2. **确认改动不违反红线**（§2.4 表格里 16 条）
3. **写代码**：按 §5 的模板写注释
4. **跑测试**：
   ```bash
   # 后端
   cd backend && pip install -r requirements.txt
   .venv/bin/python -m pytest -q tests/

   # 前端
   cd frontend && npm install && npm test && npm run lint && npm run typecheck && npm run build
   ```
5. **PR 描述**：
   - 说了什么改了什么（业务视角）
   - 涉及哪些 feature
   - 是否新增/修改了 §2.4 不变量（如违反，说明理由）
   - 是否新增了 Alembic 迁移（如是，说明 upgrade/downgrade 已验证）

### 7.2 触及红线的改动（需要走讨论流程）

**必须先开 issue 讨论**的改动：
- 修改三层角色模型（§2.4 #1-3）
- 修改错误信封 / 错误码（§2.4 #4, #6）
- 修改 JWT claims（§2.4 #7）
- 修改事务 flag（§2.4 #12）
- 修改 API 前缀（§2.4 #13）
- 修改限流策略（§2.4 #15）
- 修改迁移链路（§2.4 #16）
- 升级 §4 的技术栈版本（major 升级）
- 引入 §4.3 禁止的新框架

**Issue 模板**：
```markdown
## 变更动机
<为什么要改这个不变量>

## 影响范围
<会波及哪些模块>

## 兼容性
<是否向后兼容>
<是否需要 Alembic 迁移>
<是否需要前端适配>

## 迁移计划
<分几步，每步做什么>
<如何回滚>

## 风险
<已知风险与应对>
<未验证项（明确标记）>
```

### 7.3 提变更的最低门槛

- **至少一个** review 通过（同 feature 的负责人）
- **测试全绿**（后端 pytest + 前端 typecheck/build）
- **新增代码有中文注释**（§1.2）
- **PR 描述完整**（按 §7.1 第 5 步）

### 7.4 紧急修复流程

遇到生产事故或安全漏洞：
1. 直接开 PR，最小改动
2. 在 PR 描述顶部标注 `⚠️ URGENT`
3. 至少 1 个 review + 相关测试
4. 合并后 24 小时内补 issue 讨论

### 7.5 遇到本文档与代码不一致

- **以代码为准**，同时**在同一个 PR 里修文档**
- 如果不确定谁是新的，问 feature 负责人
- 不允许"我一会儿再修文档"——修文档是同一个 PR 的一部分

---

## 附录 A：常见问答

**Q：中文注释会不会影响 IDE 提示？**
A：不会。Python docstring 和 TypeScript `/** */` 都是标准语法，IDE 正常识别。中文标点用全角（「」/ 。）比英文更清晰。

**Q：注释太啰嗦怎么办？**
A：注释是给别人看的——如果别人要读 3 遍才懂，注释就该写。参考 §5 的示例，密度就是仓库基线。

**Q：小改动（改一行 bug）也要写注释吗？**
A：是的。**关键节点**必须写。改 3 行代码里如果是权限判定或事务边界，注释不能少。改一个字符串常量不需要注释。

**Q：`# type: ignore` 之类的类型注释要中文吗？**
A：不强制。如果 `type: ignore` 附近有需要解释的东西，加中文注释；类型系统本身的注释保持英文。

**Q：新增路由要登记到别的装配文件吗？**
A：不用。运行时只认 `app/main.py` 的 `include_router`。

**Q：`app/core/models/__init__.py` 什么时候可以往里加 import？**
A：只加属于九张平台基线表的核心模型。Feature 与其他能力模型留在所属包，由 Alembic 显式迁移；导入到 core 会把它们错误地加入 0001 基线集合。

**Q：前端 queryKey 命名能自由发挥吗？**
A：不能。必须对齐 §3.2 的约定，特别是 `['project', id, ...]` 这种前缀约定——作用域切换的缓存失效依赖这些 key 的**结构**，改结构会破坏 `useConsoleScope`。

---

## 附录 B：文件路径快速索引

**后端关键文件**：
- 应用入口：[backend/app/main.py](../backend/app/main.py)
- 公共基础能力：[backend/app/core/](../backend/app/core/)
  - `config.py`（配置）、`database/`（基类与会话）、`security/`（认证、权限、加密、脱敏）、`http/`（错误、分页、限流、请求上下文）、`notifications/notify.py`（通知写库）
- 公共基础能力唯一入口：[backend/app/core/](../backend/app/core/)
- 跨域执行能力：[backend/app/execution/](../backend/app/execution/)（HTTP 与模板解析）
- 模型调用能力：[backend/app/llm/](../backend/app/llm/)
- 表达式基础原语：[backend/app/core/expressions/](../backend/app/core/expressions/)
- 特性模块：[backend/app/features/](../backend/app/features/)
- 迁移：[backend/alembic/versions/](../backend/alembic/versions/)

**前端关键目录**：
- 应用与路由：[frontend/src/app/](../frontend/src/app/)；入口为 [app/App.tsx](../frontend/src/app/App.tsx) 与 [main.tsx](../frontend/src/main.tsx)
- API 客户端：[frontend/src/shared/api/client.ts](../frontend/src/shared/api/client.ts)；领域 API 与合同在 `frontend/src/features/<domain>/`
- 全局作用域：[frontend/src/app/providers/](../frontend/src/app/providers/)
- 页面：[frontend/src/pages/](../frontend/src/pages/)；跨页面组合：[frontend/src/widgets/](../frontend/src/widgets/)
- 通用 UI/工具/主题：[frontend/src/shared/](../frontend/src/shared/)

**文档**：
- [docs/current-system-analysis.md](./current-system-analysis.md) — 旧项目分析
- [docs/migration-plan.md](./migration-plan.md) — 迁移计划
- [docs/target-architecture.md](./target-architecture.md) — 目标架构
- **本文档**：编码约定与架构约束

---

**版本**：v1.7 · **生效日期**：2026-10-30 · **上次修订**：2026-10-30

**v1.7 修订内容**：更新前端 app/features/shared/widgets 目录、会话与作用域归属、领域 API/合同示例和当前缓存边界；保留 B0–B9 后端职责约定。

**v1.6 修订内容**：记录 B0–B9 域内职责、canonical Schema/路由包、窄 Protocol、业务目标准备及事务/资源所有者约束。

**v1.5 修订内容**：记录 E0–E4 业务共享能力实际归属：跨域 HTTP/模板解析在 `execution/`、表达式原语在 `core/expressions/`、模型调用与追踪在 `llm/`；业务域保留授权、结论与资源配置。

**v1.4 修订内容**：清理 `app.models`、`app.shared`、旧 Agent/治理转发模块及前端纯页面转发文件；明确当前代码只使用规范导入路径。

**v1.3 修订内容**：公共基础能力与平台核心模型已归并至 `app/core/`；更新现状目录、导入约定、证据路径和兼容入口说明。

**v1.2 修订内容**：
- 新增 §1.1「通用工作规范」：每次回复使用中文 + 每次工作开始前必须读取本文档
- 原 §1.1「中文注释」重编为 §1.2，原 §1.2「提交前自检清单」重编为 §1.3
- 提交前自检清单增加「通用检查」分组（中文回复 + 已读本文档）
- 顶部 banner 明确「⚠️ 每次工作开始前必读本文档」

**v1.1 修订内容**：
- 项目角色修正为五档（viewer/member/editor/owner/admin），`admin` 仅在平台管理员判定时派生
- 目录树补充 `ProjectOutboundTarget` 的实际位置（`app/models/project.py`）、标注 `app/scripts/` 为已弃用
- `defects.ts` API 模板对齐实际文件（severity/status 可选、`api.put` 而非 `api.patch`、`BugUpdate` 是独立 interface 不含 `project_id`）
- 不变量 #6 证据路径区分定义（`services/project_service.py:83-90`）与调用点（`router.py`）
- 不变量 #16 明确指向顶层 `backend/scripts/seed_admin.py`，避免与已弃用的 `app/scripts/seed_admin.py` 混淆

**维护者**：所有参与本仓库的工程师。**违反本文档的 PR 一律拒绝，除非先修文档**（且走 §7.2 讨论流程）。

## 后端综合职责边界（B0–B9，2026-10-29）

本轮规范入口与验证见 [综合交付记录](agent-cluster-refactor/backend-comprehensive-delivery.md)。顶层 core/execution/llm/agents/tools/skills/mcp/features 继续保持。多资源领域可将 `schemas.py`、`router.py` 改为同名包；包入口显式导出唯一 DTO/路由，不定义第二份实现、不通配转发。`main.py` 仍只挂载一次领域 router，HTTP 字段、错误信封与权限不随文件移动改变。

- 用例结果唯一类型在 `test_management/executors/contracts.py`；断言/数据/模板作用域准备使用 `preparation.py`。API、业务、Web 适配归 `adapters/`，禁止跨域引用执行器私有 helper。
- 业务动作绑定、映射、前置条件与请求只由 `business/executors/action_executor.py` 和 `targets.py` 持有；流程顺序仍在 `business_flow_executor.py`，结果写入与输出引用分别归 `result_writer.py`、`output_state.py`。用例适配经只读 `PreparedActionTarget` 先验证目标，再生成 Faker/解析数据；用例数据与平台运行请求头不得混用。用例模式保留原断言语义，流程/Provider 模式保留业务前置条件和输出契约。
- 任务服务使用 run/plan/command/state/assembly 与既有 access/query/message/resource/serializers；`TaskService` 是稳定公开门面，不保留死私有转发。Worker 只持有生命周期、Provider 装配和分派；lease/completion 与独立 handler 各有唯一实现。处理器仅接收明确实体、上下文或窄 Protocol，不接收完整 Worker/TaskService，不传万能字典或 `Callable[..., Any]`。消息/命令仍共享调用方原事务；租约/心跳保持独立 Session、所有者和代次核验。
- 安全 runtime 的数据库边界限于 preparation/case_runner/result_writer；HTTP 发送仅由 case_runner 调共享执行器。变异、断言、严重级别和证据归一化保持纯算法。ZAP protocol 不查库，stages 负责检查点和阶段协调；Connector/Orchestrator 为公开门面，原 ScanWorker 独占扫描队列。
- API 目录按 interface/module/request/relation/change 拆分；底层 request_store 供导入、hash、调试复用，response_mapper 只做纯转换，response_loader 明确加载数据库数据。写入服务保留原 commit/flush/rollback 顺序。
- Fixture 校验、引用、依赖边、存储和响应分别归明确服务模块；创建/更新/替换事务由 FixtureService 持有。DataFactory 只协调依赖计划和事务，generation_context/provider_dispatch/fixture_runner/result_writer 复用现有 Provider/模板。LifecycleManager 和 CleanupRunner 继续负责原准备/清理顺序、池租约与缓存，不新增全局上下文缓存。共享缺失值哨兵使用 `execution.templates.MISSING`。
- Web 按 page/case/auth/execution/session 拆服务，浏览器句柄继续由 session_manager 独占。Agent 定义、工具治理、Skill/MCP 引用分别归 definition/tool_governance/reference 服务；会话状态、轮次、响应和工作区装配使用 session_state/session_turn/session_response/workspace_response。Skill/MCP 不反向依赖 Agent 协调层。
- 跨域只读 ORM 引用仅用于既有归属/状态/快照读取（例如业务动作目标读取 API 身份、任务读取已批准用例、报告读取执行事实）；跨域写入仍经所属领域公开服务，禁止导入别域 `_` 实现。

## 附录 C：Web UI Automation Phase 1 增量约定（2026-10-19）

Web UI 是既有测试执行体系的扩展：`TestCase.target_type=WEB`，步骤仍存 `TestStep`，
运行仍走 `RunService` / `TestCaseExecutor` / `TestRun` / `CaseExecution`。
`web_ui` 内部按 `models/`、`services/`、`runtime/` 分层；不改变 JWT、错误信封、角色或事务 flag。

Playwright 只充当 Chromium 驱动，pytest 仍是测试入口。固定操作白名单解释结构化步骤，
禁止执行 LLM/用户原始脚本。Agent 生成草稿不等于确认，修改步骤、页面定位或登录态后须重新审核。
密码、Cookie、LocalStorage/JWT 和浏览器附件复用 `core.security.crypto` 加密，响应不回传凭据。
浏览器资源只由 Web 模块独占，禁止连接或接管 ZAP 和用户浏览器。

迁移 `0012` 必须兼容 `seed_admin` 的重复初始化；只显式创建 Web 扩展表，不将新模型加入
`app/core/models/__init__.py`。附加 schema 类型 `WEB` 采用向后兼容扩展，旧 API/业务用例继续沿原路径执行。

人工扫码发生在独立的人工浏览器，完成后仅导入目标测试环境的 storage_state。
生产环境和项目外目标不应通过自动化模块扩大授权；执行时以项目出站白名单为准。
