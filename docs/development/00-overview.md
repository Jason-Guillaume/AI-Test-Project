# 本轮开发全景（第一版协作基础设施）

分析日期：2026-10-12（Asia/Shanghai）。仓库当前**无 git**（`ls .git` 不存在）；Alembic head `0002`（bug 表）。结论标签：✅ 已完成、⚠️ 部分完成、🚧 待补齐。本日志是静态文档快照，只记录本次交付的基础设施本身，不做代码分析。

> 当前代码已于 2026-10-27 移除公开注册验证码；下表仅记录该开发阶段的历史交付，不作为当前功能清单。

✅ 本轮（2026-10-12）只交付"团队协作基础设施"：编码规范、项目开发指引（Claude skill）、本轮开发日志（本文档集）。不做业务功能新增，不做生产部署，不接 CI/CD。

证据：coding-conventions.md v1.2、SKILL.md v1.2、本目录 00–06 编号文档。

| 交付物 | 路径 | 版本 | 状态 | 阅读入口 |
|---|---|---|---|---|
| 编码规范 | `docs/coding-conventions.md` | v1.2 | ✅ 完成 | [01-coding-conventions.md](01-coding-conventions.md) |
| 项目开发 skill | `.claude/skills/develop-this-project/SKILL.md` | v1.2 | ✅ 完成 | [02-skill.md](02-skill.md) |
| 本轮开发日志 | `docs/development/00–06`（本目录） | v1.0 | ✅ 完成 | 本文 |
| 项目现状业务功能 | phase-1 已上线（登录/注册/缺陷/组织/项目/模型配置/环境配置/仪表盘/通知/验证码） | — | ✅ 本轮不写日志 | — |
| 生产部署方案 / CI/CD | 未做 | — | 🚧 明确不做 | [05-risks-and-next-steps.md](05-risks-and-next-steps.md) |
| 前端 lint/prettier | 未做 | — | 🚧 明确不做 | 靠 `tsc -b --noEmit` + 人工约定 |
| 分布式验证码存储 | 未做 | — | 🚧 明确单进程 | 多 worker / 多实例需换 Redis |

## 本轮范围

| # | 事项 | 说明 |
|---|---|---|
| 1 | 编码规范 | 中文注释、架构不变量、17 条红线、变更流程；`docs/coding-conventions.md` |
| 2 | 项目开发指引（Skill 形态） | 日常启动/测试/加 feature/加页面/API 速查/配置速查/故障排查；Claude Code 在本项目做开发任务时自动加载 |
| 3 | 本轮开发日志 | 本目录 `00–06`；给人读的交付内容记录 |

## 不在本轮范围

| # | 事项 | 说明 |
|---|---|---|
| 1 | 业务功能新增 | 登录/注册/缺陷/组织/项目/模型配置/环境配置/仪表盘/通知/验证码的完整 CRUD + 权限 + 通知集成已在更早的 phase-1 上线 |
| 2 | 生产部署 / CI/CD / Docker / 监控告警 | 明确不做；生产部署文档未写 |
| 3 | 前端 lint / prettier 配置 | 明确**不做**，靠 `tsc -b --noEmit` + 人工约定 |
| 4 | 分布式验证码存储 | 明确**单进程**；多 worker / 多实例需换 Redis |
| 5 | LLM 调用 / 测试报告 / 真实环境执行 | phase-1 已标记"未接入"，本轮不覆盖 |

## 阅读顺序

`01` 编码规范 → `02` skill → `03` Ultracode 验证发现 → `04` 关键决策 → `05` 未完成与后续 → `06` 附录。

顶层入口：`docs/development.md`（索引页）。配套 skill：`.claude/skills/develop-this-project/SKILL.md`。配套规范：`docs/coding-conventions.md`。
