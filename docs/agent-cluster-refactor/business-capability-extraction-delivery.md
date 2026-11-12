# 业务域共享能力提取交付记录

交付日期：2026-10-29。按 [14 计划](14-business-capability-extraction-plan.md) 与 [15 实施提示词](15-business-capability-agent-prompt.md) 完成 E0–E4。E5 只整理建议契约，没有实现、注册或开放新工具。

本轮没有修改 REST API、角色/权限判定、业务结论、模型授权、数据库结构或依赖版本。事务提交仍由原领域 service/run service 持有；暂停、取消、任务回执和人工确认入口及其校验未改。

## E0：代码与回归基线

实施前保留了工作区既有改动，没有重置或清理它们。先尝试运行计划中的定向组：`test_api_catalog.py`、`test_11_business_executor.py`、`test_12_business_integration.py`、`test_15_test_executor.py`、`test_19_data_factory.py`、`test_20_test_data_lifecycle.py`、`test_21_mock_management.py`、`test_25_security_execution.py`；沙箱禁止连接本机 PostgreSQL，实测为 **84 passed、96 errors**，错误都在数据库 fixture 连接阶段，不能作为产品失败或完整基线。

最近一份此前全量记录见[任务模块拆分交付记录](task-module-split-delivery.md)：`pytest -q --tb=no` 为 **958 passed、68 failed、3 errors、79 warnings**。该记录将错误定位为 3 个 Agent 节点源文件被 pytest 当作测试收集、缺少 `ctx` fixture；失败集中在 ZAP API、ZAP/Agent 审批、Web 流程和治理 Skill。它是最近的历史比较值，不等同于本次迁移前在相同工作区重跑的基线。

E0 核对的行为差异如下：

| 能力 | 既有领域行为 | 提取后的承接方式 |
|---|---|---|
| HTTP 出站 | 业务执行拒绝时返回 `error_message`；调试返回其既有 HTTP 错误，并带 `outbound_target_id`。显式启用的项目白名单可放行内网目标。 | 共享策略返回判定，业务和调试各自映射原有错误契约；目标记录读取仍由 projects 提供。 |
| 比较 | 业务前置条件把非缺失的 `None` 转为 `"None"`，未知操作符为 false，IN 保留空项；测试/Web 比较将 `None` 当空串，未知操作符回退 EQ，IN 丢弃空项。 | 只共享可配置的文本、CSV 与数值比较原语；测试/Web 和业务各自保留领域入口及判定。 |
| 路径读取 | 业务映射、测试断言和 Web 使用相同的有限 JSON/字典路径子集；Mock matcher 另有 matcher 级 EXISTS 规则。 | 抽出受限纯读取函数；Mock matcher 的独立规则留在原领域。 |
| 模型配置 | Provider 依赖上层选择的默认或显式授权候选；密钥加密与启用配置归模型配置域。 | Provider 通过 model_configuration 公开读取窄配置，不自行决定调用者授权范围。 |
| 模板 | 整段占位符保留原类型，混合文本字符串化；缺失、required、命名空间与 Faker 规则由唯一解析器处理。 | 迁移原解析实现和上下文类型，不新增缓存或另一套算法。 |

## E1：共享 HTTP 执行

| 原职责/调用点 | 规范路径 | 结果 |
|---|---|---|
| `features/business/executors/api_executor.py`：`ApiRequestExecutor`、`ApiRequestResult`、HTTP 发送循环 | `app/execution/http/executor.py`、`contracts.py` | 唯一共享发送循环；`ApiRequestResult` 是 `HttpExecutionResult` 的类型别名。旧业务模块主体实现已删除。 |
| URL、环境头和请求字段合并 | `app/execution/http/request_builder.py` | 业务、测试、安全、Fixture 与调试调用公共 builder。 |
| 项目目标授权查询 | `app/features/projects/services/outbound_service.py` | 由 projects 公开读取明确启用的目标，HTTP 层不查业务私有服务。 |
| 接口参数与请求体读取 | `app/features/api_catalog/services/request_service.py` | API 调试、接口服务和导入服务走公开读取函数。 |
| 调试独立发送实现 | `app/features/api_catalog/services/debug_service.py` | 改用共享发送与目标策略；调试鉴权、请求转换、拒绝状态、`outbound_target_id` 和响应结构由调试服务继续负责。 |
| 业务流程、用例、测试数据创建/清理、安全基线与重放 | `business_flow_executor.py`、`test_case_executor.py`、`api_create_provider.py`、`cleanup_runner.py`、`security_testing/runtime/runner.py` | 已迁移到共享 executor 和 builder；未发现剩余 `ApiRequestExecutor.build_url/get_environment_headers` 旧调用。 |

共用发送保留 `trust_env=False`、不跟随重定向、独立 connect/write/read/pool timeout、总时长截止、流式读取和 `200_000` 字符截断。传输错误由共享结果分类，再由业务/调试适配为各自历史错误。调试显式 JSON `null` 与业务“无 JSON body”的区分由 `json_body_present` 保留。LLM、MCP、通知与 ZAP 控制连接继续使用各自访问策略。

## E2：表达式基础能力

| 原路径 | 新路径/消费者 | 领域边界 |
|---|---|---|
| `features/business/executors/mapping_resolver.py` 的 `_jsonpath_extract`、解析器和点路径读取 | `app/core/expressions/paths.py`；业务映射与 `test_management/executors/assertion_engine.py` 调用 | 仅保留既有 `$`、点路径和非负数组下标子集；缺失值返回 `None`，不执行代码，也不引入完整 JSONPath 引擎。 |
| 测试断言的 `_compare` | `app/core/expressions/operators.py`；测试断言及 Web UI 比较 | 共享既有测试/Web 语义：`None` 视作空串、IN 丢弃空项、数值优先比较、未知操作符回退 EQ。 |
| 业务前置条件 `_compare` | `app/core/expressions/operators.py` 的文本/CSV 原语 | `_compare` 仍在 business：保留 `None` 的专门分支、未知操作符 false、IN 空项处理和前置条件是否阻断流程的领域结论。 |
| Mock 请求 matcher 路径语义 | `features/mock_management/matchers/` | 保留独立 matcher 规则，不用通用 EXISTS 替代。 |

测试通过/失败、安全问题分类、业务流程能否继续仍由原领域决定；安全比较与规则执行没有整体迁入 core。

## E3：LLM 调用与追踪

| 原路径/调用方 | 规范路径 | 保留的职责与语义 |
|---|---|---|
| `app/agents/providers/llm_provider.py` | `app/llm/providers/openai_compatible.py` | 唯一生产/Fake Provider、结构化 JSON 校验、工具调用限制、候选切换及尝试回调实现。 |
| Provider 协议与错误 | `app/llm/contracts.py`，由 `app/llm/__init__.py` 导出 | Agent、任务和领域服务通过公开协议处理结果与错误。 |
| `app/agents/providers/langfuse_tracer.py` | `app/llm/tracing.py` | 通用追踪实现；Agent 状态和任务持久化仍由上层处理。 |
| 模型配置 ORM 查询与密钥解密 | `features/model_configuration/services/model_config_service.py` 的 `load_model_for_provider` | 仅返回已启用的默认/指定配置及内存解密的最小 DTO；加密、管理员配置权限、候选授权和调用者选择仍归原域与上层。 |
| 报告摘要提示词 | `features/reports/prompts/report_summary.md` 与 `prompts/__init__.py` | 报告领域拥有固定摘要文本、版本和加载器；从 Agent 提示词加载入口移除该报告资源。 |

Agent、报告、Web 和任务的实际调用点及测试替身均已迁到 `app.llm` 公开路径。候选链保留在现有 Provider 内，没有为一个实现额外拆出 `routing.py`。未改变 API、任务状态、授权、审批、工具白名单或报告统计/脱敏规则。

## E4：模板解析

`features/test_data/runtime/variable_resolver.py` 的唯一解析实现迁到 `app/execution/templates/resolver.py`；原文件删除。`ResolveScope`、`RequestContext` 等上下文契约继续与实现同文件，尚无拆分独立上下文模块的需要。

用例执行、Fixture Provider、造数运行时与清理、Mock 服务/响应、Web UI runtime 和测试均直接引用新路径。保持命名空间、完整占位符类型、混合字符串、缺失/required、点路径与扁平键回退、递归深度、Header 大小写、Faker 白名单/locale/choices 与每次生成时机。解析器不读取数据库或网络；业务映射和 Fixture 优先级仍由调用方处理。

旧 `app.agents.providers`、`app.features.business.executors.api_executor` 和 `app.features.test_data.runtime.variable_resolver` 源码路径均未保留兼容目录或第二套主体实现。

## 验证结果

| 验证 | 实际结果 |
|---|---|
| `.venv/bin/python -m compileall -q app tests scripts alembic/env.py` | 通过，退出码 0。 |
| `pytest tests/test_business_capability_extraction.py tests/test_27_langfuse_tracing.py -q` | **13 passed，1 warning**。覆盖 HTTP 响应/截断与显式 null、表达式领域语义、模板语义及追踪入口。 |
| `pytest tests/test_15_test_executor.py -k TestAssertionEngine -q` | **17 passed，9 deselected，1 warning**。 |
| `pytest tests/test_15_test_executor.py::TestAcceptanceSingleApi::test_login_passes_and_masks_sensitive -q` | **1 passed，11 warnings**。全量首次运行曾发现用例执行器、Fixture 清理和安全执行器仍调旧静态 builder；这些调用已迁移后复跑通过。 |
| 后端全量：`pytest -q --tb=no -r fE` | **963 passed、69 failed、3 errors、79 warnings，320.21 秒**，退出码 1；不是全绿。使用随机 `testplatform_test-p*` 隔离 PostgreSQL，夹具负责建库、迁移和删除。 |

全量回归中，计划涉及的 API 目录、business executor/integration、test executor、Data Factory、数据生命周期、Mock、security execution、Agent、报告/通知、Langfuse 和 Task 测试均未出现在失败清单中；这些用例在该次全量运行通过。失败清单集中为：`test_29_zap_scan.py` 48 项、`test_30_web_ui.py` 1 项、`test_31_web_ui_console.py` 1 项、`test_32_zap_agent_approval.py` 17 项、`test_33_web_agent_loop.py` 1 项、`test_36_agent_governance_details.py` 1 项。3 个 errors 是 `app/agents/workflows/legacy/nodes/{test_case_generator,test_planner,test_point_generator}.py` 的节点函数被 pytest 当测试收集、缺少 `ctx` fixture。

### 失败归类与未测项

- **可确认的基线错误：** 上述 3 个 `ctx` fixture 收集 errors 与最近历史全量记录中的 3 个 errors 相同。
- **已知基线失败类型重现：** ZAP 路由/API 返回 404 或目标 ID 缺失、ZAP/Agent 人工审批、Web UI、治理 Skill 失败，均属于[上一份全量记录](task-module-split-delivery.md)记录过的失败族；本次没有修改 ZAP 路由、Web 浏览器运行、工具审批或 Skill 文件导入实现。
- **未能逐条证明的新旧：** 上一份交付记录保存了 **68** 项失败的类别而没有完整失败节点清单；本次是 **69** 项。聚合差值为 +1，不能仅据此把某个测试断言为本轮新增或断言全部是基线。本轮提取专项测试及受影响的 HTTP/造数/安全执行套件没有失败。
- **未测项：** 没有在迁移前同一工作区上完成 PostgreSQL 全量基线；没有升级用户现有数据库或验证现有数据保留（本轮没有新增迁移）；没有发送真实模型、通知、ZAP 扫描或第三方网络请求。当前全量失败项需单独排查后再得到全绿结论。

首次全量执行暴露的旧静态 builder 漏迁已经修复，随后全量重跑从 **925 passed / 107 failed / 3 errors** 收敛到上表结果；未跳过测试、未移除断言。

## E5：后续工具契约（仅建议）

以下 key、输入/输出及边界是后续开发契约，不表示已建立目录、处理器、注册项或模型授权。

| 建议 key | 建议归属 | 契约边界 |
|---|---|---|
| `business.validate_flow` | `tools/builtin/business/` | 读取指定项目流程版本，回报绑定、引用和前置条件问题；不写入、不执行接口。 |
| `business.preview_mapping` | `tools/builtin/business/` | 只用显式样例预览脱敏请求草稿和缺失项；不准备 Fixture、不发请求。 |
| `environment.list_available` / `environment.get_summary` | `tools/builtin/environment_configuration/` | 仅当前项目有效绑定和安全字段白名单；不返回凭据原文或 Header 秘密。 |
| `api_catalog.compare_versions` | `tools/builtin/api_catalog/` | 只比较实际保存的历史快照；缺少数据时明确返回不支持。 |
| `test_data.preview_template` | `tools/builtin/test_data/` | 有限样例解析并脱敏；不执行 Provider、不查库、不启动准备链。 |
| `report.get_evidence` | `tools/builtin/reports/` | 返回项目可见报告的有界摘要和真实执行引用，不泄露原始敏感请求/响应。 |

## 回退方式

本轮没有数据库迁移、依赖升级或业务数据写入，因此不需要 schema downgrade。需要回退时，以本交付涉及的文件清单为单位反向恢复旧实现并把调用点一并切回；不要恢复 `app.shared`、`app.models` 等已清理兼容目录。由于工作区实施前已有其他本地修改，不要使用全仓 `git reset` 或无差别还原；先保存当前补丁，再仅反向应用本交付的路径与调用点变更。保留新的行为测试，直到确认旧实现完整恢复并验证后再决定是否移除。

相关规范已更新至 [编码规范 §2.1、附录 B](../coding-conventions.md)，文档导航见[本目录索引](README.md)与[文档总索引](../README.md)。


后续入口（2026-10-29）：[后端综合职责拆分 B0–B9](backend-comprehensive-delivery.md)。本文历史范围、结果与限制保持原事实。
