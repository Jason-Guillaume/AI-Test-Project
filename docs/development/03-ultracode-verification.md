# Ultracode 验证发现的事实错误

v1.0 skill 写完用 Ultracode Workflow 并行跑了 **12 个 verifier agent** 对代码库做交叉核对。抓到 **11 处**原稿错误并全部改正。命中率约 55%（11/20 项高风险声明）。

## 事实错误清单（v1.0 → v1.1）

| # | 原稿错误 | 实际 | 涉及位置 |
|---|---|---|---|
| 1 | Auth：`DELETE /logout` | `POST /logout`（204，无 body） | SKILL.md §8 |
| 2 | Defects：`GET /projects/{id}/bugs` 嵌套路由 | **不存在**；用 `GET /bugs?project_id=X` query param | SKILL.md §8 |
| 3 | Projects：`outbound-targets` 路径段 | 实际 `/targets` | SKILL.md §8 |
| 4 | ModelConfigs：`POST /model-configs/validate` | **不存在**（只有内部 service 方法） | SKILL.md §8 |
| 5 | ModelConfigs：`PATCH /model-configs/{id}/default` | `POST /model-configs/{config_id}/set-default` | SKILL.md §8 |
| 6 | Environments：`/{id}` 路径参数 | 实际按 `/{name}` 定位 | SKILL.md §8 |
| 7 | Environments：upsert 语义 | **无 upsert**；默认环境走 `POST .../set-default`；DELETE 默认环境会 400 拒绝 | SKILL.md §8 |
| 8 | Environments：`GET /environments/{id}/headers` 子路由 | **不存在**；headers 走 create/update schema | SKILL.md §8 |
| 9 | Dashboard：`GET /dashboard/summary` | 实际 `GET /dashboard/overview` | SKILL.md §8 |
| 10 | Health：`/api/v1/healthz` 与 `/api/v1/ready` | **两者都不存在**；实际 `/healthz`（根路径，不带 API_PREFIX）和 `/api/v1/dashboard/ready`（需登录） | SKILL.md §4 / §8 / §10 |
| 11 | 限流：登录 5/min、注册 3/min | 实际 **登录 60/min（IP）+ 10/min（username）**；**注册 10/小时**；数字来自 `config.py`，不是硬编码在 `rate_limit.py` | SKILL.md §9.3 |

## 验证方法

| 环节 | 做法 |
|---|---|
| 阶段 | 先写再验（不是先验再写） |
| 侦察 | 4 个并行 scout agent 收集事实 → 合成 v1.0 |
| 验证 | Ultracode Workflow 并行 12 个 verifier agent 对代码库核对关键声明 |
| 覆盖 | 12 项关键声明 × 每项 grep / 读源码比对 → 11 项抓到错误 |
| 修正 | 全部改正 → v1.1 |

## 方法论收获

**Ultracode 的"先写再验"比"边写边猜"更可靠**——v1.0 里凡是没直接读过代码就写下的路径 / 数字全部在验证阶段被抓出来。

**后续开发文档一律按这个模式**：写 → 并行核对 → 修正。

## 附带发现（不列入 11 处错误清单，但已记入规范）

1. `auth.py` 里有个陈旧 docstring，声称的路由前缀 `/api/v1/auth` 与 `/api/v1/users/me` 均**不存在**——真实路由是 `/api/v1/auth/*` 与 `/api/v1/me*`
2. `test_07_schema_gate.py:40` 断言的是裸 `/healthz` 路径（不带 `/api/v1` 前缀）——这佐证了 `/healthz` 与 `/health` 是在根路径注册的
3. 路径参数命名统一为 `{xxx_id}` 后缀（`bug_id` / `project_id` / `member_id` / `target_id` / `organization_id` / `config_id` / `user_id`），**不是** `{id}`——已同步到 SKILL.md §8

## 证据

- Ultracode workflow journal：`.claude/projects/-Users-a1-Desktop-ai-test-project/…/subagents/workflows/wf_7802bfbc-af6/journal.jsonl`（12 个 verifier agent 完整返回值）
- v1.0 → v1.1 完整 diff：见 `.claude/skills/develop-this-project/SKILL.md` 文末「v1.0 → v1.1 修正」块
- 决策背景：见 [04-key-decisions.md](04-key-decisions.md) §5.2「为什么 Ultracode 验证放在写完之后」
