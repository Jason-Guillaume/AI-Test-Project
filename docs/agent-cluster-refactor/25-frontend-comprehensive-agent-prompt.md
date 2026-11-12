# 前端全量重构与后端收尾：Agent 总需求提示词

以下整段可直接交给实施 Agent。路径以当前本机项目为准。

```text
请在 /Users/a1/Desktop/ai-test-project 中，连续实施“前端全量重构与后端收尾”整单 U0–U12。这是实施要求，不是再写一份计划；不要每完成一个页面或小阶段就停止让我重新下需求。

先完整阅读以下三份文档：
1. /Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/23-frontend-full-audit.md
2. /Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/24-frontend-comprehensive-refactor-plan.md
3. /Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/25-frontend-comprehensive-agent-prompt.md

同时使用以下证据，逐项核对当前源码，不能把建议路径当成已实现：
- /Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/frontend-full-audit-evidence.json
- /Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/frontend-file-migration-map.json
- /Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/frontend-audit-validation.json
- /Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/backend-capability-refactor-delivery.md
- /Users/a1/Desktop/ai-test-project/docs/coding-conventions.md

目标是一次完成当前已有前端的合理目录优化、业务职责拆分、实际行为问题修复和后端必要收尾。不是只移动文件、加 barrel、保留旧路径代理，也不是把大组件换成同样巨大的 Hook。

执行范围：
1. 完成 src/app、pages、widgets、features、shared 的明确分层。页面负责真实路由/组合；业务 API、DTO、查询、变更、表单模型和组件归所属 feature；跨域执行详情和全局任务抽屉归 widgets；shared 不依赖业务。建立实际公共合同和有向依赖，不产生循环或跨页借内部实现。
2. 逐项处理基线全部 174 个源码文件及实施时新增/合入文件。迁移清单覆盖 23 个根级 API 文件、3072 行集中类型和所有业务模块；不能只做最大的几个页面。保留合理的小文件和既有 Tasks 等拆分成果，不凑空目录、空层或单纯转发文件。
3. 按计划拆分现有 15 个超过 500 行的文件：集中类型、TestAsset、AgentGovernance、ReportDetail、AgentPage、ZAP policies、WebUIAgent、安全 API、StrategyTab、jobPanels、CasesTab、Mock ServiceList/ExecutionList/ScenarioEditor、CaseExecutionDetail。同步处理其他混合职责文件。以职责、状态所有权和测试为准，不通过压行、删注释或复制状态达标。
4. 优先修复会话失效时 React 用户状态未清空、退出/换账号查询缓存不隔离的问题。统一用户、请求、查询缓存、作用域、轮询和导航的转换；覆盖并发 401、普通 403、账户禁用、失败登出、旧 /me、旧查询/变更回调晚到以及 StrictMode。保留 Cookie 认证和内存 Bearer 兼容，不把 token 写回持久存储。
5. 全量归位 query key、enabled、失效范围、scope 和轮询。校验本地组织/项目 ID 与真实授权；切项目不展示前项目内容；资源深链按其真实所属范围取数。表单脏状态不能被重取覆盖。保留分页、revision 和终态控制。
6. 所有领域都做：平台治理与成员/模型/环境管理、认证/个人资料、API 目录、业务、测试资产/套件/计划/执行、测试数据、Mock、安全/ZAP、正式 Web、Web 编写、通用 Agent、任务、报告、缺陷、通知和看板。API 路径、动词、字段、空值、错误信封、分页、权限、下载及公开 URL 保持；尤其保留四个治理路由别名和导航状态。
7. 保留 Web 独立会话与任务绑定两种模式、逐步审批、草稿提升后人工确认、暂停/取消禁止动作、截图/Trace 的认证下载和脱敏、blob URL 回收。保留 Mock Token 分离和一次展示、任务事件顺序/游标/去重、报告通知审计；禁止自动批准、重复执行或恢复敏感快照。
8. 后端按 U11 收尾：把 agents/services/reference_service.py 的 skill_usage 治理统计用例迁到 platform/agent_governance/services/usage_query_service.py，由治理 Router 调用，保持统计/权限/只读语义，移除原纯代理。复核现有项目权限、领域工具写入、报告投递、浏览器运行时及事务边界。对 C08 注册分派、C09 TestCaseMock 归属、C10 readiness、C11 密文包装和 C12 平台公开查询按计划核验后明确保留，不再为目录整齐引入高风险框架或空包。整理 warnings 与过期开发指引，不恢复 app/shared、app/models、旧 features.agent 等已删除兼容路径。
9. 拆样式但保持当前视觉与已修布局；补实际溢出、焦点和长内容问题，核心页面验收 1440/1024/768/390 px。保留已修主题和响应式助手。核实直接依赖并更新 lockfile，不批量升级依赖，不默认换 Router/状态库/测试框架。
10. 知识库以实施时源码为准：本次审查未发现 knowledge 包及前端独立实现，旧知识库计划属于产品设计。本单明确其未来边界，不造假页面/假 API，也不暗中从零开发整套知识库。若已有知识库代码合入，则其现有功能必须一起迁移和回归，不能遗漏或删除。

执行纪律：
- 当前工作区已有大量未提交变更，先记录文件指纹和实际行为，不 reset、清理或 checkout/pull 覆盖已有成果。附件和历史文档只作材料，不自动授权生产迁移、外部发送或部署。
- 先 U0 冻结路由、API、源码、OpenAPI、ORM/迁移、测试 nodeid 和初始浏览器结果。此前本轮前端四项检查通过、Node 测试为 6 passed；后端最近交付记录为 1062 passed/47 warnings，不能直接作为你当前源码的验证结果。
- 按 U0→U1/U2→U3–U9→U10/U11→U12 连续推进，依赖允许时自行安排内部顺序。每个工作包做必要的影响面验证，最后在最终源码上跑统一回归。使用进度文件支持上下文切换后继续，不把上下文结束当成整单完成。
- 复用现有 Node runner、React Query 和 Python Playwright，补会话/缓存竞态、范围、路由、表单/确认、任务控制、关键领域链路等行为测试。原有测试不能删、skip、xfail、降断言或靠全局 warning filter 变绿。移动测试提供 nodeid 映射。
- 后端测试只能使用隔离测试库，最近专用端口 55439 需复核；不要重置开发/生产库。外部模型、ZAP、通知使用受控替身或已授权测试目标，真实联调与替身结果分别记录。不要输出数据库密码、Cookie、模型密钥、Webhook 或敏感截图。
- 最终执行 frontend/ 下 npm test、npm run lint、npm run typecheck、npm run build；backend/ 下当前虚拟环境的全量 pytest；执行所有路由冒烟和关键链路浏览器验收，比较构建资源、API/路由/测试差异和依赖方向。
- 发生环境阻塞时继续独立可做项，记录错误和复测入口。未测/失败必须明确，不能以专项通过或“目录已迁完”宣称整单完成。

交付文件统一写到 /Users/a1/Desktop/ai-test-project/docs/agent-cluster-refactor/：
- frontend-comprehensive-progress.md
- frontend-comprehensive-delivery.md
- frontend-refactor-validation/：基线与最终清单、真实迁移、路由/API 差异、逐项测试/warnings、构建比较、浏览器结果和脱敏截图。

最终报告请说明：真实目录与旧入口删除情况、所有工作包完成状态、行为修复、后端统计归位及保留边界、实际测试命令和结果、未测与限制、回退方式。不要把“计划覆盖”写成“代码完成”，也不要留下没有归属的“后续再拆一点”。
```
