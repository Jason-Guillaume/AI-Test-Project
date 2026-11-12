# P9 RAG 与 Context Manager 实施记录

## 范围与复用

- 保留既有知识库文档、切片、版本、项目授权和 Agent 绑定；没有新建文档管理系统。
- 保留既有 AgentSession 与消息持久化；新增有来源校验的会话摘要和 Agent 长期记忆，不复制原始消息。
- P7 独立评测引擎和 LLM-as-a-Judge 不在本阶段范围内。

## 检索实现

知识检索在 PostgreSQL 查询中应用授权过滤、关键词条件、相关度排序和候选上限，再执行现有 BM25 评分、Top-K 和最低相关性阈值。结果保留 chunk、文档版本及来源信息。可以向服务层注入经过版本及权限验证的向量候选，并以 Reciprocal Rank Fusion 融合；当前部署没有 pgvector 扩展或 embedding provider，故 HTTP 运行路径明确返回 `vector_status=UNAVAILABLE`、`reranker_status=UNAVAILABLE`，当前策略为 BM25。

Alembic `0057_runtime_search_indexes` 尝试启用 pg_trgm 并为知识切片文本和消息内容建立 GIN trigram 索引；扩展不可用时迁移允许继续，查询仍有候选上限。文档版本与来源追溯由原有模型继续承担。

## 上下文实现

- 默认只读取同一 AgentSession 的近期消息，并额外召回有限数量的同会话相关历史消息；当前用户输入优先保留。
- 较长会话生成确定性的抽取式摘要索引，记录源消息 ID、内容摘要哈希、版本和有效期；原始消息仍是可追溯事实，源消息变化或越权时摘要不参与上下文。
- 长期记忆按项目、Agent、memory key 和版本管理。可引用原始消息来源，读取时重新校验项目、Agent、会话和内容哈希；写入权限受现有项目权限控制。
- Context manifest 记录来源、范围、摘要/记忆版本、token 预算、已省略和未检索数量；上下文内容作为不可信信息提供给模型。

## API 与迁移

- 知识检索接受可选 `candidate_k`，并返回策略、候选数量、截断状态、耗时及向量/重排可用状态；既有字段保持兼容。
- Agent 长期记忆提供按 Agent 列表、创建/更新新版本和过期操作，采用 expected-version 防止并发覆盖。
- 新表由 Alembic `0059_agent_session_summaries` 与 `0060_agent_long_term_memory` 建立。工作区当时已有 `0058_data_lifecycle_trash` 未提交迁移，故迁移链按 0057 → 0058 → 0059 → 0060 排序；该 0058 由工作区原有数据生命周期变更提供，本记录不包含其功能范围。

## 验收记录

定向测试：`tests/test_55_context_manager.py`、`tests/test_56_context_pagination.py`、`tests/test_59_agent_memory.py`、`tests/test_60_retrieval_performance.py`、`tests/test_61_rag_quality_fixtures.py`、`app/knowledge/tests/test_isolation.py`，结果 **21 passed**。

10,000 条合成 chunk 的查询上限设为 200，搜索耗时 39 ms，返回 200 个候选并报告截断。PostgreSQL `EXPLAIN` 证实 trigram GIN 索引可用于关键词候选查询（索引计划执行 3.520 ms；该计划验证显式关闭了 seqscan，应用查询计时未关闭 seqscan）。这项数据仅是本地合成数据基准，不代表生产负载 SLA。

小型中英混合检索 fixture 用 Recall@1 和 MRR 验证关键词检索排序；它们是检索工程回归指标，不是 Agent 正确率或标准答案评测。
