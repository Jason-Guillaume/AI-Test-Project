# 未完成与后续迭代

> 本文记录 2026-10-12 的历史风险清单；其中验证码相关条目反映当时状态，验证码已于 2026-10-27 从当前产品移除。

未完成 6 项、后续迭代 6 项；按 ROI 排序，非承诺。

## 已知未完成 / 未覆盖

| # | 事项 | 状态 | 说明 |
|---|---|---|---|
| R1 | Phase-1 开发日志 | 🚧 未写 | 更早的 phase-1（登录 / 注册 / 缺陷 / 组织 / 项目 / 模型配置 / 环境配置 / 仪表盘 / 通知 / 验证码的完整 CRUD + 权限 + 通知集成）没有单独写一份开发日志；那些内容散落在 commit message 里 |
| R2 | CI/CD 流程 | 🚧 未写 | 当前全靠本地跑 pytest + `npm run typecheck` + `npm run build` |
| R3 | 生产部署文档 | 🚧 未写 | 本轮明确不覆盖生产 |
| R4 | API 变更通知机制 | 🚧 未设计 | 后端字段变目前靠人工同步 `frontend/src/types/index.ts` |
| R5 | skill 的国际化 | 🚧 未考虑 | 如果团队协作里有非中文用户，需要另写英文版 |
| R6 | skill 的自动化更新 | 🚧 无 CI | Alembic head 变更、新增 API 端点、新增 feature 模块时，需要人工更新 skill §6.2 / §8 / §13；没有做 CI 检查保证 skill 与代码同步 |

## 后续可能的迭代

按 ROI 排序，非承诺：

| # | 迭代方向 | 说明 |
|---|---|---|
| N1 | skill 自检脚本 | 给 skill 加一个"每次 commit 前跑一遍"的自检脚本——检查 skill 里写的路径 / 端点 / 命令是否仍然存在于代码库 |
| N2 | Phase-1 开发日志 | 从 git log 生成一份 phase-1 的开发日志 |
| N3 | API 契约自动校验 | 起后端 → 拉 openapi.json → 和 skill §8 表格对比，不一致就在 CI 里报警 |
| N4 | 前端 lint | 接 ESLint + Prettier，替换目前的 `tsc -b` + 人工约定（要改 SKILL.md §7.4 里的"没有 ESLint"坑条目） |
| N5 | 多语言 skill | 英文版 `SKILL.md` |

## 快速索引（想做什么 → 去哪看）

| 想做什么 | 去哪看 |
|---|---|
| 启动项目 | SKILL.md §3–§5 |
| 加后端 feature | SKILL.md §6.1 |
| 加前端页面 | SKILL.md §7.1 |
| 查某个 API 长什么样 | SKILL.md §8 |
| 改配置 | SKILL.md §9 |
| 遇到问题 | SKILL.md §11 |
| 理解为什么这么写 | [coding-conventions.md](../coding-conventions.md) |
| 想知道现在在什么阶段 | [00-overview.md](00-overview.md) + 本文 |

## 证据

- R1–R6 与 N1–N6 均**未实施**，是明确的「未做」清单；不做不代表永远不做
- 与 [00-overview.md](00-overview.md)「不在本轮范围」的对照：R1–R6 是本轮未做的事的完整版；00-overview 里列的是"根本不在本轮范围"，两者有交集但不重叠
