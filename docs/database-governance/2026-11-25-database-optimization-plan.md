# 数据库精简与去重方案

**兼容现有业务代码的路线，可把平台主库从 198 张物理表逐步减到 195 张。** 第一步可以从最大的三项重叠索引入手。业务表先试点接口请求体，历史辅助表在回滚演练通过后再合并。如果测试数据工厂也完成隔离，主库可进一步降到 194 张。允许同步调整 ORM、业务服务和 Worker 时，项目级路线可以分阶段降到 180 张，两项可选改动全部完成后为 178 张。[项目级重构方案与逐表去向](2026-11-25-project-schema-refactor.md)

## 一、当前数据库

2026-11-25 对项目配置的本地 PostgreSQL 开发库做了只读采样。表数统计 `public` 中的普通表和分区表，包含 `alembic_version`。行数来自逐表 `COUNT(*)`。容量是表、索引及 TOAST 的合计，测试目标库和文件系统中的制品另计。

| 核查项 | 实测结果 | 对设计的影响 |
|---|---:|---|
| 开发库 / 工作区 Alembic head | `0097` / `0099` | 工作区的 `0098`、`0099` 只加列。后续迁移须接在发布时的实际 head 后 |
| 物理表 / 已注册的 ORM 表 | 198 / 195 | 差额是迁移版本表、`model_global_migration_audit` 和 `td_sandbox_task`。195 张 ORM 表在开发库中均存在 |
| 有数据 / 空表 | 45 / 152 | 分母为去掉迁移版本表的 197 张。开发环境很少使用的模块也会有空表，生产用途要单独核实 |
| 全部 198 张表的关系总量 / 这些表自身的索引总量 | 62.88 MiB / 19.17 MiB | 两列分别取 `pg_total_relation_size` 与 `pg_indexes_size` 之和。生产节省量和查询耗时需要单独采样 |
| 测试用例、步骤、断言、测试点、前置条件、用例数据 | 合计 47.78 MiB，占 76.0% | 优先检查这些表的索引和内容，再决定是否值得重构用例存储 |

ORM 表最多的四个模块是语音评测（35）、测试管理（22）、任务编排（17）和测试数据（16）。六张大表中有 5,743 条用例和 27,704 条步骤。对有效用例按项目、测试点、目标及其引用、名称、类型、优先级、说明、状态和启用标志分组，重复组为 0。同一用例内按排序、名称、步骤类型、目标和配置核对，重复步骤组也为 0。这两项核查覆盖精确匹配，语义近似仍需业务判断。

上轮治理在 `0086` 记录了 190 张物理表，并清理了 `security_execution(test_run_id)` 的重复索引。本轮使用新的开发库采样，下面的索引收益单独计算。[上轮实测对照](database_before_after_comparison.md) · [上轮合并评估](database_merge_plan.md) · [当前模型注册入口](../../backend/alembic/env.py)

## 二、按收益排序

| 顺序 | 调整 | 主库物理表净变化 | 可验收的收益 |
|---|---|---:|---|
| 1 | 清理主键已覆盖的普通索引，先试点步骤、断言、用例三张大表 | 0 | 三个试点索引占 1.34 MiB，全部 79 个候选共 2.67 MiB，约占本地索引总量的 13.9% |
| 2 | Skill 正文只写入文件树，在既有 API 中派生 `content` | 0 | 88/88 条当前定义都有完全相同的正文副本，合计 106,935 个 UTF-8 逻辑字节 |
| 3 | `api_request_body` 并入 `api_interface` | −1 → 197 | 移除一个一对一子表，接口详情、导入比对和调试可直接从接口取请求体 |
| 4 | 将三张历史迁移辅助表归并为一张迁移证据表 | −2 → 195 | 把相同用途的历史记录放在一处，仍可按旧主键重建三张原表 |
| 可选 | 将 `td_sandbox_task` 交给测试目标库的 fixture 管理 | −1 → 194 | 平台主库少一张测试专用表，测试目标库继续提供相同的表 |

这几项可独立发布。如果当前主要压力是磁盘或写入成本，可先做前两项。若主要压力是表结构的维护成本，建议做到第 4 项。表数是旧表退役后的净值，双写过渡期会暂时保留旧表。三个试点约占全部候选索引空间的一半。合并请求体时应按对象去重计算其索引占用；正文的逻辑字节单独报告，实际磁盘收益在实施后复测。

## 三、第一批改动

### 清理主键上重复维护的索引

开发库中有 79 个有效普通索引，在同一表上与主键的访问方法、全部键及顺序、操作符类和排序规则一致。筛选排除了表达式、部分索引、额外覆盖列、约束支撑索引和复制标识。以 `test_step.id` 为例，数据库同时维护 `pk_test_step` 和 `ix_test_step_id`，后者单独占 752 KiB。代码中可见 `primary_key=True, index=True`，原始迁移也显式建立了这个普通索引。[步骤模型](../../backend/app/features/test_management/models/test_step.py) · [测试管理建表迁移](../../backend/alembic/versions/0006_create_test_tables.py)

先处理 `ix_test_step_id`、`ix_test_assertion_id`、`ix_test_case_id`。在目标环境保存原索引定义、表空间和存储选项，检查依赖与命名使用，比较同一批主键查询、详情读取和批量写入的执行计划与延迟。新迁移使用逐项核对过的名称，同步移除当前 ORM 的冗余声明。老版本建库脚本仍可按原顺序重放。若性能回退，用保存的定义逐个重建。大表采用 PostgreSQL 并发索引操作时应独立于迁移事务执行，重试前复核索引有效状态。

### Skill 正文采用单一写入位置

`skill_definition.content` 和 `files_json['SKILL.md']` 在本地 88 行中逐行相同。创建、编辑和 ZIP 导入会同步两个值，Agent 组装又把二者写进任务快照。现在的加载器已经支持从老格式 `content` 补入口文件。88 条版本快照中，77 条缺少文件树入口，兼容读取和版本恢复必须覆盖这批数据。[Skill 读写](../../backend/app/skills/services/skill_service.py) · [历史格式加载器](../../backend/app/skills/loader.py) · [任务快照组装](../../backend/app/agents/assembly/builder.py)

1. 当前定义以文件树中的 `SKILL.md` 为正文。兼容只传 `content` 的客户端，将该值写进入口文件；返回既有的 `content` 字段时从文件树读取。保留其他文件、版本号、启用状态和回收站记录。
2. 在每个目标库分别统计「仅旧字段」「两份相同」「两份冲突」。仅旧字段补进文件树，两份冲突保留原值并核实来源。全部读写端都能读新格式、冲突清零后，再退出双写并移除旧列。
3. 历史修订和已冻结的任务快照原样保留。旧修订若只给出正文，恢复时替换当前入口，保留该修订未提供的附件和 MCP 绑定。重放旧任务则只读该任务冻结的内容。新的修订和快照可只存一份入口正文并带格式版本。版本接口和页面按同一格式派生、比较正文，避免格式升级显示为内容变更。覆盖 ZIP 导入、上述两种历史路径和 API 输出；回退时从文件树重建旧列，并向旧读取端提供其所需的快照格式。[历史修订格式](../../backend/alembic/versions/0023_builtin_security_skills.py) · [版本比较页面](../../frontend/src/pages/admin/AgentGovernance/SkillPane.tsx)

## 四、表合并设计

### 先合并接口与请求体

`api_request_body.interface_id` 同时受唯一约束和指向 `api_interface.id` 的级联外键保护。目录读写按接口 ID 取唯一请求体，开发库未发现其他表以外键引用请求体。297 个接口中，127 个有请求体记录，170 个没有。127 条记录里有 47 条显式设置为 `none`，另有 47 条的 `content_type` 与父接口按 NULL 安全比较有差异。这些都是迁移时能检查的真实样本。[请求体模型](../../backend/app/features/api_catalog/models/api_request_body.py) · [读写入口](../../backend/app/features/api_catalog/services/request_store.py) · [API 返回结构](../../backend/app/features/api_catalog/services/response_mapper.py)

| 旧字段或状态 | `api_interface` 上的目标 | 兼容要求 |
|---|---|---|
| 有子行时的 `id` | 可空且唯一的 `request_body_id` | 保留公开的 `body.id`，新记录沿用独立序列。原接口 ID 与请求体 ID 即使不同也可往返 |
| 没有子行 / 有行且 `body_type='none'` | 前者所有请求体列为空，后者有 ID 且类型为 `none` | API 可分别返回 `body=null` 与含 ID 的对象 |
| `body_type`、`content_type`、`schema_json`、`raw_text` | 同类型的 `request_body_*` 列 | 保留请求体自己的媒体类型，包括 NULL。父接口的 `content_type` 独立 |
| `created_at`、`updated_at` | `request_body_created_at`、`request_body_updated_at` | 可还原原行与时间。后台回填不得产生接口新版本或伪造变更日志 |

数据库用约束保证有请求体 ID 时类型和两个时间戳齐全，缺少 ID 时整组为空。两个存储位置共用一次分配的请求体 ID；移除子表前转移或重建序列所有权，保留已分配 ID 的高水位。若目标环境另有入向外键，须先验证清空请求体、重建请求体和删除接口时的引用行为；兼容不了的环境保留原表。列表查询只取摘要列，防止请求体的大 JSON 或文本拖慢分页。

代码切换除目录详情、导入比对和调试以外，还要覆盖 FunASR 接口绑定、运行准备和 OpenAPI 导出中的直接 ORM 查询。验收时核对请求体逐字段值、`source_hash`、重复导入结果、回收站恢复，再比较列表和详情的查询次数与 P95。开发库请求体表连索引共 152 KiB；字段并入父表后仍占空间，主要收益是简化读写。[导入比对](../../backend/app/features/api_catalog/services/import_service.py) · [FunASR 绑定](../../backend/app/features/asr_evaluation/services/funasr_tuning_service.py) · [运行准备](../../backend/app/features/security_testing/runtime/preparation.py) · [OpenAPI 导出](../../backend/app/features/security_testing/zap/openapi_export.py)

### 再合并三张迁移辅助表

三张表用于历史迁移核对、撤销回填和保存治理决定。仓库内仍有迁移及验收代码依赖旧表名。建议新增仅用于迁移的 `migration_evidence`，以 `(revision, kind, source_key)` 为主键。用带类型检查的 JSON 负载保存各类别的原始字段和空值，保留下面指定的真实外键，写权限限于迁移角色。

| 原表 | 本地行数 | 目标记录及关键约束 |
|---|---:|---|
| `test_scope_migration_check` | 15 | `0047 / metric`，以指标名为键，保存原 ID、迁移前后计数；恢复原表时还原指标唯一约束和序列 |
| `test_scope_api_backfill` | 0 | `0047 / case_backfill`，以用例 ID 为键。保留有类型的 `test_case_id` 外键及 `ON DELETE CASCADE`，用检查约束限定仅本类记录使用此外键，并保证其值与来源键相符 |
| `model_global_migration_audit` | 0 | `0046 / model_decision`，以原资源 ID 为键，保存项目、原状态、替代资源和决定。保留历史标识，即使相关资源后来发生变化 |

在新迁移中复制数据，按类别比对行数、键集合和逐行字段。退役时同步移除两个旧辅助模型的注册，将证据表注册到 Alembic 的元数据中，并更新按当前版本查询核对表的测试。若外部只读消费者仍依赖表名，可提供同名只读视图。回退本次合并时，先移除兼容视图、重建三张原表及约束并还原记录，保留私有模型既有的禁用决定。[模型注册](../../backend/app/features/test_management/models/__init__.py) · [范围核对测试](../../backend/tests/test_47_test_scope.py) · [私有模型迁移](../../backend/alembic/versions/0046_project_knowledge.py)

若还需跨越历史版本 `0047` 降到 `0046`，有一个额外风险。旧标记只记 `test_case_id`，降级会清空被标记用例**当时的** `api_id`，包括回填后又人工改绑的用例。目标环境有标记时，须用可信变更记录或备份识别、保全后续改绑，并在演练中核对。来源无法区分时，应停在 `0047` 或以上。演练至少放入未改动的回填、回填后改绑、从未回填的手工关联和非空模型决策各一例。[旧回填与降级逻辑](../../backend/alembic/versions/0047_test_scope.py)

### 可选的第四张表

`td_sandbox_task` 由 `0009` 为数据库 Provider 的白名单测试建立，开发库是空表。先让测试 fixture 在独立目标库建立和销毁该表，更新建表断言及测试连接。逐环境核查 Provider 的 `config_json`、数据库策略的 `allowed_tables`、目标连接和外部脚本。仍有使用方的环境继续保留；已迁走的环境才可从平台库退役。回退需恢复原结构、索引、已有数据及对应测试连接。[建表来源](../../backend/alembic/versions/0009_test_data_center.py) · [数据工厂测试](../../backend/tests/test_19_data_factory.py) · [生命周期测试](../../backend/tests/test_20_test_data_lifecycle.py)

## 五、保留的业务边界

| 对象 | 目前的处理建议 |
|---|---|
| 测试用例及步骤、断言、数据、目录归属 | 保留子表及其 ID。断言可引用步骤，数据项有有效记录名称唯一约束，各子项支持独立回收。开发库恰好每条用例挂一个目录，模型和接口仍允许一条用例挂多个节点。[用例范围模型](../../backend/app/features/test_management/models/test_scope.py) · [断言模型](../../backend/app/features/test_management/models/test_assertion.py) |
| ASR 工作队列与运行结果 | 转写和处理队列各自有父运行、租约及恢复逻辑。成功转写的 `asr_model_run.segments` 与规范化片段存在双写，可在有真实 ASR 负载的环境抽样。这里两侧都是 0 行；先核对时间单位、片段顺序、供应商扩展字段、旧格式回退和重跑，再决定是否停止双写。[结果记录](../../backend/app/features/asr_evaluation/services/comparison_service.py) · [新旧片段读取](../../backend/app/features/asr_evaluation/services/segments_service.py) |
| 新旧模型配置 | 长期可将 `model_configuration`、`asr_connection`、`asr_parameter_set` 的读写分别迁往 `model_resource`、`model_revision`、`model_parameter_profile`。目前三张旧表分别被 7、5、4 个外键引用，仍有双向同步。须迁完旧 ID、授权名单、默认及备用模型、任务快照和 Worker，并验证历史可重放，再单独评估退役。独立凭据表继续承担密文访问控制。[同步与旧接口投影](../../backend/app/platform/model_configuration/services/model_center_service.py) · [模型关系](../../backend/app/platform/model_configuration/models.py) |
| 任务运行事实、投递记录、回收站审计 | 调用事实用于用量和成本，投递记录有租约、重试及幂等状态，回收审计还需追踪恢复。各自保留事实粒度和保留周期，可独立统计占用。[运行事实服务](../../backend/app/orchestration/tasks/services/runtime_fact_service.py) · [回收与审计模型](../../backend/app/core/models/data_lifecycle.py) |

## 六、发布、验收与回滚

1. **按环境建基线。** 先在脱敏副本或预发布重跑下方只读查询，记录实际 Alembic head、行数、对象大小、约束、依赖以及核心请求耗时。核实所有写入端、原生 SQL 和外部报表。本文的 198 张和容量数字只代表本地开发库。
2. **先扩展，再回填。** 用新 Alembic revision 添加兼容列或证据表。请求体混部期间仍统一读写旧子表，先部署兼容版。确认所有写入端都已升级后，统一启用同事务双写，先锁接口父行，再更新旧子行并镜像到父列，覆盖新增、修改、清空三种操作。回填也先锁父行，再重读子行，以接口 ID 分批，可断点重跑。这样旧版和新版写入端不会以相反锁顺序同时操作两表。Skill 也先让全部读端兼容，再切换快照格式。
3. **核对后切读。** 覆盖软删除记录、缺失值、并发编辑和迁移期间新建的对象。请求体和证据行做双向键差集与空值安全的字段比较，差异应为 0；Skill 兼容响应和历史还原应逐字段一致。用同一数据及并发度比较主键查询、接口分页、详情与写入的 P95，超出该服务既有性能预算就继续使用旧路径。
4. **最后退役。** 切读后继续双写，直到覆盖一次完整的导入、任务执行及重试周期，确认旧读端调用清零。单独安排接口目录的短写入窗口，排空在途写入后完成末次比对、切换写入位置和退役旧表。此前可直接切回旧读路径。收缩后如需回退，先隔离该域写入，按新结构还原带原 ID、时间戳及序列的旧结构，核对增删改后再放旧应用接流量。其他阶段分别使用对应的反向迁移。
5. **验证两条迁移路径。** 在一次性测试库分别演练空库升级至新 head，以及从有数据的 `0097` 经工作区后续版本升级、降级、再升级。覆盖 API 请求体有无与旧 ID、Skill 旧修订恢复、带真实外键的回填证据，以及 Provider 测试隔离。验收记录应标明最终物理表净变化、索引字节、接口响应差异和回滚比对结果。

## 附录　只读复核 SQL

下列查询返回汇总和索引名称，可在目标 PostgreSQL 库中复核本方案的主要数字。

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '8s';

SELECT version_num FROM public.alembic_version;

SELECT count(*) AS physical_tables,
       sum(pg_total_relation_size(oid)) AS total_bytes,
       sum(pg_indexes_size(oid)) AS index_bytes
FROM pg_class
WHERE relnamespace = 'public'::regnamespace AND relkind IN ('r', 'p');

SELECT count(*) AS interfaces, count(b.id) AS bodies,
       count(*) FILTER (WHERE b.id IS NULL) AS missing_body,
       count(*) FILTER (WHERE b.body_type = 'none') AS explicit_none,
       count(*) FILTER (WHERE b.id IS NOT NULL
                         AND b.content_type IS DISTINCT FROM i.content_type) AS media_type_diff
FROM public.api_interface i LEFT JOIN public.api_request_body b ON b.interface_id = i.id;

SELECT count(*) AS skills,
       count(*) FILTER (WHERE content = files_json->>'SKILL.md') AS equal_rows,
       sum(octet_length(convert_to(content, 'UTF8')))
           FILTER (WHERE content = files_json->>'SKILL.md') AS duplicate_text_bytes
FROM public.skill_definition;

WITH candidates AS (
    SELECT t.relname AS table_name, ix.relname AS index_name,
           pg_relation_size(ix.oid) AS bytes
    FROM pg_index i
    JOIN pg_index p ON p.indrelid = i.indrelid AND p.indisprimary
    JOIN pg_class t ON t.oid = i.indrelid
    JOIN pg_class ix ON ix.oid = i.indexrelid
    JOIN pg_class pk ON pk.oid = p.indexrelid
    WHERE t.relnamespace = 'public'::regnamespace AND ix.relam = pk.relam
      AND i.indisvalid AND i.indisready AND p.indisvalid AND p.indisready
      AND NOT i.indisunique AND NOT i.indisprimary AND NOT i.indisexclusion
      AND NOT i.indisreplident AND NOT i.indisclustered
      AND i.indpred IS NULL AND i.indexprs IS NULL
      AND i.indnkeyatts = p.indnkeyatts AND i.indnatts = p.indnatts
      AND i.indkey = p.indkey AND i.indclass = p.indclass
      AND i.indcollation = p.indcollation AND i.indoption = p.indoption
      AND NOT EXISTS (SELECT 1 FROM pg_constraint c WHERE c.conindid = i.indexrelid)
)
SELECT table_name, index_name, bytes, count(*) OVER () AS candidates,
       sum(bytes) OVER () AS candidate_bytes
FROM candidates ORDER BY bytes DESC, index_name;

ROLLBACK;
```
