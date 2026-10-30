# 后端综合职责拆分交付（B0–B9）

日期：2026-10-29。依据 [18 综合计划](18-backend-comprehensive-refactor-plan.md)、[19 总需求](19-backend-comprehensive-agent-prompt.md)。**B0–B9 全部完成，生产调用已迁移，最终全量 1049 passed、0 failed、0 errors、0 skipped、47 warnings。** 原 1042 项逐项保留并全部通过，新增 7 项全部通过。

本轮保留全部既有工作区修改、业务能力、权限、人工批准、任务状态、事务和回执。没有新增依赖、框架、迁移或数据库结构变更，没有前端源码改动；没有恢复 app.shared/app.models/features.agent 等已删除入口。当前工作区仍包含本轮之前的大量改动，因此 HEAD 仅是版本背景，不能单独标识交付内容。

执行过程见[进度记录](backend-comprehensive-progress.md)。机器资产统一位于 [validation](backend-comprehensive-validation/)，最终验收入口为 [b9-final/acceptance.json](backend-comprehensive-validation/b9-final/acceptance.json)。

## 工作包与生产入口

下表路径均相对 `backend/app/`。全部实际文件、公开函数与事务说明见 [package-mapping.json](backend-comprehensive-validation/b9-final/package-mapping.json)；完整符号位置见 [symbols.json](backend-comprehensive-validation/b9-final/symbols.json)。

| 包 | 已交付实现与迁移 | 行为证据 |
|---|---|---|
| B0 | 保存 517 个源码/配置文件的内容清单、可恢复源码快照、Git 状态、411 个装饰器路由入口、497 处事务/IO 调用位置，以及各包实际测试清单；另保存本轮更新文档的原始内容 | 当前源码起点重跑 1042 passed；[B0 资产](backend-comprehensive-validation/b0/)、[当前基线](backend-comprehensive-validation/b0-verified/summary.json) |
| B1 | `test_management/executors/contracts.py` 唯一定义 CaseExecutionResult；`preparation.py` 公开断言/数据/作用域准备；`adapters/api.py`、`business.py`、`web.py` 分派目标；`results.py` 汇总结果。Web adapter、安全执行改用公开准备/执行入口 | 执行器、业务、安全、Fixture 与 Web 专题及全量通过；没有第二份绑定/映射实现 |
| B2 | `tasks/services/run_service.py` 创建运行/参与者/快照；`plan_service.py` 采用批准范围与依赖；`command_service.py` 处理幂等命令；`state_service.py` 统一事件/入队/状态；`assembly_service.py` 复用 Agent 组装与模型授权。保留 access/query/message/resource/serializers，TaskService 为公开门面 | 任务、通知、治理回归与完整检查点通过；消息服务不反向依赖门面私有方法 |
| B3 | `tasks/runtime/worker.py` 保留启停/分派/Provider 装配；`lease_service.py`、`completion_service.py` 持有租约和完成/失败；planning、api_execution、security_execution、web_authoring、reporting、reviewing、chat、finalizing 独立处理器真实接线 | B1–B3 最终检查点 1042 passed；另补 4 项同/异所有者新代次下迟到结果保护，B4 和最终全量通过 |
| B4 | 安全 runtime 拆为 preparation/case_runner/candidate_values/evidence/result_writer，runner 公开入口委托唯一实现；ZAP `protocol/` 分离能力、范围、认证、导入、爬取、扫描与结果；`stages/` 分离阶段、检查点、持久化；job_plan/job_command/job_query/scanner_query 分离职责 | 607 项安全/ZAP 专题暴露的问题已修复；安全+租约补测 47 passed；B4 全量 1046 passed |
| B5 | API 目录拆 interface/module/request/relation/change 服务；request_store 承接公开请求子资源读写；response_mapper 纯转换、response_loader 显式读库；导入/调试/hash 使用 canonical 请求契约 | API 目录导入、预览、去重、hash、调试、权限与全量通过 |
| B6 | Fixture 拆 validation/references/dependencies/storage/access/response；DataFactory 拆 generation_plan/provider_dispatch/generation_context/fixture_runner/result_writer/contracts；复用既有 providers、fixture_resolver、LifecycleManager、CleanupRunner | Fixture CRUD、依赖环、GLOBAL/项目隔离、Provider、池数据、准备/清理生命周期与全量通过 |
| B7 | business 拆 action_executor/targets/contracts、流程顺序、结果写入、输出状态；Web 拆 page/case/auth/execution/session；Agent 拆 definition/link_validation/tool_governance/reference，以及 session_access/message_store/proposal/session_state/session_turn/session_response/workspace_response | 业务、Web、Legacy Agent、治理引用保护、任务内 Web 与全量通过；浏览器句柄仍归 session_manager，Legacy 图边/暂停点未重写 |
| B8 | test_management/test_data/security_testing/business/api_catalog 均改为按资源组织的 `schemas/` 和 `router/` 包；显式 canonical exports，main 仍只挂载一次领域聚合 router；清理死私有转发与跨域私有导入，共享缺失值哨兵公开为 `execution.templates.MISSING` | 269 路径、418 method/path 操作、368 Schema 完整对比；默认收集 1049 项；跨域私有导入/重复 DTO/模型迁移变化均为 0 |
| B9 | 完整回归、F/B0/最终逐项覆盖映射、源码一致性、warnings、权限与 F 阶段保护回归、文档及回退清单 | [最终 summary](backend-comprehensive-validation/b9-final/summary.json)、[全部逐项结果](backend-comprehensive-validation/b9-final/cases.json)、[验收断言](backend-comprehensive-validation/b9-final/acceptance.json) |

清理后 TaskWorker 240 行、TaskService 284 行、ApiService 130 行、WebUIService 143 行，均保留必要公开门面/协调。文件大小不是验收条件：现有格式 parser、Mock 协议替身、Legacy 图和部分领域策略保留完整职责，没有为了行数继续切片或复制另一套工作流。

## 契约、事务与资源归属

- **测试与业务执行：** CaseExecutionResult 只有一份真实定义。测试适配不提交事务，CaseExecution、Fixture 和 Mock 生命周期仍由 RunService 持有。流程原有内部提交继续保留，已在事务位置清单中记录。API HTTP 仍走 execution/http。单动作默认绑定、映射和 HTTP/Web 发送只有业务域实现；用例模式保留原先不额外运行流程前置条件/输出契约的语义，流程和 Provider 模式继续运行它们。
- **输入优先级与时机：** PreparedActionTarget 只读检查动作绑定和 API 归属，随后才生成 Faker/解析用例数据；测试数据保持对 Fixture 同名输出的优先级。API 动作用例按平台额外头→环境头→映射头合并；名为 `__web_headers` 的普通数据仍是普通映射值，不被平台头覆盖，也不自动变成 HTTP 头。Web 保留其原执行变量、确认指纹和敏感值处理。
- **任务原子性：** 运行创建/快照、方案采用、工作依赖和状态使用原 Session。命令键、运行号、方案版本、行锁以及命令成功回执在原提交点一并提交。事件序号与通知同事务写入；回滚不会留下通知。state/run/plan 等辅助能力不各自拆出新提交。
- **外部回执：** `run:<run_id>:<work_key>`、`api_test_run`、`web_test_run`、`security-case-run:<run_id>:<work_id>`、`security-plan-preview:<run_id>:v<version>:api:<api_id>`、`report:<test_run_id>` 等键和 STARTED/成功/待核对顺序保留。未知副作用不盲目重放，旧 ZAP 工作项仍按原禁用/关联规则处理。
- **租约与控制：** 领取、心跳、过期恢复、失败落库继续使用独立 Session 和原锁。处理器接收明确实体或窄 Protocol，不传完整 Worker/TaskService。暂停/取消在原模型/副作用边界生效；完成、异常与心跳额外核验所有者及代次，旧尝试不得清除新租约或覆盖新状态。Worker 生命周期没有额外调度线程主体。
- **安全/ZAP：** case_runner 是 runtime 唯一直接 HTTP 发送者，preparation/result_writer 是明确数据库边界，变异/断言/严重级别/证据算法继续禁直接 HTTPX、eval 等能力。ZAPProtocolState 只持有协议范围、扫描引用和认证能力位，不保存会话凭据；protocol 不查库。ScanStageContext 是有限连接器/Session 工厂/预算配置。原 ScanWorker 唯一领取队列，统一任务仅关联和跟踪；scope、危险方法、主动扫描批准、认证复核、限额、取消、证据脱敏和 Finding 去重保持。
- **Fixture/Web/Agent：** Fixture 的依赖检查与写入仍在原 CRUD 事务内，运行计划逐 Fixture 懒惰复核可见性，不增加跨项目/跨运行全局缓存。LifecycleManager 的 prepare_run/setup_case/cleanup_case/cleanup_run 与 CleanupRunner 复用原实现，数据库 Identifier、绑定值、授权和池租约未改。Web 浏览器进程/线程/配额仍由原 session_manager 独占。Agent 工具覆写与修订共同提交，Skill/MCP 引用协调留在 Agent 上层；会话恢复与 append-only 轮次、提案锁和人工确认语义保持。

必要只读 ORM 引用保留在可信协调层：动作目标读取 API 身份/归属、任务读取批准资产、报告读取正式执行事实；没有通过只读模型引用新增跨域写入能力。API mapper、协议与 Schema 的数据库边界另由源码审计和真实行为测试核验。

事务/IO 位置：[起点清单](backend-comprehensive-validation/b0/transaction-io-boundaries.json)、[最终变更路径清单](backend-comprehensive-validation/b9-final/transaction-io-boundaries.json)。

## 逐项测试与检查点

| 检查点 | 收集/通过 | 失败/错误/跳过 | warnings | 报告会话耗时 |
|---|---:|---:|---:|---:|
| B0 当前基线 | 1042 / 1042 | 0 / 0 / 0 | 47 | 302.783 秒 |
| B1–B3 修复后完整检查点 | 1042 / 1042 | 0 / 0 / 0 | 47 | 306.017 秒 |
| B4 完整检查点（含 4 项租约测试） | 1046 / 1046 | 0 / 0 / 0 | 47 | 323.176 秒 |
| 其余领域首次完整回归（含 Faker 时机） | 1048 / 1048 | 0 / 0 / 0 | 47 | 320.041 秒 |
| 最终 B5–B8/B9 合并验收（含请求头边界） | **1049 / 1049** | **0 / 0 / 0** | **47** | **308.214 秒** |

最终 pytest 终端计时为 **307.17 秒**，报告插件会话计时包含额外收尾，为 308.214 秒。没有在无新增变化时重复后端全量；最后一次覆盖了实际新增的请求头边界修复和 7 项新增场景。

F4 历史 JUnit 把 nodeid 写成 `tests.module.Class::test`，本轮将它逐项映射为标准 `tests/module.py::Class::test`。F4 的 1042 项与 B0 标准收集清单一一对应，最终全部保留且 passed；原测试 nodeid 删除/改名 0。新增 7 项是 4 个租约代次场景、2 个无效动作目标下的 Faker 顺序场景、1 个普通数据/平台请求头边界场景。

[完整一对一映射及新增项](backend-comprehensive-validation/b9-final/nodeid-comparison.json) · [各包原测试文件/nodeid](backend-comprehensive-validation/b0/test-packages.json) · [现存测试源码断言审计](backend-comprehensive-validation/b9-final/test-source-audit.json)。既有测试只迁移 canonical helper 导入、源码 IO 归属断言与协议状态插桩；断言数未减少，源码边界测试增加 1 条。没有通过删除、skip、弱化断言或改成功 Mock 消除失败。

根目录及 backend 默认 pytest 各收集 1049 项，清单完全相同，未收集 app 中生产函数；见 [default-collection.json](backend-comprehensive-validation/b9-final/default-collection.json)。

### 中间失败与修复

失败尝试保留真实结果，没有当作成功覆盖。完整运行索引见 [run-index.json](backend-comprehensive-validation/run-index.json)。

- 首次本机 PostgreSQL 验证受沙箱 TCP 权限限制，565 passed、2 failed、475 errors；获准后同一源码重跑基线全绿。
- B1–B3 提取初期出现局部名称遮蔽、Web 返回对象及 retry_block_reason 同名递归。随后全量剩 1 个旧 helper 测试导入；公开化时误改 build_agent_guidance 的中间副本也未通过。修正真实导入/调用后完整检查点 1042 passed。
- B4 初次存在安全准备常量循环依赖、rule_view 名称遮蔽/漏导入，以及原 source guard/Mock 插桩仍指向旧位置。修复依赖和调用；测试边界精确迁移到真实 IO 所有者与协议状态，原禁止能力/脱敏断言保留。安全与租约复核及 B4 全量通过。
- B5–B8 收集/定向失败来自仍指向旧 masking/_EXECUTOR 的测试导入；迁移真实 canonical 位置后通过。最后补齐 Faker 生成时机和普通数据/平台请求头隔离；最终回归覆盖全部修复。

最终 47 条 warning 与 B0 分类/数量一致：24 DeprecationWarning、11 UserWarning、10 PytestCollectionWarning、1 InsecureKeyLengthWarning、1 SAWarning。来自既有 anyio/Starlette/httpx 弃用、10 项 Pydantic 字段名提示及 1 项 Mock operation id 提示、导入的 ORM Test* 类、短测试 JWT key 和既有 SQLAlchemy 测试数据提示。没有全局过滤、改 API 字段名或升级框架来隐藏它们；[逐条 warnings](backend-comprehensive-validation/b9-final/warnings.json)。

## 接口、源码与环境核验

- OpenAPI 前后均为 **269 路径、418 method/path 操作、368 Schema**。除现存 Mock catch-all 根据无序 methods 集合产生的随机 operationId 后缀外，完整规范内容相同；只归一化该路径的 7 个 operationId 字段，未忽略其它字段。工具目录 16 项内容保持。见 [contract-comparison.json](backend-comprehensive-validation/b9-final/contract-comparison.json)。
- 跨域私有导入 0、通配导入 0、重复 DTO 定义 0。ORM 与全部 Alembic 内容相对 B0 字节一致，本轮新增迁移 0。五个同名 Schema/Router 文件改为真实资源包，稳定公开入口没有变；新路由均被聚合挂载。
- 当前 app/test/script/迁移源码与最终固定副本逐文件一致；测试运行前后 app/tests 源码没有变化。当前 app 内容 SHA-256 为 `14037fbd09623ad3b2295aeca340d92440b8fbc328a456d2a52b0ab43f19a0c7`；完整 Python 内容标识、HEAD 背景见 [version.json](backend-comprehensive-validation/b9-final/version.json)。
- [structure-audit.json](backend-comprehensive-validation/b9-final/structure-audit.json) 列出本轮相对 B0 的 33 个既有 Python 路径变化、207 个新增文件、10 个被同名包替代的 Schema/Router 文件。已有用户改动与历史迁移修改均被保留，未混用全仓 Git diff 作为本轮清单。
- 本轮触及/新增源码无尾随空白。全仓 git diff --check 仍有 4 个在 B0 前就存在的 services/__init__.py 文件末尾空行；相应内容与 B0 相同，没有为了清理它们修改用户已有变更。
- 所有数据库验证通过用户指定的本机 PostgreSQL 账号，只创建/删除 `testplatform_test-p<PID>`；未使用 testplatform_dev。账号口令作为临时验证输入注入进程环境，验证后已清理临时口令文件；未写入仓库、快照或报告；[凭据检查](backend-comprehensive-validation/b9-final/credential-audit.json) 无匹配。
- 全量继续覆盖 F 阶段 ZAP 路由/生命周期、Skill/MCP 引用保护、HTTP JSON null、UTF-8 跨块、总超时、浏览器登录及跨项目隔离。浏览器与 HTTP 服务均为本地受控服务，LLM/ZAP/通知使用原测试替身。

可复现最终全量的等价命令（口令从外部环境提供，使用新 run-id，避免覆盖交付资产）：

```bash
cd backend
env -u TEST_DATABASE_NAME \
  TEST_POSTGRES_USER=root TEST_POSTGRES_HOST=127.0.0.1 TEST_POSTGRES_PORT=5432 \
  TEST_POSTGRES_PASSWORD="${TEST_POSTGRES_PASSWORD:?请在环境中配置隔离测试口令}" \
  PYTHONPATH="$PWD/../docs/agent-cluster-refactor/backend-comprehensive-validation" \
  COMPREHENSIVE_REPORT_DIR="$PWD/../docs/agent-cluster-refactor/backend-comprehensive-validation/<new-run-id>" \
  .venv/bin/python -m pytest -q --tb=no -ra -p pytest_report_plugin
```

原执行参数和隔离副本路径保存在最终 summary/checkout/version 中；报告生成插件已以无凭据源码保存在 validation 根目录。最终全量也验证了当前解释器与已有依赖，没有升级依赖。

## 剩余限制与回退

B0–B9 没有未完成工作包。真实外部 OWASP ZAP 引擎/目标扫描、外部 LLM 质量、真实通知租户和独立生产部署均不在本单验收范围；本轮没有发起这些外部动作，没有扩大主动扫描授权或添加相关新 UI。较长 parser、协议 Mock 和原 Legacy 图保留其完整职责，不能把它们未重写视作新的功能交付。

逐路径回退清单见 [rollback-paths.json](backend-comprehensive-validation/b9-final/rollback-paths.json)，起点源码/文档快照与内容清单保存在 B0：

1. 先比对当前路径与最终 manifest，识别本轮以后的人工作业；不要覆盖后续改动。按工作包选择恢复边界，不执行 git reset --hard、整仓 restore 或覆盖用户原始变更。
2. 对新增文件只处理清单内且没有后续修改的文件。B8 同名文件/包回退时先核对并移除本轮包文件，再从 B0 源码快照逐文件恢复原 schemas.py/router.py 及对应消费者；不要删除归属不明的目录或数据。
3. 本轮前已存在但本轮修改的路径，从 B0 内容恢复对应文件/代码块；用户在 B0 前的修改保留。文档有独立快照，历史验证和交付记录留存并注明回退，不删除证据。
4. 没有数据库结构变更，无需 Alembic downgrade；真实执行、报告、池数据和浏览器产物不随源码回退删除。运行切换仍只允许一个任务 Worker 与一个扫描队列所有者，浏览器资源按原生命周期释放。
5. 回退后重新跑相关验证和全量；不要将新旧运行主体并行启动以规避回退问题。
