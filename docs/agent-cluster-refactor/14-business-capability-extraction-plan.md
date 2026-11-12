# 业务域共享能力提取与工具化计划

本文定义跨业务域 HTTP 执行、表达式基础能力、LLM 调用和模板解析的目标归属、实施顺序及验收要求，并单列业务工具扩展需求，供实施 Agent 使用。本次只编写文档，未执行代码迁移、功能开发或测试。

编制日期：2026-10-29。核对对象为当前工作区，HEAD 为 `e46cbc9`，包含已有本地改动；实施时重新核对实际代码。前轮任务 T0–T3、core 归并和纯转发文件清理已有实现与记录，不能重复建设或按旧设计恢复已删除的兼容目录。

[返回索引](README.md) · [实施需求提示词](15-business-capability-agent-prompt.md) · [业务能力提取交付记录](business-capability-extraction-delivery.md) · [任务模块拆分交付记录](task-module-split-delivery.md) · [core 交付记录](core-consolidation-delivery.md)

## 1. 目标与本轮范围

从 `features` 中提取已经被多个业务模块使用的执行与基础能力，消除对其他领域私有实现的依赖。业务实体、业务规则、权限、审批、事务和执行记录继续由原领域持有。

默认实施 **E0–E4**：基线核对、HTTP 执行共享化、表达式基础能力提取、LLM 调用独立、模板解析归属调整。**E5 是新增业务工具的独立功能阶段，本轮只输出建议契约，不自动注册或开放给模型。** 通知渠道、ZAP、Playwright 的进一步内部拆分另作后续需求，不为统一目录把所有外部客户端搬到公共层。

不引入新框架、消息中间件或依赖升级，不修改数据库结构、HTTP 接口、角色体系、任务状态机与人工确认规则，不开发知识库，不继续扩大 T4–T6 或前端拆分。

## 2. 当前代码依据

| 现状 | 代码路径 | 提取理由 |
|---|---|---|
| HTTP 执行器位于 business，被测试、安全、造数等调用 | `backend/app/features/business/executors/api_executor.py` | 已是跨域能力，归属不应要求调用方依赖业务流程内部 |
| 调试另有 HTTP 发送、超时和截断实现 | `backend/app/features/api_catalog/services/debug_service.py` | 可共享运输与请求构建，但保留调试鉴权、错误与响应契约 |
| 测试断言引用业务映射私有 JSONPath 函数 | `backend/app/features/test_management/executors/assertion_engine.py` → `business/executors/mapping_resolver.py` | 纯路径读取应有公开公共入口 |
| 业务前置条件、测试断言、Web 比较存在复用或相似逻辑 | `business/executors/precondition_evaluator.py`、`test_management/executors/assertion_engine.py`、`web_ui/runtime/playwright_executor.py` | 可提取已确认一致的基本操作，领域结论和不同语义必须保留 |
| 模型调用归 agents，却被报告、Web、任务使用 | `backend/app/agents/providers/llm_provider.py` 及调用方 | 模型调用、结构化校验、候选链和追踪可独立于 Agent 编排 |
| `${namespace.path}` 已有统一解析实现 | `backend/app/features/test_data/runtime/variable_resolver.py` | 调整共享归属，不重写第二套解析器 |
| 业务、Mock、Fixture 等已有工具适配 | `backend/app/tools/builtin/` | 复用并补全真实能力，不能仅增加目录项声称完成 |

前轮交付记录存在全量测试未通过及测试收集问题；数量和根因以 E0 新复现为准，不将历史失败全部视为与本轮无关。最近的实际实现和清理说明优先于早期计划中的保留旧路径建议。

## 3. 建议目标目录

只创建有真实实现的模块；较小的职责可先合并文件，不要求每一行都生成目录。

```text
backend/app/
├── execution/                         # 被测业务的共享执行能力
│   ├── http/
│   │   ├── contracts.py               # 请求、响应和执行选项
│   │   ├── executor.py                # 统一发送、流式读取、超时和截断
│   │   ├── request_builder.py         # 通用 URL/请求组装
│   │   └── outbound_policy.py         # 策略契约、判定结果和校验协调
│   └── templates/
│       ├── resolver.py                # 迁移现有唯一模板解析器
│       └── context.py                 # ResolveScope/RequestContext 等契约
├── core/
│   └── expressions/
│       ├── paths.py                   # 当前支持的 JSON/字典路径读取
│       └── operators.py               # 已确认一致的比较基础操作
├── llm/
│   ├── contracts.py                   # Provider 协议、错误、输入输出契约
│   ├── providers/                     # 当前兼容接口调用实现
│   ├── routing.py                     # 现有候选链、切换和尝试记录
│   └── tracing.py                     # 通用模型调用追踪
├── agents/                            # 组装、会话、工具使用与领域工作流
├── tools/builtin/
│   ├── business/                      # 现有工具；E5 再增加业务预览/校验
│   ├── environment_configuration/    # E5 拟新增脱敏环境只读工具
│   ├── api_catalog/
│   ├── test_data/
│   └── reports/
└── features/
    ├── projects/                      # 项目目标授权与策略数据来源
    ├── model_configuration/          # 模型配置、加密凭据和资源授权
    ├── environment_configuration/    # 项目环境绑定和覆盖配置
    ├── api_catalog/                   # 接口定义、调试鉴权与返回适配
    ├── business/                      # 流程、动作、映射、前置条件和结果
    ├── test_management/               # 用例执行协调、断言结论与执行记录
    └── ...                            # 其他领域保持归属
```

E5 尚未实现时不建立占位工具目录。`execution` 和 `llm` 包入口保持轻量，不集中加载全部业务模型和处理器。

## 4. E1：提取共享 HTTP 执行

### 4.1 职责与路径

- 将现有 `ApiRequestExecutor`、`ApiRequestResult` 的通用执行实现迁入 `app/execution/http/`；结果类是否改名以最小改动为准，不为目录迁移调整返回语义。
- URL、Header 和 Body 的通用构建迁入 request builder；接口定义如何读取、参数覆盖优先级及调试输入转换仍由 api_catalog 公开服务提供。
- 将 `_load_params/_load_body` 等跨服务调用整理为 api_catalog 的明确公开读取契约，避免新共享模块依赖接口私有实现。
- 出站策略的数据获取和项目授权留在 projects 的公开服务。HTTP 层经明确策略接口取得允许/拒绝及必要目标引用，不直接依赖 business、任务或 Agent。
- 调试、业务流程、用例、安全、数据准备/清理全部切换到同一规范 HTTP 发送实现；不能只新增 executor 而继续保留两套发送循环。

### 4.2 必须保留的可观察行为

现有调试拒绝目标时可能抛 HTTP 错误，执行器则返回 `error_message`；调试结果还包含 `outbound_target_id`。保留调用方适配，不把错误和字段强行统一成同一种外部响应。

E0 为以下行为建立差异表和测试后再共享实现：

- 环境 base_url/gateway/path 拼接、路径参数替换、Header/Query/Body 覆盖顺序，以及当前实际支持的 JSON、Form、Multipart、Raw 请求方式。
- scheme/host/port、非法端口、停用目标、跨项目目标及显式放行的内网目标处理；默认不新增目标授权，不能把白名单失败改为自动直连。
- `trust_env=False`、`follow_redirects=False`、分段超时、总时长限制、响应流式读取和当前 `200_000` 截断行为。
- 连接/超时/HTTP 错误映射、响应状态与头、耗时字段、截断标识和脱敏行为。已有差异先由适配层承接，不在结构重构中悄悄修成另一种产品行为。

该能力针对被测目标。LLM、MCP、飞书、ZAP 控制端点有各自配置和访问策略，不自动经过测试项目的目标白名单，也不能以这些管理连接绕过被测目标授权。

## 5. E2：提取路径读取和比较基础操作

`mapping_resolver._jsonpath_extract/_parse_jsonpath_parts/_dot_path_extract` 中可共享的纯读取逻辑归 `core/expressions/paths.py`。保持现有支持子集、缺失值和数组索引行为，不新增完整 JSONPath 引擎、不执行表达式代码。

比较逻辑必须先按实际实现建立行为表，而不是按注释认定相同。当前已核对的差异包括：

- 业务前置条件使用 `str(None)`；测试比较将 `None` 归为空字符串。
- 业务未知操作符返回 false；测试比较的未知操作符回退到相等比较。
- IN 的空项、非字符串期望值处理不完全相同；测试另有数值比较和 EXISTS 语义。

只提取一致的底层操作。对不一致的行为保留具名领域适配或显式语义参数，不能把整个 `_compare` 替换成另一模块的函数。避免为兼容几个差异设计可执行任意规则的通用引擎。

测试用例是否通过、安全问题如何分类、业务前置条件是否阻止流程等结论仍由原领域决定。Web 读取比较基础能力时不再依赖测试管理内部实现；安全结果判定不整体迁入 core。

## 6. E3：LLM 调用独立

迁移 `agents/providers/llm_provider.py` 的协议、错误类型、生产/测试 Provider 与候选切换逻辑，以及 `langfuse_tracer.py` 中真正通用的追踪实现。按文件规模拆分，现有构造与调用参数尽量保持。

边界要求：

- `llm` 不导入 Agent 图、节点、任务 Worker 或报告结构；Agent/报告/Web/任务依赖其公开协议和实现。
- 模型配置、启用状态、加密凭据及资源授权继续由 `features/model_configuration` 和现有上层授权流程管理。首轮可通过该领域明确的公开服务加载配置；若发现循环则注入窄配置加载接口，不把配置管理和密钥主数据搬入 llm。
- 保持默认模型/显式模型/候选链、重试与切换、结构化 JSON/Pydantic 校验、工具调用轮次、工具白名单、错误码和尝试回调行为。迁移不能使原本失败的结构化结果静默成功，也不能扩大模型工具权限。
- 通用追踪归 llm；与 Agent 状态相关的埋点和任务持久化仍由上层回调负责。检查 Langfuse 测试替身的真实模块绑定，不恢复过期私有符号来伪造通过。
- 领域提示词与输出 schema 归领域。`reports/services/ai_summary.py` 当前使用 `agents.prompts.load_prompt`，应让报告模块持有其摘要提示词与加载入口；共享提示词加载若确有复用，使用无 Agent 依赖的资源加载器，不保留业务对 Agent 内部资源的反向依赖。
- 保留脱敏、不记录明文密钥、Fake Provider 行为及现有调用测试注入方式；测试不访问真实模型服务。

## 7. E4：模板解析调整归属

迁移当前 `test_data/runtime/variable_resolver.py` 的唯一实现到 `execution/templates/`；先保留实际算法，按需要分出上下文契约，不重写解析器。

环境/Fixture/Mock/运行数据由调用方构建上下文，模板引擎不读取数据库、发网络请求或查询业务配置。可通过窄类型契约接收环境值，不引入对 test_data、business、Mock 模型和服务的反向依赖。

保持：整段占位符保留原类型、混合文本字符串化、缺失与 required 规则、点路径及扁平键回退、命名空间、Header 大小写、嵌套上限、Faker 白名单/locale/choices 和随机值生成时机。Faker 并非纯函数，不能因共享而新增结果缓存或跨用例复用。

business 的输入/输出映射和变量生命周期仍归 business；模板解析不替代业务映射、字段类型校验或数据准备优先级。同步切换所有实际调用方和测试，不维护两个解析算法。

## 8. E5：独立业务工具需求清单

下列为建议的后续功能，key 是拟定契约，不是现有能力声明。本轮 E0–E4 不将其新增为已注册或可调用工具。

| 领域/建议 key | 建议路径（相对 backend/app） | 输入/输出与边界 |
|---|---|---|
| `business.validate_flow` | `tools/builtin/business/` | 读取项目内指定流程版本，返回缺失绑定、变量引用和前置条件问题；不写流程、不执行接口 |
| `business.preview_mapping` | `tools/builtin/business/` | 使用显式样例值预览参数映射，返回脱敏请求草稿及缺失项；不准备 Fixture、不发请求 |
| `environment.list_available` / `environment.get_summary` | `tools/builtin/environment_configuration/` | 仅当前项目活动绑定；返回安全字段白名单，不返回 Header/凭据原文或管理密钥 |
| `api_catalog.compare_versions` | `tools/builtin/api_catalog/` | 仅使用实际存在的历史结构/变更快照；数据不足明确返回不支持，不编造版本差异 |
| `test_data.preview_template` | `tools/builtin/test_data/` | 样例上下文有限解析，展示缺失值和脱敏结果；不执行 Provider，不调用数据库或数据准备链 |
| `report.get_evidence` | `tools/builtin/reports/` | 当前项目可见报告和真实执行来源；返回有界摘要及引用，不泄露原始敏感请求/响应 |

E5 实施时先复用对应业务公开服务，缺少服务先建设并验证契约，再做薄工具适配。稳定 key、参数、风险、真实处理器、允许通道和审计需一致。只读预览仍要核对是否生成随机值、持久化或外部请求，不把写入包装成只读；不能仅凭管理员配置或绑定 Skill 开放权限。

这些本地 Python 能力直接通过工具调用即可；不要求新增 MCP 服务。新增工作方法 Skill 可引用工具，但不复制执行代码或把项目事实写进 Skill。

## 9. 阶段出口与验证

| 阶段 | 实施范围 | 验收证据 |
|---|---|---|
| E0 | 核对最新实现、调用点、清理状态、前轮失败、HTTP/比较语义和外部 IO；建立行为基线 | 真实路径图、差异表、受影响测试及当前失败分类；不照搬旧失败数量 |
| E1 | 共享 HTTP 请求构建、发送与策略协调，切换业务/调试/测试/安全/造数实际调用 | 拒绝/允许目标、错误返回、Body/超时/截断、环境覆盖、真实调用路径验证，无第二套发送循环 |
| E2 | 共享纯路径读取与比较基础操作，保留领域差异 | None/缺失/空项/未知操作符、数值与路径边界测试，领域结论不变 |
| E3 | LLM 协议与调用、切换和追踪独立，报告资源归领域 | Fake/Mock 调用验证默认/候选链、错误/结构校验、工具限制、脱敏、追踪和测试注入 |
| E4 | 唯一模板解析器迁移及调用方收口 | 造数、用例、Mock 和安全基线相关回归；无重复实现和反向业务依赖 |
| E5 | 后续独立工具开发 | 对应服务真实可用、工具通道受控、权限/无副作用/脱敏验证；另行交付 |

可复用的测试入口（按实际修改选取，每批不必重复全跑）：

```bash
cd backend
.venv/bin/python -m compileall -q app tests scripts alembic/env.py
.venv/bin/python -m pytest tests/test_api_catalog.py tests/test_11_business_executor.py tests/test_12_business_integration.py tests/test_15_test_executor.py -q
.venv/bin/python -m pytest tests/test_19_data_factory.py tests/test_20_test_data_lifecycle.py tests/test_21_mock_management.py tests/test_25_security_execution.py -q
.venv/bin/python -m pytest tests/test_16_agent.py tests/test_17_report_notification.py tests/test_27_langfuse_tracing.py tests/test_35_tasks.py tests/test_task_module_split.py -q
```

E0 按当前测试入口复核 pytest 收集、Langfuse 和 ZAP/Web 等既有失败；对相关阻塞先修复最小问题，已证实无关项记录复现证据和范围，不为了全绿删除断言、跳过测试或虚构成功。HTTP 验证使用 Mock transport/受控本地服务，LLM 使用 Fake/Mock，不发送真实测试、扫描、模型或通知请求。

数据库测试使用显式配置的隔离 PostgreSQL，凭据不写入文档和普通输出，不清理开发/生产库或归属不明的数据。新增测试只覆盖本轮真实兼容风险和未覆盖边界，不为每个转发/包装重复写测试。收尾运行后端全量回归，分别记录新增失败、已复现基线失败与未测项；编译、OpenAPI 和文件移动不能替代行为验收。

## 10. 调用方、兼容和交付

优先将当前内部调用方、脚本和测试直接迁到规范路径，不恢复已删除的 `app.shared`、`app.models`、`features.agent` 等历史转发目录。不默认为每个移动文件新增 re-export；只有确实存在且需保留的公开调用契约才保留最小单向门面，列出实际消费者、原因和清理条件，不保留两套主体实现。

现有历史迁移和已落地 core/任务实现以当前代码为准，不为本轮文件移动新增 schema revision、修改旧迁移或重新进行迁移链路清理。工具 key、工作流 key、状态、运行快照、回执及原 HTTP 契约保持。

实施后创建 `docs/agent-cluster-refactor/business-capability-extraction-delivery.md`，记录 E0 基线、E1–E4 实际路径/符号映射、HTTP/比较语义承接方式、真实测试结果、必要门面、已知限制及 E5 契约待办。同步编码规范、当前架构说明、相关能力路径及索引，不改写前轮测试记录为本轮成功证据。

无 schema 变化时按代码批次回退，不执行数据库降级，不删除真实业务产物；禁止在新旧执行主体并存时重复运行工作项。未完成验证明确标记，不能把规划目录、只登记的工具或未接通的客户端标为已交付能力。
