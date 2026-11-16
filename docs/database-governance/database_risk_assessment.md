# 数据库治理风险评估

| 风险 | 等级 | 当前证据 | 缓解与状态 |
|---|---|---|---|
| 物理库版本与代码 head 不一致 | **开发库已解决 / 其他环境待核对** | `testplatform_dev` 于2026-11-16已升级到0086；未访问预发/生产 | 按环境核对版本矩阵；生产迁移单独审批，不从本机状态推断 |
| 0085 timeout 超限值归一化不可逆 | **开发库无影响 / 其他环境中高** | 两个超限计数均为0；downgrade不会还原超10800的旧值 | 其他环境升级前必须采集影响行数并导出原值或备份 |
| 后端全量回归未全绿 | **中高** | 1254通过、9失败、6错误；多项组织/权限与API目录用例失败；migration/Jenkins用例全量运行不稳定 | 失败路径不在本轮改动范围；需单独确认预期行为或修复，不能宣称全回归通过 |
| Alembic revision 冲突 | **已解决（代码）** | 上游提交 `1f466ba` 将 Jenkins migration 承接到0085；当前单 head 0086 | 保留旧 Jenkins 0082 stamp 兼容测试；不人工 stamp 跳过迁移 |
| Alembic metadata漏生命周期模型 | **已解决** | env.py注册完整187张模型表，含两张生命周期表 | 后续 autogenerate仍需人工审查DROP/ALTER建议 |
| security_execution 重复索引 | **已解决（本机开发库）** | 0086已应用；catalog只留 `ix_security_execution_test_run_id`，invalid indexes为0 | 生产库需按迁移窗口单独执行并监控锁等待 |
| DB-only `model_global_migration_audit` 与 `td_sandbox_task` | **中 / 暂留** | 0086升级后仍保留 | 未取得多环境保留证据前不删除；不以无ORM模型认定废弃 |
| 0047迁移辅助表 | **中 / 暂留** | `test_scope_api_backfill` downgrade读取回填记录；`test_scope_migration_check`保存核对证据 | 回滚窗口及审计保留期结束前保留 |
| Model Center 新旧模型兼容 | **中-高** | 0034建立资源映射后，服务仍同步 legacy model/ASR 配置 | 逐调用链迁移并核对历史任务、权限与密钥；不直接删旧表或把密钥移入普通 JSON |
| 执行实体跨域合并 | **高** | ASR/测试数据/业务执行/安全扫描/Agent事实各有不同 FK、恢复和审计边界 | 不做通用执行表；当前无证据支持合并 |
| 缺乏跨环境依赖证据 | **高 / 设计边界** | 全量结构分析来自本机仓库与开发库，不含生产/预发/外部消费者 | 所有删除/数据清理候选仍为0；跨环境评审后再考虑 |

## 评估边界

本轮只升级本机开发库，没有访问生产库、没有 DROP TABLE 或数据清理。PostgreSQL隔离迁移专项通过，但完整后端测试有失败与错误，详见 [`database_regression_report.md`](database_regression_report.md)。
