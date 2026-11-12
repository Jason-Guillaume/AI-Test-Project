# 后端综合拆分进度（B0–B9）

本轮起点：2026-10-29，保留全部已有本地改动。依据 18/19 综合需求连续推进，不将内部工作包当作用户审批。

| 包 | 状态 | 实际路径/下一步 |
|---|---|---|
| B0 | 已验证 | validation/b0：517 个源码快照、内容 hash、Git 状态、411 路由入口、497 事务/IO 调用位置；当前全量 1042 passed/47 warnings，与 F4 相同 |
| B1 | 已验证 | executors/contracts、preparation、adapters；迁移安全/Web 私有调用 |
| B2 | 已验证 | tasks/services run、plan、command、state；保留门面 |
| B3 | 已验证 | tasks/runtime handlers、lease、completion；窄能力契约 |
| B4 | 已验证 | security runtime；ZAP protocol、stages、job services |
| B5 | 已验证 | api_catalog 资源服务与公开请求 bundle |
| B6 | 已验证 | Fixture 校验/依赖/转换；生成计划/分派/记录 |
| B7 | 已验证 | business action/flow；Web 与 Agent 服务 |
| B8 | 已验证 | 五个领域 canonical schemas 包；路由/跨域引用审计 |
| B9 | 已验证 | 全量回归、nodeid 对比、统一交付与索引 |

## 基线与边界

- F4 历史报告：1042 passed，47 warnings；当前结果必须由本轮实测补充。
- 源码恢复仅使用 `backend-comprehensive-validation/b0/source-baseline.tar.gz` 中的逐文件内容，并先比对本轮 manifest；不 reset/restore 全工作区。
- 快照仅收录 Python 源码和明确配置，不含 .env、登录态、数据或运行产物。
- 使用用户提供的本机 PostgreSQL 账号，仅创建/删除 `testplatform_test-p<PID>`。禁止测试写入 `testplatform_dev`。
- `route-entries.json` 保存当前 method/path、装饰器响应契约；`transaction-io-boundaries.json` 保存提交/flush/rollback 与执行调用位置。
- 外部扫描、通知和 LLM 使用原测试替身；浏览器/HTTP 测试只访问受控本地服务。

## 检查点记录

- B0 首次验证报告插件在收尾时遇到路径相对化错误，已修复临时报告工具；不将无完整报告的运行标为通过。

- B0 沙箱首次数据库验证被本机 TCP 权限阻止：565 passed、2 failed、475 errors；提权后对同一源码完整重跑为 1042 passed、47 warnings（b0-verified，302.783 秒）。
- B1–B3 初次定向：134 passed、22 failed；修正提取后的 scope/model_snapshot 局部名称遮蔽及 Web 返回对象。第二次：88 passed、1 failed；修正 retry_block_reason 门面同名递归。原测试未删除、跳过或弱化。
- B1–B3 全量检查点正在运行，结果以 `b1-b3-checkpoint/summary.json` 为准。生产 Worker 现约 240 行，处理器仅接收当前数据库实体与明确的 ProviderFactory；租约/完成使用独立 Session 工厂。

- B1–B3 检查点最终：1042 passed、47 warnings，304.93 秒（b1-b3-final 固定源码副本）。公开 helper 测试导入已迁移，nodeid 与断言保持。
- B4：607 项安全/ZAP 专题中，初次因源码边界断言/Mock 插桩位置变化和 rule_view 名称遮蔽出现失败；边界断言已精确迁移至 case_runner/preparation/result_writer，算法目录仍禁 HTTPX/eval，Connector 状态仍不得保存凭据。补充安全+租约组 47 passed。
- B4 全量检查点：1046 passed、47 warnings，322.27 秒（b4-checkpoint）；新增 4 项验证不同所有者及同所有者新代次下迟到成功/异常不覆盖新租约。
- B5–B8：主体和生产调用已迁移。OpenAPI 对比 269 路径、368 schema，除原有 Mock catch-all operationId 的进程随机方法后缀外完整内容相同。
- B5–B8 初次收集因业务测试仍导入旧私有 masking helper 失败；迁移 canonical 导入后定向为 257 passed、2 failed，剩余两项仅引用旧 `_EXECUTOR` 插桩位置，已迁移到 action_executor。
- 最后边界复核：用例动作目标检查必须先于 Faker 求值，新增只读 PreparedActionTarget 以保留原顺序；另增 2 个负向行为测试。正在复核该组并准备最终全量。

## 最终状态：B0–B9 全部已验证

- 最终冻结代码全量：**1049 passed、0 failed、0 errors、0 skipped、47 warnings**；pytest 307.17 秒，报告会话 308.214 秒。
- 原 F4/B0 的 1042 项逐项映射并全部保留/通过；新增 7 项通过（4 租约代次、2 Faker 时机、1 普通数据/平台请求头隔离）。原测试未减少断言，源码 IO 边界测试增加 1 条断言。
- 默认根目录/backend 收集均 1049，nodeid 清单一致。OpenAPI 269 路径/418 操作/368 Schema 保持；只归一化既有 Mock catch-all operationId 的随机后缀。
- 当前源码与最终冻结副本逐字节一致，运行前后源码不变；跨域私有导入、重复 DTO、ORM/迁移变化、明文测试库口令匹配均为 0；warnings 分类与数量保持基线。
- B1–B3 公开 helper 改名的中间副本曾误改 build_agent_guidance，导致验证失败，已保留真实报告并修复；B5–B8 两项旧 `_EXECUTOR` 导入亦已修复。最后边界组 35 passed，随后最终全量覆盖全部修复。
- 规范、架构、Agent 模块说明和索引已更新；历史 T/E/F 记录仅追加后续入口。
- 下一步：无本单未完成工作。统一交付与回退入口：[backend-comprehensive-delivery.md](backend-comprehensive-delivery.md)，最终机器验收：[b9-final/acceptance.json](backend-comprehensive-validation/b9-final/acceptance.json)。
