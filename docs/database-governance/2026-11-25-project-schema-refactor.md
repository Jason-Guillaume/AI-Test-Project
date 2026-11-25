# 平台数据库项目级重构方案

**建议以 180 张物理表为重构目标，分三次验收：198 → 186 → 183 → 180。** 这条路线保留现有功能，对 ORM、服务、Worker 和迁移同步改造。在此基础上，合并两类定义修订、隔离测试专用表各可再减 1 张，全部满足条件时为 **178 张**。

上一版的 194 张对应较少改动业务代码的路线。本方案从同一个 198 张基线重新计数。接口请求体、迁移证据和测试专用表各只计一次。统计对象为平台 PostgreSQL 的 `public` 物理表，含 `alembic_version`；临时双写表在退役后才算入净减数。目标假设同期没有其他功能新增表。[前次实测、索引与正文去重方案](2026-11-25-database-optimization-plan.md)

实施结果与隔离库验证见[减表实施与验收](2026-11-25-schema-refactor-verification.md)。

## 一、每张表的去向

目标列中已有的表继续使用，新表名是本方案的建议命名。只移动测试专用表的收益单列在可选阶段。

| 阶段与业务 | 现有表 | 目标表 | 净减 | 主要改动 |
|---|---|---|---:|---|
| A1 接口目录 | `api_interface`、`api_request_body`、`api_parameter`、`api_response` | `api_interface`、`api_contract_entry` | 2 | 请求体并入接口，参数和响应各作为一种有序明细 |
| A2 会话摘要 | `agent_session`、`agent_session_summary` | `agent_session` | 1 | 缓存摘要跟随会话，消息继续独立保存 |
| A3 Web 执行配置 | `test_case`、`web_case` | `test_case` | 1 | 在用例上保存可空的 Web 专属配置和确认指纹 |
| A4 项目安全设置 | `project`、`security_project_setting` | `project` | 1 | 项目承载可选设置，设置保留独立的修订号和权限 |
| A5 ASR 工作队列 | `asr_work_item`、`asr_processing_work_item` | `asr_queue_item` | 1 | 共享领取、续租和重试存储，两类运行各保留真实外键 |
| A6 ASR 人工审核 | `asr_review_audit`、`asr_speaker_review_audit`、`asr_speaker_name_audit` | `asr_review_event` | 2 | 同表记录文本审核、说话人归属审核和改名，保留不同审核对象 |
| A7 计划与套件 | `test_plan`、`test_suite`、`test_plan_suite`、`test_suite_case` | `test_collection`、`test_collection_member` | 2 | 计划与套件共享目录结构，成员关系仍限定为计划含套件、套件含用例 |
| A8 历史迁移证据 | `test_scope_migration_check`、`test_scope_api_backfill`、`model_global_migration_audit` | `migration_evidence` | 2 | 统一保存核对数、回填标记和历史决定 |
| B1 用例明细 | `test_step`、`test_assertion`、`test_case_precondition`、`test_case_data` | `test_case_component` | 3 | 同一用例的四类子记录共用存储，各自保留 ID、排序、约束和回收能力 |
| B2 旧模型中心 | `model_configuration`、`asr_connection`、`asr_parameter_set` | `model_resource`、`model_revision`、`model_parameter_profile`（三表均已存在） | 3 | 切换旧接口及消费者，复用现有凭据表和 ID 映射 |
| C1 可选，定义修订 | `agent_definition_revision`、`skill_definition_revision` | `definition_revision` | 1 | 保留定义类型、父外键与不可变快照 |
| C2 可选，测试沙箱 | `td_sandbox_task` | 由独立测试目标库的 fixture 建表 | 1 | 平台库退役该表，Provider 测试仍有真实目标表 |

**阶段 A 共减 12 张，落在 186 张。** B1 完成后为 183 张，B2 再减 3 张为 180 张，累计比当前少 18 张（9.1%）。以 180 张为起点，C1、C2 单独实施任意一个均为 179 张，两项均完成才是 178 张。若模型兼容迁移未通过，可以在 183 张独立交付。

## 二、决定设计的实测数据

2026-11-25 再次只读核对本地开发库，数据库版本为 `0097`，共 198 张表。工作区 head 为 `0099`，后两次迁移只新增列。以下都是开发库的精确计数。

| 核查对象 | 实测结果 | 对重构的约束 |
|---|---|---|
| 接口参数与响应 | 参数 181 行、响应 131 行，两表有 131 个相同的整数 ID。两表在开发库均无入向外键 | 对外 ID 要连同参数或响应的类型解释。导入和替换操作须只作用于指定类型 |
| 四类用例明细 | 步骤 27,704 行、断言 11,651 行、前置条件 4,516 行、数据项 9,026 行，共 **52,897 行**。有 **11,652 个整数 ID** 同时出现在至少两表，最多横跨四表 | 全量逐条保留。直接拼接旧主键会覆盖数据，回收站也会找错对象 |
| 断言对步骤的引用 | 11,651 条断言里，当前 `step_id` 非空为 0。实际库仍有指向 `test_step` 的外键 | 演练须另备有步骤级断言的样本，验证删除步骤及恢复流程 |
| Web 用例 | 991 条用例的 `target_type='WEB'`，`web_case` 为 0 行 | “类型是 WEB”和“已配置 Web 执行”是两个条件，列表、调度和人工确认依赖后者 |
| 模型映射 | 5 条旧文本模型均有相应的 `MODEL_CONFIGURATION` 映射。旧 ASR 连接和参数集均为 0 行；三张旧表分别有 7、5、4 条入向外键 | 可用文本模型验证现有 ID，须补充 ASR、多修订和共享连接样本才能验收退役 |
| 队列、审核与集合 | 两张 ASR 队列、三张审核表以及四张计划和套件表在开发库均为空 | 合并依据是模型约束和运行代码。性能、并发和非空历史的迁移须在隔离环境验证 |

## 三、先完成能独立发布的 186 张

**接口目录。** 同一接口至多有一个请求体，将可空的请求体 ID、类型、独立媒体类型、结构、原文和时间戳放在接口上。继续区分没有请求体与显式的 `none`，保留原 ID 和序列。参数与响应留为逐行明细，`api_contract_entry` 设置内部主键、`kind`、`public_id`、`interface_id`、`sort`，以 `(kind, public_id)` 唯一。位置、状态码和 `response_key` 保留可索引的列，支持具体响应码、范围码和 `default`。批量替换按接口和类型共同过滤；保留原有的 ID 分配、排序、权限、导入哈希及调试返回。列表查询只取接口摘要，避免每页携带请求体。[请求读写](../../backend/app/features/api_catalog/services/request_store.py) · [导入比较](../../backend/app/features/api_catalog/services/import_service.py) · [响应键迁移](../../backend/alembic/versions/0082_api_response_keys.py)

**三个一对一扩展。** 会话摘要以 `session_id` 为主键，刷新逻辑已锁定会话。摘要可作为按需加载的一组字段移入会话，继续校验消息来源、内容摘要和过期时间，刷新时保留会话列表原有排序及时间戳语义。Web 配置要显式记录是否存在，保住认证配置和确认人的外键，改步骤或依赖后仍会使确认失效。项目安全设置也要区分“从未设置”和“显式保存默认值”，保留原设置 ID、独立修订、操作者及时间，读取未配置项目仍只返回默认值。生产环境的强制拒绝规则和管理权限沿用现有实现。[摘要读写](../../backend/app/agents/services/context_memory.py) · [Web 配置读写](../../backend/app/features/web_testing/services/case_service.py) · [项目设置契约](../../backend/app/features/security_testing/services/setting_service.py)

回收站的永久清理会反查实际外键。摘要和安全设置移入父行后，这两个依赖须改成显式检查：仅剩摘要的会话、仅剩安全设置的项目，仍应在清理预览和实际执行时被拦截。回收站查询目前用资源类型和原表 ID，合并多种记录后也须用公开 ID 加类型过滤。[回收站清理与旧 ID 查询](../../backend/app/lifecycle/service.py)

**ASR 队列和人工审核。** 队列表保留 `available_at`、`lease_owner`、`lease_generation`、租约到期时间和尝试次数。`run_id` 与 `processing_run_id` 分别以唯一外键指向原父表，通过类型约束保证恰有一个非空。两类任务各自保留领取条件、处理类型、优先顺序和状态机。续租和完成按类型、队列行 ID、父运行 ID、owner、generation 原子核对；失去租约的 Worker 不再写入。持有租约的一方在同一事务内保存结果并移除工作项。切换前停止旧领取，排空在途任务或按原恢复规则接管。提交状态不确定的运行转人工核对；已有远端任务 ID 的运行沿用原轮询路径。[两种领取与恢复路径](../../backend/app/features/asr_evaluation/runtime/worker.py)

审核表为文本块、说话人归属和被改名说话人各留一个真实的主体外键，按审核类型限定恰有一个主体，沿用主体删除时的级联。归属审核中“本次选中的说话人”是另一条可空外键，删除说话人时保留该审核并将选中值置空。保留归属审核的 `(assignment_id, version)` 唯一约束、空文本确认、加入参考样本标志、改名前后值及操作者。旧三表 ID 各自在其类型内有效。[审核模型](../../backend/app/features/asr_evaluation/models/asr_models.py) · [说话人审核与改名](../../backend/app/features/asr_evaluation/services/diarization_service.py)

**计划、套件和成员。** `test_collection` 保留项目、类型、名称、描述和软删除字段；计划独有环境外键、状态、执行方式，套件独有套件类型和启停状态。有效名称按 `(project_id, kind, name)` 唯一。`test_collection_member` 保存排序、软删除和两种受约束的目标外键，只允许“计划 → 同项目套件”“套件 → 同项目用例”，套件用例成员另保留启停标志。用类型化外键或数据库触发器约束父子类型和项目归属，按各自原规则保证有效成员唯一。`test_run.plan_id` 迁到计划类型的集合引用，沿用删除置空语义。API、回收站及关联记录仍按原类型和旧 ID 寻址。[计划模型](../../backend/app/features/test_management/models/test_plan.py) · [套件模型](../../backend/app/features/test_management/models/test_suite.py) · [计划服务](../../backend/app/features/test_management/services/plan_service.py)

**历史证据。** 三张辅助表合成 `migration_evidence`，保留原始键、载荷、回填用例的级联外键和反向重建能力。深度降级跨越 `0047` 前，要另行核对“被迁移回填、后来人工改绑”的用例，这个风险在旧标记中无法单靠 ID 区分。[字段映射及深度降级处理](2026-11-25-database-optimization-plan.md) · [原始迁移](../../backend/alembic/versions/0047_test_scope.py)

## 四、从 186 张到 180 张的两项改动

### B1　把四类用例明细合为一张，186 → 183

一个步骤、断言、前置条件或数据项仍是一条独立记录。`test_case_component` 设内部主键、`kind`、旧公开 ID、所属用例、排序、创建修改时间和全套回收字段，共用 `(test_case_id, kind, sort, public_id)` 读路径。类型专属的名称、操作符、期望值、必填标志等保留原类型、长度和必填规则；原有可扩展配置继续存各类型相应的 JSON。有效数据项名称仍按用例唯一。

断言用可空的 `step_component_id` 强外键引用步骤，物理删除步骤时只清空断言的这项引用。写入及变更时同时约束目标为同一用例的步骤；迁移前先盘点历史跨用例引用，若有则单独处理。软删、撤销软删、批量恢复的父子顺序沿用生命周期服务。回收站中的 `资源类型 + 旧 ID`、页面 URL、Agent 工具和历史执行结果继续通过 `(kind, public_id)` 定位。步骤和断言同为 ID 1 时，仍能分别读取、修改和恢复。

关键改动覆盖用例 CRUD、生成、执行准备、Web 保存时批量替换步骤和回收站。每次批量清除都同时限定用例及类型，防止保存 Web 步骤时连带清空用例断言。切换前逐表核对 52,897 条记录的去向、排序和字段，再用包含步骤级断言、同名已删数据项和重号的样本验证恢复及重跑。[用例 CRUD](../../backend/app/features/test_management/services/case_service.py) · [执行准备](../../backend/app/features/test_management/executors/preparation.py) · [Web 步骤写入](../../backend/app/features/web_testing/services/case_service.py) · [资源回收与恢复](../../backend/app/lifecycle/service.py)

### B2　统一模型配置的写入和引用，183 → 180

| 旧对象 | 权威存储及兼容处理 |
|---|---|
| `model_configuration` | 逻辑模型用 `model_resource`，可执行版本用 `model_revision`，密文留在 `model_credential`。在现有表中补齐输入/输出单价、排序、原创建及修改时间、回收字段。保留旧整数 ID、授权用的字符串 `domain_id`、有序备用配置，默认候选继续按 `(sort_order, 旧 ID)` 选择 |
| `asr_connection` | 按连接版本映射到固定的 revision，保留项目范围、角色、任务类型、共享连接别名及原凭据使用范围 |
| `asr_parameter_set` | 按连接、名称和版本映射到精确的 `model_parameter_profile`。在现有 `model_legacy_binding` 补齐具体 profile 的外键及还原旧项目投影所需信息 |

先让旧 API 经适配层读写模型中心，逐项迁移 16 条入向外键、任务槽位、组织授权名单、备用模型列表和调度配置中的 JSON ID。项目共享 ASR 连接及参数副本可能共享同一 revision，兼容映射须保有旧项目归属和多个别名。独立保存密文，核对默认模型、访问权限与凭据解析，不将秘密写进映射日志。切换后终止新旧模型互相生成副本。

旧 ID 的解析要区分三种场景。当前配置读取采用该资源当前被准入的版本；旧配置编辑会生成新修订，首次建立的 `MODEL_CONFIGURATION` 映射可能仍指初版。历史运行按其冻结信息回放。待执行或重试的任务则继续执行原有失效检查：内容评审要核对包含旧 ID 和凭据版本的配置指纹，建议任务还要核对带模型更新时间的输入摘要。迁移自身须保持原有指纹和时间语义，真实改配置或换钥后仍返回原来的失效结果。[模型指纹与解析](../../backend/app/platform/model_configuration/services/model_config_service.py) · [内容评审校验](../../backend/app/features/asr_evaluation/services/content_review_service.py) · [建议任务重试](../../backend/app/features/asr_evaluation/services/suggestion_job_service.py)

验收包含旧 ID 查询、历史任务重放、组织隔离、模型归档与恢复、共享 ASR 连接及同一修订下不同参数版本。逐行验证旧标识可唯一还原，未知映射、跨项目授权差异和未迁移写入都须清零才退役原三表。[兼容写入和共享配置投影](../../backend/app/platform/model_configuration/services/model_center_service.py) · [资源、版本与兼容映射](../../backend/app/platform/model_configuration/models.py) · [按 domain_id 授权](../../backend/app/core/models/identity.py)

## 五、是否值得继续到 178 张

- **定义修订共表，可减 1 张。** 两种修订都记录父定义、版本、不可变快照、创建人和时间，适合在统一修订服务中按类型存放。使用两个真实父外键、恰有一个主体的约束和各自的父版本唯一键。现有三个入向外键只能引用 Agent 修订，要保留两条运行事实引用删除置空、任务实例外键可延迟检查的语义。若团队仍分别维护两套修订服务，单独为减少这 1 张表投入的收益较低。[Agent 修订](../../backend/app/agents/models/definition.py) · [Skill 修订](../../backend/app/skills/models/definition.py) · [运行期引用](../../backend/app/orchestration/tasks/models/task.py)
- **测试目标库隔离，可减 1 张。** 将 `td_sandbox_task` 交给独立目标库的测试 fixture。先核实 Provider 配置、策略白名单、测试连接和外部脚本，验证造数、回滚及清理实际打到目标库。它对主库减少一张，跨数据库部署的总表数不因此减少。[测试目标表来源](../../backend/alembic/versions/0009_test_data_center.py) · [数据工厂测试](../../backend/tests/test_19_data_factory.py)

## 六、实施顺序与放行条件

1. **从接口目录开工。** 先在隔离的 PostgreSQL 副本固定 API 响应、主键、索引、查询次数和列表/详情 P95。开发库现有 131 组参数与响应 ID 冲突可直接做对照样本。随后按 A2–A8 独立交付，队列切换单独安排窗口。
2. **给旧数据和新写入同样的身份规则。** 对合并后可能重号的行保留 `(kind, public_id)` 唯一键，用独立内部主键承接外键。新行按类型沿用原序列高水位，同一排序值按原 ID 排列。在 API 边界转换内部 ID，例如断言详情的 `step_id` 仍返回步骤的公开 ID；合并前后的前端响应做逐字段比对。临时映射或兼容视图覆盖老消费者，旧写入端退出后再退役。[用例前端契约](../../frontend/src/features/test-management/contracts.ts) · [接口目录前端契约](../../frontend/src/features/api-catalog/contracts.ts)
3. **逐域迁移。** 先扩展结构并部署兼容读写，再按原主键分批回填。每个阶段只允许一个权威写入路径，同事务同步或追平切换前的增量；双向键差、字段差和悬空引用均为 0 才切读。对领取任务的系统只运行一套领取器。单域回退时先隔离写入，按类型、ID、序列和级联规则反向重建，补齐切换后的增改删，再恢复旧消费者。
4. **同时验证冷启动和存量升级。** 当前 `0001` 从运行时元数据创建基线，其中包含 `project` 和 `model_configuration`。应固定历史基线的列、约束和索引，避免新增项目列被重复创建或退休模型导致老表缺失。新表进现行 Alembic 元数据，旧模型按其版本退出。分别演练空库升级、从含数据的 `0097` 升级、降级及重升。[动态历史基线](../../backend/alembic/versions/0001_initial_schema.py) · [现行注册入口](../../backend/alembic/env.py)
5. **按用户行为和表数双重验收。** 每组同时检查旧 URL 和 ID、导入与幂等、非空样本、权限、回收恢复及历史重放。ASR 覆盖租约过期和重复完成，测试管理覆盖排序及步骤级断言。用统一负载对比写入、列表、执行准备和领取延迟，性能超出既有预算则保留旧结构。阶段结束再用同一 `public` 口径复核 186、183、180。现有回归入口包括[接口目录](../../backend/tests/test_api_catalog.py)、[用例管理](../../backend/tests/test_14_test_management.py)、[用例执行](../../backend/tests/test_15_test_executor.py)、[ASR 回归](../../backend/app/features/asr_evaluation/tests/test_regressions.py)和[模型中心](../../backend/app/platform/model_configuration/tests/test_model_center.py)。

表数衡量数据库的维护范围。空间收益单独验收，继续按前次实测优先评估 79 个与主键重叠的普通索引和 88 条 Skill 的重复正文。它们都不计入这里的 18 张净减少量。
