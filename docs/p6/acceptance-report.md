# P6 自动化验收与兼容报告

验收日期：2026-11-10（Asia/Shanghai）。代码位于当前工作区，未自动提交、推送或合并。

## 基线审计结论

- 当前分支：feature/case-generation-closed-loop；审计开始 HEAD aa46bf1。
- 本地 develop / origin/develop 引用：f64ebd2；当前分支包含其后续前端路由修复 9731f70 和审核闭环 aa46bf1。未联网更新 Git 引用，结论以本地实际引用为准。
- 初始工作区已有前端工作台、package/lock、tsconfig，以及未跟踪的 P5 E2E、LLM stub、0049 迁移测试、编排脚本和 .idea；均保留并在相关范围续作。
- 0047→0048→0049 迁移链与 P5 审核闭环已在隔离 PostgreSQL 上真实验收。P5 发现并修复单条入库冲突未保存错误原因的问题；验收脚本修正 Origin、仅测试进程限流、桩返回数量、进程清理和测试库隔离。

## 测试隔离与模型控制

- 后端沿用 tests/conftest.py，每次 pytest 使用带 PID 的独立 PostgreSQL 库，Alembic base→head 建表，测试结束删除该库。
- 迁移兼容测试使用独立 UUID scratch 库；验证旧审核数据升级、唯一约束与回退，不对开发库迁移或写入。
- E2E 使用 testplatform_e2e_gen_<PID> 专属库、独立后端端口 8101、前端 5174、本地 LLM stub 8799。只在该库设置全局任务并发 2，结束停止进程并删除库。
- P6 后端用受控 Stub 验证模型边界；真实 Provider 的最底层 HTTP 也使用替身。E2E 模型配置仅指向本地 stub；LANGFUSE_ENABLED=false，不消耗真实模型额度。

## 已完成的执行结果

| 阶段 / 检查 | 结果 |
| --- | --- |
| P5 后端范围、审核闭环与 0049 迁移回归 | 17 passed |
| P5 Playwright 核心闭环（修复阻断后） | 13 passed，46.7 秒 |
| P6 初版异步 / 并行 / 生命周期 / 恢复 | 5 passed，16.82 秒 |
| 统一任务 + P5 + 初版 P6 阶段回归 | 39 passed，73.94 秒 |
| P6 扩展边界测试 | 10 passed，19.36 秒 |
| 最终生成、0050 升降级与追踪专项回归（补充前） | 19 passed，29.59 秒 |
| 最终全量后端 pytest（含 P6 + 0051 联合底座） | **1149 passed，47 warnings，405.33 秒** |
| 前端 node --test | **41 passed** |
| 前端 TypeScript | 通过 |
| 前端生产构建 | 通过 |
| P6 改动文件 ESLint | 通过，0 warnings |
| 全量前端 ESLint | 未通过：3 个原有问题，见下文 |
| Python 编译、shell 语法与 git diff --check | 通过 |
| 扩展 Playwright（首次全量 P6 场景） | **15 passed，约 1.1 分钟** |

最终完整回归已包含全部新增及补充用例，1149 项为本次单轮全量通过数；不将历史重复运行结果累加。下文保留阶段性失败与修复记录，最终结果以本节和末尾冻结确认记录为准。

## 需求覆盖与证据

| 验收要求 | 后端 / E2E 证据 |
| --- | --- |
| HTTP 立即返回任务身份，不调用模型 | test_submit_idempotent_and_review_import；P6 HTTP 即时返回 E2E，响应小于 2 秒、模型延迟 5 秒 |
| Worker 正常领取、模块分发、Supervisor 聚合 | 独立模块 WorkItem + 跨 Run 依赖；完整草稿与 Review 验证 |
| 多子 Agent 并行 | 双线程屏障证明同时进入；E2E 比较模块执行时间区间重叠 |
| 部分失败不丢成功结果 | test_partial_and_review_retry；原 E2E 01/08 |
| 模型超时、指数退避、尝试上限 | test_timeout_backoff_and_attempt_limit；真实 Provider timeout 上限检查 |
| 模块和 Review 独立失败重试 | test_partial_and_review_retry；成功模块调用次数不增加，已审核草稿保留 |
| 取消待执行 / 在途任务 | test_cancel_preserves_completed_module、test_cancel_running_safe_boundary；P6 运行中取消 E2E |
| Worker 中断恢复、迟到结果隔离 | test_expired_lease_late_result_and_restart：过期租约→INTERRUPTED→重领，新旧代次验证 |
| 重复请求与并发幂等 | 重复 request_key 复用、摘要不同 409；双 Session 并发提交返回同一批次 |
| 刷新恢复和历史批次 | 原 E2E 02；P6 显式刷新后自动恢复任务引用与状态 |
| 同项目多任务和资源额度 | 双任务可提交、第三个拒绝；手动重试同样校验额度；全局与模块闸门专项 |
| 跨项目权限与模型授权 | 原 E2E 12、P6 后端 outsider 的创建/查看/取消/重试拒绝；执行前复核授权 |
| 审核、编辑、拒绝、恢复和入库 | 原 13 项 E2E 及 48/49 后端回归；正式用例仍为 DRAFT，不自动执行 |
| 任务时间线、脱敏与 token 预算 | 模块元数据和事件读取；公共快照去除 instruction/skills/request；预算预留、网络前无事务 |
| 迁移和兼容 | 0048 存量数据升级；0050 存量审核数据升降级与模块唯一约束；项目删除级联 |

## Playwright 场景明细

1. 创建批次，失败模块保留成功草稿。
2. 刷新后历史批次与草稿恢复。
3. 编辑草稿并复核数据库，原始 payload 不变。
4. 单条接受生成 DRAFT 正式用例，重复接受幂等。
5. 项目内重名返回 409，失败原因持久化。
6. 拒绝附原因并恢复待审核。
7. 批量审核二次确认、逐项失败、重复执行无重复资产。
8. 仅失败模块异步重试，已入库草稿不覆盖。
9. 批次审核审计时间线。
10. 并发接受同一草稿只创建一个正式用例。
11. 网络中断后的入库重试。
12. 跨项目隔离与非法资源访问。
13. 与正式用例重名的质量提示。
14. P6 HTTP 即时返回、重复键复用、页面刷新恢复、双模块执行时间重叠。
15. P6 运行中取消、保留成功草稿、刷新恢复取消状态。

## 新旧流程兼容

- 旧同步创建与 regenerate 路径保持原响应，标记 deprecated；没有静默改变既有调用方状态或返回码。
- 新工作台使用 202 异步路径；响应在原 BatchResponse 基础上添加可空 task_id / task_run_id。旧批次仍可审核和同步再生成。
- 异步批次通过旧 regenerate 请求返回清晰 409，防止双流程同时写入。
- 原审核接口和正式 TestCase 状态语义保持，已接受草稿不会被模块重试覆盖。
- 不改变公共 TaskRun 状态枚举；SUCCEEDED / SUCCEEDED_WITH_ISSUES 分别映射批次 COMPLETED / PARTIAL_FAILED。
- 通用任务接口仅展示安全快照；生成任务不能误走执行任务的暂停、目标更新或重试命令。

## 已知未通过项与风险

全量 ESLint 检查发现以下原有问题，文件本轮未改动：

- frontend/src/pages/admin/Organizations.tsx:323：_models 未使用（error）。
- frontend/src/pages/console/TestManagement/TestCases.tsx:180：nodes 表达式导致 useMemo/useEffect 依赖变化（2 warnings）。

这些问题不阻断 TypeScript、生产构建、前端测试或 Playwright；本轮未扩展到管理后台/页面无关整理。后端 warnings 主要为现有 Starlette/Pydantic/依赖废弃提示，未造成测试失败。

生产部署限制：默认全局调度额度仍为 1；启用并行需运维调高既有数据库控制行。不能混部由旧 Worker 消费新工作项。真实模型供应商容量、Langfuse 远端可用性和生产压测未验证；本轮使用可控替身验收，不作真实额度调用。取消不强杀在途请求，预算为保守预留。详细事务、恢复和部署策略见 implementation.md。

## 最终补充与联合验收过程

- 最终 P6 代码 Playwright：15 passed（约 1.1 分钟）；最新前端构建通过（8.13 秒），TypeScript 和 41 项前端测试通过。
- 新增 Worker 生命周期测试：在途调用未结束时 stop→start 不复制执行池；P6 专项共 14 passed。
- 逆序回归发现新测试夹具未恢复共享 Worker 和未清理专属失败任务，导致 7 项后续测试失败；已修复夹具为删除专属项目、恢复并发闸门和 Worker 原运行状态。修复后原顺序中仅出现一次运行期迁移 head 变化导致的断言失败。
- 共享工作区在该次测试建库后新增 0051，出现“库版本 0050 / 文件 head 0051”的预期基线漂移。用户已明确要求将 0051 纳入联合验收；没有撤销或覆盖其他开发改动。
- 新建隔离库迁移到 0051 后，按相同逆序执行最终补充回归：**49 passed，13 warnings，70.14 秒**。
- 0051 专项迁移：**1 passed，11.63 秒**，验证旧批次根回填、跨 Task 根引用拒绝、Trace/deadline 历史 NULL、Agent 修订/父实例列和 downgrade 0050 数据保留。
- 联合验收追加结果以下方最终记录为准；此前 1130 项全量通过仅对应 0051 加入前的基线，不冒充当前联合 head 的全量结果。

### 联合运行底座最终修正

另一聊天确认冻结后，保留新增 Agent 独立会话、统一执行根/Trace、截止时间、续租 fencing、依赖饥饿修复和逐调用预算结算；不继续开发 P8/P9/P10。双方重叠修改造成的重复参数及前端重复字段已清理，P6+运行底座专项一轮 27 passed，冻结版前端构建通过、41 项测试通过，冻结版 Playwright 15 passed。

旧 test35 通过重放已 FAILED Attempt 模拟重试耗尽，与新增严格 fencing 冲突，并遗留幽灵租约造成后续连锁失败。按真实状态机修正测试：领取新的 RUNNING Attempt，再调用 fail_work；finally 恢复共享 Worker、原待办时间并取消专属故障任务。没有放宽生产租约校验。包含旧测试的全量进程已安全中断（232 项通过后中断，不算全量验收结果）；最终完整回归重新从独立数据库运行。最终代码哈希记录在 verification-snapshot.json。

### fencing 与原执行闭环兼容修复

修正旧测试后，定向回归还发现真实兼容问题：原 queue_report 先将当前 Work/Attempt 标记为 SUCCEEDED，再调用 enqueue_work；后者 flush 使严格收尾校验在同一事务中读到提前写入的终态，拒绝收尾并留下 RUNNING 租约。现改为先登记报告依赖、再设置当前成功终态，保持外部执行和幂等回执不变，也不放宽 fencing。修复后 test35 + P6 + runtime foundation：**42 passed，13 warnings，60.35 秒**。仍加载旧实现的全量进程安全中断（688 项通过后中断，不算全量验收），修复后的最终完整验收另行执行。

### 最终共享队列断言修正

一轮完整冻结验收为 1148 passed / 1 failed。唯一失败来自新增底座测试要求 worker.tick()==0，该调用可合法领取其他测试留下的工作，不能据此判断目标批次超时是否正确。已仅修改测试为调用 recover_expired，检查目标批次 FAILED、所有模块 attempts==0、Stub.calls==[]。生产代码不变；单项修正复测 **1 passed，11.21 秒**，最后完整回归重新执行。


## 最终冻结验收结论

- **完整后端：1149 passed，47 warnings，405.33 秒（6 分 45 秒）**。
- **前端：41 passed；生产构建通过（8.16 秒）；TypeScript 通过**。
- **最终 Playwright：15 passed（约 1.1 分钟）**。包含即时响应、刷新恢复、实际时间重叠的模块并行、运行中取消和原审核入库闭环。
- Python 编译、shell 语法、变更文件 ESLint 与 git diff --check 通过。全量前端 ESLint 的 1 error / 2 warnings 为已列明的原有问题，未误报为全量 lint 通过。
- 0050、0051 升降级、历史数据保留、外键隔离、幂等、恢复、超时和迟到结果用例均包含在最终完整回归中。
- 校验 verification-snapshot.json 所列源码哈希与最终工作区一致；其他聊天已明确冻结，未继续扩大到 P8/P9/P10。
- 全部数据库操作仅在专属测试库进行，开发库未迁移；无真实模型额度消耗。代码仍在工作区，未自动提交、推送、部署或合并 develop。

完整输出已归档：test-results/backend-pytest.txt、frontend-tests.txt、frontend-build.txt、playwright.txt。这些最终输出已移除本机数据库密码；历史失败日志未作为最终成功日志覆盖保存。
