# 交付物 2：项目开发 skill（.claude/skills/develop-this-project/SKILL.md）

skill 按工作流划分共 13 节 + 顶部必读规则；12 项关键声明在 v1.0→v1.1 用 Ultracode 并行验证抓到 11 处原稿错误，全部改正。

**用途**：Claude Code 在本项目里做开发任务时**自动加载**的前置工具文档。它不是给人读的说明书——是给 Claude 读的"你在这个仓库里怎么动手"的操作手册。

## 触发条件

skill frontmatter 的 `description` 字段：

> 在本项目（ai-test-project）中做开发任务时使用：启动/停止前后端、跑测试、做 Alembic 迁移、加 feature、加页面、加 API、查 API、看配置、常见故障排查。项目特定事实与命令。**在本项目协作中，所有对话回复必须使用中文。**

命中关键词之一即触发加载；中文回复规则同时挂在 `description` 里，让 skill 被加载进系统提示时规则先于内容出现。

## 结构（13 节 + 顶部必读）

| 节 | 内容 |
|---|---|
| ⚠️ 顶部必读 | ① 所有回复必须使用中文（附例外清单） ② 每次工作开始前完整读本文 ③ 另外读 `docs/coding-conventions.md` |
| §1 | 项目一句话（monorepo 结构 / 全栈技术栈 / 端口） |
| §2 | 目录速览（backend / frontend tree） |
| §3 | 环境准备（venv、pip、psql 建库、alembic stamp、seed_admin、npm install） |
| §4 | 日常启动 / 停止（uvicorn、npm run dev、浏览器路径） |
| §5 | 跑测试（pytest 全量 / 单文件 / 单用例；testplatform_test 隔离） |
| §6 | 后端开发速查（加 feature 三件套、Alembic 命令、脚本、红线） |
| §7 | 前端开发速查（加页面四步、页面样板骨架、QueryKey 命名、常见坑） |
| §8 | API 速查表（11 个模块 × 完整端点清单 + 路径参数命名约定） |
| §9 | 配置速查（环境变量、密码规则、限流、验证码、测试配置） |
| §10 | 运维命令速查 |
| §11 | 故障排查表（13 条症状 → 解） |
| §12 | 提交前自检清单 |
| §13 | 交叉引用 + 版本 |

## 版本演进

| 版本 | 日期 | 变化 |
|---|---|---|
| v1.0 | 2026-10-12 | 初稿；由 4 个并行 scout agent 的侦察结果综合而成 |
| v1.1 | 2026-10-12 | **Ultracode 验证修正**：12 个 verifier agent 并行核对代码库，抓到 11 处原稿错误全部改正（详见 [03-ultracode-verification.md](03-ultracode-verification.md)） |
| v1.2 | 2026-10-12 | 把「中文回复」规则从单行注释提升为顶部必读规则第 1 条；同步在 frontmatter `description` 里挂上，让规则先于内容出现 |

## 顶部必读规则（v1.2 新增小节）

**1. 所有回复必须使用中文**

在本项目中与用户 / 团队对话的一切文字产出——Claude 助手回复、代码评审意见、commit message、PR 描述、issue 讨论、错误消息文案、UI 文案、日志里带业务含义的字符串——统一使用中文。

例外（保持英文的场景）：

1. 标识符、类型名、函数名、变量名、模块路径、API 字段名（`snake_case` / `camelCase`）
2. 第三方库 / 框架 / 命令 / URL / 错误码 / HTTP 状态码的原始英文/技术名（如 `FastAPI`、`uvicorn`、`pip install`、`404 Not Found`）
3. 通用代码约定：`type: ignore`、`noqa`、`TODO`、`FIXME`、`XXX`
4. 引用第三方文档原文

**判断标准**：如果这句话是给「人」看的解释/描述，用中文；如果是「机器」读的符号/标识符，用英文。

**2. 每次工作开始前必须完整读 skill 本文**——不是扫一眼，是从头到尾读，特别是必读规则、§3–§5、§6.4、§7.4、§8、§11。

**3. 另外必须读 [docs/coding-conventions.md](../coding-conventions.md)**——里面是中文注释强制要求、架构不变量、17 条红线、变更流程。skill 只写日常操作，规则性/结构性内容一律指向 `coding-conventions.md`。

## 证据

- skill 全文：[.claude/skills/develop-this-project/SKILL.md](../../.claude/skills/develop-this-project/SKILL.md)（461 行）
- 与规范的关系：本 skill 是"操作手册"，coding-conventions.md 是"规则"；两者通过 skill §12 自检清单与 skill 顶部必读规则 ③ 双向交叉引用
- 版本演进与验证过程：见 [03-ultracode-verification.md](03-ultracode-verification.md)
