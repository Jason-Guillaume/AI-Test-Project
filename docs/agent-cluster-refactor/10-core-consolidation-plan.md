# models 与 shared 归并 core 优化计划

> 计划状态说明（2026-10-28）：本文 C 阶段曾要求保留旧路径转发；后续用户要求删除纯兼容文件，已按[core 归并交付记录](core-consolidation-delivery.md)清理。本文关于保留 shim 的内容是历史实施约束，不是当前代码状态或后续执行指令。

本文规划平台核心模型与公共基础能力的目录归并，定义目标路径、依赖边界、迁移步骤和验收要求；供实施 Agent 使用。本次只编制计划，未修改运行代码、迁移文件或数据库。

编制日期：2026-10-28。核对对象为当前工作区，HEAD 为 `e46cbc9`，含已有本地改动；该提交不代表全部文件状态。此前 Agent 共享能力 R0–R4 已做代码迁移，数据库行为验证仍有环境限制，详见[原交付记录](directory-refactor-delivery.md)。实施时重新核对代码和测试基线。

实施状态：C1–C4 的代码迁移已落地；C0 完成工作区盘点与 OpenAPI 路径计数，但未能建立完整测试基线；C5 的导入兼容测试和静态验证已完成，隔离 PostgreSQL 行为回归尚未运行。实际变更与验证以 [core 归并交付记录](core-consolidation-delivery.md) 为准。

[返回索引](README.md) · [可直接使用的 Agent 提示词](11-core-consolidation-agent-prompt.md) · [既有共享能力方案](08-directory-refactor.md)

## 1. 目标与范围

将 `backend/app/models/` 的平台核心实体和 `backend/app/shared/` 的公共能力归入 `backend/app/core/`，内部按模型、数据库、安全、HTTP 和通知写入分类。以职责归并和单一实现为完成标准，旧路径可保留必要的兼容模块。

本轮包含 Python 文件与引用迁移、兼容导出、应用/脚本/Alembic 当前装配调整、受影响测试和文档同步。不改变数据库结构、接口、角色、鉴权、错误信封、事务语义及依赖版本；不开发知识库，不重构任务状态机，不继续迁移 Agent 业务模型。

`agents/`、`tools/`、`skills/`、`mcp/`、各业务 Feature 的模型保持当前归属。它们可以依赖 core，core 的规范实现不得反向依赖这些能力或业务服务。

## 2. 已核对的关键事实

- `app/models/` 当前包含 `identity.py`、`project.py`、`configuration.py`、`notification.py` 四组基线实体；`__init__.py` 注册核心模型，并对 Agent/Skill/MCP 等历史名称懒加载。
- `app/shared/database.py` 同时定义 `Base`、`engine`、`SessionLocal`、`get_db`，导入时根据配置创建 engine；初始化脚本和测试需要在此之前设置数据库环境变量。
- `auth.py`、`roles.py`、`notify.py` 等依赖核心模型；模型依赖数据库基类，因此移动时必须保持单向依赖并控制包初始化。
- 历史 `0001_initial_schema.py` 通过 `app.models` 与 `app.shared.database.Base` 找到基线表，并按九张表白名单创建/删除。历史文件保持不动，由旧路径兼容到新实现。
- `backend/alembic/env.py` 还显式注册 Agent、Skill、MCP、工具和任务模型。基线注册与完整迁移 metadata 发现是不同职责，不得合并为 core 顶层全量导入。
- 既有 R0–R4 交付记录中的数据库测试曾受隔离库凭据与连接限制影响。本计划不将应用可导入或编译成功视为数据库回归成功。

## 3. 目标目录

```text
backend/app/
├── core/
│   ├── __init__.py               # 轻量入口，不自动加载模型、engine、业务包
│   ├── config.py                 # 配置与既有运行时密钥读取
│   ├── database/
│   │   ├── __init__.py           # 不自动创建 engine
│   │   ├── base.py               # 唯一 Base 与 metadata
│   │   └── session.py            # 唯一 engine、SessionLocal、get_db
│   ├── models/
│   │   ├── __init__.py           # 明确注册平台核心实体，不加载上层业务模型
│   │   ├── identity.py
│   │   ├── project.py
│   │   ├── configuration.py
│   │   └── notification.py
│   ├── security/
│   │   ├── auth.py
│   │   ├── roles.py
│   │   ├── passwords.py
│   │   ├── crypto.py
│   │   ├── sensitive.py
│   │   └── sanitizer.py
│   ├── http/
│   │   ├── dependencies.py       # DB、Current 等 Depends 组合
│   │   ├── errors.py
│   │   ├── pagination.py
│   │   ├── rate_limit.py
│   │   └── request_context.py
│   └── notifications/
│       └── notify.py            # 保留当前公共通知写库行为
├── models/                      # 旧模型路径转发与历史名称懒加载
├── shared/                      # 旧公共路径转发
├── agents/                      # 各能力包保持当前独立目录
├── tools/
├── skills/
├── mcp/
└── features/                    # 业务模型、服务与执行器保持归属
```

所有新增包按需包含轻量 `__init__.py`。`core/models` 可按明确约定注册核心模型；`core`、`database`、`security`、`http` 的包初始化不要递归导入整个子树。

## 4. 逐文件路径映射

以下路径均相对 `backend/app/`。

| 当前路径 | 规范目标路径 | 要求 |
|---|---|---|
| `models/identity.py` | `core/models/identity.py` | User、Organization 等只有一份类定义 |
| `models/project.py` | `core/models/project.py` | 项目、成员与出站目标的数据和约束不变 |
| `models/configuration.py` | `core/models/configuration.py` | 保持当前 ModelConfiguration、Environment 归属关系，不合并其他环境实体 |
| `models/notification.py` | `core/models/notification.py` | 通知表与字段不变 |
| `models/__init__.py` 的核心模型注册 | `core/models/__init__.py` | 旧入口继续注册相同核心表；非核心历史名称留旧入口懒加载 |
| `shared/config.py` | `core/config.py` | Settings、settings、环境与密钥读取行为不变 |
| `shared/database.py` 的 Base | `core/database/base.py` | 基类模块不导入配置、session、models 或业务能力 |
| 同文件 engine、SessionLocal、get_db | `core/database/session.py` | engine 只创建一次，Session flag 和关闭逻辑不变 |
| `shared/auth.py`、`roles.py`、`passwords.py`、`crypto.py` | `core/security/` 对应文件 | 保留认证、授权、撤销和加解密语义 |
| `shared/sensitive.py`、`sanitizer.py` | `core/security/` 对应文件 | 保留通用脱敏唯一实现及原 Agent/业务兼容路径 |
| `shared/dependencies.py`、`errors.py`、`pagination.py`、`rate_limit.py`、`request_context.py` | `core/http/` 对应文件 | 依赖注入、错误与 HTTP 行为不变 |
| `shared/notify.py` | `core/notifications/notify.py` | 保留吞异常、不阻断主事务和现有通知结构 |

不把通知渠道、飞书发送等服务搬入 core；这些继续在 `features/notifications/`。不新增通用 Repository、Service 基类或抽象框架。

## 5. 依赖和兼容要求

### 5.1 规范实现依赖

```text
core/database/base                 → SQLAlchemy
core/config                        → 现有配置依赖
core/database/session              → core/config + core/database/base
core/models                        → core/database/base
core/security、http、notifications → 必需的 core 模型及公共模块
features、agents、tools、skills、mcp → core
旧 app.models / app.shared          → 新规范实现（单向）
```

security/http 之间只按实际需要引用具体文件，避免双方 `__init__.py` 集中导出导致循环。配置可以使用现有第三方库和标准库，不得为取得模型或身份而导入上层业务。

### 5.2 对象唯一性与配置初始化

- `Base`、`Base.metadata`、`engine`、`SessionLocal`、`settings`、核心 ORM 类以及 FastAPI 依赖函数均只有一个规范实现。旧新导入应取得同一对象；不复制 `DeclarativeBase`、配置实例、连接池或限流状态。
- `core/database/base.py` 独立加载不初始化连接池。`session.py` 保持现有首次导入创建 engine 的策略，不借目录迁移改成另一套生命周期。
- 保持 `.env` 寻址、默认值、密钥读取、环境变量优先级、脚本 `--database-url` 和测试环境变量设置顺序；不要把旧包的初始化副作用放入 `core/__init__.py`。
- 迁移后测试仍应真实覆盖新调用点；检查 `monkeypatch` 路径和 `dependency_overrides`。对旧模块重新赋值不一定影响新模块的函数全局变量，必须核对实际替换位置，不能只改测试断言或跳过测试。

### 5.3 历史导入和迁移

- `app.models.<module>`、`app.shared.<module>` 保留必要的单向转发。旧 `app.models` 的 Agent/Skill/MCP 等历史名称继续懒加载到所属能力包，不能迁入 `core/models/__init__.py` 或因普通导入提前加载。
- `backend/alembic/versions/` 历史迁移保持不动。`0001` 的旧导入必须仍找到相同基类、模型及九张基线表，`0002+` 的显式建表行为保持。
- 当前 `alembic/env.py` 可切换到 core 的基类及核心注册入口，并保留现有能力/业务模型的完整发现方式；不能以 core 模型集合代替整个迁移 metadata。
- 仅搬文件不新增 Alembic revision，不改表名、外键、索引、约束和现有数据。原 `AUTO_CREATE_SCHEMA` 默认关闭及服务层事务规则不变。
- 应用、当前脚本、测试和其他兼容转发更新到新实现；历史迁移必需的旧入口长期保留并写明原因。无需为了删除旧目录修改历史迁移。

## 6. 阶段实施计划

按依赖顺序直接迁入最终目录，避免先建立临时 `core/shared/` 再整体移动一次。每批应保持可导入，保留旧入口以承接尚未切换的调用方。

| 阶段 | 工作 | 阶段出口 |
|---|---|---|
| C0：盘点与基线 | 核对当前变更、旧导入、历史迁移、脚本启动顺序、测试替身及未完成验证；保存 OpenAPI、核心表结构和测试基线 | 明确文件映射、兼容入口及现有失败，不能把前轮环境阻塞写成成功 |
| C1：配置与数据库 | 迁入 config，拆分唯一 Base 与 session，旧 config/database 入口转发；更新核心依赖链 | 新旧对象一致，设置数据库环境后首次导入使用正确地址，轻量 core 导入无额外初始化 |
| C2：核心模型 | 四组实体迁入 core/models，保留旧子模块及懒加载；核对当前 Alembic 模型注册 | 无重复映射，旧路径注册相同基线模型，core 不加载上层能力包 |
| C3：公共能力分类 | 迁移 security/http/notifications，保留公共函数和状态唯一性 | 认证、权限、错误、分页、限流、通知与脱敏行为一致 |
| C4：调用方收口 | 当前应用、各能力、业务模块、脚本与测试切换规范导入；整理原 Agent/业务转发链，更新文档 | 活跃生产代码不再依赖旧实现，剩余旧引用有明确兼容或测试用途 |
| C5：验收与交付 | 补充必要兼容/导入测试，验证数据库迁移和核心行为，记录结果与回退方式 | 必需行为验证通过才标完成；未测项、旧问题和环境限制明确记录 |

历史迁移文件、兼容模块和专门验证兼容性的测试不要求消除旧路径。其他当前调用方原则上使用 core，不通过大范围字符串替换修改无关说明或第三方代码。

## 7. 验收与验证入口

| 类别 | 必须验证 |
|---|---|
| 对象与导入 | 新旧 Base、metadata、engine、SessionLocal、settings、核心模型、get_db 等对象一致；多种导入顺序无循环或重复表 |
| 初始化 | 新进程中 `import app.core` 不加载上层业务或创建 engine；脚本设置数据库参数后 session 使用正确配置，未多创建限流状态或连接池 |
| 数据库 | 全新隔离库升级、已有隔离库升级、重复 seed 幂等；基线九表和后续表无冲突，数据及迁移 head 不变；迁移与核心注册在不同导入顺序下行为一致 |
| HTTP 与安全 | 路由的 method/path 与已公开契约保持；认证、Cookie/Bearer 兼容、令牌撤销、账户禁用、项目隔离、错误信封、分页、限流和 request_id 回归 |
| 公共能力 | 配置/密钥读取、加解密、通知失败不阻断主事务、脱敏结果保持 |
| 上层能力 | Agent、任务、治理、MCP 与原业务导入可用；旧运行和原人工确认流程仍可使用 |

可复用的现有测试入口（以执行时实际文件为准）：

```bash
cd backend
.venv/bin/python -m compileall -q app alembic/env.py scripts
.venv/bin/python -m pytest tests/test_01_schema_and_seed.py tests/test_02_auth_flow.py tests/test_04_admin_authorization.py -q
.venv/bin/python -m pytest tests/test_16_agent.py tests/test_35_tasks.py tests/test_36_agent_governance_details.py tests/test_task_notifications.py -q
```

按本轮实际影响补充已有配置、错误、分页、脱敏和安全测试；收尾运行后端完整回归，因为 core 被全模块使用。新增测试聚焦对象唯一性、导入副作用、基线迁移和初始化顺序，不为每个一行转发重复写测试。只有前端实际修改时才增加前端验证，不为目录归并改动前端。

数据库验证使用显式配置的隔离测试环境，遵守当前 `tests/conftest.py` 的设置要求，不清空开发或生产库。不在文档、日志或输出中展示凭据。`compileall`、OpenAPI 生成、`alembic heads` 以及当前无法完成的离线迁移均不能代替真实升级和行为验证。

## 8. 文档交付与回退

实施后创建 `docs/agent-cluster-refactor/core-consolidation-delivery.md`，记录基线、C 阶段、路径映射、兼容入口、实际命令与结果、未测范围及已知限制；本次不预填成功记录。

同步更新 `docs/coding-conventions.md` 的现状目录和证据路径、08/09 中实际受影响的公共底座路径、治理运行说明及文档索引。保留原 R0–R4 交付记录作为历史证据，不把旧验证结果改写成 C 阶段结果。

纯目录迁移不降库。回退采用对应代码批次及路由/脚本装配恢复，处理进程资源时按现有部署方式执行；不同时运行两套 Worker 或重复创建连接资源。验证旧入口在回退后可继续使用，保留已有业务数据。

代码归并后，规范与 R 阶段设计已同步为 `app/core` 现状；`app.models`、`app.shared` 仅承担历史导入兼容，历史 Alembic 文件保持不动。
