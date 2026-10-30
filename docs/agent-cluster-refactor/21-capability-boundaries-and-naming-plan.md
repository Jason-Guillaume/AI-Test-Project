# 能力边界与模块命名复核方案

日期：2026-10-29。核对对象为已完成 platform/orchestration 迁移的当前工作区。本轮是源码静态复核和方案修订，没有移动源码、改数据库或执行测试。

本文补充并修订 [20 目录归属方案](20-features-directory-layout-plan.md) 对 Web、Mock 和工具层的判断。第一轮迁移结果见 [目录布局交付](features-directory-layout-delivery.md)。

其余业务、平台和公共能力的完整复核见 [22 后端全模块审查与实施清单](22-backend-capability-audit.md)。后续整体验收按 22 排序，本文继续作为 Web/Mock 专题细则。

## 1. 结论与判定规则

第一轮解决了平台管理与任务编排的归属，但尚未完整区分“智能体、工具适配、业务能力、执行运行时”。不能只把 features 的列表缩短就认为边界已清晰。

- **智能体**：解释目标、观察反馈、模型决策、计划、提案、人工审核和状态图。
- **工具适配**：将可调用操作映射到受控能力，处理调用上下文、输入输出适配与工具注册。工具风险和调用权限继续由现有 dispatcher/授权机制控制。
- **业务能力**：持有正式资产、业务规则、资源权限、事务、持久化和领域生命周期；可同时供人工界面、任务与智能体使用。
- **执行运行时**：完成具体技术操作，持有驱动和活动句柄；不负责模型决策或正式业务资产写入。
- **应用编排**：协调上述能力完成跨域用例、任务控制和人工确认后的保存；不复制底层业务规则。

一个能力“可以被 Agent 当作工具使用”，并不意味着其数据库、管理 API、执行服务都应放进 `tools/`。相反，目录必须能看出同一能力在不同层中的明确分工。

## 2. Web 的实际组成

| 实际职责 | 当前源码证据 | 建议归属 |
|---|---|---|
| 页面对象、认证配置、用例确认指纹、截图/Trace 资产 | `features/web_ui/models/web_ui.py` 中 PageObject、WebAuthProfile、WebCase、WebArtifact；page/case/auth/execution services | `features/web_testing/` |
| 目标解释与观察→决策→执行→人工审核循环 | `agents/workflows/legacy/nodes/web_agent.py`，其中 `web_decide_node` 调用模型，图节点已位于 agents | `agents/workflows/web_authoring/`；保留原图节点 key、边及暂停点 |
| 智能体探索会话与步骤记录 | `features/web_ui/models/web_ui.py` 中 WebAgentSession、WebAgentStep；`services/session_service.py` | 数据与局部会话服务归 `agents/browser_authoring/`，不与正式用例资产混放 |
| 浏览器执行、观察、活动会话和回收 | `features/web_ui/runtime/playwright_executor.py`、observer.py、session_manager.py | `execution/browser/`，作为正式 Web 测试与智能体探索共同使用的运行时 |
| 将业务用例加载、变量解析、结果和截图写入正式执行记录 | `features/web_ui/runtime/adapter.py` 的 run_web_case/run_web_binding | 留在 `features/web_testing/executors/`；不能随驱动一起搬入通用 runtime |
| AI 草稿生成与保存 | `features/web_ui/services/draft_service.py` 同时读业务上下文、调用模型并保存用例 | 候选生成归 `agents/browser_authoring/`；收集上下文、调用生成、校验并保存由 `orchestration/web_authoring/` 协调 |
| 已有工具入口 | `tools/builtin/web_ui/web_ui_tool.py` 当前只适配 generate_draft | `tools/builtin/web_testing/` 适配草稿用例；需要浏览器步骤调用时由 `tools/builtin/browser/` 提供受限适配 |

### 命名建议

将正式业务能力 `features/web_ui` 更名为 **`features/web_testing`**。该目录表示 Web 测试能力，避免被理解为前端界面代码或 Web 智能体本体。

`web_authoring` 表示通过模型或交互探索编写用例；`browser` 表示浏览器技术能力。这里的命名区分真实职责，不要求为此创建第二个 Agent 或第二套工作流。

WebAgentSession、WebAgentStep 即使迁移 Python 模型所属，也保留原表名、列、外键和唯一实体注册；本轮不要求更改公开 DTO 名称。内部类名若随后调整，需统一处理字符串关系和导入，不能再声明一套映射同一张表的 ORM。

### 抽取浏览器 runtime 的前置条件

当前 runtime 仍依赖 WebStep、TargetPolicy 等业务契约，不能直接移动文件后继续反向导入 web_testing。

1. 在 `execution/browser/contracts.py` 放唯一的浏览器技术步骤/观测/结果契约。业务用例、AI 提案分别转换到该契约；保留原输入校验与操作白名单，不再复制第二份验证算法。
2. 将 TargetPolicy 拆为业务侧加载项目授权目标、运行时按已验证策略限制访问。通用运行时不查 ProjectOutboundTarget 表，也不接受模型自行提供授权目标。
3. 认证档案的项目权限、环境匹配、过期及解密留在可信服务；runtime 仅在原受控执行边界获得必要的临时凭据，继续执行 Cookie/Origin 校验、DNS/出站限制与脱敏。
4. BrowserSession/SessionRegistry 只有一份实际实现。保留现有线程归属、配额、空闲回收与关闭责任，`main.py` 仍负责进程退出释放。
5. 智能体、正式 Web 执行、业务 Web 动作以及安全检查调用同一运行时的公开操作。安全工具已经调用 `security_snapshot()`，这是实际复用证据。

### 探索会话与正式用例的分界

会话打开、观察、关闭和步骤记录由 browser_authoring 服务持有；会话提升为正式用例的 promote 用例归应用编排，调用 Web 测试公开保存服务。原有 session API 的 route handler 可随应用用例调整归属，HTTP 路径和 schema 不变，由 main 统一装配，不让正式测试业务反向导入上层编排。

单次 LLM 草稿生成与有状态 Agent 循环不同。本方案将 Web 候选生成归入 authoring，是为了统一 Web 编写能力，并不要求报告总结等全部 LLM 调用都成为 Agent。报告的单次摘要服务可继续通过 llm 提供方工作。

## 3. Mock 的实际组成

当前 Mock 包不是只有一个可调用函数：

- `models/__init__.py` 定义 MockService、MockEndpoint、MockScenario、MockMatcher、MockContext、MockExecution、TestCaseMock。
- `router.py` 提供管理功能；`runtime_router.py` 提供真实 Mock 请求入口，使用 X-Mock-Token/public_runtime 规则，而非平台 JWT。
- `services/mock_runtime_service.py` 完成上下文、匹配、场景选择和执行留痕；`runtime/response_builder.py` 支持静态响应、延迟、超时和空响应。
- `tools/builtin/mock_management/mock_tool.py` 提供受限的只读查询，供 Agent 引用已配置场景。工具不能据此获得创建场景、读取运行 Token 或响应体敏感值的权限。

因此建议将业务包 **`features/mock_management` 更名为 `features/mocking`**，名称覆盖资产管理和实际运行；将对应工具适配包改为 `tools/builtin/mocking`，但完整 Mock 能力继续拥有自己的业务模型与运行服务。

本轮不将 Mock 整包移入 tools，也不另建第二套 Mock 引擎。匹配与响应组件目前依赖 Mock 业务实体，先保留在 mocking 内部；只有明确需要无领域依赖的通用引擎时，才另行提取中立契约。

现有工具 key `runtime.mock_management.*`、`web_ui.generate_draft` 是外部标识，本轮保持不变；Python 路径与工具标识不必同时改名。ToolDefinitionOverride、Agent 白名单、已有配置和审计不能因目录更名失效。

## 4. 比目录名称更重要的现存问题

| 优先级 | 源码事实 | 修正方向 |
|---|---|---|
| P0 | `agents/workflows/legacy/nodes/web_agent.py` 从 `features.web_ui.router` 取得 service 单例 | 改用明确公开服务或受控调用接口；模型/节点不得依赖 HTTP router 的装配副作用 |
| P0 | 同一节点直接读取并锁定 `orchestration.tasks.models.TaskRun`，任务编排又调用 Agent | 将任务控制检查由上层注入；保留动作前刷新、行锁和原事务范围，不能把回调改成提前一次布尔检查 |
| P0 | `tools/builtin/test_management/execution_tool.py:create_test_run` 自行创建计划、套件、关联并 commit；`orchestration/tasks/adapters.py` 反过来调用该工具 | 将“选定用例创建并执行运行”收口到 test_management 的公开应用服务；任务与工具分别调用服务。先按原样提取，维持原有提交顺序和副作用回执 |
| P1 | Mock 工具直接查询 ORM、组装 Agent 专用可见结果 | 抽取 mocking 的公开 Agent-safe 查询服务，由工具适配；字段白名单、隐藏资源与 Token 隔离仍在服务端强制执行 |
| P1 | Fixture、测试资产、业务和安全工具也含 ORM 查询、资源验证或资产组装 | 逐个识别并迁到所属业务公开服务，优先迁写入与重复业务规则；必要的独立只读投影可以保留，不把任何 ORM 引用一概判定为错误 |
| P1 | Web 草稿服务跨越模型生成与资产保存；单一 web_ui 包混合正式测试、探索会话与驱动 | 按第 2 节分层，保存仍由正式资产服务执行，草稿不自动获得执行批准 |

工具层当前承担领域事务，比“Mock 目录是否在 tools 下”更实质。迁移完成后，应用调用关系应以服务为中心，而不是让所有上层调用都绕进工具注册层。

任务控制与 Web 动作是高风险边界。现有领取提案、暂停/取消、动作执行、结果记录与锁释放顺序必须先建立测试基线，再抽取协调接口；不允许搬目录时顺手缩短锁范围或将一个 Session 拆成多个独立提交。

## 5. 对剩余十个 feature 的复核

| 模块 | 判断 |
|---|---|
| api_catalog | 是接口定义、导入和请求资源资产；保留。接口查询工具是其适配入口，不拥有另一份接口模型 |
| business | 是业务域、动作、流程、规则和执行语义；保留。不将流程执行本身改称 Agent |
| dashboard | 是统计查询/展示读模型；保留。当前没有必要创建 analytics 平台或 Agent |
| defects | 是缺陷与来源关联资产；保留。Agent 发现问题后调用其公开服务 |
| mock_management | 改名 mocking，内部保留管理与运行分工；Agent 工具保持独立适配 |
| reports | 是正式报告资产、统计和单次 AI 摘要；保留。可复用 llm，不据此整体迁入 agents |
| security_testing | 是策略、规则、用例、发现和安全执行域；保留。Agent 负责规划/解释；ZAP 服务和扫描记录不进入工具适配层 |
| test_data | 是 Fixture、Provider、池、连接和生成生命周期；保留。Agent 只获得授权的能力入口，不获得任意 SQL 或凭据 |
| test_management | 是测试点、用例、计划、套件、运行及结果；保留。工具中的临时计划创建逻辑必须回归这里 |
| web_ui | 改名 web_testing；将智能体编写、交互会话和通用浏览器运行时分离 |

本轮不为降低同级目录数量再合并 reports/dashboard/defects，也不将所有资产改成 Tool。新增层级必须对应实际职责与调用者。

## 6. 目标目录与调用关系

以下只列本轮变化位置；每个文件/包在迁入真实实现时创建，不预建空目录。

```text
app/
├── agents/
│   ├── browser_authoring/            # 探索会话/步骤数据、会话服务、候选生成
│   └── workflows/web_authoring/      # 原 Web 图节点、决策、暂停点
├── orchestration/
│   ├── tasks/                       # 原任务调度与状态
│   └── web_authoring/               # 编写入口、上下文协调、提升正式用例
├── execution/
│   ├── browser/                     # 契约、驱动、观察、活动句柄与访问策略执行
│   ├── http/
│   └── templates/
├── tools/builtin/
│   ├── browser/                     # 实际需要时迁入受限浏览器操作适配
│   ├── web_testing/                 # Web 编写/测试的工具适配
│   └── mocking/                     # Mock 公开查询服务的工具适配
├── features/
│   ├── web_testing/                 # 页面/认证/正式用例/执行结果/领域适配
│   ├── mocking/                     # Mock 资产、匹配、响应、运行与审计
│   └── ...                          # 其余八个业务域
├── platform/
└── core/
```

典型调用：

```text
人工页面 ──→ Web 测试服务 ──→ 浏览器 runtime
任务编排 ──→ 测试运行服务 ──→ 领域执行适配 ──→ 浏览器 runtime
Web 编写编排 ──→ Web Agent / 候选生成
Web Agent ──→ 受控浏览器操作 ──→ 浏览器 runtime
提升正式用例 ──→ Web 测试资产服务
Agent ──→ Mock 工具适配 ──→ Mock 公开查询服务
被测系统 ──→ Mock Runtime HTTP 入口 ──→ Mock 运行服务
```

“受控浏览器操作”保留固定工作流可调用范围。抽取接口或接入工具注册，不意味着向模型自由开放全部浏览器动作；不得增加任意脚本、evaluate、原始 DOM 或凭据读取能力。

## 7. 分阶段实施与验收

1. **先建立新基线并补边界行为验证。** 当前第一轮交付记录说明完整数据库回归尚未完成，不能继承更早的通过数。准备隔离 PostgreSQL 后记录当前原测试、OpenAPI、metadata、工具 key/权限/handler binding、图节点和暂停点、事务与副作用位置。
2. **先修调用方向。** Agent 去除 router 依赖；临时计划创建提取为正式服务，任务不再借用工具实现；任务动作许可通过上层协调注入，保持原行锁和事务语义。
3. **收口工具中的业务逻辑。** 优先测试执行写入、Mock 安全查询及安全执行；逐个审查测试资产、Fixture 与业务工具，不要求机械清除所有只读 ORM 投影。
4. **调整领域命名。** web_ui→web_testing、mock_management→mocking，同步源码、测试、脚本、模型发现、字符串导入和维护中的文档。保留现有 URL、公开 Schema、数据库表和工具 key；不要为改名批量编辑历史迁移或历史交付证据。
5. **抽取浏览器运行时。** 先形成唯一技术契约与可信策略输入，再迁移驱动、观察和 registry；同时切换正式测试、智能体、业务动作、安全快照与 main 的生命周期调用者。
6. **分离 Web 编写能力。** 会话/步骤模型与服务迁入 Agent 编写包；模型决策节点迁入工作流包并重新接线到原图；草稿生成与 promote 的应用编排接入原 HTTP 和工具入口。人工独立使用与任务内使用都要覆盖。
7. **交付与完整验证。** 每批跑受影响测试，全部完成后跑完整后端回归，并记录实际结果与阻塞。保留全部既有用例，不删除、跳过或弱化测试；不以静态规则测试替代真实行为验证。

重点验证：

- Web 手工创建/修改/确认/调试，页面或认证变化后旧确认失效；正式 TestRun 的 Fixture/Mock/清理链保持。
- 草稿仍为未批准资产；探索提案必须经过人工确认，驳回不执行；提升用例、步骤预算、空转预算、断线与重启后的句柄处理保持。
- 任务与独立会话权限；相同/不同运行、环境和参与者绑定；暂停/取消与浏览器动作交错；领取提案失败、动作后落库失败、租约迟到结果不误重放。
- Browser registry 单例、线程/配额/空闲清理/退出关闭、出站限制、Cookie/Origin 校验、截图/Trace/观测脱敏与安全快照不退化。
- Mock 管理 JWT 与运行 Token 的鉴权边界、上下文隔离、场景匹配/优先级、延迟/超时/空响应、生命周期清理及留痕保持；Agent 只读字段集不扩张。
- 原工具 key、风险/授权配置、白名单、调用上下文和回执保持；不能因重命名意外扩大 Agent 写入或浏览器操作权限。
- API method/path、请求响应、Schema、ORM metadata、表数和实体注册一致；没有双实现或旧包绕行。Python 文件变动如引起自动 operationId 差异，应逐项评估调用方，不能直接忽略所有差异。

本方案的验收目标是“资产、智能体、工具和运行时各有唯一职责与实现”，而不是要求每个 feature 都迁出或要求目录数量继续减少。
