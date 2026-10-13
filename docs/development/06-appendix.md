# 附录：术语、索引与变更日志

## A. 术语表

| 术语 | 定义 |
|---|---|
| phase-1 | 本轮之前的业务功能阶段：登录 / 注册 / 缺陷 / 组织 / 项目 / 模型配置 / 环境配置 / 仪表盘 / 通知 / 验证码的完整 CRUD + 权限 + 通知集成。本轮不做 phase-1 内容 |
| phase-2（本轮） | 2026-10-12 的团队协作基础设施交付：编码规范 + 项目开发 skill + 本开发日志 |
| skill | Claude Code 的 `.claude/skills/<name>/SKILL.md` 文件；带 frontmatter `description` 的关键词触发机制；命中关键词即被自动加载进系统提示 |
| Ultracode | Claude Code 的多 agent 编排模式；本次用 4 个 scout 拼 v1.0，再用 12 个 verifier 交叉核对 |
| scout agent | 侦察 agent：并行收集项目事实（backend / frontend / alembic / 配置等） |
| verifier agent | 验证 agent：对代码库做交叉核对，验证关键声明是否与源码一致 |
| 红线 | 不能违反的架构不变量；17 条集中在 coding-conventions.md §2.4 |
| `SessionLocal` 三参数 | `autocommit=False, autoflush=False, expire_on_commit=False`；不可修改 |
| `API_PREFIX` | `/api/v1`；所有 feature router 挂载前缀；`/healthz` 与 `/health` 例外，走根路径 |
| head | Alembic 当前 revision id；当前 head = `0002`（bug 表） |
| 中英边界 | 给「人」看的用中文；给「机器」读的（标识符、命令、URL、状态码）用英文 |
| 越权 404 | 跨资源越权统一返 404（不返 403），避免暴露资源存在性 |
| no-throw notify | `app/shared/notify.py` 内部 swallow 失败，不阻塞主流程 |
| 验证码字符集 | 排除 `0/O/1/I/l`；每个字符单独旋转 ±30°；一次性使用；进程内 dict + Lock 存储；单进程部署 |

## B. 文件路径快速索引

### 本轮交付

| 路径 | 说明 |
|---|---|
| [docs/coding-conventions.md](../coding-conventions.md) | 编码规范 v1.2（1081 行） |
| [.claude/skills/develop-this-project/SKILL.md](../../.claude/skills/develop-this-project/SKILL.md) | 项目开发 skill v1.2（461 行） |
| [docs/development.md](../development.md) | 本日志的索引页 |
| [docs/development/00-overview.md](00-overview.md) | 本轮开发全景 |
| [docs/development/01-coding-conventions.md](01-coding-conventions.md) | 交付物 1：编码规范 |
| [docs/development/02-skill.md](02-skill.md) | 交付物 2：项目开发 skill |
| [docs/development/03-ultracode-verification.md](03-ultracode-verification.md) | Ultracode 验证发现的 11 处错误 |
| [docs/development/04-key-decisions.md](04-key-decisions.md) | 关键决策 |
| [docs/development/05-risks-and-next-steps.md](05-risks-and-next-steps.md) | 未完成与后续迭代 |
| [docs/development/06-appendix.md](06-appendix.md) | 本文件：术语 / 索引 / 变更日志 |

### 相关代码入口（供交叉验证，非本日志交付物）

| 路径 | 说明 |
|---|---|
| `backend/app/main.py` | `create_app()` 入口；API router 装配 |
| `backend/app/shared/database.py` | 唯一 `Base = declarative_base()` 定义点 |
| `backend/app/shared/config.py` | 所有环境变量与限流数字 |
| `backend/app/shared/notify.py` | no-throw 通知；事件字典 |
| `backend/alembic/versions/0002_*.py` | 当前 head，bug 表迁移 |
| `frontend/src/App.tsx` | 前端路由 |
| `frontend/src/types/index.ts` | 前端类型契约（唯一） |
| `frontend/src/api/client.ts` | axios 实例；`baseURL` 已含 `/api/v1` |

## C. 变更日志

### 本开发日志（v1.0 → v1.1）

**v1.1（2026-10-12）——序号化 + 多文件拆分**

1. 所有列表改为编号（便于用「§X.Y 第 N 项」精确引用）
2. 修复原 development.md §4.5 表格里"10 处"与表内 11 行的不一致，统一为 11 处
3. 修复原 development.md §5.2 中「命中率 50%（10/20）」为「55%（11/20）」
4. §4.5 表格新增「涉及位置」列，标明每条错误对应 skill 里的哪一节
5. §3.2 v1.1 版本演进里补出被改的 6 处错误清单（原只在描述里）
6. §3.3 关键约束从 5 条扩展到 10 条，覆盖 coding-conventions §2.4 里的高优先项
7. 拆分多文件：按参考格式（`NN-name-in-kebab-case.md`）拆成 00–06 共 7 个编号文件；`docs/development.md` 保留为索引页

**v1.0（2026-10-12）——首版**

1. 记录本轮三个交付物：coding-conventions.md v1.2、SKILL.md v1.2、本文件 v1.0
2. 汇总 Ultracode 验证发现并修正的 11 处事实错误
3. 明确本轮未做的事
4. 明确 skill 与 development.md 的分工

### 配套文件版本

| 文件 | 当前版本 | 关键变化 |
|---|---|---|
| coding-conventions.md | v1.2 | 新增 §1.1 通用工作规范（中文回复 + 必读本文） |
| SKILL.md | v1.2 | 顶部「⚠️ 必读规则」小节 + frontmatter description 挂中文规则 |
| 本开发日志 | v1.1 | 序号化 + 多文件拆分（v1.0 单文件） |

### 未验证项（诚实标注）

1. **仓库无 git**（`ls .git` 不存在），因此本日志不引用 commit hash；后续若接入 git，可在 [00-overview.md](00-overview.md) 首段补 HEAD
2. **本日志的准确性依赖于 SKILL.md 与 coding-conventions.md 的准确性**；两者已各自通过验证阶段（详见 [03-ultracode-verification.md](03-ultracode-verification.md)），但日志本身未再经并行验证
3. **Alembic head 变更 / 新增 API 端点 / 新增 feature 模块时**，本日志不会自动同步；对应更新位置见 [05-risks-and-next-steps.md](05-risks-and-next-steps.md) R6
