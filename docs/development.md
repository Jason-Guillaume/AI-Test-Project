# 项目开发日志（索引）

分析日期：2026-10-12（Asia/Shanghai）。仓库当前**无 git**；Alembic head `0002`。本文件是本开发日志的**目录索引**；具体章节在 [`docs/development/`](development/) 目录下按 `NN-name-in-kebab-case.md` 拆分。

✅ 本轮（2026-10-12）交付"团队协作基础设施"：编码规范 + 项目开发 skill + 本开发日志。不做业务功能新增，不做生产部署。

## 章节

| 编号 | 标题 | 文件 |
|---|---|---|
| 00 | 本轮开发全景 | [00-overview.md](development/00-overview.md) |
| 01 | 交付物 1：编码规范 | [01-coding-conventions.md](development/01-coding-conventions.md) |
| 02 | 交付物 2：项目开发 skill | [02-skill.md](development/02-skill.md) |
| 03 | Ultracode 验证发现的事实错误 | [03-ultracode-verification.md](development/03-ultracode-verification.md) |
| 04 | 关键决策 | [04-key-decisions.md](development/04-key-decisions.md) |
| 05 | 未完成与后续迭代 | [05-risks-and-next-steps.md](development/05-risks-and-next-steps.md) |
| 06 | 附录（术语 / 索引 / 变更日志） | [06-appendix.md](development/06-appendix.md) |

## 快速索引（想做什么 → 去哪看）

| 想做什么 | 去哪看 |
|---|---|
| 启动项目 | [.claude/skills/develop-this-project/SKILL.md](../.claude/skills/develop-this-project/SKILL.md) §3–§5 |
| 加后端 feature | SKILL.md §6.1 |
| 加前端页面 | SKILL.md §7.1 |
| 查某个 API 长什么样 | SKILL.md §8 |
| 改配置 | SKILL.md §9 |
| 遇到问题 | SKILL.md §11 |
| 理解为什么这么写 | [coding-conventions.md](coding-conventions.md) |
| 想知道现在在什么阶段 | [development/00-overview.md](development/00-overview.md) |
| 想知道本轮有哪些未完成 | [development/05-risks-and-next-steps.md](development/05-risks-and-next-steps.md) |
| 想知道本轮交付了什么 | [development/01-coding-conventions.md](development/01-coding-conventions.md) + [02-skill.md](development/02-skill.md) |

## 配套文件

- [coding-conventions.md](coding-conventions.md)——编码规范 v1.2（1081 行）：中文注释规则、架构不变量、17 条红线、变更流程
- [../.claude/skills/develop-this-project/SKILL.md](../.claude/skills/develop-this-project/SKILL.md)——项目开发 skill v1.2（461 行）：Claude Code 在本项目做开发任务时自动加载

## 阅读顺序

`00` 全景 → `01` 编码规范 → `02` skill → `03` 验证发现 → `04` 关键决策 → `05` 未完成与后续 → `06` 附录。

**当前版本**：v1.1（2026-10-12）——多文件拆分版；v1.0 单文件版已替换。
