"""验收项 20：测试数据中心 Phase C —— 用例 / Run 生命周期闭环。

覆盖 §12–§18 的四个验收场景 + Setup / Cleanup 失败语义 + Agent 引用边界：

- 场景一：接口造数 → BUSINESS_ACTION 引用变量；输出 task_id；断言引用变量；Cleanup 被调用
- 场景二：DATABASE_PATCH 改特殊状态（affected_rows 可断言）；表 / 环境白名单失败 → 用例 ERROR
- 场景三：FAKER phone / email 来自白名单生成器，取两次不相等，且不出现配置字面值
- 场景四：RUN 共享 —— 20 条用例，RUN Fixture 只生成一次、只清理一次
- Setup 失败 → 用例 ERROR（不是 FAILED），run.error +1 而 run.failed 不变
- Cleanup 失败 → 原断言错误码仍在；PASSED 仍是 PASSED 且 cleanup_status=FAILED
- 项目隔离：造数记录只属于本次运行的项目与环境，其他项目查不到
- Agent：required_fixtures 落 test_case_fixture；缺 Fixture 明确提示且不创建 Provider / 不执行 SQL

HTTP 用 StubServer（127.0.0.1 环回）+ 项目出站白名单；数据库场景用测试夹具自身的库。
"""

from __future__ import annotations

import json

from sqlalchemy import text

from tests.conftest import unique
from tests.test_15_test_executor import (
    StubServer,
    _add_action,
    _add_binding,
    _add_mapping,
    _add_output_var,
    _build_plan_with_cases,
    _case_execs,
    _create_case,
    _run,
)
from tests.test_19_data_factory import (
    _create_project,
    _bind_env,
    _db_connection,
    _db_policy,
    _dev_env,
    _make_fixture,
    _make_provider,
    _step,
    _stub_env,
    _task_seed_row,
    _task_status,
)

API = "/api/v1"


# --------------------------------------------------------------------------- 公共辅助


def _declare_fixtures(api, admin, case_id, *fixture_keys):
    """声明用例所需 Fixture（后端按数组顺序重排 sort）。"""
    r = api.put(
        f"/test-cases/{case_id}/fixtures", username=admin,
        json={"fixtures": [{"fixture_key": k, "sort": i} for i, k in enumerate(fixture_keys)]},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _add_data(api, admin, case_id, *, name, source_type, config=None, required=True, sort=0):
    """新增一条测试数据（FIXTURE / FAKER 走 config_json，value 留空）。"""
    r = api.post(
        f"/test-cases/{case_id}/data", username=admin,
        json={
            "name": name, "value_type": "STRING", "value": None,
            "source_type": source_type, "config_json": config,
            "required": required, "sort": sort,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


def _data_executions(db, *, test_run_id=None, scope=None):
    """查询项目的造数执行记录。"""
    from app.features.test_data.models.execution import DataExecution

    query = db.query(DataExecution)
    if test_run_id is not None:
        query = query.filter(DataExecution.test_run_id == test_run_id)
    if scope is not None:
        query = query.filter(DataExecution.scope == scope)
    return query.all()


def _provider_executions(db, data_execution_id):
    """查询造数步骤的提供器执行记录。"""
    from app.features.test_data.models.execution import ProviderExecution

    return (
        db.query(ProviderExecution)
        .filter(ProviderExecution.data_execution_id == data_execution_id)
        .all()
    )


def _status_code_assertion(expected="200", sort=0):
    """构造 HTTP 状态码断言配置。"""
    return {
        "assertion_type": "STATUS_CODE", "operator": "EQ",
        "expected_value": expected, "required": True, "sort": sort,
    }


def _sandbox_count(db):
    """统计沙箱任务记录数量。"""
    return db.execute(text("SELECT count(*) FROM td_sandbox_task")).scalar()


# --------------------------------------------------------------------------- 场景一


class TestScenarioOneApiThenBusinessAction:
    """接口造数 → API 创建任务 → BUSINESS_ACTION 运行任务；Cleanup 被调用。"""

    def test_fixture_output_feeds_api_and_action(self, api, admin, db):
        """验证固定数据输出`feeds`API和动作场景及其预期结果。"""
        with StubServer() as stub:
            task_bodies: list[dict] = []
            deleted: list[str] = []
            stub.add_fn("POST", "/projects",
                        lambda h, body: (200, {"code": 0, "data": {"id": 555}}))
            stub.add_fn("POST", "/tasks",
                        lambda h, body: (task_bodies.append(json.loads(body))
                                         or (200, {"code": 0, "data": {"task_id": 8801}})))
            stub.add_fn("POST", "/tasks/555/run",
                        lambda h, body: (200, {"code": 0, "data": {
                            "task_id": 8801, "status": "RUNNING"}}))
            stub.add_fn("DELETE", "/projects/555",
                        lambda h, body: (deleted.append(h.path) or (200, {"code": 0, "message": "deleted"})))
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)

            project_iface = iface("POST", "/projects", "创建项目")
            task_iface = iface("POST", "/tasks", "创建任务")
            run_iface = iface("POST", "/tasks/{id}/run", "运行任务")

            # 夹具：创建项目，输出 project_id；带 API 清理句柄（DELETE 已建项目）。
            project_fixture = _make_fixture(
                api, admin, pid, key="ACTIVE_PROJECT", cleanup_policy="AFTER_CASE",
                steps=[_step("API", 10, name="创建项目", config={
                    "api_id": project_iface,
                    "input_mappings": [
                        {"target": "owner", "location": "BODY", "expression": "${faker.name}"},
                    ],
                    "output_mappings": [{"name": "project_id", "expression": "$.data.id"}],
                    "cleanup": {"method": "DELETE", "path": "/projects/${fixture.ACTIVE_PROJECT.project_id}"},
                })],
                outputs=[{"name": "project_id", "value_type": "INTEGER",
                          "source_path": "project_id", "sort": 1}],
            )

            # 用例一：API 创建任务，body 由 FIXTURE + FAKER 数据项组成，断言引用输出变量。
            case_api = _create_case(
                api, admin, pid, name=unique("创建任务-引用夹具输出"),
                api_id=task_iface,
                assertions=[
                    _status_code_assertion("200", 0),
                    {"assertion_type": "JSON_PATH", "path": "$.data.task_id",
                     "operator": "EXISTS", "expected_value": None,
                     "required": True, "sort": 1},
                ],
            )
            _declare_fixtures(api, admin, case_api, "ACTIVE_PROJECT")
            _add_data(api, admin, case_api, name="project_id", source_type="FIXTURE",
                      config={"fixture_key": "ACTIVE_PROJECT", "output": "project_id"}, sort=0)
            _add_data(api, admin, case_api, name="title", source_type="FAKER",
                      config={"generator": "name", "locale": "zh_CN"}, sort=1)

            # 用例二：BUSINESS_ACTION 运行任务，路径变量来自同一夹具输出。
            from app.features.business.models.business_domain import BusinessDomain
            from app.features.business.models.business_flow import BusinessFlow

            domain = BusinessDomain(project_id=pid, name=unique("domain"), status="ACTIVE")
            db.add(domain)
            db.flush()
            flow = BusinessFlow(project_id=pid, domain_id=domain.id,
                                name=unique("flow"), status="ACTIVE")
            db.add(flow)
            db.flush()
            action = _add_action(db, flow.id, "运行任务", "RUN_TASK", 10)
            binding = _add_binding(db, action.id, run_iface)
            _add_mapping(db, binding.id, "INPUT", "task_id", "PATH", field="id")
            _add_output_var(db, action.id, "task_id")
            db.commit()

            case_action = _create_case(
                api, admin, pid, name=unique("运行任务-业务动作引用变量"),
                target_type="BUSINESS_ACTION", business_action_id=action.id,
                assertions=[
                    _status_code_assertion("200", 0),
                    {"assertion_type": "JSON_PATH", "path": "$.data.status",
                     "operator": "EQ", "expected_value": "RUNNING",
                     "required": True, "sort": 1},
                ],
            )
            _declare_fixtures(api, admin, case_action, "ACTIVE_PROJECT")
            _add_data(api, admin, case_action, name="task_id", source_type="FIXTURE",
                      config={"fixture_key": "ACTIVE_PROJECT", "output": "project_id"}, sort=0)

            plan_id = _build_plan_with_cases(api, admin, pid, [case_api, case_action], env_id)
            run = _run(api, admin, plan_id, env_id)

            assert run["total"] == 2 and run["passed"] == 2, run
            assert run["error"] == 0 and run["failed"] == 0, run

            execs = {e["test_case_id"]: e for e in _case_execs(api, admin, run["id"])}
            api_case = execs[case_api]
            action_case = execs[case_action]
            assert api_case["status"] == "PASSED", api_case
            assert action_case["status"] == "PASSED", action_case

            # API 用例：输出 task_id 断言通过；请求体里 project_id 来自夹具输出、title 是 FAKER 生成值。
            assert all(a["passed"] for a in api_case["assertion_results"]), api_case["assertion_results"]
            assert len(task_bodies) == 1, task_bodies
            body = task_bodies[0]
            assert body["project_id"] == 555, body
            assert body["title"] not in ("title", "name"), f"必须是生成值：{body!r}"

            # 上下文快照记录了注入的数据值（不记录夹具原始任务 ID 之外的运行时值）。
            assert api_case["context_json"]["data"]["project_id"] == 555

            # 业务动作用例：路径变量确实来自夹具输出。
            assert all(a["passed"] for a in action_case["assertion_results"])
            assert action_case["request_snapshot"]["url"].endswith("/tasks/555/run")

            # Cleanup 被调用：两条 CASE 夹具各清一次。
            db.expire_all()
            case_execs = _data_executions(db, test_run_id=run["id"], scope="CASE")
            assert len(case_execs) == 2, [e.scope for e in case_execs]
            assert {e.cleanup_status for e in case_execs} == {"SUCCESS"}, [
                (e.cleanup_status, e.cleanup_error_message) for e in case_execs]
            assert len(deleted) == 2, deleted

            # 清理句柄拿到的是本次生成的 project_id，不是别的任务 ID。
            assert deleted[0] == "/projects/555" and deleted[1] == "/projects/555", deleted
            assert project_fixture["fixture_key"] == "ACTIVE_PROJECT"


# --------------------------------------------------------------------------- 场景二


class TestScenarioTwoDatabaseSpecialState:
    """DATABASE_PATCH 改特殊状态；白名单之外 → 用例 ERROR。"""

    def test_patch_status_is_assertable(self, api, admin, db):
        """验证局部更新状态是否`assertable`场景及其预期结果。"""
        from tests.test_15_test_executor import _admin_id, _make_env, _make_iface, _whitelist

        with StubServer() as stub:
            stub.add("GET", "/health", 200, {"code": 0, "data": {"affected_rows": 1}})
            pid = _create_project(api, admin)
            # 造数连接和这次运行必须是同一个环境，否则会先报环境不一致。
            env_id = _make_env(db, stub.base_url, _admin_id(db), name=unique("dev-db"))
            _bind_env(db, pid, env_id)
            _whitelist(db, pid, stub.port, _admin_id(db))
            conn_id = _db_connection(api, admin, pid, env_id)
            _db_policy(api, admin, pid, env_id, ["td_sandbox_task"], ["UPDATE"])

            seed_id = _task_seed_row(db, status="PENDING")
            provider = _make_provider(
                api, admin, pid, provider_type="DATABASE_PATCH",
                config_json={
                    "connection_id": conn_id, "table": "td_sandbox_task",
                    "operation": "UPDATE", "values": {"status": "FAILED"},
                    "where": {"id": seed_id},
                },
            )
            _make_fixture(
                api, admin, pid, key="FAILED_TASK",
                steps=[_step("DATABASE_PATCH", 10, name="改特殊状态", provider_id=provider["id"])],
                outputs=[{"name": "affected_rows", "value_type": "INTEGER",
                          "source_path": "affected_rows", "sort": 1}],
            )

            case_id = _create_case(
                api, admin, pid, name=unique("特殊状态-断言受影响行数"),
                api_id=_make_iface(db, pid, "GET", "/health", "健康检查"),
                assertions=[
                    _status_code_assertion("200", 0),
                    {"assertion_type": "JSON_PATH", "path": "$.data.affected_rows",
                     "operator": "EQ", "expected_value": "1",
                     "required": True, "sort": 1},
                ],
            )
            _declare_fixtures(api, admin, case_id, "FAILED_TASK")
            _add_data(api, admin, case_id, name="affected_rows", source_type="FIXTURE",
                      config={"fixture_key": "FAILED_TASK", "output": "affected_rows"}, sort=0)

            plan_id = _build_plan_with_cases(api, admin, pid, [case_id], env_id)
            run = _run(api, admin, plan_id, env_id)
            assert run["passed"] == 1 and run["error"] == 0, run

            execs = _case_execs(api, admin, run["id"])
            assert execs[0]["status"] == "PASSED", execs[0]
            assert all(a["passed"] for a in execs[0]["assertion_results"]), execs[0]
            assert execs[0]["context_json"]["data"]["affected_rows"] == 1

            # 特殊状态真的落在被测库上。
            assert _task_status(db, seed_id) == "FAILED"

    def test_non_whitelisted_table_marks_case_error(self, api, admin, db):
        """验证`non``whitelisted``table``marks`用例错误场景及其预期结果。"""
        with StubServer() as stub:
            stub.add("GET", "/health", 200, {"code": 0, "data": {}})
            # 连接、策略和这次运行必须是同一个环境，否则会先报环境不一致。
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            conn_id = _db_connection(api, admin, pid, env_id)
            _db_policy(api, admin, pid, env_id, ["td_sandbox_task"], ["UPDATE"])

            provider = _make_provider(
                api, admin, pid, provider_type="DATABASE_PATCH",
                config_json={
                    "connection_id": conn_id, "table": "environment",
                    "operation": "UPDATE", "values": {"is_active": False},
                    "where": {"id": 1},
                },
            )
            _make_fixture(
                api, admin, pid, key="OUTSIDE_TABLE",
                steps=[_step("DATABASE_PATCH", 10, name="越界表", provider_id=provider["id"])],
                outputs=[{"name": "affected_rows", "value_type": "INTEGER",
                          "source_path": "affected_rows", "sort": 1}],
            )

            case_id = _create_case(
                api, admin, pid, name=unique("越界表-造数失败"),
                api_id=iface("GET", "/health", "健康检查"),
                assertions=[_status_code_assertion("200", 0)],
            )
            _declare_fixtures(api, admin, case_id, "OUTSIDE_TABLE")

            plan_id = _build_plan_with_cases(api, admin, pid, [case_id], env_id)
            run = _run(api, admin, plan_id, env_id)

            # 造数失败是 ERROR，不是 FAILED：断言从未执行。
            assert run["error"] == 1 and run["failed"] == 0, run
            execs = _case_execs(api, admin, run["id"])
            assert execs[0]["status"] == "ERROR", execs[0]
            assert execs[0]["error_code"] == "DATABASE_TABLE_NOT_ALLOWED", execs[0]
            assert execs[0]["assertion_results"] in ([], None), execs[0]
            # 环境表原样不动。
            assert _sandbox_count(db) is not None
            assert db.execute(
                text("SELECT count(*) FROM environment WHERE is_active = false")
            ).scalar() == 0


# --------------------------------------------------------------------------- 场景三


class TestScenarioThreeFakerWhitelist:
    """FAKER 数据项：白名单生成器，两次取值不相等，且不出现字面值。"""

    def test_faker_values_are_generated_and_unique(self, api, admin, db):
        """验证`faker``values`是否为`generated`和`unique`场景及其预期结果。"""
        with StubServer() as stub:
            captured: list[dict] = []
            stub.add_fn("POST", "/users",
                        lambda h, body: (captured.append(json.loads(body))
                                         or (200, {"code": 0, "data": {"id": 1}})))
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            user_iface = iface("POST", "/users", "创建用户")

            case_ids = []
            for i in range(2):
                case_id = _create_case(
                    api, admin, pid, name=unique(f"随机用户-{i}"),
                    api_id=user_iface,
                    assertions=[_status_code_assertion("200", 0)],
                )
                _add_data(api, admin, case_id, name="phone", source_type="FAKER",
                          config={"generator": "phone", "locale": "zh_CN"}, sort=0)
                _add_data(api, admin, case_id, name="email", source_type="FAKER",
                          config={"generator": "email", "locale": "zh_CN"}, sort=1)
                case_ids.append(case_id)

            plan_id = _build_plan_with_cases(api, admin, pid, case_ids, env_id)
            run = _run(api, admin, plan_id, env_id)
            assert run["passed"] == 2 and run["error"] == 0, run

            execs = _case_execs(api, admin, run["id"])
            bodies = sorted(captured, key=lambda b: b.get("phone", ""))
            assert len(bodies) == 2, bodies
            for body in bodies:
                assert body["phone"] not in ("phone", "13800138000"), body
                assert body["email"] not in ("email", "a@b.c"), body
                assert "@" in body["email"], body

            # 两次取到的值不相等：FAKER 不复用上一次的结果。
            assert bodies[0]["phone"] != bodies[1]["phone"], bodies
            assert bodies[0]["email"] != bodies[1]["email"], bodies

            # 执行记录里的值一样是两个不同值。
            data = sorted(
                ((e["context_json"]["data"]["phone"], e["context_json"]["data"]["email"])
                 for e in execs),
            )
            assert data[0] != data[1], data


# --------------------------------------------------------------------------- 场景四


class TestScenarioFourRunScopeShared:
    """RUN 作用域夹具：20 条用例只生成一次、只清理一次。"""

    def test_run_scope_fixture_generated_once(self, api, admin, db):
        """验证运行范围固定数据`generated``once`场景及其预期结果。"""
        with StubServer() as stub:
            generated: list[dict] = []
            deleted: list[str] = []
            stub.add_fn("POST", "/users",
                        lambda h, body: (generated.append(h.path)
                                         or (200, {"code": 0, "data": {"user_id": 9}})))
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"task_id": 1}})
            stub.add_fn("DELETE", "/users/9",
                        lambda h, body: (deleted.append(h.path) or (200, {"code": 0})))
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)

            _make_fixture(
                api, admin, pid, key="NORMAL_USER", scope="RUN",
                cleanup_policy="AFTER_RUN", cache_enabled=True,
                steps=[_step("API", 10, name="创建用户", config={
                    "api_id": iface("POST", "/users", "创建用户"),
                    "output_mappings": [{"name": "user_id", "expression": "$.data.user_id"}],
                    "cleanup": {"method": "DELETE", "path": "/users/${fixture.NORMAL_USER.user_id}"},
                })],
                outputs=[{"name": "user_id", "value_type": "INTEGER",
                          "source_path": "user_id", "sort": 1}],
            )

            task_iface = iface("POST", "/tasks", "创建任务")
            case_ids = []
            for i in range(20):
                case_id = _create_case(
                    api, admin, pid, name=unique(f"批量任务-{i}"),
                    api_id=task_iface,
                    assertions=[_status_code_assertion("200", 0)],
                )
                _declare_fixtures(api, admin, case_id, "NORMAL_USER")
                _add_data(api, admin, case_id, name="user_id", source_type="FIXTURE",
                          config={"fixture_key": "NORMAL_USER", "output": "user_id"}, sort=0)
                case_ids.append(case_id)

            plan_id = _build_plan_with_cases(api, admin, pid, case_ids, env_id)
            run = _run(api, admin, plan_id, env_id)

            assert run["total"] == 20 and run["passed"] == 20, run
            assert run["error"] == 0 and run["failed"] == 0, run

            # 造数只发生一次（RUN 作用域），不随用例数增长。
            db.expire_all()
            run_execs = _data_executions(db, test_run_id=run["id"], scope="RUN")
            case_execs = _data_executions(db, test_run_id=run["id"], scope="CASE")
            assert len(run_execs) == 1, [e.scope for e in run_execs]
            assert case_execs == [], [e.scope for e in case_execs]

            # Provider 只执行一次；清理只执行一次。
            assert len(_provider_executions(db, run_execs[0].id)) == 1
            assert run_execs[0].cleanup_status == "SUCCESS", run_execs[0]
            assert len(generated) == 1, generated
            assert deleted == ["/users/9"], deleted

            # CASE 阶段没有自己的造数记录：不重复清理，标 SKIPPED。
            statuses = {e["status"] for e in _case_execs(api, admin, run["id"])}
            assert statuses == {"PASSED"}, statuses
            cleanup_statuses = {e["cleanup_status"] for e in _case_execs(api, admin, run["id"])}
            assert cleanup_statuses == {"SKIPPED"}, cleanup_statuses

            # 20 条用例都用到了同一个 user_id。
            user_ids = {e["context_json"]["data"]["user_id"] for e in _case_execs(api, admin, run["id"])}
            assert user_ids == {9}, user_ids


# --------------------------------------------------------------------------- Setup 失败


class TestSetupFailureIsError:
    """Setup（造数）失败 → 用例 ERROR，不是 FAILED。"""

    def test_disabled_fixture_is_error_not_failed(self, api, admin, db):
        """验证`disabled`固定数据是否错误不失败场景及其预期结果。"""
        with StubServer() as stub:
            stub.add("GET", "/health", 200, {"code": 0, "data": {}})
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            # DISABLED 夹具：连声明都不允许（前端下拉也不会出现）。
            _make_fixture(
                api, admin, pid, key="OFF_USER", status="DISABLED",
                steps=[_step("STATIC", 10, name="s", config={"values": {"u": 1}})],
                outputs=[{"name": "u", "value_type": "INTEGER", "source_path": "u", "sort": 1}],
            )
            r = api.put(
                f"/test-cases/1/fixtures", username=admin,
                json={"fixtures": [{"fixture_key": "OFF_USER"}]},
            )
            # 用例不存在 → 404；先建一个用例再验证状态校验。
            case_id = _create_case(
                api, admin, pid, name=unique("停用夹具用例"),
                api_id=iface("GET", "/health", "健康检查"),
                assertions=[_status_code_assertion("200", 0)],
            )
            r2 = api.put(
                f"/test-cases/{case_id}/fixtures", username=admin,
                json={"fixtures": [{"fixture_key": "OFF_USER"}]},
            )
            assert r2.status_code == 400, r2.text
            assert r2.json().get("code") == "FIXTURE_DISABLED", r2.json()

            # 绕过接口直接落一行 test_case_fixture，模拟「运行前夹具被停用」：
            # 运行期必须报 ERROR，不能降级成 FAILED。
            from app.features.test_data.models.case_fixture import TestCaseFixture
            from app.features.test_data.models.fixture import Fixture

            db.flush()
            fixture_row = (
                db.query(Fixture).filter(Fixture.fixture_key == "OFF_USER").first()
            )
            db.add(TestCaseFixture(test_case_id=case_id, fixture_id=fixture_row.id, sort=0))
            db.commit()

            plan_id = _build_plan_with_cases(api, admin, pid, [case_id], env_id)
            run = _run(api, admin, plan_id, env_id)

            assert run["error"] == 1 and run["failed"] == 0, run
            assert run["passed"] == 0, run
            execs = _case_execs(api, admin, run["id"])
            assert execs[0]["status"] == "ERROR", execs[0]
            assert execs[0]["error_code"] == "FIXTURE_DISABLED", execs[0]
            assert "DISABLED" in execs[0]["error_message"], execs[0]
            # 没有造数记录：夹具根本没被执行。
            db.expire_all()
            assert _data_executions(db, test_run_id=run["id"]) == []

    def test_missing_fixture_key_is_error_not_failed(self, api, admin, db):
        """验证缺失固定数据键是否错误不失败场景及其预期结果。"""
        with StubServer() as stub:
            stub.add("GET", "/health", 200, {"code": 0, "data": {}})
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            other_pid = _create_project(api, admin)
            # 别的项目的私有夹具：本项目不可见 → FIXTURE_NOT_FOUND。
            _make_fixture(
                api, admin, other_pid, key="OTHER_USER",
                steps=[_step("STATIC", 10, name="s", config={"values": {"u": 1}})],
                outputs=[{"name": "u", "value_type": "INTEGER", "source_path": "u", "sort": 1}],
            )
            from app.features.test_data.models.case_fixture import TestCaseFixture
            from app.features.test_data.models.fixture import Fixture

            case_id = _create_case(
                api, admin, pid, name=unique("跨项目夹具用例"),
                api_id=iface("GET", "/health", "健康检查"),
                assertions=[_status_code_assertion("200", 0)],
            )
            db.flush()
            other = db.query(Fixture).filter(Fixture.fixture_key == "OTHER_USER").first()
            db.add(TestCaseFixture(test_case_id=case_id, fixture_id=other.id, sort=0))
            db.commit()

            plan_id = _build_plan_with_cases(api, admin, pid, [case_id], env_id)
            run = _run(api, admin, plan_id, env_id)

            assert run["error"] == 1 and run["failed"] == 0, run
            execs = _case_execs(api, admin, run["id"])
            assert execs[0]["status"] == "ERROR", execs[0]
            assert execs[0]["error_code"] == "FIXTURE_NOT_FOUND", execs[0]


# --------------------------------------------------------------------------- Cleanup 失败


class TestCleanupFailureKeepsResult:
    """Cleanup 失败 → 原结论与原错误码不动，只写 cleanup_*。"""

    def test_cleanup_failure_does_not_overwrite_assertion_result(self, api, admin, db):
        """验证清理失败是否不`overwrite`断言结果场景及其预期结果。"""
        with StubServer() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"task_id": 7}})
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            create_iface = iface("POST", "/tasks", "创建任务")
            bad_iface = iface("POST", "/tasks/nope", "清不掉的接口")

            _make_fixture(
                api, admin, pid, key="CLEANUP_BROKEN", cleanup_policy="AFTER_CASE",
                steps=[
                    _step("API", 10, name="创建任务", config={
                        "api_id": create_iface,
                        "output_mappings": [{"name": "task_id", "expression": "$.data.task_id"}],
                    }),
                    # CLEANUP 步骤指向一个 404 接口：清理必须失败。
                    _step("API", 10, name="清不掉", provider_id=None, phase="CLEANUP", config={
                        "api_id": bad_iface,
                    }),
                ],
                outputs=[{"name": "task_id", "value_type": "INTEGER",
                          "source_path": "task_id", "sort": 1}],
            )

            case_id = _create_case(
                api, admin, pid, name=unique("清理失败-断言仍通过"),
                api_id=create_iface,
                assertions=[
                    _status_code_assertion("200", 0),
                    {"assertion_type": "JSON_PATH", "path": "$.data.task_id",
                     "operator": "EXISTS", "expected_value": None,
                     "required": True, "sort": 1},
                ],
            )
            _declare_fixtures(api, admin, case_id, "CLEANUP_BROKEN")
            _add_data(api, admin, case_id, name="task_id", source_type="FIXTURE",
                      config={"fixture_key": "CLEANUP_BROKEN", "output": "task_id"}, sort=0)

            plan_id = _build_plan_with_cases(api, admin, pid, [case_id], env_id)
            run = _run(api, admin, plan_id, env_id)

            # 结论不受清理影响。
            assert run["passed"] == 1 and run["failed"] == 0 and run["error"] == 0, run
            assert run["status"] == "SUCCESS", run

            execs = _case_execs(api, admin, run["id"])
            ce = execs[0]
            assert ce["status"] == "PASSED", ce
            assert ce["error_code"] is None, ce
            assert ce["error_message"] is None, ce
            assert all(a["passed"] for a in ce["assertion_results"]), ce
            # 清理失败单独记账，不覆盖结论。
            assert ce["cleanup_status"] == "FAILED", ce
            assert ce["cleanup_error_code"] == "CLEANUP_FAILED", ce
            assert ce["cleanup_error_message"], ce

            db.expire_all()
            data_execs = _data_executions(db, test_run_id=run["id"])
            assert len(data_execs) == 1, data_execs
            de = data_execs[0]
            assert de.status == "READY", de
            assert de.error_code is None, de
            assert de.cleanup_status == "FAILED", de
            assert de.cleanup_error_code == "CLEANUP_FAILED", de

    def test_failed_case_stays_failed_after_cleanup_failure(self, api, admin, db):
        """断言失败的用例，清理再失败也保持原错误码。"""
        with StubServer() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"task_id": 7}})
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            create_iface = iface("POST", "/tasks", "创建任务")
            bad_iface = iface("POST", "/tasks/nope", "清不掉的接口")

            _make_fixture(
                api, admin, pid, key="CLEANUP_BROKEN_2", cleanup_policy="AFTER_CASE",
                steps=[
                    _step("API", 10, name="创建任务", config={
                        "api_id": create_iface,
                        "output_mappings": [{"name": "task_id", "expression": "$.data.task_id"}],
                    }),
                    _step("API", 10, name="清不掉", phase="CLEANUP", config={
                        "api_id": bad_iface,
                    }),
                ],
                outputs=[{"name": "task_id", "value_type": "INTEGER",
                          "source_path": "task_id", "sort": 1}],
            )
            case_id = _create_case(
                api, admin, pid, name=unique("断言失败-清理也失败"),
                api_id=create_iface,
                # 期望 201，实际 200 → 断言失败（FAILED，不是 ERROR）。
                assertions=[_status_code_assertion("201", 0)],
            )
            _declare_fixtures(api, admin, case_id, "CLEANUP_BROKEN_2")

            plan_id = _build_plan_with_cases(api, admin, pid, [case_id], env_id)
            run = _run(api, admin, plan_id, env_id)

            assert run["failed"] == 1 and run["error"] == 0 and run["passed"] == 0, run
            ce = _case_execs(api, admin, run["id"])[0]
            assert ce["status"] == "FAILED", ce
            assert ce["error_code"] == "ASSERTION_FAILED", ce
            assert ce["cleanup_status"] == "FAILED", ce
            assert ce["cleanup_error_code"] == "CLEANUP_FAILED", ce


# --------------------------------------------------------------------------- 项目隔离


class TestProjectIsolation:
    """造数记录只属于本次运行的项目与环境。"""

    def test_execution_records_stay_in_project(self, api, admin, db):
        """验证执行记录记录`stay``in`项目场景及其预期结果。"""
        with StubServer() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"task_id": 4}})
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            other_pid = _create_project(api, admin)

            task_iface = iface("POST", "/tasks", "创建任务")
            _make_fixture(
                api, admin, pid, key="ISOLATED_TASK",
                steps=[_step("API", 10, name="创建任务", config={
                    "api_id": task_iface,
                    "output_mappings": [{"name": "task_id", "expression": "$.data.task_id"}],
                })],
                outputs=[{"name": "task_id", "value_type": "INTEGER",
                          "source_path": "task_id", "sort": 1}],
            )
            case_id = _create_case(
                api, admin, pid, name=unique("隔离-造数用例"),
                api_id=task_iface,
                assertions=[_status_code_assertion("200", 0)],
            )
            _declare_fixtures(api, admin, case_id, "ISOLATED_TASK")

            plan_id = _build_plan_with_cases(api, admin, pid, [case_id], env_id)
            run = _run(api, admin, plan_id, env_id)
            assert run["passed"] == 1, run

            db.expire_all()
            rows = _data_executions(db, test_run_id=run["id"])
            assert len(rows) == 1, rows
            row = rows[0]
            assert row.project_id == pid, row
            assert row.environment_id == env_id, row

            # 另一个项目按项目查不到这条造数记录。
            mine = api.get(
                f"/projects/{pid}/data-executions", username=admin,
                params={"test_run_id": run["id"]},
            ).json()
            assert len(mine["items"]) == 1, mine
            theirs = api.get(
                f"/projects/{other_pid}/data-executions", username=admin,
                params={"test_run_id": run["id"]},
            ).json()
            assert theirs["items"] == [], theirs["items"]

            # 记录归属字段本身也要对：夹具与 Provider 执行记录的 project_id 一致。
            from app.features.test_data.models.execution import FixtureExecution

            fixture_rows = (
                db.query(FixtureExecution)
                .filter(FixtureExecution.data_execution_id == row.id)
                .all()
            )
            assert fixture_rows, fixture_rows
            assert {f.project_id for f in fixture_rows} == {pid}, fixture_rows
            assert {p.project_id for p in _provider_executions(db, row.id)} == {pid}


# --------------------------------------------------------------------------- Agent 引用边界


def _make_run_ctx(db, user):
    """构造运行`ctx`。"""
    from app.features.agent.nodes._context import NodeContext
    from app.features.agent.providers.llm_provider import FakeLLMProvider

    return NodeContext(db=db, user=user, provider=FakeLLMProvider())


def _user_of(db, username):
    """按用户名查询用户记录。"""
    from app.models.identity import User

    return db.query(User).filter(User.username == username).first()


class TestAgentFixtureReference:
    """Agent 只能引用已注册 Fixture，不创建 Provider，不执行 SQL。"""

    def test_validator_rejects_missing_fixture(self, api, admin, db):
        """验证校验器拒绝缺失固定数据场景及其预期结果。"""
        from app.features.agent.nodes.validator import validator_node
        from app.features.agent.schemas import TestCaseDraft

        pid = _create_project(api, admin)
        user = _user_of(db, admin)

        draft = TestCaseDraft(
            name=unique("缺少夹具的用例"), target_type="API",
            assertions=[{"assertion_type": "STATUS_CODE", "operator": "EQ",
                         "expected_value": "200", "required": True, "sort": 0}],
            required_fixtures=["FAILED_TASK"],
        )
        state = {
            "generated_test_cases": [draft.model_dump()],
            "available_fixtures": [],
            "available_fixtures_ok": True,
            "existing_test_context": {"cases": []},
            "confirmed_point_ids": [],
        }
        result = validator_node(_make_run_ctx(db, user), state)

        assert result["current_stage"] == "FAILED", result
        assert result["error"]["code"] == "TEST_CASE_VALIDATION_FAILED", result
        assert "当前缺少 FAILED_TASK Fixture" in result["error"]["message"], result

    def test_save_cases_persists_required_fixtures(self, api, admin, db):
        """验证保存`cases``persists`必填`fixtures`场景及其预期结果。"""
        from app.features.agent.schemas import TestCaseDraft
        from app.features.agent.tools.test_asset_tool import save_cases
        from app.features.test_data.models.case_fixture import TestCaseFixture

        pid = _create_project(api, admin)
        user = _user_of(db, admin)
        _make_fixture(
            api, admin, pid, key="ACTIVE_PROJECT",
            steps=[_step("STATIC", 10, name="s", config={"values": {"project_id": 1}})],
            outputs=[{"name": "project_id", "value_type": "INTEGER",
                      "source_path": "project_id", "sort": 1}],
        )
        # 另一个 RUN 作用域夹具，Agent 同样只引用不拥有。
        _make_fixture(
            api, admin, pid, key="NORMAL_USER", scope="RUN",
            steps=[_step("STATIC", 10, name="s", config={"values": {"user_id": 2}})],
            outputs=[{"name": "user_id", "value_type": "INTEGER",
                      "source_path": "user_id", "sort": 1}],
        )
        before_providers = self._provider_count(db, pid)
        before_tasks = _sandbox_count(db)

        draft = TestCaseDraft(
            name=unique("Agent 引用夹具"), target_type="API",
            test_data=[{"name": "project_id", "value_type": "INTEGER", "source_type": "FIXTURE",
                        "config_json": {"fixture_key": "ACTIVE_PROJECT", "output": "project_id"},
                        "required": True, "sort": 0}],
            assertions=[{"assertion_type": "STATUS_CODE", "operator": "EQ",
                         "expected_value": "200", "required": True, "sort": 0}],
            required_fixtures=["NORMAL_USER", "ACTIVE_PROJECT"],
        )
        results = save_cases(
            db, pid, user, [draft], agent_session_id=0, generation_version=1,
        )
        assert len(results) == 1, results

        case_id = results[0]["id"]
        rows = (
            db.query(TestCaseFixture).filter(TestCaseFixture.test_case_id == case_id).all()
        )
        # 按声明顺序落库（Agent 只给 key，运行时值不入库）。
        keys = [r.fixture_id for r in rows]
        from app.features.test_data.models.fixture import Fixture

        by_key = {f.fixture_key: f for f in db.query(Fixture).filter(
            Fixture.id.in_(keys)).all()}
        assert sorted(by_key) == ["ACTIVE_PROJECT", "NORMAL_USER"], by_key
        assert sorted(r.sort for r in rows) == [0, 1], rows

        # 没有新建 Provider，也没有执行任何 SQL 造数。
        assert self._provider_count(db, pid) == before_providers
        assert _sandbox_count(db) == before_tasks

    @staticmethod
    def _provider_count(db, project_id):
        """统计数据提供器记录数量。"""
        from app.features.test_data.models.provider import DataProvider

        return db.query(DataProvider).filter(DataProvider.project_id == project_id).count()

    def test_save_cases_refuses_missing_fixture_without_side_effects(self, api, admin, db):
        """验证保存`cases``refuses`缺失固定数据不带`side``effects`场景及其预期结果。"""
        from fastapi import HTTPException

        from app.features.agent.schemas import TestCaseDraft
        from app.features.agent.tools.test_asset_tool import save_cases

        from app.features.test_data.models.case_fixture import TestCaseFixture

        pid = _create_project(api, admin)
        user = _user_of(db, admin)
        before_providers = self._provider_count(db, pid)
        before_tasks = _sandbox_count(db)
        before_fixtures = self._fixture_count(db, pid)
        before_links = db.query(TestCaseFixture).count()

        draft = TestCaseDraft(
            name=unique("Agent 引用不存在的夹具"), target_type="API",
            required_fixtures=["FAILED_TASK"],
            test_data=[{"name": "task_id", "value_type": "INTEGER", "source_type": "FIXTURE",
                        "config_json": {"fixture_key": "FAILED_TASK", "output": "task_id"},
                        "required": True, "sort": 0}],
            assertions=[{"assertion_type": "STATUS_CODE", "operator": "EQ",
                         "expected_value": "200", "required": True, "sort": 0}],
        )
        try:
            save_cases(db, pid, user, [draft], agent_session_id=0, generation_version=1)
            raise AssertionError("缺少 Fixture 必须拒绝落库")
        except HTTPException as exc:
            assert exc.status_code == 404, exc
            assert "当前缺少 FAILED_TASK Fixture" in str(exc.detail), exc

        # 不落库、不建 Provider、不执行 SQL。会话库里已有其他用例的引用，只比较增量。
        assert self._provider_count(db, pid) == before_providers
        assert self._fixture_count(db, pid) == before_fixtures
        assert _sandbox_count(db) == before_tasks
        assert db.query(TestCaseFixture).count() == before_links

    @staticmethod
    def _fixture_count(db, project_id):
        """统计固定数据记录数量。"""
        from app.features.test_data.models.fixture import Fixture

        return db.query(Fixture).filter(Fixture.project_id == project_id).count()

