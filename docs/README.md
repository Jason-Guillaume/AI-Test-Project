# 文档索引

本目录收录平台的全部设计与交付文档。文件命名统一为英文 kebab-case，中文标题保留在各文档正文内。

## 快速入口

| 需求 | 文档 |
|---|---|
| 本地启动前后端联调 | [getting-started.md](getting-started.md) |
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

## 开发流程与规范

| 文档 | 说明 |
|---|---|
| [coding-conventions.md](coding-conventions.md) | 编码规范（中文注释规则、架构不变量、红线、变更流程） |
| [development.md](development.md) | 项目开发日志索引，章节在 [development/](development/) 目录 |

## 功能开发计划与需求

| 文档 | 模块 |
|---|---|
| [security-testing-phase1-dev-plan.md](security-testing-phase1-dev-plan.md) | 安全测试 Phase 1 开发计划 |
| [security-testing-phase1-requirements.md](security-testing-phase1-requirements.md) | 安全测试 Phase 1 需求说明 |
| [test-data-center-dev-plan.md](test-data-center-dev-plan.md) | 测试数据中心 + Data Factory 开发计划 |

## 交付报告（按时间顺序）

| 文档 | 模块 | 交付日期 |
|---|---|---|
| [mock-management-phase1-delivery-report.md](mock-management-phase1-delivery-report.md) | Mock 管理 Phase 1 | 2026-10-15 |
| [web-ui-automation-phase1-delivery-report.md](web-ui-automation-phase1-delivery-report.md) | Web UI 自动化 Phase 1 | 2026-10-19 |
| [security-testing-phase2-zap-delivery-report.md](security-testing-phase2-zap-delivery-report.md) | 安全测试 Phase 2（OWASP ZAP 集成） | 2026-10-21 |

## 验证资产与部署文档

| 路径 | 说明 |
|---|---|
| [zap/README.md](zap/README.md) | ZAP 部署与验证指南（含冒烟脚本 `zap_smoke_check.sh`） |
| [web-ui-phase1/](web-ui-phase1/) | Web UI Phase 1 验收记录（pytest 摘要、浏览器验证截图） |
