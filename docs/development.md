# 项目开发日志（索引）

分析日期：2026-10-12（Asia/Shanghai）。本文件是本开发日志的**目录索引**；具体章节在 [`docs/development/`](development/) 目录下按 `NN-name-in-kebab-case.md` 拆分。

> 注：本日志写于 2026-10-12，当时仓库尚无 git、Alembic head 为 `0002`。当前仓库已接入 git（主干 `develop`），Alembic head 已推进至 `0014`，以下正文中的版本描述以当时状态为准。

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

### 接口文档上传与云部署

接口管理的导入窗口支持选择 UTF-8 编码的 `.json`、`.yaml`、`.yml` 文件（最大 2 MiB），也可直接粘贴文档。浏览器读取文件内容后，通过现有的认证接口提交解析预览；确认导入时再次提交内容并由服务端重新解析。原文件不会保存到服务器磁盘，因此无需共享上传目录或对象存储，多实例部署也不依赖会话粘性。导入记录保存文件名和解析结果相关信息，不保存原始文件。

云部署时，前端和 API 应通过 HTTPS 提供服务，并将 `/api/v1` 转发到后端。网关或反向代理需要允许足够大的请求体：文件内容会作为 JSON 字符串传输，转义可能使请求体大于原文件，建议上限至少 12 MiB（例如 Nginx 的 `client_max_body_size 12m`），同时根据实际安全策略设置超时和访问控制。2 MiB 是文件选择界面的限制，粘贴内容和直接调用 API 不受该界面限制；生产环境应同时在网关设置请求体上限。上传的文档不应包含不希望发送到服务端的敏感信息。
