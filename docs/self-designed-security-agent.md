# 自研安全评估 Agent

## 当前实现

统一任务新增 `SECURITY` 工作流。创建任务时可绑定当前项目 1 到 10 个 ACTIVE API、一个执行环境和至少一个启用的安全策略。每个 API 都必须已有启用的 ACTIVE 功能用例，作为安全变异基线。

Planner 通过受控只读工具读取 API 范围、策略目录和未关闭 Finding，再通过 `security.preview_plan` 为每个 API 生成结构化预览。每个工具调用写入统一任务审计。LLM 只收到目标、策略和预览摘要，用于说明覆盖和验收条件；它不能添加目标、策略、请求或变异。Agent、Skill、工具白名单和模型版本沿用统一任务中的运行快照与调用审计。单次预览总量上限为 500 项，超过上限时必须缩小范围后重新规划。

方案确认由用户发起。普通风险项可以随方案确认；需要高风险确认的项默认不纳入执行，用户勾选明确授权后才会落成已确认安全用例。计划超出预览上限时禁止执行，暂不可执行的计划项会被排除。

安全执行通过 `security.execute_cases` 调用现有 `SecurityCaseService`、安全变异执行器和 TestRun。执行服务会再次拒绝未完成人工确认的高风险用例；结果随后进入现有报告、审阅、SecurityFinding 和产物回链，不创建第二套执行器或报告存储。

## ZAP 停用范围

- 任务创建页不再提供 ZAP 目标或扫描策略。
- 安全测试页不再挂载扫描器 UI。
- FastAPI 不再挂载 ZAP 路由，也不再启动 ZAP `ScanWorker`。
- ZAP 历史 ORM、迁移和实现文件保留，以免删除历史数据或覆盖尚未提交的仓库改动；新任务契约不接受 ZAP 扫描配置，旧 ZAP 计划工作项会被阻止。

## Agent Skills 和工具

治理中心提供只读的 `security.list_strategies`、`security.read_api_context`、`security.read_findings`、`security.inspect_web_session`，以及有副作用边界的 `security.preview_plan`、`security.confirm_plan`、`security.execute_cases`。安全 Planner 必须获授权使用策略/API/Finding 读取和计划预览工具；选择 Web 会话时还需获授权使用 Web 检查工具；执行 Worker 必须获授权使用计划确认和安全用例执行工具。调用输入与结果按任务运行留痕。

迁移 `0023` 会预置并启用四个可关联的 Skill：API 授权边界审查、结构化 API 变异评估、安全 Finding 证据分诊、受控 Web 页面被动安全观察。管理员可在 Agent 治理中心将适用 Skill 绑定到安全 Agent；任务创建时把 Skill 正文和版本冻结到运行快照。

## 当前边界

本阶段覆盖多个登记 API 的结构化安全变异，并可选检查同一项目、同一执行环境中已打开的受控 Web 页面。Web 检查只读当前主文档响应头和有限表单/资源结构，不导航、不点击或提交数据；候选信号进入方案预览与报告 AI 总结，并明确标记为未确认线索。它不做自动爬虫、任意 URL 探测、shell 执行或模型生成的原始请求，也不代表对 Web 应用全部路由的覆盖。

## 部署

部署前在 backend 目录执行 `alembic upgrade head`（包含安全评估和 Skill 的 revisions `0022`、`0023`），再启动新版服务。Agent 管理员需要给安全工作流授权策略/API/Finding 读取、`security.preview_plan`、`security.confirm_plan`、`security.execute_cases`、报告和 TestRun 读取工具，并关联适用的 Skill 与已授权模型。
