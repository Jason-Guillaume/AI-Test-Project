# 关键决策

| # | 决策 | 结论 | 理由（浓缩） |
|---|---|---|---|
| D1 | 项目开发指引的载体形态 | **Claude skill** + 本开发日志 | skill 被自动加载、有触发条件；非 Claude 用户看不到，用本日志兜底 |
| D2 | 验证策略的时序 | **先写再验**（不是先验再写） | 侦察成本高；先写再验能覆盖更广，抓错效率高 |
| D3 | 中英文边界 | **给「人」看的用中文；给「机器」读的用英文** | 见 [04-key-decisions.md §5.3](#53-中英文边界) 判断清单 |

## 5.1 为什么用 skill 而不是只做 `docs/development.md`

原始任务是"写一份项目开发文档"。改写为 Claude skill 的动机：

1. skill 会被 Claude Code **自动加载**到系统提示里，团队后续做开发任务时不需要手动去读文档
2. skill 的 frontmatter `description` 是关键词触发条件，命中就生效；普通 md 没有这个自动挂载机制
3. 项目开发指引本质是"给 AI 的操作手册"，不是"给读者的说明书"，天然适合 skill 形态

**代价**：非 Claude 用户（比如新人同事刚 clone 完代码）看不到 skill 内容，得先装 Claude Code。所以保留一份本文件（`docs/development/00–06`）作为**给人读的**开发日志。

## 5.2 为什么 Ultracode 验证放在写完之后而不是之前

理论上应该先侦察再写，但侦察成本高——12 个 endpoint 表、20 个配置项、50 条 pitfall，逐个 grep 会花掉大量上下文。**先写再验**的策略：

1. 用 scout 结果（4 个并行侦察 agent）拼出 v1.0
2. 用 Ultracode Workflow 并行验证 12 项关键声明
3. 修正 → v1.1

结果：抓出 11 处错误，命中率约 55%（11/20 项高风险声明），验证成本远低于"猜对了但没验证"的隐性代价。

## 5.3 中英文边界

在 skill 与 coding-conventions 里都写了同一句话：**"如果这句话是给『人』看的解释/描述，用中文；如果是『机器』读的符号/标识符，用英文。"**

**判断清单**：

| # | 类型 | 语言 |
|---|---|---|
| 1 | 标识符、类型名、函数名、变量名、模块路径、API 字段名 | 英文 |
| 2 | 第三方库名（FastAPI、antd）、命令（uvicorn、pip install）、URL、错误码、HTTP 状态码 | 英文原文 |
| 3 | 通用代码约定（`type: ignore`、`TODO`、`FIXME`） | 英文 |
| 4 | 引用第三方文档原文 | 保持原文 |
| 5 | 其它 | 中文 |

## 证据

- D1：skill 与 development/ 目录的分工已在 SKILL.md §13 与 coding-conventions.md 交叉引用中双向挂钩
- D2：完整验证过程与结果见 [03-ultracode-verification.md](03-ultracode-verification.md)
- D3：判断标准在 SKILL.md 顶部必读规则第 1 条与 coding-conventions.md §1.1.1 都写了两遍
