# 文档索引

本目录收录平台的全部设计与交付文档。文件命名统一为英文 kebab-case，中文标题保留在各文档正文内。

2026-10-30 前端整单资料：[审查](agent-cluster-refactor/23-frontend-full-audit.md)、[U0–U12 计划](agent-cluster-refactor/24-frontend-comprehensive-refactor-plan.md)、[执行提示词](agent-cluster-refactor/25-frontend-comprehensive-agent-prompt.md)、[连续实施进度](agent-cluster-refactor/frontend-comprehensive-progress.md)、[实施交付与回退](agent-cluster-refactor/frontend-comprehensive-delivery.md)。静态基线与迁移建议保留原始审查时点，当前实际路径以交付台账为准。

## 快速入口

| 需求 | 文档 |
|---|---|
| 本地快速启动 | [根目录启动指南](../local-startup-guide.md) |
| 本地启动详细说明与故障排查 | [getting-started.md](getting-started.md) |
| 了解编码规范 / 红线 | [coding-conventions.md](coding-conventions.md) |
| 了解项目当前阶段与历史决策 | [development.md](development.md)（开发日志索引） |
| 查看某模块的交付结论 | 见下方「交付报告」 |

## 架构与迁移（历史分析）

| 文档 | 说明 |
|---|---|
| [current-system-analysis.md](current-system-analysis.md) | 旧项目现状分析（逐模块、逐端点） |
| [target-architecture.md](target-architecture.md) | 目标架构与阶段一设计 |
| [migration-plan.md](migration-plan.md) | 旧→新 API 映射、字段与状态码差异 |
| [architecture-audit-unification-plan.md](architecture-audit-unification-plan.md) | 前后端架构审计与统一改造计划 |
| [agent-governance-runtime.md](agent-governance-runtime.md) | Agent、Skill、MCP 与任务 LangGraph 运行边界及配置步骤 |

## 开发流程与规范

| 文档 | 说明 |
|---|---|
| [coding-conventions.md](coding-conventions.md) | 编码规范（中文注释规则、架构不变量、红线、变更流程） |
| [development.md](development.md) | 项目开发日志索引，章节在 [development/](development/) 目录 |
| [self-designed-security-agent.md](self-designed-security-agent.md) | 自研安全评估 Agent、工具治理、审批边界与迁移说明 |

## 功能开发计划与需求

| 文档 | 模块 |
|---|---|
| [security-testing-phase1-dev-plan.md](security-testing-phase1-dev-plan.md) | 安全测试 Phase 1 开发计划 |
| [security-testing-phase1-requirements.md](security-testing-phase1-requirements.md) | 安全测试 Phase 1 需求说明 |
| [test-data-center-dev-plan.md](test-data-center-dev-plan.md) | 测试数据中心 + Data Factory 开发计划 |
| [project-knowledge-business-assembly-plan.md](project-knowledge-business-assembly-plan.md) | 项目知识库、Agent 业务组装与人工编辑实施计划 |
| [agent-cluster-refactor/README.md](agent-cluster-refactor/README.md) | 任务与智能体集群重构：需求、架构、协作、前端、实施、验收及智能体交接指令 |
| [agent-cluster-refactor/08-directory-refactor.md](agent-cluster-refactor/08-directory-refactor.md) | Agent、Tool、Skill、MCP、知识库共享能力的目标目录、依赖及兼容迁移 |
| [agent-cluster-refactor/09-optimization-requirements.md](agent-cluster-refactor/09-optimization-requirements.md) | 可直接交给 Agent 的优化需求：路径映射、实施范围、阶段验收与知识库后续需求 |
| [agent-cluster-refactor/10-core-consolidation-plan.md](agent-cluster-refactor/10-core-consolidation-plan.md) | models/shared 归并 core：目标目录、历史兼容路径、对象唯一性、迁移与验收（历史计划） |
| [agent-cluster-refactor/11-core-consolidation-agent-prompt.md](agent-cluster-refactor/11-core-consolidation-agent-prompt.md) | 可复制的 core 归并实施 Agent 提示词，含文件路径与交付要求 |
| [agent-cluster-refactor/12-task-module-split-plan.md](agent-cluster-refactor/12-task-module-split-plan.md) | tasks 拆分计划：回归收尾、查询/消息/资源服务、报告/审阅处理器及事务验收 |
| [agent-cluster-refactor/13-task-module-split-agent-prompt.md](agent-cluster-refactor/13-task-module-split-agent-prompt.md) | 可复制的任务模块优化需求提示词，默认执行 T0–T3 |
| [agent-cluster-refactor/14-business-capability-extraction-plan.md](agent-cluster-refactor/14-business-capability-extraction-plan.md) | 业务域 HTTP、表达式、LLM、模板共享能力提取计划及独立工具需求 |
| [agent-cluster-refactor/15-business-capability-agent-prompt.md](agent-cluster-refactor/15-business-capability-agent-prompt.md) | 可交给 Agent 的业务共享能力需求提示词，默认执行 E0–E4 |
| [agent-cluster-refactor/16-backend-stabilization-and-split-plan.md](agent-cluster-refactor/16-backend-stabilization-and-split-plan.md) | 后端装配、治理、HTTP 与测试修复计划，含逐项回归及后续 D1–D4 目录优化 |
| [agent-cluster-refactor/17-backend-stabilization-agent-prompt.md](agent-cluster-refactor/17-backend-stabilization-agent-prompt.md) | 可交给 Agent 的修复需求提示词，默认执行 F0–F4 |
| [agent-cluster-refactor/18-backend-comprehensive-refactor-plan.md](agent-cluster-refactor/18-backend-comprehensive-refactor-plan.md) | 一单覆盖 B0–B9 的后端综合拆分、20–31 工程人日估算、内部检查点与统一验收 |
| [agent-cluster-refactor/19-backend-comprehensive-agent-prompt.md](agent-cluster-refactor/19-backend-comprehensive-agent-prompt.md) | 可一次性交给 Agent 持续执行完整工作包的总需求提示词 |
| [agent-cluster-refactor/20-features-directory-layout-plan.md](agent-cluster-refactor/20-features-directory-layout-plan.md) | platform、orchestration 与 features 的当前模块归属和迁移验收 |
| [agent-cluster-refactor/backend-stabilization-delivery.md](agent-cluster-refactor/backend-stabilization-delivery.md) | F0–F4 修复、浏览器登录超时定位、逐项测试结果、差异和回退方式 |
| [agent-cluster-refactor/business-capability-extraction-delivery.md](agent-cluster-refactor/business-capability-extraction-delivery.md) | E0–E4 共享 HTTP、表达式、LLM、模板能力实际迁移、行为承接、测试结果与回退说明 |
| [agent-cluster-refactor/core-consolidation-delivery.md](agent-cluster-refactor/core-consolidation-delivery.md) | C0–C5 实际路径、历史兼容入口及后续删除记录、验证结果与未完成事项 |
| [agent-cluster-refactor/task-module-split-delivery.md](agent-cluster-refactor/task-module-split-delivery.md) | T0–T3 任务服务与处理器实际迁移、回归结果、接口委托入口及后续事项 |
| [agent-cluster-refactor/features-layout-baseline.md](agent-cluster-refactor/features-layout-baseline.md) | features 目录迁移前源码状态、OpenAPI、ORM metadata 和 pytest 收集基线 |
| [agent-cluster-refactor/features-directory-layout-delivery.md](agent-cluster-refactor/features-directory-layout-delivery.md) | 平台与 tasks 实际迁移映射、Web UI 依赖调整、实测结果和未完成项 |

## 交付报告（按时间顺序）

| 文档 | 模块 | 交付日期 |
|---|---|---|
| [mock-management-phase1-delivery-report.md](mock-management-phase1-delivery-report.md) | Mock 管理 Phase 1 | 2026-10-15 |
| [web-ui-automation-phase1-delivery-report.md](web-ui-automation-phase1-delivery-report.md) | Web UI 自动化 Phase 1 | 2026-10-19 |
| [security-testing-phase2-zap-delivery-report.md](security-testing-phase2-zap-delivery-report.md) | 安全测试 Phase 2（OWASP ZAP 集成） | 2026-10-21 |
| [agent-cluster-refactor/business-capability-extraction-delivery.md](agent-cluster-refactor/business-capability-extraction-delivery.md) | 业务域共享能力提取 E0–E4 | 2026-10-29 |
| [agent-cluster-refactor/backend-stabilization-delivery.md](agent-cluster-refactor/backend-stabilization-delivery.md) | 后端稳定化 F0–F4 | 2026-10-29 |

## 验证资产与部署文档

| 路径 | 说明 |
|---|---|
| [zap/README.md](zap/README.md) | ZAP 部署与验证指南（含冒烟脚本 `zap_smoke_check.sh`） |
| [web-ui-phase1/](web-ui-phase1/) | Web UI Phase 1 验收记录（pytest 摘要、浏览器验证截图） |

- [后端综合职责拆分交付（B0–B9）](agent-cluster-refactor/backend-comprehensive-delivery.md)：执行器、任务服务/运行时、安全/ZAP、API 目录、Fixture、业务/Web/Agent 及 Schema/路由；[进度与检查点](agent-cluster-refactor/backend-comprehensive-progress.md)。
