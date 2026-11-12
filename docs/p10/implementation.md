# P10 Agent 运行质量治理收口

## 范围与复用

- 复用 `RuntimeCallFact`、`RuntimeEventFact`、`TaskRun`、`TaskWorkItem`、`TaskAgentInstance` 与 `AgentDefinitionRevision`，不新增第二套指标账本。
- 复用 `/api/v1/agent-governance/runtime/overview` 与管理端「Agent 运行质量」页；统计数据来自真实 PostgreSQL 运行事实。
- 复用既有 Agent/Skill Revision 列表、启停、恢复历史版本为新 Revision 的管理入口。
- 本阶段不增加固定答案评测集、独立 Evaluation Engine、LLM-as-a-Judge、质量分数或质量门禁。现有只读评审工具保持原状，不扩展为自动评测流水线。

## 指标与口径

页面展示任务成功/部分完成/失败/取消比例、平均与 P95 执行时长、工作项重试率、子 Agent 失败率、模型调用状态、Token、可确定成本、工具与 Skill 状态、RAG/上下文使用量及用例草稿人工编辑/拒绝率。

模型成功率分母仅包括 `SUCCEEDED + FAILED`；`UNKNOWN` 调用仍计入调用总量，但在模型明细中单独显示，不会降低或抬高已知终态成功率。模型平均延迟、P50、P95 仅使用 `RuntimeCallFact.duration_ms > 0` 的实测样本，响应同时返回有效样本数；零值不冒充实测时长。模型延迟趋势告警使用相同正时长口径，并要求当前与基线各至少 5 个有效样本。

成本只统计带明确价格快照和币种的调用。缺少价格时成本为 `null` 并计入未定价调用，不按 Token 猜测。多币种总额不混加。人工反馈仅来自现有用例草稿审核记录，不能外推为正确率；Skill 指标是装载状态，不代表 Skill 产出质量。API 带 `metric_definition_version`、统计窗口、水位和逐项 definitions。

## Revision 治理

Agent 编辑会创建不可变 `AgentDefinitionRevision`。版本使用情况按 `RuntimeCallFact.agent_definition_revision_id` 聚合；已有恢复 API 从历史快照创建一个新的 Revision，避免重写历史。Skill 版本与工具调用统计复用现有治理目录和运行事实。没有标准答案的执行数据不显示准确率或正确率。

## 接口与界面

- `GET /api/v1/agent-governance/runtime/overview`：支持项目范围与最多 90 天时间窗，返回任务、模型、Agent Revision、Tool、Skill、人工反馈、异常、数据水位及统计口径。
- Agent Revision 表展示模型调用、失败数、Token、币种成本和平均时延。
- 模型表展示配置/模型版本、已知终态成功率、未知调用、Token、已知成本、平均/P50/P95 时延和有效延迟样本数。
- 页面保留请求加载、错误重试、空指标占位和分页；只消费服务端真实统计结果。

## 数据库与验收

本阶段无需新增表或迁移。目标字段与索引已由 `0053_runtime_call_facts`、`0054_runtime_event_facts`、`0055_runtime_agent_session_links` 提供；Agent 版本快照沿用既有治理表。

回归覆盖：模型成功率排除未知状态、运行指标 API 的正时长样本、PostgreSQL P50/P95、Revision/权限既有治理回归，以及 TypeScript 类型和构建检查。性能容量仍受 90 天查询上限和现有事实索引约束；生产高基数聚合需按实际数据量观测，必要时再评估按日预聚合，不在本次复制第二份事实数据。
