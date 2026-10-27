# 平台 QA Skill 导入目录

迁移 `0023` 至 `0026` 共预置 77 个适配现有治理模型的中文 Skill：40 个 QA Skill、17 个平台功能工作流 Skill，以及 20 个安全测试 Skill。`0024`/`0025` 提供通用 QA、16 个 API 维度及设计/Web/数据/质量/交付专题；`0026` 补充平台模块工作流与安全测试专项。迁移应用后，它们会显示在「管理后台 → Agent 治理中心 → Skill」中，可由管理员按职责组合到 Agent。

## API 专项目录（16 个）

Schema/版本兼容、参数类型/等价类、边界值、必填/Null/默认值、状态码/错误响应、认证/会话、权限矩阵/租户隔离、幂等/重试、并发/竞态、分页/排序/过滤/搜索、业务状态/流程、批量/部分失败、文件上传/下载、异步任务/Webhook、限流/配额、敏感字段/数据最小化。

## 通用与专项目录（17 个）

决策表与业务规则、成对/组合覆盖、跨模块状态迁移、用例质量评审、探索式测试、测试数据/清理、Mock/集成边界、Web 表单校验、响应式/浏览器兼容、可访问性、移动端规划、性能规划、依赖故障/恢复、LLM/Agent 评测、缺陷报告、发布就绪、数据库一致性/迁移。

目录按专题拆分，避免把 REST API 的多种检查维度压进单一提示词。Agent 的单次配置最多绑定 30 个 Skill，应按工作职责挑选；并非每个运行都应注入整套目录。

## 平台功能工作流（17 个）

组织/项目访问边界、项目初始化、API 定义导入、API 变更影响、业务模型映射、测试资产追溯、测试计划组装、运行失败诊断、测试数据工厂、Mock 路由、Agent 任务审批、Skill 组合治理、模型/环境配置、报告证据、通知投递、仪表盘指标和缺陷修复回归。

## 安全测试专题（20 个）

除 `0023` 的 API 授权边界、结构化 API 变异、Finding 分诊和受控 Web 被动观察外，`0026` 新增范围/授权规则、威胁建模、登录/会话、Web 安全策略、CSRF/CORS、输入校验/注入风险、业务逻辑、文件处理、敏感数据、限流/资源保护、依赖/配置基线、外部请求/重定向、Agent 工具与提示注入、修复复测、风险报告和停止条件/影响控制。

## 选择与适配

- 用例、接口、报告和人工确认边界按当前平台工具与任务运行时编写；Skill 本身只提供指令，不新增执行工具或绕过权限。
- ARTEX 目录中的 API、安全审计、Playwright 与报告能力用于梳理需求。项目已有 4 个安全 Skill 覆盖授权边界、结构化变异、Finding 分诊和受控页面观察，因此不重复加入高强度渗透编排、攻击载荷、外部扫描器脚本或 MCP 凭据操作内容。
- API 专项 Skill 采用“设计维度分离”的方式；认证/授权、限流、并发和文件场景仍只在有测试身份、隔离数据、批准环境和清理方案时执行。
- 平台功能 Skill 以核对、追溯、诊断和变更评审为主；项目配置、资产写入、运行、通知、导入/导出等副作用操作遵循平台授权与确认流程。
- 安全 Skill 只允许在明确授权的项目/环境中使用平台现有结构化能力；禁止凭据猜测、破坏性操作、拒绝服务、外部扫描、任意脚本/载荷和生产探测。范围或隔离条件不明确时只输出评审方案。
- 移动端、性能、可靠性与 LLM/Agent 评测中没有平台执行器支撑的部分会明确标记为规划/评审能力，不宣称平台已能直接执行。
- 两个 Awesome 仓库用于确定技能主题和目录方向；本目录的正文是针对当前平台重新编写，不复制上游 Skill 正文。`awesome-qa-skills` 标注 PolyForm Noncommercial 1.0.0，因此不将其正文打包进平台；如未来需要分发上游内容，应先按该仓库许可证处理。

## 参考来源

- ARTEX 本地资料：`skills/api-recon`、`skills/api-security-audit`、`skills/access-control-audit`、`skills/business-logic-audit`、`skills/pentest-report`、`skills/playwright-cli`、`skills/vulnerability-validation`。
- [kenchikuliu/awesome-ai-test-skills](https://github.com/kenchikuliu/awesome-ai-test-skills)：测试技能分类与浏览器测试、组合测试、调试和回归工作流主题。
- [naodeng/awesome-qa-skills](https://github.com/naodeng/awesome-qa-skills)：需求、测试策略、用例、API/UI、回归、失败分析和报告主题；许可见其 [LICENSE](https://github.com/naodeng/awesome-qa-skills/blob/main/LICENSE)。

迁移启用 Skill 后，它们会出现在可选列表；是否注入运行上下文仍由 Agent 的 Skill 绑定决定。迁移不会自动创建 Agent，也不会更改已有 Skill 或用户自定义配置。
