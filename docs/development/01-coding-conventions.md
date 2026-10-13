# 交付物 1：编码规范（docs/coding-conventions.md）

规范按主题划分共 7 节 + 2 附录；17 条红线在 §2.4 集中列示。v1.1 阶段用 Ultracode 验证抓到 6 处原稿错误并全部改正。

| 节 | 内容 | 关键 |
|---|---|---|
| §1.1 | 通用工作规范 | 1.1.1 所有回复必须使用中文；1.1.2 每次工作开始前必须完整读本文 |
| §1.2 | 中文注释要求 | 模块级 / 函数级 / 关键节点；例外清单 |
| §1.3 | 提交前自检清单 | 与 skill §12 联动 |
| §2 | 后端架构 | tree / 分层 / `SessionLocal` 三参数 / **17 条不变量在 §2.4** |
| §3 | 前端架构 | tree / Provider 层级 / QueryKey 约定 / 页面骨架 |
| §4 | 技术栈（版本锁定） | FastAPI / SQLAlchemy 2.0 / Alembic 1.20 / PostgreSQL 16 / React 18.3 / TS 5.6 / Vite 5.4 / antd 5.21 / @tanstack/react-query 5.59 |
| §5 | 注释风格示例 | 好 / 坏对比 |
| §6 | 反例 | 一眼看出该不该这么写 |
| §7 | 提变更流程 | 改配置 / 改数据库 / 加角色 等场景 |
| 附录 A | 常见问答 | |
| 附录 B | 文件路径快速索引 | |

## 版本演进

| 版本 | 日期 | 变化 |
|---|---|---|
| v1.0 | 2026-10-12 | 初版；覆盖中文注释、架构不变量、17 条红线 |
| v1.1 | 2026-10-12 | Ultracode 验证抓到 6 处事实错误并全部改正（详见下方清单） |
| v1.2 | 2026-10-12 | 新增 §1.1「通用工作规范」，把「中文回复」与「每次工作开始前必须读本文」两条硬规则显式化；对应重新编号 §1.1→§1.2、§1.2→§1.3；补齐 4 处交叉引用 |

## v1.1 修正清单

| # | 原稿错误 | 实际 |
|---|---|---|
| 1 | 「project 四档」 | **5 档**：viewer / member / editor / owner / admin，其中 admin 仅对 platform_admin 派生 |
| 2 | `outbound_targets.py` 位置 | 实际在 `app/models/project.py` 内 |
| 3 | `app/scripts/seed_admin.py` 未标注 | 应标 **legacy** |
| 4 | defects.ts 前端模板 | severity/status 应为**可选**；用 `api.put` 不是 `api.patch`；`BugUpdate` 应独立于 `project_id` |
| 5 | 不变量 #6 证据路径 | 混淆了「定义点」与「调用点」 |
| 6 | 不变量 #17 证据路径 | 未区分顶层与 legacy scripts |

## 关键约束（17 条不变量的浓缩）

| # | 不变量 |
|---|---|
| 1 | `app/shared/database.py` 是**唯一**的 `declarative_base()` 定义点；`app/models/base.py` 只做再导出 |
| 2 | Alembic `env.py` 必须 import `app.models`，否则 Alembic 看不到新表 |
| 3 | `SessionLocal` 三个参数不能改：`autocommit=False, autoflush=False, expire_on_commit=False` |
| 4 | `API_PREFIX = "/api/v1"` 是唯一挂载点；所有 feature router 通过 `include_router(..., prefix=API_PREFIX)` 挂载 |
| 5 | `notify()` 是 no-throw：内部 swallow 失败不阻塞主流程 |
| 6 | 跨资源越权**统一返 404**（不返 403，避免暴露资源存在性） |
| 7 | 测试库 `testplatform_test` 独立于生产库 `testplatform` |
| 8 | 验证码字符集排除 `0/O/1/I/l`（防混淆）；每个字符单独旋转；一次性使用（用后即删） |
| 9 | `seed_admin` 输出不能泄露密码 / secret |
| 10 | `app/bootstrap/routes.py` 与 `app/main.py` `create_app()` 里 `include_router` 保持同步（前者的 docstring 声明是装配点） |
| 11–17 | 见 [coding-conventions.md §2.4](../coding-conventions.md#L1) |

## 证据

- 完整 17 条不变量与 7 节结构：[docs/coding-conventions.md](../coding-conventions.md)（1081 行，本目录下不复制全文）
- 与本 skill 的关系：编码规范定义"必须遵守什么"（规则），skill 定义"具体怎么操作"（命令 / 流程 / API 速查）；两者互为交叉引用
- v1.1 修正过程：见 [03-ultracode-verification.md](03-ultracode-verification.md)（方法论一致）
