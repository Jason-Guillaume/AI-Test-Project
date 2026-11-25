# SuperAgent 优化验收报告

2026-11-25，在 `develop` 工作树完成三批改动。起始提交为 `4881117`，当时领先 `origin/develop` 一个提交。本次使用本地 Chromium、真实 HTTP 接口和一次性 PostgreSQL 16 / pgvector。模型、MCP 服务、用户、业务文档和任务均为隔离样例。

## 逐项交付

下表的“通过”指对应工程验收已通过。模型效果及生产容量的验证条件见后文。文件路径相对于仓库根目录。

| 编号 | 批次 | 状态与证据 | 主要改动文件 |
|---|---|---|---|
| #1 子 Agent 空输出 | 一 | 通过。空白响应按 `EMPTY_SUBAGENT_OUTPUT` 可重试，不发成功回执。历史空检查点重新执行，指纹匹配的有效兄弟节点复用原结果。 | `backend/app/agents/runtime/subagents.py`、`backend/tests/test_58_subagent_parallel.py` |
| #2 无词项检索 | 一 | 通过。关闭语义通道后，`???`、`é`、`😀` 均无命中。单测分别覆盖语义候选、空查询浏览和零条权限探测。 | `backend/app/knowledge/service.py`、`backend/app/knowledge/tests/test_isolation.py`、`test_models.py` |
| #3 重复尾块与历史引用 | 二 | 通过。1000、1001、1200 字符各一块，1201 字符两块，重叠 200 字符。多页 PDF 保留页码并跳过空页。新解析版本带策略标识。两个 PostgreSQL 会话竞争同一版本时，第二个会话保留第一次产生的 Chunk ID，解析次数为 1。 | `backend/app/knowledge/service.py`、`models.py`、`router.py`、`backend/tests/test_97_rag_hybrid_postgres.py`、迁移 `0099` |
| #4 上下文预算 | 二 | 通过。256 token 内保留最近用户意图及可容纳的短规则，超长条目的 ID、版本和省略原因写入 manifest。过期或撤权记忆经过原来源校验。 | `backend/app/agents/services/context_manager.py`、`backend/tests/test_55_context_manager.py`、`test_59_agent_memory.py` |
| #5 父子检索问题 | 一 | 通过。提交后修改任务目标，捕获的 Planner 与子 Agent 请求仍使用冻结的“退款原路返回”。父节点专用文档未进入子节点输入。修正子节点成功后主流程写追踪事实可能等待自身行锁的问题。 | `backend/app/orchestration/tasks/runtime/handlers/planning.py`、`backend/tests/test_35_tasks.py` |
| #6 多文件 Skill | 一 | 通过。通用主子、同步生成和异步生成均捕获最终模型请求，附件中的唯一规则按当前节点变量展开一次。冻结后修改文件不替换旧输入，仅有 `content` 的旧快照仍能审阅。提交快照统一加锁，Worker 的授权复查只读取键、启用态与版本。 | `backend/app/agents/assembly/{builder,context}.py`、`backend/app/agents/services/case_generation_service.py`、`backend/app/tools/builtin/case_generation/generation_tools.py`、`backend/app/orchestration/tasks/runtime/handlers/case_generation.py` |
| #7 检索窗口 | 二 | 通过。真实 pgvector 在同一授权语料上将 1000 个向量候选、50 个词法候选送入各自阶段，最终最多 8 条。请求的 `candidate_k` 只覆盖词法窗口。诊断记录各阶段配置、实际数量、模型修订、索引代及降级状态。越权文本在重排前排除。 | `backend/app/knowledge/{service,hybrid,router}.py`、`backend/tests/test_97_rag_hybrid_postgres.py`、`frontend/src/pages/admin/KnowledgeSearch.tsx` |
| #8 MCP 和 Agent 有效配置 | 三 | 通过。仅经 Skill 引入的工具可追溯到 Agent、Skill 及版本。再直接绑定后仍只计一个工具。已停用的服务以及普通分析子路径显示不可用。主子树、卡片和项目下有效配置可查看模型继承、文件、知识范围及工具来源。 | `backend/app/agents/assembly/builder.py`、`backend/app/platform/agent_governance/{router.py,services/dependency_service.py}`、`frontend/src/pages/admin/AgentGovernance/{AgentPane,McpPane,DependencyDetails}.tsx`、`agentHierarchy.mjs` |
| #9 工具治理事实 | 三 | 通过。工具停用、尝试超期均未调用处理器；实际执行失败、成功分别计数。外层事务回滚后仍能按调用 ID 和 Attempt 查询，敏感入参、返回值和错误正文未进入事实。异步模块提交后停用工具也产生恰好一条拒绝。 | `backend/app/tools/{dispatcher,registry}.py`、`backend/app/orchestration/tasks/runtime/handlers/case_generation.py`、`backend/app/orchestration/tasks/services/runtime_fact_service.py`、`backend/tests/{test_51_generation_tasks,test_58_subagent_parallel}.py` |
| #10 指定 Agent 试搜 | 一 | 通过。两种视口均在页面上保存仅授权 A 的范围，用该 Agent 搜到 A 的 v2 并查看对应 Chunk。相同查询切到项目范围后还可见 B。来源接口重新校验当前可见范围。 | `frontend/src/pages/admin/{Knowledge,KnowledgeSearch}.tsx`、`backend/app/knowledge/router.py`、`frontend/e2e/superagent-optimization.spec.ts` |
| #11 迟到响应 | 一 | 通过。分别扣住旧项目、旧 Agent、前次提交的响应，再切换或提交下一次搜索。释放响应后，当前范围和命中均未被覆盖。另实测加载、无命中、断网错误及恢复后重试。 | `frontend/src/pages/admin/{Knowledge,KnowledgeSearch}.tsx`、`frontend/e2e/superagent-optimization.spec.ts` |
| #12 环境类型分页 | 三 | 通过。按服务端总数翻页，桌面和手机均选 200 条/页，在第二页查看并编辑第 201 条。第一页的选择在翻页后归零。 | `frontend/src/pages/admin/Environments.tsx`、`frontend/e2e/superagent-optimization.spec.ts` |
| #13 质量页与追溯 | 三 | 通过。可控时钟推进后，使用原筛选刷新可见刚失败的尝试。按项目名称切换后标题、请求和结果同步。异常链接带 Run 与事件 ID，能定位具体子 Agent 及该次检索的版本、Chunk；后端另验证失败工具事件和跨 Run 拒绝访问。授权探测单独计数。 | `frontend/src/pages/admin/AgentRuntime.tsx`、`frontend/src/pages/console/Tasks/{TaskDetailPage,TaskRunPanels,TaskTraceTimeline}.tsx`、`backend/app/orchestration/tasks/{router.py,services/query_service.py,services/task_service.py,services/runtime_fact_service.py}` |
| #14 队列公平性与恢复 | 二 | 通过。两队列都有工作时，各自每两轮至少优先一次。记录新入队时间，显示数量、最老等待时间及向量过期租约。旧记录入队时间未知。独立验证租约接管和旧 token 被拒绝。 | `backend/app/knowledge/{worker,indexing,models,router}.py`、`frontend/src/pages/admin/KnowledgeRetrieval.tsx`、`backend/alembic/versions/0099_knowledge_queue_observability.py` |

## 两条业务链路与截图

第一条使用同一项目的 A、B 文档。A 有两个版本，旧版为七天，新版为两天。通过页面只勾选 A，保存范围后用该 Agent 查询“退款 SLA”，检查版本 ID、片段 ID 和正文，再用同题验证项目范围包含 B。试搜与来源均经实际后端授权。

第二条通过真实任务接口提交退款回归任务，本地模型桩在子 Agent 阶段返回受控错误。已结束的尝试进入既有的模型重试流程。管理员在原质量页刷新，进入对应 Run 高亮的 `SUB_AGENT` 失败事件，再查看同一运行的检索版本和片段。工具拒绝、工具执行失败及原审核流程另由 PostgreSQL 集成测试覆盖。

| 操作证据 | 桌面 1440×900 | 手机 390×844 |
|---|---|---|
| 保存 Agent 文档范围 | [01 桌面](screenshots/01-agent-scope-1440x900.png) | [01 手机](screenshots/01-agent-scope-390x844.png) |
| 指定 Agent 试搜 | [02 桌面](screenshots/02-agent-search-1440x900.png) | [02 手机](screenshots/02-agent-search-390x844.png) |
| 查看 A 的 v2 和对应片段 | [03 桌面](screenshots/03-document-source-1440x900.png) | [03 手机](screenshots/03-document-source-390x844.png) |
| 同题切换项目范围 | [04 桌面](screenshots/04-project-search-1440x900.png) | [04 手机](screenshots/04-project-search-390x844.png) |
| 刷新质量页定位异常运行 | [05 桌面](screenshots/05-quality-failure-1440x900.png) | [05 手机](screenshots/05-quality-failure-390x844.png) |
| 定位失败的子 Agent 及尝试 | [06 桌面](screenshots/06-focused-subagent-1440x900.png) | [06 手机](screenshots/06-focused-subagent-390x844.png) |
| 同次运行的检索证据 | [07 桌面](screenshots/07-run-retrieval-1440x900.png) | [07 手机](screenshots/07-run-retrieval-390x844.png) |
| MCP 的直接与 Skill 依赖 | [08 桌面](screenshots/08-mcp-dependencies-1440x900.png) | [08 手机](screenshots/08-mcp-dependencies-390x844.png) |
| 项目下的有效配置 | [09 桌面](screenshots/09-agent-effective-config-1440x900.png) | [09 手机](screenshots/09-agent-effective-config-390x844.png) |
| 编辑第 201 条环境类型 | [10 桌面](screenshots/10-environment-page-201-1440x900.png) | [10 手机](screenshots/10-environment-page-201-390x844.png) |

截图中的项目、任务、Attempt、修订及片段 ID 属于当次 E2E 隔离库，每次从空库重跑会重新分配。云端追踪投影在本次隔离环境关闭，事件从本地数据库查询。清单包含基线提交、测试夹具及每张 PNG 的 SHA-256 和视口尺寸。[截图版本清单](screenshots/manifest.json)

## 分批回归与复跑

| 阶段 | 已执行的验证 |
|---|---|
| 第一批 | 修复前重现空结果、无词项回填、多文件 Skill 和 SQLite 夹具问题。修复后 Agent、知识和工具组合 55 项通过，PostgreSQL 业务回归 28 项通过，父子冻结目标与异步旧快照定向 2 项通过。知识链路 Chromium 3 项通过。 |
| 第二批 | 知识、上下文、工具等定向组合 67 项通过，PostgreSQL 检索、来源、记忆和窗口 8 项通过。另单独演练租约过期和两代索引来回切换。 |
| 第三批及最终复核 | 后端定向套件 96 项通过，其中包含四种工具结果、审批恢复、双会话解析及租约回滚。前端 57 项单测、类型检查和构建通过。Chromium 10 项通过，包括 13 个管理入口 × 2 个视口，以及 9 项业务操作用例，共保存 20 张业务截图。 |

原有保障也经过回归。有效子节点检查点由 `test_completed_child_checkpoint_is_reused_without_provider_call` 验证，固定版本与撤权由 `test_pinned_version_failed_update_and_revocation`、`test_source_requires_exactly_authorized_version` 验证，审核入库由 `test_submit_idempotent_and_review_import` 验证，租约回收由 `test_lease_expiry_recovery_and_stale_worker_cannot_write` 验证。SQLite 缺失的 `model_legacy_binding` 只在测试夹具补建。

配套改动包括前端接口 `frontend/src/features/agent-governance/{api/agentGovernance.ts,contracts.ts}`、`frontend/src/features/tasks/api/tasks.ts`，树筛选契约及测试 `frontend/src/pages/admin/AgentGovernance/agentHierarchy.d.mts`、`frontend/tests/agentHierarchy.test.mjs`，知识与索引夹具 `backend/app/knowledge/tests/{test_models,test_isolation,test_indexing}.py`，同步与离线评测用例 `backend/app/tools/tests/test_case_generation.py`、`backend/tests/test_61_rag_quality_fixtures.py`，以及隔离模型和浏览器编排 `backend/scripts/llm_stub_server.py`、`scripts/e2e_case_generation.sh`、`frontend/e2e/{superagent-optimization,all-routes-responsive}.spec.ts`。

后端在 `backend/` 运行；数据库测试需将 `TEST_POSTGRES_HOST`、`TEST_POSTGRES_PORT`、`TEST_POSTGRES_USER`、`TEST_POSTGRES_PASSWORD` 指向允许创建和删除测试库的隔离 pgvector 实例。测试夹具按进程分配专属数据库。知识模块单跑 45 项通过，知识与工具合并 63 项通过，数字有重叠。

```bash
LANGFUSE_ENABLED=false .venv/bin/python -m pytest -q app/knowledge/tests
LANGFUSE_ENABLED=false .venv/bin/python -m pytest -q app/knowledge/tests app/tools/tests
LANGFUSE_ENABLED=false DEFECT_SHARE_ARCHIVE_ENABLED=false .venv/bin/python -m pytest -q \
  tests/test_35_tasks.py tests/test_51_generation_tasks.py tests/test_55_context_manager.py \
  tests/test_56* tests/test_57* tests/test_58_subagent_parallel.py tests/test_59_agent_memory.py \
  tests/test_61* tests/test_62* tests/test_97_rag_hybrid_postgres.py
```

前端在 `frontend/` 运行 `npm test`、`npm run typecheck`、`npm run build`。浏览器由仓库根目录下的脚本启动，使用临时管理员、本地桩模型和一次性数据库。设置 `E2E_DATABASE_URL` 指向隔离 pgvector 实例，并预先安装仓库 Playwright 使用的 Chromium。

```bash
PGTZ=Asia/Shanghai E2E_ROUTE_UNTIL=/admin/recycle-bin E2E_VIEWPORT_WIDTHS=1440,390 \
E2E_SUPERAGENT_SCREENSHOTS="$PWD/docs/superagent-optimization/screenshots" \
ZAP_ENABLED=false AUTOMATION_POLL_ENABLED=false DEFECT_SHARE_ARCHIVE_ENABLED=false \
  bash scripts/e2e_case_generation.sh superagent-optimization.spec.ts \
  all-routes-responsive.spec.ts --grep-invert 'representative business pages' --workers=1
```

冒烟复用了原有路由清单，覆盖管理首页、用户、组织、项目、知识、模型、环境、Agent、运行质量、MCP、Skill、工具、回收站。断言包含页面标题、核心内容、主操作可达性、页面级横向溢出及浏览器异常。

## 同题检索评测

合成集含 7 道题、9 个片段，5 道可回答题、2 道无答案或权限负例。覆盖中文退款规则、API 字段、错误码、中英混合、跨段约束及相似旧版。对同一题使用相同项目、Agent、可见版本和 Top-K。重复来源比例为 1/9。

| 合成策略 | Recall@2，5 题 | MRR@2，5 题 | 负例仍有命中，2 题 | 越权来源 |
|---|---:|---:|---:|---:|
| BM25 | 1.00 | 1.00 | 0/2 | 0 |
| 向量 | 0.80 | 0.70 | 1/2 | 0 |
| RRF | 1.00 | 1.00 | 1/2 | 0 |
| RRF 加重排 | 1.00 | 1.00 | 0/2 | 0 |
| BM25 降级后重排 | 1.00 | 1.00 | 0/2 | 0 |

向量及重排使用预制排名和分数。BM25 复用运行时分词、评分，RRF 复用运行时融合函数。“BM25 降级后重排”是同题比较的候选策略。当前生产检索参数、模型及分块结构维持原设置。负例命中率只衡量召回，真实回答、引用及盲审仍缺采集。

从仓库根目录运行下列命令可生成逐题 JSON，包括正确来源前后名次、窗口、修订、Recall、MRR、nDCG、命中、降级及指标样本数。

```bash
LANGFUSE_ENABLED=false backend/.venv/bin/python backend/scripts/evaluate_superagent_retrieval.py \
  docs/superagent-optimization/retrieval-fixture.json --output /tmp/superagent-evaluation.json
```

替换题集时，在 `chunks` 提供脱敏片段与项目和版本，在每题填写 `project_id`、`agent_id`、`visible_versions`、`answerable`、`relevant_chunks`。填入授权模型采集的 `vector.ids` 及各策略重排窗口的 `scores`，可附 `duration_ms`、`model_calls`、`cost` 和带人工支持性标注的 `answers`。缺失观测输出 null 并标注样本数。越权命中或引用使评测以非零状态退出。当前样例计时含本地执行和桩耗时。真实模型的 P50/P95、调用成本、引用支持率、无答案误答率、结构化分块收益及生产队列吞吐仍待验证。[样例](retrieval-fixture.json) · [本次逐题结果](retrieval-results.json) · [评测入口](../../backend/scripts/evaluate_superagent_retrieval.py)

## 回滚与发布边界

- **应用回退已演练。** 隔离库升到 `0099` 后，用新应用创建 A 的 v1、冻结 Chunk，再上传 v2。从 `4881117` 单独取出的旧后端连接同一库，当前项目搜索返回 v2，原冻结快照仍解析 v1 原 Chunk。随后仅在演练库执行 `alembic downgrade 0098`，旧后端再次通过相同断言。部署时优先切回上一套前后端制品并保留兼容列。数据库回退仅在确认后执行，降级会丢弃新增的入队时间及分块策略标记。
- **索引回退已演练。** 同一项目准备并补齐新代，激活新代后搜索，再在“索引与模型”对原 STANDBY 代使用“切换 / 回滚”。两次检索诊断均指向预期索引代，Chunk ID 相同。保留备用代及其向量任务，不退役回滚目标。新增文档版本继续向 BUILDING、ACTIVE 和 STANDBY 登记任务。
- **恢复与权限。** 已验证历史检查点、有内容但缺文件字段的旧 Skill、过期租约和重试。模块生成、汇总审核、草稿导入、组织授权、只读 MCP 审批与项目隔离沿用原工作流。重建若需改变 Chunk，只能先生成可并存的新文档版本并验证原引用。
- **交付范围。** 本次只验证工作树和隔离数据库。生产迁移、活动索引切换、存量重建、外部模型或服务部署均待单独确认。工作树中原有 Dagu 改动含尚未提交的 `0098` 迁移，`0099` 依赖其迁移链。后续集成应按该链安排。期间出现的其他前端样式及数据库方案改动也保留在共享工作区。
