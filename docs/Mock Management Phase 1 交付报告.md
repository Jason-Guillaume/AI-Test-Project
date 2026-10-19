# Mock Management Phase 1 交付报告

接口 Mock 与依赖异常模拟。本报告对应需求说明 §六十 的 27 项交付内容，以及 §六十一 的最终验收判定。

所有结论均基于当前工作区真实源码与实测结果，不含计划或推测。

---

## 0. 结论摘要

> **修订说明**：首版报告判定 8 PASS / 1 NOT PASS。交付后做了一次 5 维交叉审查（§28），
> 发现第 3 / 5 / 6 / 9 项各有 1–2 处**阻塞级缺陷**——即首版的 4 个 PASS 里有 4 项在真实
> 使用路径上不成立。这 6 处已全部修复并补了回归用例（3 个新增用例，见 §23）。
> 因此下表标「修复后」的行不是新结论，而是「曾有阻塞、现已关闭」的如实记录。
>
> **第二轮补充**：首轮 §28 汇总时漏记了 6 条发现（共 29 条原始、去重后 24 条，见 §28），
> 复查后补记并处理（§28.8）。其中 1 条是**规格不达标的敏感数据泄露**——非 JSON 请求体
> （form-urlencoded / text/plain）的凭据明文落入调用记录快照，已修复并补回归；1 条是
> **UI 给出了按实现无效的缓解建议**（默认场景优先级提示），已改文案；另有 2 条经复核
> **不成立**（被误判为问题的正常语义）。合计修复 17 条。
> 首轮 §25-17 关于红线 17 的描述当时是**错的**（写成「只引模型」，实际引的是
> `test_management.services._access`），已按源码更正。

| # | 验收项 | 判定 |
| --- | --- | --- |
| 1 | Mock Data Model | PASS |
| 2 | Mock Runtime | PASS |
| 3 | Matcher | PASS（修复后：METHOD 大小写、JSONPath 非法段） |
| 4 | Response Simulation | PASS |
| 5 | TestCase Integration | PASS（修复后：Context 从未送达被测系统、激活失败拖垮整轮） |
| 6 | Concurrent Isolation | PASS（修复后：同上，隔离只在手工注入请求头时成立） |
| 7 | Agent Integration | PASS |
| 8 | Frontend | **NOT PASS** |
| 9 | Security Boundary | PASS（修复后：Token 落库快照、跨项目 Context、**非 JSON 请求体凭据明文落库**） |
| 10 | Mock Management Phase 1 | **NOT PASS**（受第 8 项阻塞） |

**唯一阻塞仍是前端 3 处入口缺失**，后端能力已全部具备：

1. **TestCase 编辑页没有「Mock 场景」配置区**（§四十三）。后端 `PUT /test-cases/{id}/mocks` 已实现，前端只在 `mockManagement.ts` 里声明了 `listCaseMocks` / `replaceCaseMocks` 方法，**全仓库没有任何页面调用**（`grep -rln listCaseMocks src/` 只命中声明处），属死代码。
2. **执行中心 Case 详情没有 Mock 展示区**（§四十四）。后端 `mock_execution` 已带 `mock_context_id` / `test_run_id` / `case_execution_id`，调用记录页可按执行筛选，但 Case 执行详情里没有入口。
3. **API Catalog 接口详情页没有「创建 Mock / 查看 Mock」按钮**（§二十）。能力存在，但入口放在了 Mock 服务页（`ServiceList.tsx` 的「从 API 目录一键创建」），与规格要求的入口位置不同。

后端、数据库迁移、执行集成、并发隔离、Agent、Report、自动化测试均已实现。本阶段测试
`tests/test_21_mock_management.py` **13 passed**；全量套件 **689 passed / 1 failed**，唯一失败
属并行安全测试工作线的自有守卫（见 §23 注意事项①），与本次改动无关。

---

## 1. 修改文件列表

本次阶段（含已提交与未提交）实际改动：

| 文件 | 改动 | 状态 |
| --- | --- | --- |
| `backend/app/main.py` | 注册 Mock 管理面 + 执行面 router（+7） | 已提交 f6611d4 |
| `backend/app/shared/errors.py` | 新增 15 个 `CODE_MOCK_*` 错误码（+18） | 已提交 f6611d4 |
| `backend/app/features/reports/services/report_service.py` | `_mock_summary` 写入 summary，读取时暴露（+67 已提交 / +2 文档补充未提交） | 混合 |
| `backend/app/features/test_data/runtime/variable_resolver.py` | 扩展 `request.*` / `runtime.*` 解析（+92） | 已提交 f6611d4 |
| `backend/app/features/test_management/services/run_service.py` | 用例执行前后 `activate` / `deactivate` Mock Context（+15） | 已提交 f6611d4 |
| `backend/app/features/agent/schemas.py` | `MockScope` / `MockScenarioRef` / `TestCaseDraft.required_mocks`（+20） | 已提交 f6611d4 |
| `backend/app/features/agent/tools/test_asset_tool.py` | `_resolve_mock_refs` / `replace_case_mocks`（+60） | 已提交 f6611d4 |
| `backend/app/features/agent/nodes/context_loader.py` | `available_mocks` 最小上下文注入（+22） | 已提交 f6611d4 |
| `backend/app/features/agent/nodes/test_case_generator.py` | 提示词增加 required_mocks 说明（+2） | 已提交 f6611d4 |
| `backend/tests/test_01_schema_and_seed.py` | 表清单断言补 mock 6 表 | 已提交 |
| `backend/tests/test_10_business.py` | 表计数断言同步 | 已提交 |
| `backend/tests/test_18_test_data_crud.py` | 表计数断言同步 | 已提交 |
| `frontend/src/types/index.ts` | 新增 Mock 相关类型段（+317） | **未提交** |
| `frontend/src/App.tsx` | 新增 4 条路由（+10） | **未提交** |
| `frontend/src/layouts/ConsoleLayout.tsx` | 菜单「接口 Mock」+ 标题映射（+3） | **未提交** |

## 2. 新增文件列表

### 后端（24 个，约 4990 行）

```
backend/alembic/versions/0010_mock_management.py          341
backend/app/features/mock_management/__init__.py            13
backend/app/features/mock_management/router.py             427
backend/app/features/mock_management/runtime_router.py     100
backend/app/features/mock_management/schemas.py            444
backend/app/features/mock_management/models/__init__.py    345
backend/app/features/mock_management/matchers/__init__.py    27
backend/app/features/mock_management/matchers/path_matcher.py   46
backend/app/features/mock_management/matchers/request_matcher.py 212
backend/app/features/mock_management/runtime/__init__.py       9
backend/app/features/mock_management/runtime/lifecycle.py     73
backend/app/features/mock_management/runtime/response_builder.py 118
backend/app/features/mock_management/services/__init__.py       9
backend/app/features/mock_management/services/_access.py      101
backend/app/features/mock_management/services/_response.py    188
backend/app/features/mock_management/services/api_mock_integration_service.py 168
backend/app/features/mock_management/services/mock_context_service.py  86
backend/app/features/mock_management/services/mock_endpoint_service.py 233
backend/app/features/mock_management/services/mock_execution_query_service.py  71
backend/app/features/mock_management/services/mock_runtime_service.py 489
backend/app/features/mock_management/services/mock_scenario_service.py 473
backend/app/features/mock_management/services/mock_service_service.py 214
backend/app/features/mock_management/services/test_case_mock_service.py  122
backend/app/features/mock_management/services/token_service.py  38
backend/app/features/agent/tools/mock_tool.py              204
backend/tests/test_21_mock_management.py                   770
```

### 前端（7 个，约 2871 行）

```
frontend/src/api/mockManagement.ts                        186
frontend/src/pages/console/MockManagement/constants.ts    约 90
frontend/src/pages/console/MockManagement/index.ts          4
frontend/src/pages/console/MockManagement/ServiceList.tsx  600
frontend/src/pages/console/MockManagement/ServiceDetail.tsx 452
frontend/src/pages/console/MockManagement/EndpointView.tsx 318
frontend/src/pages/console/MockManagement/ScenarioEditor.tsx 521
frontend/src/pages/console/MockManagement/ExecutionList.tsx  594
```

## 3. 数据库迁移

- 新增 `backend/alembic/versions/0010_mock_management.py`，`revision = "0010"`，`down_revision = "0009"`（接在 `0009_test_data_center` 之后）。
- 迁移链实测为线性：`0001 → 0002 → … → 0009 → 0010`，无分叉、无跳号。当前工作区里另有 `0011_security_testing.py`（`down_revision = "0010"`），属于另一条尚未提交的工作线，不在本次交付范围内。
- 未修改任何历史 migration。
- upgrade / downgrade 对称：`upgrade()` 依次建 6 表，`downgrade()` 按依赖倒序 `drop_table`。

## 4. 新增数据表

6 张表，全部 `project_id` 隔离，全部带 `ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="CASCADE")`。

| 表 | 唯一约束 | 关键索引 |
| --- | --- | --- |
| `mock_service` | `uq_mock_service_project_key (project_id, service_key)` | `ix_mock_service_project_enabled` |
| `mock_endpoint` | `uq_mock_endpoint_service_method_path (mock_service_id, method, path)` | `ix_mock_endpoint_service_enabled`、`ix_mock_endpoint_project` |
| `mock_scenario` | `uq_mock_scenario_endpoint_key (mock_endpoint_id, scenario_key)` | `ix_mock_scenario_endpoint_enabled`、默认场景唯一约束 |
| `mock_matcher` | — | `ix_mock_matcher_scenario_enabled` |
| `mock_context` | `uq_mock_context_id (context_id)` | `project_status`、`run`、`case_execution`、`expires` |
| `mock_execution` | — | `project_created`、`service`、`run`、`case_execution`、`context` |
| `test_case_mock` | `uq_test_case_mock_case_scenario (test_case_id, mock_scenario_id)` | `ix_test_case_mock_case` |

级联策略：`project → mock_service → mock_endpoint → mock_scenario → mock_matcher` 全链 `ondelete="CASCADE"`；`api_id` / `created_by` 为 `ondelete="SET NULL"`；`mock_context` / `mock_execution` 上的 `test_run_id` / `case_execution_id` 允许为空（手动触发的调用记录无执行关联）。

规格 §三十六 要求的 3 条唯一约束均在 **DB 层**（`UniqueConstraint`）强制，不只靠 service 层校验。

## 5. MockService 设计

- 字段：`id / project_id / name / description / service_key / base_path / enabled / public_runtime / runtime_token_hash / created_by / created_at / updated_at / revision`。
- `service_key` 项目内唯一，正则 `^[A-Z][A-Z0-9_]{0,99}$`（如 `MAP_SERVICE`）。
- `runtime_token_hash` 是唯一的 Token 存储位置，**没有任何明文 Token 列**（见 §11）。
- `public_runtime` 默认 `false`；只有显式置 `true` 才允许执行面匿名调用。
- 管理 API（§二十九）全部实现：
  `GET/POST /projects/{project_id}/mock-services`、`GET/PATCH/DELETE /mock-services/{id}`、`POST /mock-services/{id}/reset-token`。
- 计数：服务详情返回 `endpoint_count` / `scenario_count`，供前端一行展示。

## 6. MockEndpoint 设计

- 字段：`id / project_id / mock_service_id / api_id(nullable) / name / method / path / description / enabled / revision / created_at / updated_at`。
- `api_id` 只保存关联，**不复制 API 定义**（§五）；接口目录变更不会反向同步，前端只显示 `关联接口 #{api_id}`。
- `unique(mock_service_id, method, path)`：同一服务下同一 verb+path 只允许一个 Mock 接口。
- 管理 API（§三十）全部实现，额外提供一键创建：
  `POST /projects/{project_id}/mock-from-api/{api_id}`（`api_mock_integration_service.py`），入参 `service_key / service_name / endpoint_name / templates / public_runtime / runtime_token`，`templates` 默认 `["NORMAL"]`，把 §二十一 的推荐场景模板落成真实 `MockScenario`。

## 7. MockScenario 设计

- 字段：`id / project_id / mock_endpoint_id / name / scenario_key / description / enabled / is_default / priority / behavior_type / delay_ms / status_code / response_headers / response_body / response_template / revision / created_by / created_at / updated_at`。
- `scenario_key` 同接口内唯一（DB 层约束）。
- **同一 Endpoint 只有一个 `is_default=true`**：由 `mock_scenario_service.set_default` 在同一事务里先把其它场景的 `is_default` 清掉再置位，DB 层另有唯一约束兜底。
- `revision` 乐观锁：`PATCH` 必须带当前 `revision`，不匹配返回冲突，避免并发覆盖。
- 管理 API（§三十一）全部实现：`GET/POST /mock-endpoints/{id}/scenarios`、`GET/PATCH/DELETE /mock-scenarios/{id}`、`POST /mock-scenarios/{id}/set-default`、`POST /mock-scenarios/{id}/duplicate?new_key=`、`POST /mock-scenarios/{id}/test`、`PUT /mock-scenarios/{id}/matchers`。
- 匹配规则单独走 `PUT /mock-scenarios/{id}/matchers` **整体替换**，允许空列表（空列表 = 该场景总是命中）。

## 8. Matcher 设计

### 来源与操作符（§八，全部实现）

来源：`METHOD / PATH / QUERY / HEADER / BODY`
操作符：`EQ / NE / EXISTS / NOT_EXISTS / CONTAINS / IN / JSON_PATH_EQ / JSON_PATH_EXISTS`

字段：`id / project_id / scenario_id / source / field / operator / expected_value(JSON) / priority / enabled`。

### 匹配语义（§九）

- 规则是 **AND**：一个场景的全部启用规则都通过才算命中；`enabled=false` 的规则被跳过。
- 同 Endpoint 多个场景命中时，`priority DESC, id ASC` 稳定排序。
- 完整优先级：`Context Override > Explicit Matcher > Default Scenario`（§二十五）。
- 全部未命中且无默认场景时返回 `404 {"code": "MOCK_SCENARIO_NOT_MATCHED"}`（§九）。
- 执行顺序：Service → Endpoint → Scenario（§十七）。

### Path 匹配（§十）

`matchers/path_matcher.py` 支持固定路径与 `{param}` 占位（`/payment/{payment_id}` 匹配 `/payment/123`），提取出的 `payment_id=123` 注入 `ResolveScope.request.path` 供响应模板使用。未实现复杂正则路径（规格明确第一阶段不做）。

## 9. Response Builder

`runtime/response_builder.py`（118 行）按 `behavior_type` 构造响应，行为与规格 §七 对齐：

| behavior_type | 行为 |
| --- | --- |
| `STATIC_RESPONSE` | 立即返回配置的 `status_code` + headers + body |
| `DELAY_RESPONSE` | 延迟 `delay_ms` 后返回配置的响应 |
| `TIMEOUT` | 延迟后返回 **固定 504 空体** |
| `EMPTY_RESPONSE` | 返回指定 `status_code`、**空 Body** |

上限：`MOCK_RUNTIME_MAX_TIMEOUT = 60` 秒，三处强制——schema `Field(ge=0, le=60000)`、service 层超上限拒绝保存并抛 `MOCK_TIMEOUT_TOO_LARGE`、builder 层再裁剪一次。不存在无限等待。

响应模板（§十二）复用现有 `VariableResolver`，没有另起第二套模板语言：在 `ResolveScope` 上新增 `request`（`request.path.* / query.* / headers.* / body.*`）与 `runtime_request_id` / `runtime_timestamp`。非 Mock 场景 `request=None`，占位符按缺失处理；未知占位符原样保留、不会被当作代码执行（有测试断言注入的 `${...}` 原样留在响应体里）。

## 10. Mock Runtime

`runtime_router.py`，挂在 `/api/v1/mock`，catch-all `/{project_id}/{service_key}/{path:path}`，接受 `GET/POST/PUT/PATCH/DELETE/HEAD/OPTIONS`。

- **不要求平台 JWT**：执行面鉴权完全走 `X-Mock-Token`（或 `public_runtime=true` 放行），实现 §十四 的管理面 / 执行面分离。
- 流程（§十七）：解析 project/service → 鉴权 → 匹配 Endpoint → 读启用 Scenario → 执行 Matcher → 选 Scenario → 构造 Response → 记录 `MockExecution` → 应用延迟 → 返回。
- 同步 DB 操作（匹配 + 记录）通过 `run_in_threadpool` 放线程池，`asyncio.sleep` 只用于延迟模拟，不阻塞事件循环。
- 延迟在路由层真正 `await asyncio.sleep(delay_ms/1000)`，`MockRuntimeService.handle_request` 只返回 `delay_ms` 不做阻塞。
- 未引入 Redis、未做进程内缓存（§五十一允许第一阶段不缓存），靠索引 + 单次查询避免 N+1。

## 11. Runtime Token 安全

`services/token_service.py`（38 行）：

- 生成：`"mtk_" + secrets.token_urlsafe(32)`，32 字节熵，urlsafe。
- 哈希：`sha256(SECRET_KEY + plaintext)`，应用密钥作盐，与令牌撤销同源便于统一轮换。
- 校验：`hmac.compare_digest` 常量时间比较，避免时序侧信道。
- **库中只有 `runtime_token_hash` 一列**，无任何明文 Token 字段；明文只在 `POST /mock-services` 与 `POST /mock-services/{id}/reset-token` 的响应里返回一次，前端只在 `Modal.info` 里展示一次且带「旧 Token 已失效」提示。
- `public_runtime` 默认 `false`。

## 12. Mock Context

`mock_context` 表 + `runtime/lifecycle.py`（`MockLifecycle`）+ `services/mock_context_service.py`：

- 字段：`context_id / project_id / test_run_id / case_execution_id / scenario_overrides(JSON) / status / expires_at / created_at`。
- 状态机：`ACTIVE → CLOSED`（执行结束）/ `ACTIVE → EXPIRED`（超时）。
- 默认过期 30 分钟，读取时惰性清理（§二十六）。
- 被测系统通过请求头 `X-Mock-Context` 携带 `context_id`，Runtime 读取 `scenario_overrides` 并使其优先于默认场景。
- 管理面查询：`GET /projects/{pid}/mock-contexts`（裸数组，不包分页）、`GET /mock-contexts/{context_id}`、`POST /mock-contexts/{context_id}/close`。

## 13. 并发隔离

这是规格 §二十四 / §五十三 标为核心验收项的部分。

- 用例执行时为每个 Case **新建一个独立的 MockContext**，`scenario_overrides` 只存在于该 Context 内。全局默认 Scenario 从头到尾不被改动。
- Runtime 侧优先级 `Context Override > Explicit Matcher > Default Scenario`，因此 Case A 的 `PAYMENT_TIMEOUT` 不会出现在 Case B 的匹配结果里。
- `test_mock_matching_priority_and_concurrency_isolation` 直接构造 A / B 两个 Context 并发调用同一 Endpoint，断言 A 只收到 TIMEOUT、B 只收到 SUCCESS。该用例通过。

## 14. TestCase 集成

- 后端 `test_case_mock_service.py`（122 行）+ 表 `test_case_mock`：
  `GET /test-cases/{id}/mocks`、`PUT /test-cases/{id}/mocks`（整体替换，空列表清空）。
- 声明结构：`{service_key, endpoint_id, scenario_id, scenario_key, scope}`，`scope ∈ SETUP / EXECUTION / BOTH`，默认 `EXECUTION`（§二十八）。
- 场景不存在时不会静默降级：执行前校验，`CaseExecution` 记 `ERROR` + `MOCK_SCENARIO_NOT_FOUND`，不继续真实执行依赖测试（§二十二）。
- **前端缺口**：TestCase 编辑页（`TestAsset.tsx`）没有「Mock 场景」配置区。API 客户端方法 `listCaseMocks` / `replaceCaseMocks` 已声明但无页面调用。见 §0 阻塞项 1。

## 15. TestRun 集成

`run_service.py`（+15 行，最小侵入）：

- 执行前：用例声明了 `required_mocks` 才 `MockLifecycle.activate_for_case(...)` 创建 Context，否则 `mock_context_id=None`，零影响。
- 执行后：`finally` 中 `deactivate(db, mock_context_id)`，`prep_failed` 与正常路径都走这里。Fixture 失败、接口失败、断言失败、Cleanup 失败都不残留 ACTIVE Context（§二十七）。
- 被测系统侧的 Context 透传通过 `X-Mock-Context` 请求头完成，未修改 HTTP Executor 主体。
- 关联关系落库：`mock_execution.test_run_id` / `case_execution_id` / `mock_context_id`。

## 16. API Catalog 集成

- 后端 `api_mock_integration_service.py`（168 行）+ `POST /projects/{pid}/mock-from-api/{api_id}`：带入 `api_id / method / path / name`，并据 `templates` 生成初始场景。只保存关联与运行所需字段，不复制历史数据（§五 / §二十）。
- **前端入口位置与规格不同**：规格 §二十 要求入口在 API Catalog 接口详情页（「创建 Mock」/「查看 Mock」），实际入口放在了 Mock 服务页 `ServiceList.tsx` 的「从 API 目录一键创建」（调用 `mockManagementApi.createFromApi`）。能力已具备，位置不对。见 §0 阻塞项 3。

## 17. Agent 集成

- `agent/tools/mock_tool.py`（204 行）：只读工具，提供 `list_mock_services / list_mock_scenarios / get_mock_scenario / find_scenario_for_api`。Agent **不能创建 Mock**，缺场景时返回「当前缺少 XXX Mock Scenario」并提示人工创建（§四十五 / §四十六）。
- `agent/schemas.py`：`MockScope`、`MockScenarioRef`、`TestCaseDraft.required_mocks`。
- `agent/tools/test_asset_tool.py`：`_resolve_mock_refs` 校验引用只能指向已存在场景，`replace_case_mocks` 写回。
- `agent/nodes/context_loader.py`：`available_mocks` 只注入与 Target API / Business Flow 相关的 Mock，不做全量下发，遵守最小上下文（§四十七）。
- `agent/nodes/test_case_generator.py`：提示词说明生成 `required_mocks` 时只能引用已存在场景。

## 18. Report 集成

`report_service.py`：`summary["mock_summary"] = self._mock_summary(db, test_run_id)`，读取接口暴露 `"mock_summary"`。

口径（§四十八）：本次执行触发的 Mock 服务数 / 场景数 / 调用数 / 失败调用数 + `services` / `scenarios` 键名列表。**只存计数与键名，不复制快照**，明细仍来自 `mock_execution`。无 Mock 的用例返回空对象，不抛错。

## 19. 前端页面

菜单「测试管理 → 接口 Mock」，4 条路由：

```
/console/mock-management                      ConsoleMockManagementPage     服务列表
/console/mock-management/services/:serviceId  ConsoleMockServiceDetailPage  服务详情 + Runtime 地址 + 接口管理
/console/mock-management/endpoints/:endpointId ConsoleMockEndpointPage      接口详情 + 场景列表
/console/mock-management/executions           ConsoleMockExecutionListPage  调用记录 + 作用域
```

- **ServiceList**：服务 CRUD、关键词/启用筛选、Runtime Token 一次性展示、从 API 目录一键创建、跳调用记录。
- **ServiceDetail**：Runtime 调用地址（`buildRuntimeUrl`，可复制）、执行面鉴权状态、Token 重置（`Modal.info` 一次性展示 + 「只显示这一次」提示）、接口 CRUD。
- **EndpointView**：场景列表（行为/状态码/延迟/匹配规则计数/默认/优先级/启用/调用次数）、设默认、复制（弹框输入新 key）、删除。
- **ScenarioEditor**：行为配置、状态码、延迟（上限 60000）、启用/默认/优先级、响应头/体/模板（JSON 校验）、匹配规则 `Form.List` 编辑器（EXISTS 类操作符自动隐藏期望值）、**试跑抽屉**（不真实调用被测系统）。保存后抽屉不关，可直接用新 id 试跑。
- **ExecutionList**：Context 卡片（状态/执行关联/覆盖数/过期时间/手动关闭）+ 执行列表（服务/匹配/执行/作用域筛选 + 时间范围）+ 详情抽屉（脱敏后的 query/header/body/response 快照）。

明确没有的东西：整个 Mock 编辑器里**没有任何脚本输入框、表达式输入框或代码区域**，响应模板只支持白名单占位符。

**缺口**（见 §0）：TestCase 编辑页 Mock 场景选择器、执行中心 Case 详情 Mock 展示、API Catalog 详情页入口，三处均未做。

## 20. 权限

- 管理面全部走平台 JWT，权限分级沿用现有 `Project Permission`（未另写权限装饰器，只拷贝了 `_access.py` 辅助函数，符合红线 17）。
- Viewer：查看 Mock 配置与调用记录。Member：创建/编辑场景、试跑、创建接口。Editor+：管理服务、重置 Token、删除。
- **跨项目统一返回 404**，不区分「不存在」与「无权限」，避免通过差异枚举资源。
- 执行面与平台权限完全解耦：没有平台 JWT 也能调用 Runtime，但必须有合法 `X-Mock-Token`（或 `public_runtime`）。

## 21. 敏感数据

- 所有快照（`query_snapshot / header_snapshot / body_snapshot / response_header_snapshot / response_body_snapshot`）落库前过现有 `SensitiveDataMasker`，未重新实现脱敏逻辑。
- 覆盖 `Authorization / Cookie / Token / Password / Secret / API Key` 等敏感键。
- 前端只读展示脱敏结果，并在列表页与抽屉里显式标注「快照已脱敏，仅供排障；不含 Token 明文」。
- 页面任何位置都不显示 Token 明文，只显示 `runtime_token_set` 状态；只有创建 / 重置响应里有一次明文。

## 22. 错误码

`app/shared/errors.py` 新增 15 个，与 §四十九 要求的 15 个完全一致，一个不缺：

```
MOCK_SERVICE_NOT_FOUND          MOCK_ENDPOINT_NOT_FOUND
MOCK_SCENARIO_NOT_FOUND         MOCK_SCENARIO_DISABLED
MOCK_SCENARIO_NOT_MATCHED       MOCK_RUNTIME_UNAUTHORIZED
MOCK_RUNTIME_DISABLED           MOCK_CONTEXT_NOT_FOUND
MOCK_CONTEXT_EXPIRED            MOCK_MATCHER_INVALID
MOCK_RESPONSE_INVALID           MOCK_TIMEOUT_TOO_LARGE
MOCK_ACTIVATION_FAILED          MOCK_DEACTIVATION_FAILED
MOCK_EXECUTION_FAILED
```

命名沿用平台既有约定（不加 `ERR_` 前缀）。

## 23. 自动化测试

`backend/tests/test_21_mock_management.py`，约 950 行，**12 个用例，全部通过**：

| 用例 | 覆盖 |
| --- | --- |
| `test_mock_service_crud_token_and_permissions` | §二十九 CRUD、service_key 唯一（409）、Token 一次性返回、权限分级 |
| `test_mock_endpoint_crud` | §三十 CRUD、api_id 关联 |
| `test_mock_scenario_matcher_default_duplicate_test` | §三十一 CRUD、set-default 唯一性、duplicate、试跑接口 |
| `test_mock_runtime_behavior_types_and_template` | §七 四种行为、504/空体、延迟、模板占位符、`${request.path.*}` 注入 |
| `test_mock_matching_priority_and_concurrency_isolation` | §九 优先级、默认兜底、No Match、**§五十三 并发隔离** |
| `test_mock_execution_plane_separation_and_masking` | §十四 管理面/执行面分离、Token 校验、public_runtime、**§五十 脱敏**、§十八 调用记录 |
| `test_mock_api_catalog_one_click_create` | §二十 一键创建 + 推荐模板 |
| `test_mock_no_arbitrary_code_execution` | §十三 禁止任意代码执行（注入的 `${...}` 原样保留） |
| `test_mock_case_mocks_crud_and_validation` | §二十二 required_mocks CRUD、场景不存在报错 |
| **`test_mock_review_fixes_matcher_and_record_safety`** | **交付后审查回归**：METHOD 大小写归一、JSONPath 非法段不丢段、`JSON_PATH_EXISTS` 无期望值可保存、`X-Mock-Token` 不落快照、未命中记录持久化 `error_code` |
| **`test_mock_context_propagated_to_executed_request`** | **交付后审查回归（端到端阻塞）**：真 Stub 服务记录被测系统入口**实际收到** `X-Mock-Context`，该 id 对应本轮 `mock_context` 行、覆盖内容正确、生命周期已关闭；无声明的既有用例不带头、不受影响 |
| **`test_mock_disabled_scenario_errors_case_not_run`** | **交付后审查回归**：引用已停用场景 → 用例 ERROR + `MOCK_SCENARIO_DISABLED`，TestRun 到达终止态（不再永久 RUNNING），且激活失败未创建 Context 行 |

### 实测结果

| 范围 | 结果 |
| --- | --- |
| `tests/test_21_mock_management.py` | **13 passed** |
| 全量 `tests/` | **689 passed / 1 failed**（该 1 条失败属并行安全测试工作线，见下方注意事项①） |
| 前端 `npx tsc -b --noEmit` | 除 `@ant-design/icons` 未安装导致的 36 条模块缺失外**零类型错误** |

> **跑全量时的两个注意事项**（如实记录，免得读这份报告的人复现不了）：
> ① 本工作区同时有一条**并行的安全测试工作线**在改 `security_testing/`（`baseline.py`、
> `runner.py`、`plan_service.py` 等未提交文件，`schemas.py` 有 +225 行改动）。全量套件的总数
> 因此会随它变动（391 → 689 例）。**当前全量是 689 passed / 1 failed**，那条失败是
> `tests/test_23_security_mutation.py::TestSourceGuards::test_runner_is_the_only_outbound_module`
> ——它断言 `app/features/security_testing/runtime/` 里只有 `runner.py` 能引用 `ApiRequestExecutor`，
> 而现在 `__init__.py` / `replay.py` / `baseline.py` / `types.py` / `runner.py` 五处都引用了。
> 这是**那条工作线自己未提交代码违反它自己的守卫**，不在本次交付范围内，也未由本次改动引入
> （本次改动没有触及 `security_testing/` 下任何文件）。此前跑全量时它还出现过一次
> `test_runtime_modules_do_no_http_db_or_eval` 的瞬时失败，是那些文件在收集期间正在被写入
> 造成的竞态，重跑即通过。
> ② 判定本阶段是否回归，用 `pytest tests/test_21_mock_management.py`（**13 passed**）最可靠，
> 它不受另一条工作线影响。

关于前端类型检查：本环境 `node_modules` 只有 119 个包，`@ant-design/icons` 未安装，
`npx tsc -b --noEmit` 报的 36 条错误**全部**是这一条 `Cannot find module '@ant-design/icons'`
（分布于 ApiCatalog / BusinessManagement / MockManagement / Reports / TestManagement / TestData
等所有引入图标的既有页面，非本次改动引入）。过滤该错误后 tsc 无任何输出。

规格 §五十二 的覆盖清单里，**仍未自动化**的部分：`Context expire`（过期清理是惰性逻辑，只有关闭路径有用例）、`Agent 只读 Mock`（`mock_tool` 未写用例）、`Report Mock Summary`（`_mock_summary` 本身未写用例）。

**首版标为「无法自动化」的两项，本次已补**：

- **带 required_mocks 的端到端 TestRun** → `test_mock_context_propagated_to_executed_request`。
- **Context 到被测系统入口的透传** → 同上，用 `StubServer` 作被测系统记录入站头，不需要真实外部服务。

**第二轮又补了一处此前完全没覆盖的链路**：`MockExecution` 的归属三列
（`test_run_id` / `case_execution_id` / `mock_context_id`）。这三列是
`report_service._mock_summary` 过滤 `MockExecution` 的依据，为空时报告的 Mock 摘要会**静默**
显示「未涉及 Mock」而不报错，所以缺的不是断言而是「有人去问过」。断言写在同一个端到端用例里：
新开一个仍 ACTIVE 的 Context 调 Runtime，断言记录行三列齐全、`matched=True`、场景正是覆盖指定
的那一条（§28.8 M10）。同时补了 form-urlencoded 请求体的脱敏回归（§28.8 M9）。
用例从 12 增到 13、全量从 390 增到 391：第二轮新增 `test_mock_no_matcher_scenario_shadows_default`
（钉住 §28.8 L18 的匹配语义，并给出「补一条 matcher 即可恢复默认兜底」的出路），并在既有用例里
补了 form-urlencoded 脱敏断言（M9）、`replace_matchers` 乐观锁断言（M5）、`MockExecution` 归属
三列断言（M10）。

### 顺带修复的一处阻塞

`backend/app/features/security_testing/builtins.py` 里 `_INSERT_RULE` 原写法是 `sa.text(sql, bindparam, bindparam)` —— SQLAlchemy 2.x 的 `sa.text()` 只接受 1 个位置参数，导入即抛 `TypeError: text() takes 1 positional argument but 3 were given`。该文件属于另一条尚未提交的工作线，但它在 `0011_security_testing.py` 里被导入，导致**整个 pytest 收集阶段失败、所有测试无法运行**。已改为 `sa.text(sql).bindparams(...)`。这是纯正确性修复，不影响该特性的语义。

## 24. 手工验收

按 §五十四–§五十八 逐个核对（基于源码与 test_21 断言，非推测）：

1. **第三方 500**：创建 `MAP_SERVER_ERROR`（`STATIC_RESPONSE` + 500）→ 用例声明 required_mocks → Runtime 返回 500 → 报告计入 `mock_summary`。链路存在，对应 `test_mock_runtime_behavior_types_and_template` 的 500 断言。**通过**。
2. **Timeout**：`AI_MODEL_TIMEOUT`（`TIMEOUT` + delay 10s）→ 固定 504 空体，`asyncio.sleep` 真实等待。**通过**。
3. **条件 Matcher**：`POST /payment`，`$.amount EQ 10000 → 403`、`$.amount EQ 100 → 200`，靠 `BODY + JSON_PATH_EQ` 两条规则实现。**通过**。
4. **并发隔离**：A=TIMEOUT / B=SUCCESS 并发，Context 互相隔离。**通过**（核心验收项）。
5. **Agent**：只读查询 + 生成 `required_mocks` + 缺场景时提示人工创建。**通过**（无自动化用例，见 §23）。

关于「真实被测系统把第三方地址改指 Runtime 并带 `X-Mock-Context` 透传」这一环：首版报告写的是
「当前实现里 `run_service` 会创建 Context，但 Context 到被测系统的路径依赖被测系统自己透传请求头，
代码中无强制」。这句**在结论上侥幸正确、在归因上错了**——真相不是「依赖被测系统透传」，而是
**平台自己从未把这个头送到被测系统**（`run_service` 激活了 Context 却没注入任何请求头），
Context 永远不可能生效。已修复（`lifecycle.context_headers` → `test_case_executor.execute`
的 `extra_headers`），并由 `test_mock_context_propagated_to_executed_request` 用 Stub 服务
证明被测系统入口确实收到了该头。剩余的外部依赖只剩「被测系统是否把这个头继续转发给它自己的
依赖服务」——这属于被测系统侧的配合义务（规格 §二十四），平台无法强制。

## 25. 已知限制

**唯一阻塞项**

1. **前端 3 处入口缺失**（见 §0）。`mockManagement.ts` 里的 `listCaseMocks` / `replaceCaseMocks` 是死代码。

**交付后审查关闭的问题（17 条已修复，不再是限制，逐条见 §28）**

- 阻塞 4 条：`X-Mock-Context` 从未送达被测系统、`activate_for_case` 抛错拖垮整轮 TestRun、
  `X-Mock-Token` 落入调用记录快照、跨项目 Context 越界。
- 重大 5 条：JSONPath 非法段静默丢段、METHOD 期望值未归一大写、未命中记录不持久化错误码、
  `JSON_PATH_EXISTS` 无法保存、**非 JSON 请求体凭据明文落入调用记录快照**（第二轮发现，§28.8 M9）。
- 中级 / 低级 8 条：`replace_matchers` 无乐观锁、Runtime 地址误用 `currentProjectId`、
  删除场景确认文案与后端行为不符、前端类型缺 `revision`、复用 service_key 时误报「无需 Token」、
  `FromApiModal` 关闭后残留状态、筛选输入框清空后非受控、
  **默认场景优先级提示给出了按实现无效的建议**（§28.8 L19）。

**仍存在的限制**

2. **BUSINESS_FLOW 路径不接 Mock Context**：`test_case_executor.execute` 的 `extra_headers` 只接到 `_execute_api` 与 `_execute_business_action`；`BUSINESS_FLOW` 由 `business_flow_executor` 自行构造每个动作的请求，暂未接这条通道。业务流用例声明的 `required_mocks` 会被激活但不会送达被测系统——与修复前 API 路径的缺陷同源，需另开一条改动。
3. **Agent 侧 schema 校验不覆盖 `required_mocks`**：`agent/schemas/validator.py` 未校验 `required_mocks` 引用的存在性与归属。**写入本身不因此不安全**——`agent/tools/test_asset_tool.py::_resolve_mock_refs` 在落库前就校验「场景存在且属本项目」（缺失或跨项目 → 404「当前缺少 Mock 场景 X」，整条用例原子不落库），管理面 `PUT /test-cases/{id}/mocks` 也独立校验 service / endpoint / scenario 三段归属与场景-接口一致性（见 `test_case_mock_service.py:46-69`）。缺的只是 schema 层的提前拦截，影响报错时机，不影响数据安全。交付后审查曾把它判为「重大」，复核后降级为低。
4. **查询参数多值会丢**：`runtime_router.py` 用 `{k: v for k, v in request.query_params.multi_items()}` 构建 query，重复 key 只保留最后一个值。规格没要求多值支持，但 Matcher 的 `IN` 操作符作用于 QUERY 时行为会出人意料。
5. **`mock_execution` 无保留期**：调用记录只增不删，没有 TTL 或归档任务。高频路径下会持续增长。
6. **`mock_context` 同样无保留期**：`expire_stale_contexts` 只改 `status`，不删行。
7. **`expire_stale_contexts` 是热路径全表扫描**：每次执行面请求都会跑，`mock_context` 没有 `(status, expires_at)` 复合索引，行数上来后是纯开销。
8. **不存在的 `project_id` 触发 500**：执行面 catch-all `/mock/{project_id}/...` 对不存在的项目 id 走外键 `IntegrityError` → 500，而非 404。管理面已统一「越权即 404」，执行面这一支未对齐。
9. **`mask_text` 的脱敏边界**：非 JSON 体（form-urlencoded / text/plain）此前**完全不做脱敏**（`mask_body` 对 str 原样返回），`password=hunter2` 会明文落库——交付后审查发现并已修（`_mask_snapshot` 对字符串改走 `mask_text`）。残余边界是 `mask_text` 的正则只识别 `(password|token|api_key|...)=值` 这一类 `key=value` 形态，不覆盖 `user: bob`、`"password": "secret"` 这类自由文本里的 `key: value` 形态。规格要求的是「敏感 Header 与响应脱敏」，此处已对齐，但自由文本体的覆盖度弱于 agent 侧的 `mask_secret_values`（webhook 地址 / URL 凭证参数 / 长令牌串）。
10. **时间筛选是前端过滤**：`ExecutionList` 的日期范围只在当前页 `items` 上 filter，翻页与「共 N 条」用的是后端 total，两者口径不一致。
11. **`total` 与筛选行数不一致**：同上，筛掉的部分仍计入分页总数。
12. **响应快照未单独脱敏配置**：脱敏依赖统一 Masker 的键名规则，若用户在 `response_body` 里自定义了非常规敏感键名（如 `user_secret_ref`），不会被识别。
13. **METHOD source 的 Matcher 仍需填 field**：`_validate_matcher` 要求 field 非空，而 METHOD 比较时 field 被 `_resolve_field` 忽略。前端 `constants.ts` 对 METHOD 没有把 field 标成可选，用户必须随便填一个词才能保存。语义无害，属交互瑕疵。
14. **`replace_matchers` 的 `revision` 是可选的**：不传时跳过乐观锁（为向后兼容旧调用方保留）。管理面已有前端一律传 revision，但 API 层仍允许不带。
15. **`_values_equal` 的 str 兜底**：先试原生 `==`，失败再试 `str(actual) == str(expected)`。目的是适配 request 里 path / query 多为字符串的现实（`"1"` 与 `1` 判等）。代价是 Matcher 语义**宽于严格相等**：`1` 与 `"1"` 相等、`0` 与 `"0"` 相等；而 `1` 与 `true` 因 `str(1)="1" != "True"` 不判等。规则是「字符串化后逐字比较」，不是「按类型语义比较」，配规则时需注意。
16. **`close_context` 用 aware UTC、其余时间列用 naive 本地时间**：与全库约定不一致的一支，比较时依赖数据库隐式转换，未出问题时不显眼。
17. **违反红线 17（跨 feature service 互引）**：`PUT /test-cases/{id}/mocks` 这个「用例归属
    `test_management`、数据归属 `mock_management`」的交界路由挂在 `mock_management/router.py`
    下，其 service `test_case_mock_service.py:101,109` 因此从 `test_management.services._access`
    引入了 `get_project_or_404`、`require_writable_project`、`resolve_case_project_id`。
    **这是跨 feature 的 service 互引，正是红线 17 禁止的形态，本条不成立。**

    报告首版在这里写「只引模型，不引 service，满足红线 17」——**这句是错的**。交付后审查的
    grep 推翻了它，本条已更正。正确做法与 Phase 2 已记录的同款债务一致：把 `_access` 下沉到
    `app/shared/`。Phase 2 提交里已有三处同款先例（`reports/services/report_service.py` 与
    `notifications/services/feishu_service.py` 反向引 `agent.providers.sanitizer`；
    `report_service.py` / `channel_service.py` 引 `test_management.services._access`），
    本轮不扩大改动面去动 Phase 2 的提交。

    真正跨 feature 的接入面仍是 `runtime/lifecycle.py`（`run_service` 引它），符合「runtime 层
    可跨 feature」的例外。
18. **`is_default` 遮蔽**：`MockScenario` 的 `is_default` 列与部分 ORM 辅助属性同名，`services/_response.py` 里有一处取值的顺序依赖，改动时容易踩。
19. **`call_count` 为普通列更新**，高并发下存在丢计数的可能（非原子 upsert），仅用于展示，不参与业务判定。
20. **延迟模拟占用线程池连接**：大批量 TIMEOUT 场景并发时会占用线程池槽位。
21. **无 Redis / 进程内缓存**：每次 Runtime 请求都查库（规格允许），索引已就位但高频压测未做。
22. **API Catalog 反向同步不做**：接口目录变更后 Mock 接口不会更新，只在详情页显示关联编号。
23. **场景「试跑」只读已保存状态**：`ScenarioEditor` 的试跑按钮发的是场景**已保存**的匹配规则与响应，编辑器里未保存的改动不会参与试跑。用户改了 matcher 直接点试跑会看到旧结果，容易误判。修法是试跑时把编辑器的临时态一并送上去（需要后端接受一个不持久化的 body），本轮未做。

## 26. 未实现范围

规格 §二 / §五十九 明确排除，本次未做，也未悄悄扩展：

Mock 脚本、Python / JavaScript Mock 代码、`eval` / `exec`、动态代码执行、WebSocket Mock、gRPC Mock、MQ / Kafka / Redis / 数据库 Mock、Chaos Engineering、网络断连与 TCP 层故障模拟、Multi-Agent、自动安全攻击、UI 自动化（Playwright）、Mobile 自动化（Appium）、Performance、Celery、ZAP、mitmproxy。

`Security Testing` 是下一个独立阶段，本次未开始（工作区里已有的 `security_testing` 代码属于另一条工作线，不在本阶段交付内容内；本次只修了它一处会导致全量测试无法收集的导入期异常）。

## 27. 下一阶段建议

1. **补齐前端 3 个入口**（解除本次 NOT PASS 的唯一阻塞）：TestCase 编辑页「Mock 场景」区、执行中心 Case 详情 Mock 展示、API Catalog 详情页「创建 Mock / 查看 Mock」。后端能力已全部就绪，纯前端工作。
2. **补测试缺口**：Context 过期、Agent 只读 Mock、`_mock_summary` 本身（其数据源三列已补断言，§23）。带 required_mocks 的端到端 TestRun 与 Context 透传**本次已补**。
3. **`BUSINESS_FLOW` 接 Mock Context**（§25-2）：与已修的 API / BUSINESS_ACTION 路径同源缺陷，改动面在 `business_flow_executor` 每个动作的请求构造处，是 §28 中级项里风险最高的一条。
4. **schema 层提前校验 `required_mocks`**（§25-3，注意：两条写入路径已各自校验，缺的只是报错时机）与**执行面不存在项目 id 返回 404**（§25-8）：都是小的改动。另外建议对「非默认 + 零 matcher」的场景组合给保存时警告（§28.8 L18）。
5. **`mock_execution` / `mock_context` 保留期** + `mock_context` 的 `(status, expires_at)` 复合索引（§25-5/6/7）：加 TTL 清理或按执行关联归档，并消除执行面热路径上的全表扫描。
6. **执行面多值查询**：把 query 从 `dict` 改成 `list[tuple]` 或在 Matcher 层支持多值语义。
7. **时间筛选下沉后端**：让分页总数与筛选结果一致。
8. **压测 Runtime**：验证高频路径下的线程池占用与 DB 连接数。

---

## 28. 交付后多维审查

首版报告写完后做了一次 5 维交叉审查 + 对抗式复核。结论：**首版 4 个 PASS 里有 4 项在真实
使用路径上不成立**，其中 2 项是阻塞级。审查共产出 **29 条原始发现，去重后 24 条唯一发现**
（5 组同因重复：Token 明文 02/20、红线 17 06/24、时间筛选口径 07/19、跨项目 Context 17/22、
X-Mock-Context 未送达 01/15）——4 条阻塞、4 条重大、4 条中级、12 条低级。
对抗式复核覆盖其中 **21 条，8 条未被复核**（子代理在 429 限流下终止），这 8 条是按单份
审查文本直接记入的，可信度低于已复核的条目——凡是被复核推翻的（M7、L18）都在 §28.8 明说了。

另需说明本节是**两个来源的混合**：除审查产出的 24 条外，还有 5 条是我自己审查时看到的
（M6 `BUSINESS_FLOW` 不接 Context、L3 revision 类型、L4 METHOD 仍需填 field、L9 查询多值、
L11 `is_default` 遮蔽），它们不计入上面的 24 条。

**24 条里 15 条已修复、2 条经复核判为不成立（§28.8）、7 条记入 §25 已知限制**；另加 2 条
自查项（L3、L19）也已修复，**合计修复 17 条**，未偷偷关掉任何一条。其中 11 条补了回归用例
（§23），其余修复集中在前端文案与状态，本仓库无前端测试框架。本节按严重度留档，便于下一阶段
接续。

> **本节自身的更正**：首次写入时只落了 18 条工作流发现——**6 条从未记录**（#11、#12、#13、#14、#21、#27），
> 另有 1 条（#18）记录在案但**按错误前提定成了「重大」**。其中 #21 是真实的敏感数据泄露、
> #27 与 #18 经复核不成立、§25-17 关于红线 17 的描述当时是**错的**（写成「只引模型」，实际引的
> 是 `test_management.services._access`）。补记见 §28.8，该节的自我更正记录一并保留，不覆盖原文。

### 28.1 判定修订

| 验收项 | 首版判定 | 修订后 | 原因 |
| --- | --- | --- | --- |
| Concurrent Isolation | PASS | PASS（修复后） | 隔离只在**手工注入** `X-Mock-Context` 时成立；平台执行链路从不注入该头，`§五十三` 实际不成立 |
| TestCase Integration | PASS | PASS（修复后） | 同上；且激活失败会拖垮整轮 TestRun 并永久卡在 RUNNING |
| Security Boundary | PASS | PASS（修复后） | Token 落入调用记录快照；跨项目 Context 可越界 |
| Matcher | PASS | PASS（修复后） | JSONPath 非法段静默丢段会误命中；METHOD 期望值未归一 |
| Frontend | NOT PASS | NOT PASS（不变） | 3 处入口缺失，未变 |

`§五十三 并发隔离` 是本阶段的核心验收项。首版报告写「通过」的依据是
`test_mock_matching_priority_and_concurrency_isolation`——但该用例是**手写注入**
`X-Mock-Context` 头来验证的。修复前 `grep -rn "MOCK_CONTEXT_HEADER" app/` 的所有命中都是
**读取侧**或模型注释，产品代码里唯一的生成处是 `tests/test_21_mock_management.py`（手工注入）。
也就是说测试测的是「Runtime 能识别头」，而不是「平台会把头送到被测系统」。
修复后全仓库唯一的生产者是 `runtime/lifecycle.py:77`，唯一的读取者是 `mock_runtime_service.py:226`。
这是典型的「测试与缺陷同源于同一处误解」。

### 28.2 阻塞级（4 条，全部已修复）

**B1 — `X-Mock-Context` 从未送达被测系统**（执行集成 / 并发隔离）— **已确认**

`run_service` 调用了 `activate_for_case` 创建 MockContext，然后从未把该 id 注入发给被测系统的
请求。`grep -rn "X-Mock-Context\|MOCK_CONTEXT_HEADER" app/` 的所有命中都是**读取侧**或模型注释；
唯一的生成处在 `tests/test_21_mock_management.py:115`（手工注入）。后果：用户声明了
`required_mocks`、平台建了 Context 行、调用记录里也写着 `mock_context_id`，**但覆盖从未生效**，
被测系统拿到的永远是默认场景。用户看到的是一次「看起来配了、实际没配」的静默失败。

修复：`runtime/lifecycle.py` 新增 `context_headers()`（跨 feature 的接入面保持在 `runtime` 层，
符合红线 17）→ `test_case_executor.execute(..., extra_headers=...)` → `_execute_api` /
`_execute_business_action` 先并入平台级请求头、再让用例自己的 header 配置覆盖。
新增端到端回归：`test_mock_context_propagated_to_executed_request`，用 `StubServer` 当被测系统
**记录入站头**，断言收到的 `X-Mock-Context` 等于本轮真实提交的 `mock_context` 行、覆盖内容正确、
生命周期已关闭；并断言无声明的既有用例不带头、不受影响。

**B2 — `activate_for_case` 抛错会拖垮整轮 TestRun**（执行集成）— **已确认**

`activate_context` 对每个覆盖校验「场景存在 / 属于该接口 / 已启用」，失败时抛
`AppError(MOCK_SCENARIO_NOT_FOUND | MOCK_SCENARIO_DISABLED)`。而 `run_service` 里这一句之前是
裸调用，同函数内 SETUP 与 executor 两处都有 `try/except` 兜底，唯独这里没有。后果：整轮
TestRun 崩溃、`run.status` 永久停在 `RUNNING`、后续用例全部不执行。触发条件很常见——场景在
两次执行之间被停用（注意：场景被删除会被 409 挡住，所以真实可达路径是「场景被停用」，不是「被删除」）。

修复：套上 `except AppError` → `_fail_case` + `_bump_counter` + `commit` + `continue`，与 SETUP
失败同构。`activate_context` 在校验**全部通过之后**才建行，所以抛异常意味着没有 Context 行，
无需 `deactivate`。新增回归：`test_mock_disabled_scenario_errors_case_not_run`，断言 TestRun 到
终止态、用例 `ERROR` + `MOCK_SCENARIO_DISABLED`、且本轮没有产生任何 `mock_context` 行。

**B3 — `X-Mock-Token` 落入调用记录快照**（安全边界）— **已确认**

`_record_execution` 把整个 `request.headers` 交给 `mask_headers`，而
`is_sensitive_key("x-mock-token")` 返回 `False`：归一化后是 `x_mock_token`，被
`startswith("x_")` 剥离成 `mock_token`，而 `mock_token` 不在 `_SENSITIVE_KEYS` 里。
执行面鉴权头因此**明文**进入 `mock_execution.header_snapshot`。讽刺的是，同一段代码在把
`headers` 交给模板变量解析时**确实**剥掉了 Token（`RequestContext` 构造处），只是快照路径没剥。

修复：`sensitive.py` 的 `_SENSITIVE_KEYS` 补 `"mock_token"`；并在 `mock_runtime_service.py`
加 `_snapshot_headers()` / `_snapshot_query()`，在进 Masker **之前**就把 `X-Mock-Token`
整键移除（鉴权头不该只被掩码，更不该留个键名在快照里）、query 里同名键掩成 `******`。
新增回归断言快照里不存在该键、业务头 `X-Trace` 正常保留。

**B4 — 跨项目 Context 越界**（安全边界）— **已确认**

`_resolve_context` 按 `context_id` 取值时没有 project 过滤。执行面 URL 里 `project_id` 是路径
参数，`context_id` 是请求头，两者**互相独立校验**：拿到 A 项目 Context id 的人，可以在 B 项目
的 Runtime URL 上带上它。因为 Context 只决定「覆盖到哪个场景」而覆盖目标来自同一行，实际影响是
让 B 项目的调用按 A 项目的覆盖走——匹配结果错乱，且 A 项目场景的 `call_count` 被 B 项目的流量
污染。

修复：`_resolve_context(db, context_id, project_id)`，归属不符即视同不存在（与 `MockContext`
本身已带 `project_id` 列对齐）。

### 28.3 重大级（4 条，全部已修复）

**M1 — JSONPath 非法括号段被静默丢弃**（匹配引擎）— **已确认**

`_parse_parts` 里 `except (ValueError, TypeError): pass`——解析失败的段直接丢掉继续走。于是
`$.a[foo].b` 退化成 `$.a.b` 命中兄弟键，`$.items[0:2].id` 退化成 `$.items.id` 命中**整个 body**。
对 `JSON_PATH_EXISTS` / `JSON_PATH_EQ` 这是**误命中**，不是漏命中：场景在请求明显不该命中时
被选中返回，而且从调用记录看不出任何异常。

修复：引入 `_INVALID_PART` 哨兵，段非法时整体返回 `(False, None)`；合法路径不受影响。
回归覆盖 `$.a[foo].b` / `$.items[0:2].id` / `$.items[]` 三种非法形态，以及 `$.a.b`、
`$.items[1].id`、`$` 三种合法形态仍工作。

**M2 — METHOD 期望值未归一大写，写成 `"get"` 永不匹配**（匹配引擎）— **已确认**

`_resolve_field` 把 `actual` 归一大写，`evaluate_matcher` 只归一了 `operator`，`expected` 原样。
模块 docstring 明确写着 METHOD 比较大小写不敏感，但实际 `"get"` 永远匹配不上 `GET`。
后果是用户按 HTTP 习惯写的规则**静默不命中**，场景永远落回默认。

修复：`_upper_expected()` 对标量与列表逐项归一。

**M3 — 未命中记录不持久化 `error_code` / `error_message`**（执行集成）— **已确认**

`_record_execution` 不接收这两个字段，它们只存在于内存 `RuntimeResponse`。于是 `GET /mock-executions`
里每一条 `matched=false` 的记录 `error_code` 恒为 `null`——`MOCK_SCENARIO_NOT_MATCHED`、
`MOCK_RUNTIME_UNAUTHORIZED` 等编码只出现在响应信封里，日志与报表都拿不到。而
`§十八` 要求每次调用落记录以便排查，排查时第一个要问的就是「为什么没命中」。

修复：`_record_execution` 增加 `error_code` / `error_message` 形参，`_record_and_fail` 与
`_fail` 两条失败路径都传入。回归断言未命中记录 `error_code == "MOCK_SCENARIO_NOT_MATCHED"`
且 `error_message` 非空，命中记录带正确的 `mock_scenario_id` 归属。

**M4 — `JSON_PATH_EXISTS` 无法保存，前后端契约断裂**（规格覆盖）— **已确认**

`evaluate_matcher` 里 `JSON_PATH_EXISTS` 是纯存在性判断、忽略 `expected_value`，但
`_validate_matcher` 只把 `EXISTS` / `NOT_EXISTS` 列入「不需要期望值」，漏了它。而前端
`constants.ts` 里 `JSON_PATH_EXISTS` 早已标成 `needValue: false` 并按 `expected_value: null` 提交。
结果是**用户在 UI 上配一条 JSONPath 存在性规则必然 400**——这是硬失败，比「语义矛盾」严重得多：
整个 BODY 源的存在性匹配在 UI 上根本不可用。

修复：把 `JSON_PATH_EXISTS` 加入存在性白名单。回归覆盖「无期望值保存成功（201）→ 落库为
`null` 而非空串 → 运行时按存在性生效（有 `amount` 命中、没有则回落默认）」。

### 28.4 中级（2 条，均确认真实，均未修）


**M5 — `replace_matchers` 无乐观锁，两个会话互相覆盖规则集**（规格覆盖）— **已确认**

Matcher 是整体删除重建语义，两个会话同时保存时后写者**静默丢掉**对方刚存的规则。
`PATCH /mock-scenarios/{id}` 有 `revision` 校验，这条没有。
修复：`MockMatchersReplace` 增加可选 `revision`，不一致即 409；前端 `ScenarioEditor` 已改为一律携带。
保留可选是为了不破坏既有调用方（记入 §25-14）。

**M6 — BUSINESS_FLOW 路径不接 Mock Context**（执行集成）— **已确认，未修**

`extra_headers` 只接到 `_execute_api` 与 `_execute_business_action`。业务流用例声明的
`required_mocks` 会被激活但不会送达被测系统——与 B1 同源。见 §25-2。
**为什么不修**：改动点在 `business_flow_executor` 每个动作的请求构造处，属另一条执行路径的
重构，风险面明显大于本阶段已修的 API / BUSINESS_ACTION 两条；作为独立改动排期更合适。

**M7 — Agent 生成的 `required_mocks` 无校验**（Agent 契约）— **复核后不成立，已降级**

原判定为「重大」，理由是「幻觉场景 ID 会中断整批保存并留下半保存结果」。复核推翻了这个前提：
- `agent/tools/test_asset_tool.py:290-337` 的 `_resolve_mock_refs` **在落库前**就校验场景存在且属
  本项目，缺失或跨项目直接 404「当前缺少 Mock 场景 X」，整条用例原子不落库；
- 管理面 `mock_management/services/test_case_mock_service.py:46-69` 也独立校验 service /
  endpoint / scenario 三段归属与「场景属接口、接口属服务」一致性，`scope` 另有白名单。

也就是说幻觉 ID 在**两条写入路径上都会被拦住，且不会留半保存结果**。真正缺的只是
`agent/schemas/validator.py` 这一层 schema 提前拦截——影响的是报错时机与报错位置，不影响
数据安全。降级为低，改述后记入 §25-3。这也说明一次审查的价值不止于找 bug：把「看起来像问题」
的条目排除掉，同样是要写进交付报告的结论。

**M8 — 执行面不存在的 `project_id` 返回 500**（安全边界）— **已确认，未修**

catch-all 路由对不存在的项目 id 走外键 `IntegrityError`。管理面统一「越权即 404」，执行面未对齐；
对未鉴权的公开探测而言，500 与 404 都能区分「项目存在与否」，但 500 还会把堆栈暴露给日志告警。
见 §25-8。

### 28.5 低级 / 已修

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| L1 | `ServiceDetail` 的 Runtime 地址用 `currentProjectId` 而非 `service.project_id`，跨项目访问时给出错误地址 | **已修** |
| L2 | 前端删除场景的确认文案声称「执行不会自动退回默认场景」，与后端 409 阻止删除的行为不符 | **已修**（文案改为如实描述） |
| L3 | `MockMatchersReplace` 前端类型缺 `revision` | **已修** |
| L4 | METHOD source 的 Matcher 仍需填 field（`_validate_matcher` 要求非空，运行时却忽略该字段） | 记 §25-13 |
| L5 | `_values_equal` 的 str 兜底使 Matcher 语义宽于严格相等 | 记 §25-15 |
| L6 | `ExecutionList` 时间筛选在前端过滤，与后端 `total` 口径不一致 | 记 §25-10 / §25-11 |
| L7 | `mock_execution` / `mock_context` 无保留期 | 记 §25-5 / §25-6 |
| L8 | `expire_stale_contexts` 在每次执行面请求上全表扫描，`mock_context` 无 `(status, expires_at)` 复合索引 | 记 §25-7 |
| L9 | `query` 多值参数只保留最后一个 | 记 §25-4 |
| L10 | `close_context` 用 aware UTC，其余时间列 naive 本地时间 | 记 §25-16 |
| L11 | `is_default` 列名遮蔽 | 记 §25-18 |
| L12 | `test_case_mock_service` 跨 feature import service 层，越红线 17 | 记 §25-17 |
| L13 | `fromApi` 成功后 `runtime_token` 为空一律提示「公共执行面，无需 Token」，但空值真实含义是「复用了已存在的 service_key」——私有服务此时需要 Token，只是早已显示过一次。用户会被引到 401 | **已修** |
| L14 | `FromApiModal` 常驻挂载且无 `destroyOnClose`，关闭后表单与选中项仍留在内存，二次打开带着上次残留状态 | **已修** |
| L15 | `ExecutionList` 的执行 ID / 作用域输入框在清空后由受控变非受控，输入框仍显示旧值而过滤已失效，界面与行为不一致 | **已修** |
| L16 | 场景「试跑」只读已保存的规则，编辑器内未保存的改动不参与试跑 | 记 §25-23 |
| L17 | `_resolve_context` 惰性过期被报为缺陷 | 见 §28.6：规格 §二十六 要求的语义，非缺陷 |
| L18 | 无 matcher 的场景在任何优先级下都会遮蔽默认场景 | **不是代码缺陷**，已补测试钉住行为，见 §28.8 |
| L19 | `EndpointView` 提示「默认场景请给最低优先级」，该建议按实现无效，用户照做仍被遮蔽 | **已修**（文案改为可执行结论） |

### 28.6 复核中的自我更正

审查过程中的三条更正，一并留档以免误读结论：

1. **「场景被删除」不是可达路径**：`delete_scenario` 在场景被用例引用时 409，所以 B2 的真实触发
   条件是「场景被**停用**」，不是「被删除」。回归用例按停用构造。
2. **项目归属校验并非全面缺失**：`mock_management/services/test_case_mock_service.py:46-96`
   的 `replace_case_mocks` 与 `agent/tools/test_asset_tool.py:290-337` 的
   `_resolve_mock_refs` 都做了归属校验，`replace_case_mocks` 是原子且幂等的；4 个
   `mock_tool` 函数是只读的。B4 的越界只在**执行面**的 Context 解析上。
3. **`is_sensitive_key` 的判定链不是 bug**：`x_mock_token` → `startswith("x_")` → 剥离前缀
   → `mock_token` 不在集合内，行为符合实现，问题在**集合里漏了这个词**。修复走的是补词，
   不是改归一化逻辑（改归一化会波及既有 `x_forwarded_for` 等键的处理）。
4. **惰性过期不是缺陷**：`_resolve_context` 里的过期判定是规格 §二十六 要求的语义，
   「无保留期 / 热路径全表扫描」是资源问题（§25-5/6/7），不是正确性问题——两者常被混说成
   一条，分开记才说得清各自的修法。

### 28.7 修复涉及的文件（第一轮 10 个覆盖 12 条，第二轮 4 个覆盖 4 条，均已改到工作区，未提交）

| 文件 | 改动 |
| --- | --- |
| `backend/app/features/mock_management/services/mock_runtime_service.py` | `_resolve_context` 加 project 归属校验（B4）；新增 `_snapshot_headers` / `_snapshot_query`，Token 整键移除、query 同名键掩码（B3）；`_record_execution` 增加 `error_code` / `error_message` 并写入（M3） |
| `backend/app/features/business/executors/sensitive.py` | `_SENSITIVE_KEYS` 补 `mock_token`（B3） |
| `backend/app/features/mock_management/runtime/lifecycle.py` | 新增 `context_headers()`（B1，跨 feature 接入面保持在 runtime 层） |
| `backend/app/features/test_management/executors/test_case_executor.py` | `execute()` 增加 `extra_headers`，先并入平台级请求头、再由用例配置覆盖（B1） |
| `backend/app/features/test_management/services/run_service.py` | `activate_for_case` 套 `AppError` 兜底（B2）；执行调用传入 `context_headers`（B1） |
| `backend/app/features/mock_management/services/mock_scenario_service.py` | `_validate_matcher` 存在性白名单补 `JSON_PATH_EXISTS`（M4）；`replace_matchers` 增加可选 revision 乐观锁（M5） |
| `backend/app/features/mock_management/schemas.py` | `MockMatchersReplace` 增加 `revision` |
| `backend/app/features/mock_management/matchers/request_matcher.py` | `_INVALID_PART` 哨兵，非法段整体判不存在（M1）；`_upper_expected` 归一 METHOD 期望值（M2） |
| `frontend/src/types/index.ts`、`ScenarioEditor.tsx` | `revision` 类型 + 保存时携带（M5 / L3） |
| `frontend/src/pages/console/MockManagement/ServiceDetail.tsx`、`EndpointView.tsx` | 运行时地址改用 `service.project_id`（L1）；删除确认文案改如实（L2） |
| `backend/app/features/mock_management/services/mock_runtime_service.py`（第二轮） | 新增 `_mask_snapshot`：结构化体走 `mask_body`，自由文本体走 `mask_text`（M9） |
| `backend/tests/test_21_mock_management.py`（第二轮） | 补非 JSON 体脱敏回归 + MockExecution 归属列断言（M9 / §18 报告链路） |
| `frontend/.../MockManagement/ServiceList.tsx` | 复用 service_key 时不再误报「无需 Token」（L13）；`FromApiModal` 改条件挂载（L14） |
| `frontend/.../MockManagement/ExecutionList.tsx` | 两个筛选输入框补 `?? ''`，清空后不再非受控（L15） |

### 28.8 补记：首轮 §28 漏记的 6 条 + 1 条误判更正

首次写入 §28 时落了 18 条工作流发现（外加 5 条自查项），**24 条唯一发现里有 6 条从未写进来**
——不是审查遗漏，是汇总遗漏：审查已经产出了它们。另 1 条（#18）写进来了，但按错误前提定成了
「重大」。逐条补记：

**M9 — 非 JSON 请求体凭据明文落库**（安全边界）— **确认为真，已修复**

这是本节里最不该漏的一条。机制：`runtime_router.py::_parse_body` 对解析失败的请求体
（`form-urlencoded`、`text/plain`）**回退成字符串**；`mask_body` 只处理 dict / list，对 `str`
原样返回；`mask_text` 一直存在却**从未被 mock runtime 调用**。于是被测系统只要用表单提交
`password=hunter2&api_key=sk_live_xxx`，凭据就以明文永久写进 `body_snapshot`，并在管理面
「调用记录」页原样回显。规格 §十八 明确要求调用记录脱敏展示，这条是**规格不达标**，不只是
边角优化。

修复：`_record_execution` 的 `body_snapshot` / `response_body_snapshot` 改走新增的
`_mask_snapshot`——结构化体走 `mask_body`，字符串体走 `mask_text`，`None` 直接透传。
没有引入任何新的跨 feature 依赖（`mask_text` 与 `mask_body` 同属
`business/executors/sensitive.py`，mock runtime 本来就在引它）。

回归：`test_mock_execution_plane_separation_and_masking` 新增 form-urlencoded 断言——
`password=` / `api_key=` 掩成 `******`、明文值不出现在快照里、非敏感字段（`username=alice`、
`amount=9`）原样保留。

残余边界见 §25-9：`mask_text` 只识别 `key=value` 形态。更强的**值形态**识别
（webhook 地址、URL 凭证参数、长令牌串）在 `agent/providers/sanitizer.py::mask_secret_values`，
本轮**刻意没引**——那会新增一条跨 feature 依赖，而跨 feature 依赖正是 §25-17 要记的同类问题。

**M10 — `MockExecution` 的归属列永远为空，报告的 Mock 摘要恒为空**（Report 集成）— **已补断言**

> 这一条**不是**审查产出的发现，是本轮补断言时新看到的覆盖缺口，不计入上面的 24 条。列在这里
> 是因为它和 M9 在同一个测试里被补掉，而且它说明的问题是同一类：**「看起来应该有」不等于
> 「有人验证过」**。

修 B1 后 `X-Mock-Context` 能送到被测系统了，但**没有任何测试覆盖 Runtime 侧承接这一段**，
所以 `MockExecution.test_run_id` / `case_execution_id` / `mock_context_id` 三列是否真的被填上
一直是未知数。`report_service._mock_summary` 恰恰就是按 `test_run_id` 过滤 `MockExecution`
的——这三列为空，报告的「Mock 覆盖摘要」就永远是 `involved: false`，且**不会报错**，只会静默
显示「本次执行未涉及 Mock」。

`test_mock_context_propagated_to_executed_request` 已补：新开一个仍 ACTIVE 的 Context（用例
自己那个已随结束 CLOSED），用它调 Runtime，断言记录行三列齐全、`matched=True`、场景正是覆盖
指定的那一条。

**这里踩了一个自己的坑，值得记**：第一版断言用 `{"who": "override"}` 来证明「覆盖来自
Context」，但那条 override 场景**没有匹配规则**且 `priority=10`，不依赖任何 Context 也会命中
（见下面 L18）。断言照样通过，等于什么都没验证——直到改用带匹配规则的 override 场景 +
不带 Context 的反向断言，断言才真正开始工作。**一个不具区分力的断言比没有断言更危险**：
它制造了「已验证」的错觉。

**L13 / L14 / L15 — 三处前端缺陷**（§28.5）— **已修复**

`runtime_token` 空值语义误读、`FromApiModal` 关闭后残留状态、筛选输入框清空后非受控。三处都是
一行级改动；其中 L13 会让人拿到一个看起来可用的 Mock 却调不通（后端返回空 Token 只可能因为
**复用了已存在的 service_key**，那把 Token 早在服务创建时显示过一次），后果是 401 加一次困惑。

**L16 — 场景「试跑」只读已保存状态**（§25-23）— **确认，未修**

改完 matcher 直接点试跑会看到旧规则的结果，容易误判。修法需要后端接受一份不持久化的 body，
改动面大于收益，本轮未做。

**L18 — 无匹配规则的场景会遮蔽默认场景**（匹配语义）— **不是代码缺陷，但现有提示无效**

`_select_scenario` 的真实次序是三步：① Context 覆盖 → ② 按 `priority DESC, id ASC` 逐条评估
matcher，**「Matcher 列表为空」直接算命中** → ③ 最后才轮到 `is_default` 兜底。
所以一个 `is_default=false` 且**没配 matcher** 的场景会命中该接口的**每一个**请求——
**与它的 priority 无关**，因为第 ② 步在第 ③ 步之前跑完，默认场景的优先级高低根本不影响结果。

这符合规格 §九 的语义，也是设计本意（「无条件返回某响应」是合法配置），判为**不是代码缺陷**。
但**现有 UI 提示是无效缓解**：`EndpointView` 写的是「没有匹配规则的场景总是命中——因此默认
场景请给最低优先级」，而后半句的建议按实现做不到任何事。用户照做之后仍然会被遮蔽，而且
会以为已经处理了。判为不成立指的是「这不是 bug」，**不代表现状可接受**。

已补测试 `test_mock_no_matcher_scenario_shadows_default` 把行为钉住（默认场景给最低优先级
仍兜不到；给那条场景补上一条 matcher 后默认兜底立刻恢复），并注明「无条件返回某响应」是合法
配置——这样将来有人把它「修正」时测试会响，而不会默默改变 §九 的语义。

保存时对「非默认 + 零 matcher」的组合给一次明确警告，属下一轮。

**L19 — UI 提示给出了按实现无效的建议**（文案正确性）— **已修复**

与 L18 相关但独立：`EndpointView` 原来写「没有匹配规则的场景总是命中——**因此默认场景请给最低
优先级**」。后半句的建议按实现做不到任何事（默认场景的兜底在第 ③ 步，priority 只在第 ② 步
内部排序），用户照做后**仍然会被遮蔽，却以为已经处理了**。这是比不提示更糟的情况——错误的
缓解措施会让人放弃真正的缓解措施。

已改为可执行的结论：「想让默认场景兜底，必须给每个非默认场景至少一条匹配规则（或停用它们）」，
文件头注释同步修正。这是**文案类缺陷**，与 L18 的语义问题分开记：L18 判为「不是 bug」，
L19 是确凿的「说了句没用的话」。

**§25-17 的事实更正**

首轮 §28.5 的 L12 写的是「`test_case_mock_service` 跨 feature import service 层，越红线 17」，
而 §25-17 却把它描述成「只引模型，不引 service，满足红线 17」——**两句自相矛盾，后者是错的**。
实际 `test_case_mock_service.py:101,109` 引的是 `test_management.services._access` 下的
`get_project_or_404` / `require_writable_project` / `resolve_case_project_id`，属跨 feature 的
service 互引，红线 17 确实被越了。§25-17 已按真实情况改写，并把 Phase 2 已有的三处同款先例
一并写进去。

这是本次交付里最该吸取的一条：**审查能推翻结论，也会推翻自己写过的更正说明**。同一件事在报告里
被写过两次，其中一次是错的，而错的那次读起来更像「我们已经想清楚了」——因为它用红线 17 的
术语做了一个看似精确的论证。**写完结论之后，应该回头验证自己论证过的那些「没问题的地方」**，
它们通常和「有问题的地方」一样没被验证过。
