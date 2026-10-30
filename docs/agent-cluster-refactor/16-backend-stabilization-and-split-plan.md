# 后端问题修复、回归收尾与后续目录拆分计划

本文承接 E0–E4 提取后的现场核查，定义功能修复、失败追踪、验收门槛与后续目录优化顺序，供实施 Agent 使用。本次只编制文档，未执行下面的修复或再次运行测试。

编制日期：2026-10-29。依据当前工作区与上一轮现场核查；HEAD 为 `e46cbc9`，包含多轮本地改动，提交号不是全部文件的实际版本。执行时重新核对代码及变更，不覆盖已有工作。

[返回索引](README.md) · [实施需求提示词](17-backend-stabilization-agent-prompt.md) · [E 阶段交付记录](business-capability-extraction-delivery.md) · [任务拆分计划](12-task-module-split-plan.md)

## 1. 范围与默认实施要求

默认执行 **F0–F4**：冻结可比较基线，修复 ZAP 装配和治理协调接线，修复共享 HTTP 边界，收口测试迁移及浏览器登录失败，完成回归和交付。

**D1–D4 是后续目录优化路线，本轮只记录，不在修复过程中提前整体搬迁。** 不重做 R/C/T/E 阶段，不开发 E5 工具、知识库或新产品，不升级框架与依赖，不修改 API 前缀、角色、错误信封、数据库结构和历史迁移，不恢复已清理的纯转发目录。

## 2. 已核查的问题与证据边界

E 阶段全量记录为 `963 passed、69 failed、3 errors、79 warnings`。前次记录缺少逐项失败清单，不能可靠判断比 68 多出的那一项属于新增还是基线。pytest 的 `lastfailed` 缓存含已删除路径和历史残留，不能代替单次全量清单。

上一轮现场核查通过 OpenAPI、真实 HTTPX MockTransport/编码行为和隔离 PostgreSQL 代表性用例确认以下问题；这不是本次文档编制重新取得的测试结果，也不证明每项的引入时间。

| 编号 | 优先级 | 当前问题与证据 | 主要路径 |
|---|---|---|---|
| FIX-01 | P1 | ZAP 独立 Router 有 28 个路由操作，但应用 OpenAPI 缺少扫描目标、扫描任务、健康检查等路径；主生命周期仅启停 TaskWorker，未找到生产装配启动 ScanWorker | `backend/app/main.py`、`features/security_testing/zap/router.py`、`zap/worker.py` |
| FIX-02 | P1 | 治理路由调用四个未导出的服务方法；Skill 历史恢复已在隔离库复现 AttributeError；Skill 更新直接走底层服务还会绕开引用保护协调 | `backend/app/features/agent_governance/router.py`、`app/agents/services/agent_service.py`、`app/skills/services/`、`app/mcp/services/` |
| FIX-03 | P2 | `json_body_present=True` 且值为 None，HTTPX 实际发送空字节且没有 JSON Content-Type；现有专项只检查 Mock 收到 json=None | `backend/app/execution/http/executor.py`、`backend/tests/test_business_capability_extraction.py` |
| FIX-04 | P2 | UTF-8 多字节字符跨 65,536 字节边界时被逐块 decode 损坏；现场中文字符得到替换字符 | 同上 `_decode_chunks` |
| FIX-05 | P2 | 小块慢响应可被 iter_bytes 聚合缓冲，3 秒预算的模拟流读到第 8 秒且没有 timeout 分类；当前循环内时钟检查不是可靠的总时长上限 | 同上发送与流读取路径 |
| FIX-06 | P2 | Web 草稿测试仍向工具模块注入已迁移的 Provider；意图契约测试仍从 agents.schemas 导入实际在 session_schemas 中的常量 | `tests/test_30_web_ui.py:306`、`tests/test_33_web_agent_loop.py:379` |
| FIX-07 | P2 | 三个生产节点函数被 pytest 当测试收集并请求 ctx fixture | `app/agents/workflows/legacy/nodes/test_*.py`、pytest 收集配置 |
| FIX-08 | 待定位 | 浏览器端到端用例登录后等待 /admin/dashboard 超时；尚不能判定为认证、路由、页面或测试环境问题 | `backend/tests/test_31_web_ui_console.py` 及对应认证/页面链路 |

上一轮隔离库定向运行的四个用例全部失败，具体原因分别是旧 Provider 注入位置、浏览器跳转超时、旧常量导入和 Skill 恢复服务缺失。不得将这些结果笼统标记为“都是旧问题”，也不得据此推定 69 项的全部根因。

## 3. F0：建立逐项可追踪基线

1. 核对当前工作区、生产装配、测试入口和实际运行配置；记录受影响文件及当前补丁摘要，保留用户已有改动，不使用全仓 reset/restore。
2. 修复前以当前命令完整采集测试结果，区分 `pytest tests/` 的实际测试结果与默认入口的误收集；记录两种入口与配置差异，不能只更换命令就声称原全量错误消失。
3. 使用 pytest 内置 JUnit 输出及标准库解析，保存 nodeid、失败/错误分类、关键异常、开始时间、代码状态摘要、运行参数和测试收集数量。无需为生成报告引入新的测试插件。
4. 对新的本轮基线和修复后结果做集合比较：已修复、仍失败、新出现、未再收集/未执行分别列出。修复前未留存的历史 nodeid 归属标为未知，不补造旧清单。
5. 本次基线采集不是允许真实扫描或外发的入口：数据库使用显式配置的隔离库，HTTP/LLM/ZAP/通知依赖使用现有受控替身；浏览器只访问受控本地服务。

建议最终证据路径为 `docs/agent-cluster-refactor/backend-stabilization-validation/<run-id>/`，包含脱敏后的 `summary.json`、`failures.json` 与必要的 JUnit 摘要。原始输出先保存在本地临时目录，检查并脱敏后再纳入文档；不提交密钥、完整凭据 URL、原始敏感请求或登录态。

## 4. F1：修复应用装配与跨能力协调

### 4.1 ZAP HTTP 与 Worker 装配

- 在 `app/main.py` 唯一路由装配处挂载现有 ZAP Router，沿用 `/api/v1`，不复制路由实现，不创建第二套扫描服务。增加关键 method/path 存在性检查，不能仅比较总 path 数量。
- 核对部署是否另有独立扫描进程。如果没有，按现有 ScanWorker 的 `ZAP_ENABLED` 和生命周期约定接入主应用；若已有，记录唯一启动所有者，避免双重消费。当前核查未发现生产启动入口，执行时仍须复核。
- TaskWorker 继续处理统一任务，ScanWorker 继续领取扫描任务；不让 TaskWorker 复制扫描执行循环。关闭配置时不启动扫描，不把“启动线程”当作自动批准扫描。
- 生命周期在正常退出及异常退出路径释放已启动资源，避免部分启动失败后遗留线程。保持人工计划/风险确认和项目出站规则。
- 测试以 Fake Worker/Connector 或 Mock transport 验证启动次数、开关、关闭和任务领取，不连接真实 ZAP、不发真实扫描。ZAP 目标 CRUD、计划审批和任务状态仍需隔离库行为回归。

### 4.2 治理接口接线

当前四个缺失调用与一个保护缺口如下：

| HTTP 操作 | 错误/不足的当前调用 | 应使用的职责 |
|---|---|---|
| 恢复 Skill 版本 | `skill_services.restore_skill_version` 不存在 | Agent 跨能力协调中的恢复逻辑，保留引用和启用保护 |
| Skill 使用统计 | `skill_services.skill_usage` 不存在 | 跨 Skill、Agent、Task 的真实聚合查询 |
| 删除 Skill | `skill_services.delete_skill` 不存在 | 检查 Agent 引用后再调用 Skill 底层删除 |
| 删除 MCP 服务 | `mcp_services.delete_mcp_server` 不存在 | 检查 Agent 工具引用后再调用 MCP 底层删除 |
| 更新 Skill | 直接调用 `skill_services.update_skill` | 应经过已有跨能力协调，保留停用已引用 Skill 的保护 |

上述协调实现已在 `agents/services/agent_service.py` 中存在，先复用正确的公开服务入口并核对必要导出，不把协调逻辑复制到路由或让 skills/mcp 反向依赖 agents。不能只给底层补同名无保护转发消除 AttributeError。

对治理 Router 全部服务调用做一次符号存在性及真实行为核查；增加恢复/查询/删除/更新和引用冲突测试，验证 2xx、404、冲突、版本递增及历史快照行为，保留平台管理员门槛。

## 5. F2：修复共享 HTTP 的真实边界

### 5.1 JSON null 的字节契约

明确区分“无请求体”和“显式 JSON null”。后者必须实际发送 `b"null"` 及正确 JSON Content-Type；保持调用方显式 Header 覆盖规则，不将 Form/Multipart/Raw 错误转成 JSON。

使用真实 HTTPX 编码和 MockTransport 捕获最终 request.content、headers，分别测试无 body、null、false、0、空数组/对象和普通 JSON；不能只断言传给 FakeClient 的 kwargs。调试输入到发送器的端到端契约也应覆盖。

### 5.2 UTF-8 分块与截断

对受限字节序列整体解码，或使用正确的增量解码器；保持有界内存和原截断标识。测试多字节字符恰好跨网络块、超过截断上限、空响应和非法 UTF-8 的既有替换行为。

修复合法跨块字符，不能悄悄扩大响应内存上限或改变所有调用方的文本/字节限制契约。先明确现有字节停止读取与字符截断的组合规则并记录。

### 5.3 总时长与慢响应

将总 deadline 贯穿连接、响应头与正文读取，区分 socket 单次读超时和整个请求预算。仅减小 chunk_size 或在 yield 后比较时钟不足以可靠限制持续滴流；采用真正能按剩余预算中止阻塞读取的实现，不引入新的运行框架。

截止后应归入现有 timeout 错误处理，并关闭响应/连接资源；保留调试与业务各自的错误对外适配，不以成功的截断响应冒充超时。已有普通大小截断行为保持。

增加确定性模拟时钟/流测试，以及受控本地慢响应验证：持续小包、响应头延迟、首字节延迟、正常响应、断连等，明确允许的小幅调度容差，不能用任意 sleep 把测试拖长。保持 `trust_env=False`、禁止重定向、项目出站授权、显式内网放行和敏感值脱敏。

## 6. F3：收口测试迁移、收集与浏览器问题

- `test_30_web_ui.py` 的 Provider 替身改到实际构造点或既有明确注入接口；请求仍通过真实草稿服务，继续断言 AI 草稿必须人工确认后执行，不删除确认检查。
- 意图常量测试从规范的 `agents/session_schemas.py` 取得 AGENT_INTENTS，继续验证全部意图出现在生产提示词中。不为一项旧导入恢复 schemas 通配转发。
- 明确后端 pytest 收集入口，例如在正确配置位置限制 `testpaths = tests`，并在默认启动目录和 CI 命令中验证生效；真实测试用例不能因此遗漏。生产节点无需为 pytest 收集而伪造 ctx fixture 或改写业务行为。
- 对浏览器登录超时采集登录响应、Cookie、实际 URL、前后端地址、API 代理和控制台错误，使用隔离用户核对。根据证据修复应用或测试，不先扩大超时时间或把预期跳转改成任意页面。测试保持与现有 Cookie/Origin 认证策略一致，证据不得保存密码/会话密钥。
- 逐族复跑剩余 ZAP、审批、Web、治理失败，区分修复装配后消失的连锁失败与独立故障；存在独立故障时在本轮必要范围内做最小修复，不随之展开目录搬迁。

## 7. F4：验收与交付门槛

建议测试入口（使用当前仓库运行时，按阶段先定向后全量）：

```bash
cd backend
.venv/bin/python -m compileall -q app tests scripts alembic/env.py
.venv/bin/python -m pytest tests/test_business_capability_extraction.py tests/test_27_langfuse_tracing.py tests/test_15_test_executor.py -q
.venv/bin/python -m pytest tests/test_29_zap_scan.py tests/test_32_zap_agent_approval.py -q
.venv/bin/python -m pytest tests/test_30_web_ui.py tests/test_31_web_ui_console.py tests/test_33_web_agent_loop.py tests/test_36_agent_governance_details.py -q
.venv/bin/python -m pytest tests/test_core_consolidation.py tests/test_task_module_split.py tests/test_35_tasks.py tests/test_task_notifications.py -q
```

新增接线与 HTTP 边界测试可写入现有相关文件或新增专门测试文件，不为每个包装方法重复测试。收尾运行标准后端全量命令，启用 JUnit 输出并生成逐项差异，确保生产节点误收集为零、收集数量变化可解释。

完整验收应满足：

1. ZAP 关键路由可达且权限有效，Worker 按配置唯一启停，审批和扫描领取通过受控测试。
2. 治理服务方法全部存在，恢复/使用统计/删除及引用保护真实通过。
3. HTTP null、分块字符及总预算在真实编码/流行为验证通过，正常请求和既有调用方不回归。
4. 旧符号导入和错误注入位置消除，浏览器失败已定位并修复或明确列出阻塞；没有测试跳过、弱化断言或伪造成功。
5. 全量测试实际结果、warnings 分组、失败 nodeid 和运行代码状态可追踪。非零失败/错误时不能声明全量验收通过，相关 D 阶段不能据此视为可安全推进。

数据库只使用随机/明确拥有的隔离测试库，凭据由环境提供，不写入文档或日志。保留前轮记录，不用本轮报告改写历史事实。本轮不要求通过修改历史迁移来解决离线 SQL 等前轮独立限制。

实施后创建 `docs/agent-cluster-refactor/backend-stabilization-delivery.md`，记录 F0–F4、逐项修复及来源判断、测试证据路径、接口与生命周期检查、未解决问题、警告分类和回退方式。不能仅以编译、OpenAPI 可生成、专项若干 passed 宣称全后端稳定。

## 8. 后续 D1–D4 目录优化路线

现有顶层 `core/execution/llm/agents/tools/skills/mcp/features` 足以表达职责。后续以领域内部拆分及公开契约收口为主，不新增万能 common/utils 包，也不再整体移动顶层目录。

| 阶段 | 后续目标路径与内容 | 进入条件与验收重点 |
|---|---|---|
| D1：执行契约与准备 | `features/test_management/executors/contracts.py`、`preparation.py`；再按需提取类型 adapters | 先消除 `web_ui/runtime/adapter.py` 对 test_case_executor 的 `_load_assertions/_load_data_values` 依赖；公开结果契约、数据准备与实际执行分开，Fixture、人工确认和执行落库不变 |
| D2：任务运行控制 | 按既有 T4–T6 规划拆 `tasks/services/run_service.py`、`plan_service.py`、`command_service.py` 及 runtime lease/completion | 当前 Worker 约 1964 行、TaskService 约 1291 行；不以行数验收，保持批准版本、命令幂等、行锁、租约、迟到结果和事务边界 |
| D3：安全域内部 | 整理 `security_testing/zap/connector.py`、`orchestrator.py` 及 `runtime/runner.py` 的协议调用、能力探测、扫描阶段、结果归一化 | 不复制扫描队列，不把纯测试 Mock 优先当生产拆分对象，不将 ZAP 领域代码泛化进 HTTP 底座 |
| D4：目录服务与 schema | 按实际资源拆 `api_catalog/services/api_service.py` 的模块/接口/请求/关系/响应转换；按资源拆大 schemas 包 | 保持当前接口、字段、分页、顺序和公开入口；不新增另一套模型或大量纯转发文件 |

execution 出站策略和 llm 配置加载当前通过业务公开服务协作，不属于必须马上修复的循环。后续存在独立复用需求时，再引入窄策略/配置加载接口，不为“彻底无依赖”改写权限和密钥管理。

默认本轮到 F4 即交付，D 阶段仅输出实际待办和建议依赖。开始 D1 前保存新的稳定基线并单独明确实施范围；每批目录拆分后运行受影响验证与完整回归。

## 9. 回退与范围控制

按 F 阶段的小批次恢复代码和装配，不用全仓重置覆盖现有改动。无 schema 改动不降库、不删除真实产物；确保回退不造成双 Worker 消费或新旧 HTTP 发送实现同时执行。回退保留失败清单与复现测试，明确哪些问题会重新出现。

本计划不要求自动部署、连接真实扫描目标或发送外部通知。问题修复后的交付证据与 D 阶段设计分别记录，保持“已修复”“待验证”“仅规划”状态清晰。
