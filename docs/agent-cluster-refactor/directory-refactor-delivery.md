# Agent 共享能力目录重构交付记录

执行日期：2026-10-28。范围：R0–R4。知识库按条件验收未迁移。

## 基线与实施边界

- 开始时仓库位于 `e46cbc9`，工作区已有多处修改和未跟踪文件。本次在现有工作区继续操作，没有重置、清理或覆盖无关改动。
- `alembic heads` 实测唯一 head 为 `0029_agent_tool_overrides`。目录迁移没有表结构变化，因此未新增 Alembic revision。
- 现有任务服务、Worker、业务执行器和接口路径保留；Agent 会话的状态机、人工暂停点、确认入口、权限校验和历史运行快照结构继续使用已有实现。
- 检查未发现知识库模型、路由、服务、表或检索实现。本轮没有创建 `app/knowledge/` 空目录或占位能力；K1–K3 留待独立产品开发。

## 阶段完成情况

### R0：盘点与验证基线

- 核对 Agent 图和会话、治理配置、Skill 文件树、MCP、任务运行时、工具调用点、兼容导入及 0001–0029 迁移链。
- ORM 迁移采用单一定义和旧路径懒加载，不改表名、外键、索引和既有数据。
- 数据库当前版本检查未能连上本地 `127.0.0.1:5432`（执行环境拒绝该连接）；没有使用开发库凭据绕过测试隔离。

### R1：工具注册与能力目录

- 工具实现迁入 `backend/app/tools/builtin/`，按 api_catalog、business、test_management、test_data、mock_management、security_testing、web_ui、reports、notifications 分域。
- 新增 `tools/contracts.py`、`registry.py`、`dispatcher.py` 和 `adapters/mcp.py`；显式注册 40 个稳定工具键，注册契约由原处理器签名生成，固定工作流和模型调用共用同一处理器。
- `catalog_only` 状态不会因此开放给模型；冒烟检查确认 `business.list_flows` 的模型调用被拒绝。原工具 key 与 MCP key 格式不变。
- `features/agent/tools/` 旧模块保留为单向兼容转发。

### R2：模型、Schema 与治理服务归属

- Agent ORM 归 `agents/models/`；Skill ORM 归 `skills/models/`；MCP ORM 归 `mcp/models/`；工具覆写 ORM 归 `tools/models/`。原治理模型文件继续转发到这些唯一类定义。
- 治理 Schema 和服务实现拆入各能力包。旧 `features/agent_governance` 保留原 HTTP Router、字段和权限门槛作为兼容聚合入口；涉及 Agent 引用的 Skill/MCP 更新、停用、删除、恢复检查由 Agent 服务层编排，Skill/MCP 服务不反向导入 Agent。
- `app.models` 历史名称改为懒加载到新模型包；Alembic 环境发现新 ORM 包，基线迁移仍按既有表白名单执行。

### R3：运行时组装与适配

- `agents/assembly/` 持有 Agent 依赖解析、运行快照、公开快照投影和上下文组装；`skills/loader.py` 与 `renderer.py` 复用现有文件树、兼容旧 content 并渲染变量。
- 任务服务委托 Agent 配置解析与快照复制，但仍负责创建任务、保存运行快照和任务状态；Worker 仍负责运行、审批复核、取消/暂停与任务工具回执。
- MCP 工具映射保持稳定 key，调用时的启用状态、审批和只读声明仍由原 MCP 服务复核。未将目录迁移扩展为新的任务平台或执行器。

### R4：Agent 本体

- Agent 路由、会话 Schema、会话与消息 ORM、会话服务、模型提供方、Langfuse 追踪、提示词资源和旧图节点分别迁入 `agents/` 下对应目录；旧图保持在 `agents/workflows/legacy/`。
- `features/tasks/runtime/subagents.py` 的实现迁入 `agents/runtime/subagents.py`，原任务运行时路径保留转发。
- 敏感字段掩码和上下文/文本脱敏实现下沉 `shared/`，原业务执行器和 Agent Provider 路径继续转发到同一实现。
- 工具侧测试资产输入契约移到 `tools/builtin/test_management/contracts.py`；Web 草稿生成由 Web UI 功能服务持有，工具只保留注册适配器，避免工具包直接依赖 Agent 实现。

## 主要路径映射

| 原路径 | 当前规范路径 | 兼容方式 |
|---|---|---|
| `features/agent/{graph.py,state.py,nodes/}` | `agents/workflows/legacy/` | 旧模块转发 |
| `features/agent/{router.py,schemas.py,models/,services/}` | `agents/router.py`、`agents/schemas.py`、`agents/models/`、`agents/services/` | 旧模块转发 |
| `features/agent/{providers/,prompts/}` | `agents/providers/`、`agents/prompts/`；通用脱敏位于 `shared/` | 旧模块转发，提示词文件已迁移 |
| `features/tasks/runtime/subagents.py` | `agents/runtime/subagents.py` | 旧模块转发 |
| `features/agent/tools/` | `tools/builtin/<domain>/` | 旧模块转发 |
| `features/agent_governance` 模型、Schema、服务实现 | `agents/`、`skills/`、`mcp/`、`tools/` | 原 HTTP Router 与服务聚合保留 |
| `features/business/executors/sensitive.py` | `shared/sensitive.py` | 旧模块转发 |

## 兼容性与安全边界

- HTTP 路由装配仍提供 `/api/v1/agent-governance/agents` 等原路径，OpenAPI 检查共得到 251 条路径。
- `features/agent` Router 与 `agents` Router 指向同一个 Router；旧 `AgentSession`、`AgentMessage` 导入与规范模型类对象相同；旧提示词入口读取到相同资源。
- 模型参数不能指定处理器导入路径、身份或确认信息；工具调用继续经显式注册和当前权限/人工确认门槛。
- 没有新增、删除或改名数据库表，也没有迁移数据。

## 实际验证

| 检查 | 结果 |
|---|---|
| `.venv/bin/python -m compileall -q app alembic/env.py` | 通过（R2、R3、R4 后端源码编译检查） |
| 后端应用导入与 `app.main.app.openapi()` | 通过，251 条路径；出现既有 Pydantic 字段名和 Mock 路由重复 Operation ID 警告 |
| Agent 旧/新 Router、会话模型、消息模型、提示词资源与脱敏入口兼容冒烟 | 通过；旧新类对象一致，提示词内容一致 |
| 工具注册冒烟 | 通过；40 个处理器已绑定、签名输入契约非空，`catalog_only` 工具不能从模型通道调用 |
| `alembic heads` | 通过；唯一结果 `0029 (head)` |
| `pytest tests/test_16_agent.py tests/test_35_tasks.py tests/test_36_agent_governance_details.py -q` | 未进入测试收集：`tests/conftest.py` 要求显式设置 `TEST_POSTGRES_PASSWORD`，当前环境未提供；数据库行为回归待在隔离测试库补跑 |
| `alembic current` / 空库迁移执行 | 未完成：当前沙箱无法连接本地 PostgreSQL；离线 `upgrade --sql` 会在既有迁移 `0002` 调用 `inspect()` 时失败，不作为升级成功证据 |

## 未完成事项

- R5 不适用：当前项目没有知识库实现可迁移。
- 后续 K1–K3：按 `project-knowledge-business-assembly-plan.md` 开发项目知识接入与检索、受来源约束的业务草稿生成、人工编辑和正式业务保存；不得把本轮目录迁移描述成已交付知识库。
- 在显式配置隔离测试库 `TEST_POSTGRES_PASSWORD` 后，补跑 09 列出的 Agent、任务、治理、Web、安全与通知回归；当前未连接开发数据库，也未用开发凭据替代测试凭据。
