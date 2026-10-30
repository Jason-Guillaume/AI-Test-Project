# 后端全模块能力边界复核与实施清单

日期：2026-10-29。覆盖 `backend/app/` 全部 635 个 Python 文件的 AST 静态扫描，并定向阅读职责混合位置的实际实现。本文是审查结果与后续方案，不是代码交付报告；本轮没有迁移源码、改表或运行行为测试。

[21 Web/Mock 专题](21-capability-boundaries-and-naming-plan.md) 继续提供 Web、Mock 的详细拆分要求；本文补齐其余模块，并给出统一实施顺序。[静态证据](backend-capability-audit-evidence.json) 保存包清单、导入关系、重复权限实现、路由事务位置和源码指纹。

## 1. 总体判断

平台的主要能力已经存在，下一轮应优化所有权与调用方向，无需重新建设 Agent、工具系统或测试执行体系。

需要落实的边界：

1. **业务服务拥有正式资产、权限、事务和业务结论。** 工具是调用入口，Agent 是决策者，运行时执行具体技术操作。
2. **任务编排拥有任务状态、租约、命令、预算和副作用回执。** 模型推理、角色提示词和结构化决策不应与这些状态写入混成一个处理器。
3. **跨域聚合可以读取事实。** 看板、报告以及受控的资产归属查询不必为了消除所有跨包导入而建立大量转发服务。
4. **目录变化不是功能变化。** API、工具 key、工作流 key、表结构、人工批准与事务边界不随 Python 路径变化。

扫描发现 6 对包级双向导入关系。这里统计包含函数内延迟导入和类型引用，不能据此断言存在启动失败的模块循环。需逐处判断是否为必要的只读关联、执行适配或真正的职责反向依赖。

## 2. 十个业务模块逐项结论

| 当前模块 | 真实职责 | 命名与归属结论 | 需要继续处理的边界 |
|---|---|---|---|
| `features/api_catalog` | 接口定义、模块、参数/请求/响应资源、导入解析、调试 | 保留目录与名称 | 项目权限底座收口；调试仍复用唯一 HTTP 执行器，解析器不因文件较长继续碎拆 |
| `features/business` | 被测业务域、流程、动作、规则、状态、绑定和映射执行 | 保留，开发说明明确“被测业务建模与执行” | Web 绑定读取与调用需明确公开契约；通用脱敏不应依赖浏览器驱动文件；不把业务流程整体改称 Agent |
| `features/dashboard` | 用户工作台、项目汇总、平台统计和就绪检查 | 看板统计可保留，属于聚合读模型 | 将 readiness 拆为平台运维检查；统计与查询可在包内按 user/platform/project 分组，暂不新建 analytics 系统 |
| `features/defects` | 缺陷、执行/安全发现来源和原子关联 | 保留 | 来源解析是受控跨域事实读取；保留来源锁、幂等键、缺陷+关联+通知的原事务，不机械拆成跨服务独立提交 |
| `features/mock_management` | Mock 资产、匹配、上下文、响应服务、执行记录 | 建议更名 `features/mocking` | 业务能力与 Agent 工具分开；工具专用安全查询回归公开服务，详见 21 |
| `features/reports` | 正式报告、确定性统计、风险与 AI 摘要 | 保留 | 将事实读取、确定性构建、AI 摘要按需包内拆分；发送报告通知属于跨能力应用用例，避免塞进通用渠道发送器 |
| `features/security_testing` | 策略、规则、计划、用例、发现、变异/断言、安全执行与 ZAP 集成 | 保留 | 测试执行器与安全执行的注册/分派边界需收口；已有 protocol/stages 分层保留，不将扫描引擎整体迁入 tools |
| `features/test_data` | Fixture、Provider、数据池、连接策略、准备/清理和生成记录 | 保留 | 收口项目权限与 Agent 查询适配；数据库写入策略继续归此域，不迁入 Agent 或通用 core.security |
| `features/test_management` | 测试点、用例、策略、计划、套件、运行、断言结果 | 保留；内部区分资产与运行即可 | 接回工具中的临时计划/套件创建；明确用例 Mock 关联用例及各执行目标适配的所有者，不新建第二套 RunService |
| `features/web_ui` | 正式 Web 测试、交互编写、Agent 会话及浏览器驱动混合 | 建议正式业务更名 `features/web_testing` | 按 21 拆出 Agent 编写能力和 `execution/browser`，保持唯一浏览器资源持有者 |

这十个目录不会因为“可被 Agent 调用”就全部成为 tools。是否属于业务能力，取决于其资产、规则和生命周期所有权。

## 3. 平台模块逐项结论

| 当前模块 | 判断 | 处理方向 |
|---|---|---|
| `platform/users` | 账户管理和注册认证入口归属正确 | 保留用户事务；JWT/密码/角色原语继续在 core.security，注册与个人组织创建保持原子性 |
| `platform/organizations` | 组织管理归属正确，HTTP 路由仍承担较多业务 | 将组织创建/改名、成员更新/移除、负责人转移和模型授权协调迁到组织服务，详见 C02 |
| `platform/projects` | 项目、成员和出站目标归属正确 | 建立唯一项目访问契约，供全部域使用；项目设置的 editor/owner 门槛与普通 member 写权限分别保留 |
| `platform/environment_configuration` | 平台环境目录和项目实际环境配置归属正确 | 保留目录；可在内部区分 catalog/project_environment/options；不能把它当基础配置随意迁入 core.config |
| `platform/model_configuration` | 模型配置、密钥、启停与候选链管理归属正确 | 保留管理能力；Provider 只读取授权后可用的配置契约；加密原语去重需保留 API Key 的规范化和失败行为 |
| `platform/notifications` | 收件箱、渠道和发送记录属于可复用平台能力 | 拆清收件箱服务、通用渠道传输与报告投递用例，移除对测试管理权限 helper 的借用 |
| `platform/agent_governance` | 已是 Agent/Skill/MCP/Tool 的管理聚合入口 | 继续保留聚合 HTTP 入口；可选更名 `ai_governance`，仅用于更准确表达范围，不是必做项，也不改变 `/agent-governance` URL |

这里的 platform 不是“仅管理员可用”的含义。普通用户收件箱、项目权限和环境选项仍按原有角色开放。

## 4. 公共能力与编排逐项结论

| 当前包 | 判断 | 必要调整与保留边界 |
|---|---|---|
| `agents` | 定义、组装、会话、工作流、提案与提示词归属正确 | 接回任务处理器中的纯模型决策；去除 router 装配依赖；任务使用统计与动作许可上移，详见 C04/C05 和 21 |
| `orchestration/tasks` | 任务状态、命令、依赖、租约、预算、事件和回执归属正确 | handlers 保留调度与业务调用；提示词/候选生成/角色决策调用 Agent 服务；不把整个 Worker 迁入 agents |
| `tools` | 注册、稳定 key、调用通道、可信上下文和外部适配归属正确 | 接口适配保持轻量；领域写入/规则移回业务服务。允许受控只读投影；不把“任何 ORM 导入”都判为错误 |
| `execution/http` | 通用发送、请求构建和出站策略协调归属合理 | 当前使用 projects 公开查询契约，属于有意的策略绑定；不是运行故障。需要纯驱动层时再注入已验证策略，保留私网与生产目标语义 |
| `execution/templates` | 无数据库读取的变量/模板解析、缺失值和作用域契约归属正确 | 保留唯一解析实现；不要合并 ResolveScope、业务 ExecutionContext 和 AgentState |
| `llm` | Provider、模型协议、调用结果与追踪归属正确 | 无 Agent 图依赖；读 model_configuration 公开契约可保留。协议层受限工具循环与 Agent 业务规划区分，不把所有 LLM 调用都包装成 Agent |
| `skills` | 定义、文件树、版本、ZIP 导入、加载和渲染归属正确 | MCP 只读依赖校验可以存在；不能视为授予执行权限。实际调用仍复核 MCP 当前审批，不将 Skill 变成可执行脚本 |
| `mcp` | 服务注册、发现、审批和 Streamable HTTP 客户端归属正确 | 保留协议与管理服务；不承担任务回执或业务状态。当前规模不必预建 transports/integrations 多层空包 |
| `core` | 数据库、配置、角色、安全、HTTP、表达式和九张基线模型边界基本稳定 | 静态导入未发现对上层包反向依赖；保留九张基线 ORM 归属，不用本次整理重新迁移核心表 |
| `main.py` | HTTP 与进程资源装配位置正确 | 保留唯一装配入口；业务迁移同步更新引用，不另建重复清单；Worker/浏览器关闭责任不散落到多个包 |

## 5. 有源码依据的实施问题

优先级说明：“优先”表示本轮职责整改应先处理，不表示已证实线上漏洞或运行失败；“后续”表示可在核心整改通过后实施。

### C01：项目权限出现重复实现和横向借用（优先）

源码扫描去除 docstring 后，发现 7 份 `get_project_or_404` 的函数体完全相同：api_catalog、business、test_management、test_data、mock_management、security_testing 以及 ZAP access；`check_writable` 也存在 6 份相同函数体。

reports、notifications、Mock 用例关联等又从 test_management 获取项目权限 helper，使通用项目权限与测试资产包绑定。

**方向：** 在 `platform/projects/services/access_service.py` 提供唯一项目读取和普通写入契约；复用 core.security.roles。各域只保留实体→project_id 回溯和领域额外策略。同步迁移调用者，不再留七份复制或建立只为兼容的空壳实现。

**保护：** 保持现有不可见 404、已可见但写权限不足 403 等既有分支，不借“统一”修改错误语义；项目设置、组织管理和安全高风险审批的额外门槛不并入普通 member 检查。

### C02：组织路由仍拥有业务事务（优先）

`platform/organizations/router.py` 的 create/update、put_member、delete_member、transfer_ownership 中共有 5 处直接 `db.commit()`，同时包含成员、角色、模型白名单及负责人规则。现有 organization_service 主要提供身份与个人组织辅助，并未承接全部管理用例。

**方向：** 按组织、成员、所有权/授权用例拆为真实服务；router 仅做认证参数与响应转换。查询与响应辅助可按需要一起迁移，不为每个函数机械创建文件。

**保护：** 组织与 owner 成员同事务、负责人移除保护、名下项目检查、模型白名单和 Agent 开关、跨组织隐藏语义保持。

### C03：通知的收件箱、渠道与报告投递职责混合（优先）

- `platform/notifications/router.py` 的标读/批量标读/删除直接提交，共 3 处 commit，并在路由中处理可见范围。
- `channel_router.py:notify_report` 协调报告、项目权限、渠道和飞书发送；ChannelService 借用测试管理的项目权限。
- `services/feishu_service.py` 同时处理报告专用卡片、通知条件、签名、HTTP 和发送记录。

**方向：** 收件箱查询和写入归 `inbox_service`；渠道 CRUD/发送记录留在 notifications；Feishu HTTP/签名按需归包内 transport。报告上下文和投递条件由 `orchestration/report_delivery` 协调，向发送服务传明确的消息数据，不让通用渠道层依赖整个 ReportService。已有报告发送 HTTP/工具入口均调用同一个应用用例，URL 不变。

**保护：** 通知失败仍只影响发送记录，不改变 TestRun/Report；不增加自动重发，原回执与发送先后顺序保持。core.notifications 的站内通知写入及其业务事务语义不一起改造。

### C04：任务 handler 仍包含智能体决策实现（优先）

`orchestration/tasks/runtime/prompts.py` 持有 Planner/API/UI/Main 等角色提示词；`handlers/planning.py`、`reviewing.py` 等直接调用 generate_structured，并与任务事件、回执和 commit 混合。

**方向：** 将角色提示词、模型输入构造和候选决策提取到 `agents` 中的明确决策服务或工作流；任务 handler 传入允许范围和冻结配置，接收类型明确的候选结果，再做状态采用和执行。模型服务不接收 TaskWorker、整份 TaskService 或持久化 TaskRun 实体。

**保护：** 任务状态、范围锁定、租约、工具回执、审批与预算仍在任务层；review 的正式事实核对与拒绝模型错误结论仍是代码规则。此提取不新增一个并行 Agent 运行器，不改变主/子 Agent 拓扑、角色 key 或图的暂停点。固定工作流与动态工具调用原有通道分别保留。

### C05：Agent 对任务的两种反向依赖应分别处理（优先/后续）

- Web 节点直接读取 TaskRun 并加锁控制动作：按 21 注入受控动作许可，属于优先整改；锁不能在浏览器动作之前提前释放。
- `agents/services/reference_service.py:skill_usage` 联查 SkillUsageEvent、TaskRun、Task 生成使用统计：这是只读聚合，不是调度故障，但会造成包级反向依赖。后续可迁入 `orchestration/governance` 的查询服务。

Skill/MCP 被 Agent 引用的停用、删除和版本恢复保护继续保留在可信跨能力协调入口，不能因为移动统计而删除引用校验。

### C06：工具层领域写入与任务借用工具实现（优先）

`tools/builtin/test_management/execution_tool.py:create_test_run` 自行写临时计划、套件、关联并 commit；任务 adapters 借用该函数。Mock、Fixture、业务及测试资产工具也有直接查询和资源组装。

**方向：** 按 21 先把临时执行用例收回 test_management 公开服务，让任务和工具分别调用；再把权限、写规则和必要的 Agent-safe 查询回归所属域。任务调用工具注册器处理真实模型工具请求仍然允许，禁止的是把工具适配器当业务实现库。

**保护：** 原 `[Agent]`/`[Task]` 来源标识、用例范围、临时资产与实际 Run 创建的提交顺序保持；不要借提取服务合并或拆分原事务。

### C07：业务与 Web/测试的关联需要明确端口（优先/后续）

`business/services/binding_service.py` 读取 TestCase/WebCase 验证 WEB 绑定；`business/executors/action_executor.py` 调 run_web_binding；Web 业务又读取流程与动作，因此出现包级双向关系。

**方向：** 为 Web 绑定查询和执行定义窄的公开契约；业务绑定与映射规则仍归 business，Web 用例校验与执行仍归 Web 测试。跨域只读身份验证可以保留，不为消除导入再复制表。若采用注入/注册，由唯一应用装配明确提供实现，禁止运行时依靠 router 导入触发注册。

`business/executors/masking.py` 为脱敏直接导入浏览器驱动文件中的 scrub，属于应先解除的工具性依赖。提取纯脱敏部分或改用公共安全能力；浏览器专用 headers/cookies/storageState 处理仍保留其上下文，不把完整 scrub 原样复制多份。

### C08：测试执行与安全执行的分派边界（后续）

`test_management/executors/test_case_executor.py:try_security` 用延迟 import 调安全 runner；安全 preparation 反向复用测试准备逻辑。这是现存可运行的集成关系，不应声称已经启动崩溃。

**方向：** 对需要解除的执行耦合，可在 test_management 中定义目标执行契约，由应用装配注册安全/Web 等适配器；通用准备与唯一 CaseExecutionResult 保持单一来源。安全扩展优先识别的现有顺序、普通用例回退、结果字段和生命周期不能改变。没有实际新增扩展需求时，优先级低于 C01–C07。

### C09：用例 Mock 声明与运行提交边界（后续）

`mock_management/services/test_case_mock_service.py` 负责用例 required_mocks 的读取、校验和整体替换，却依赖测试用例模型与测试访问服务。Mock 运行域和测试管理又互相引用。

**方向：** 将“配置用例的 Mock 依赖”应用用例归测试资产侧；Mock 域提供同项目场景校验与运行上下文契约。TestCaseMock 表和模型可以保持当前唯一归属，不要求为服务迁移改表或迁移 ORM。同步迁移声明路由的实际处理归属，保持原 URL。

**保护：** 先全部校验再重建、同用例同场景唯一、scope 和顺序、调用方原事务及 Fixture/Mock 清理次序保持。

另外，`mock_management/runtime_router.py:_handle` 在线程池协调运行并直接 commit。可提供完整的运行请求服务用例承接该提交，让 HTTP 层只适配请求与延迟；保留现有 handle_request 的 flush-only 语义供内部调用，不改成所有调用都自动 commit。执行记录仍在延迟/超时模拟之前持久化，Session 不越过原线程边界。

### C10：看板内混入运维 readiness（后续）

`dashboard/services/dashboard_service.py:readiness` 检查 SELECT 1、模型与环境等依赖。该职责与用户/项目统计不同。

**方向：** 有明确维护需要时，将该实现归 `platform/operations/readiness` 或等价的平台运维服务；保留已有 HTTP 路径和 hard/degraded 判定。看板只调用结果或由主装配挂载运维路由，不创建新的监控产品或后台巡检任务。

### C11：模型密文原语重复，但包装行为不同（后续）

`core/security/crypto.py` 与 `platform/model_configuration/services/model_config_service.py` 都实现同源 Fernet 派生。API Key 包装有 strip、空值与静默失败行为；通用密文支持原始文本并记录失败告警。

**方向：** 复用一个底层加解密/派生原语，保留两类包装的输入与错误策略；若当前没有维护需求，也可明确记录后暂留。不能简单将 API Key 的 strip 套到 Cookie、JSON 凭据或 Webhook 密文内容。

### C12：纯基础层与平台配置契约不必过度拆解（保留/可选）

`execution/http/outbound_policy.py` 调用 projects 的 find_enabled_outbound_target；`llm/providers/openai_compatible.py` 调用 model_configuration 的 load_model_for_provider。均是公开读取契约，后者返回明确的配置对象，而非 Agent 或任务实体。

**方向：** 当前可以保留这些策略/配置适配。若需要技术 runtime 完全脱离数据库，才引入类型明确的配置解析回调和已验证出站策略；授权和密钥解密仍由可信层提供。没有这一使用需求时，不为追求“零业务 import”新建大套 ports/adapters 文件。

## 6. 名称与目录统一结论

本轮建议必做的语义更名只有两项：

| 原名 | 建议名 | 理由 |
|---|---|---|
| `features/web_ui` | `features/web_testing` | 正式 Web 测试资产与执行；Agent 与浏览器 runtime 分开归属 |
| `features/mock_management` | `features/mocking` | 同时提供 Mock 管理和真实运行，名称覆盖完整能力 |

`agent_governance→ai_governance` 为可选名称整理。其他包保持名称，通过模块说明和内部服务职责澄清即可。所有更名不改公开工具标识、URL、DTO、表名、既有工作流和任务类型。

新增目标位置的职责：

- `platform/projects/services/access_service.py`：唯一项目访问契约。
- `platform/organizations/services/*`：组织管理事务，由现有实现迁入。
- `platform/notifications/services/inbox_service.py`：收件箱查询、标读与删除。
- `orchestration/report_delivery/`：报告与通知渠道的投递协调。
- `orchestration/governance/`：需要跨 Task/Agent/Skill 的只读治理聚合，实际迁入时才建。
- `agents` 中的任务角色决策服务/工作流与对应 prompts：只生成候选结果，不直接操作任务状态。
- `platform/operations/`：可选的现有 readiness 实现归属。
- Web/Mock 的其他目标位置按 21 执行，不在本文再建立另一份实现映射。

不创建尚未实现的 knowledge、mobile、通用扫描平台、插件系统或第二套执行引擎。

## 7. 建议实施顺序与范围控制

1. **先恢复可验证的基线。** 第一轮目录交付已记录数据库回归未完成；实施者先在可连接的隔离 PostgreSQL 上复核当前源码，不沿用历史成功数字。
2. **基础权限与 HTTP 服务分层。** C01→C02→C03 的收件箱与渠道权限部分；随后原测试回归。
3. **接回业务用例。** C06 临时测试执行与工具适配、C03 报告投递协调；逐项验证事务与副作用回执。
4. **分离任务智能体决策。** C04 与 C05；任务控制接口与 Web 动作原子范围按 21 一起验证。
5. **实施 Web/Mock 专题。** 21 的命名、浏览器 runtime、会话、编写与正式资产分离，以及 C07 必要公开契约。
6. **视需要处理后续项。** C08/C09 执行扩展和用例声明归属、C10 readiness、C11 加密原语。C12 默认保留，治理包可选改名不阻塞交付。
7. **更新规范与交付证据。** 当前 coding-conventions 的旧目录示意仍包含 features/tasks 等历史路径，实施后更新实际现状；计划中的新目录在落地前不能写成“已实现”。不修改历史交付报告的证据语义。

每批只处理可验证的职责迁移，不同时改算法、权限规则、数据库结构或技术栈。不要求一个 Agent 一次性完成全部后续可选项，也不能以只改目录名宣称全部边界整改完成。

## 8. 验证与交付要求

本次静态审查已做：全部 Python AST 解析、包级导入汇总、同体权限函数比对、路由直接事务位置定位、重点实现阅读；未导入应用、未启动数据库/浏览器/Worker、未执行 pytest。静态依赖不覆盖全部字符串导入、反射、注入或运行时锁行为。

实施基线和完成验收应包括：

- method/path、状态码、公开 Schema、工具 key/风险/授权、工作流节点及暂停点、模型 metadata 和原 pytest nodeid 对照。
- 账户/组织/项目权限与组织转移、成员模型授权；项目可见/可写分支以及管理员例外。
- 收件箱可见性、批量标读、通知失败隔离；报告发送的条件、回执、重复请求和发送记录。
- API、业务、Fixture、Mock、安全、Web 各执行目标及准备/清理链；正式状态/断言条数/错误码不漂移。
- 任务命令、范围批准、租约、模型失败与候选回退、子 Agent、MCP 审批变更、迟到结果与未知副作用不误重放。
- Web 专题的逐步确认、暂停/取消、资源归属、重启断线、出站与脱敏验证按 21 完整保留。
- 同一 Session 和原提交点的行为验证；尤其不能为薄化 router/工具而提前提交或分裂缺陷关联、组织创建、任务回执事务。

现有测试入口包括 test_02–05（认证/授权/隔离）、test_10–20（业务/测试/Agent/报告/数据）、test_21–34（Mock/安全/ZAP/Web）、test_35_tasks、test_36_agent_governance_details、test_task_notifications、test_task_web_session_binding 和各专项测试。按实际文件选择最小相关集合，每批通过后，最终在有效环境运行完整后端回归；必要的新增测试验证行为差异，不只断言文件路径。

交付报告应逐项列出 C01–C12 与 21 的完成/未做/受阻状态，保留原有用例，不删除或弱化测试。若环境不足，准确记录未验证项，不将导入成功或历史通过数代替本次完整行为验收。
