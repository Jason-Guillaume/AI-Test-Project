"""验收项 19：测试数据中心 Phase B —— Data Factory 运行时。

覆盖 §8–§11 运行时（对应计划 Phase B 验收标准）：
- SUCCESS_TASK：STATIC 中间变量 → API_CREATE 拿到声明的 task_id；**中间变量不出契约**，
  契约里的两个写法都成立（裸映射名 `task_id` 与 JSON 路径 `$.data.name`）
- DATABASE_PATCH：只在白名单环境改 sandbox 表；非白名单表 → DATABASE_TABLE_NOT_ALLOWED
- PRODUCTION 试跑数据库 Provider 失败（DATABASE_ENVIRONMENT_FORBIDDEN）且表不变
- FAKER：连续两次 phone 不要求不相等，但必须是真生成值、不是配置里的字面量 "phone"
- 预留 WAIT 步骤使本次生成 FAILED，错误码 FIXTURE_STEP_UNSUPPORTED，步骤落 SKIPPED 记录
- Cleanup：API 清理句柄 + CLEANUP 步骤都真的执行了；**清理失败不覆盖原错误码**
- Provider 试跑接口：单 Provider 执行记录挂在 data_execution.provider_executions
- BUSINESS_FLOW Provider：调 execute_flow 后能读到非敏感变量，token 已脱敏
- 执行记录详情：每步 input/output/error 可读，快照已脱敏

HTTP 用 StubServer（127.0.0.1 环回）+ 项目出站白名单显式放行；数据库用测试夹具自身的库。
"""

from __future__ import annotations

import re

from sqlalchemy import text

from tests.conftest import (
    TEST_DATABASE_NAME,
    TEST_DB_HOST,
    TEST_DB_PASSWORD,
    TEST_DB_PORT,
    TEST_DB_USER,
    unique,
)
from tests.test_15_test_executor import (
    StubServer,
    _admin_id,
    _add_action,
    _add_binding,
    _add_mapping,
    _add_output_var,
    _build_login_flow,
    _make_env,
    _make_iface,
    _whitelist,
)

API = "/api/v1"


# --------------------------------------------------------------------------- 公共辅助


def _create_project(api, admin, name=None):
    r = api.post(
        "/projects", username=admin,
        json={"name": name or unique("proj"), "description": "data factory test"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _dev_env(db, name="dev", admin_id=None):
    from app.models.configuration import Environment

    if admin_id is None:
        admin_id = _admin_id(db)
    env = db.query(Environment).filter(Environment.name == name).first()
    if env is None:
        env = Environment(
            name=name, display_name=name, base_url="https://example.com",
            gateway_prefix="", default_headers={}, is_active=True, created_by=admin_id,
        )
        db.add(env)
        db.commit()
        db.refresh(env)
    return env.id


def _stub_env(api, admin, db, stub):
    """建项目 + 环境 + 出站白名单 + 接口，返回 (project_id, env_id, admin_id, new_iface)。"""
    admin_id = _admin_id(db)
    pid = _create_project(api, admin)
    env_id = _make_env(db, stub.base_url, admin_id, name=unique("env"))
    _whitelist(db, pid, stub.port, admin_id)

    def iface(method, path, name=None):
        return _make_iface(db, pid, method, path, name or unique("iface"))

    return pid, env_id, admin_id, iface


def _make_fixture(api, admin, project_id, *, key, steps=None, outputs=None,
                  cleanup_policy="AFTER_CASE", status="ACTIVE", scope="CASE",
                  dependencies=None):
    body = {
        "name": key, "fixture_key": key, "entity_type": "TASK",
        "scope": scope, "status": status, "cache_enabled": True,
        "cleanup_policy": cleanup_policy,
        "steps": steps or [], "outputs": outputs or [], "dependencies": dependencies or [],
    }
    r = api.post(f"/projects/{project_id}/fixtures", username=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _make_provider(api, admin, project_id, *, provider_type, config_json,
                   name=None, enabled=True, risk_level=None):
    body = {
        "name": name or unique("prov"), "provider_type": provider_type,
        "config_json": config_json, "enabled": enabled,
    }
    if risk_level:
        body["risk_level"] = risk_level
    r = api.post(f"/projects/{project_id}/data-providers", username=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _db_connection(api, admin, project_id, env_id):
    """指向测试夹具自身库的被测库连接（必然可达）。"""
    r = api.post(
        f"/projects/{project_id}/target-databases", username=admin,
        json={
            "environment_id": env_id, "name": unique("conn"),
            "host": TEST_DB_HOST, "port": int(TEST_DB_PORT),
            "database_name": TEST_DATABASE_NAME,
            "username": TEST_DB_USER, "password": TEST_DB_PASSWORD, "enabled": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _db_policy(api, admin, project_id, env_id, tables, operations):
    r = api.put(
        f"/projects/{project_id}/database-policies/{env_id}", username=admin,
        json={"enabled": True, "allowed_tables": tables, "allowed_operations": operations},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _generate(api, admin, fixture_id, env_id, variables=None):
    return api.post(
        f"/fixtures/{fixture_id}/generate", username=admin,
        json={"environment_id": env_id, "scope": "CASE", "variables": variables or {}},
    )


def _step(step_type, sort, *, name=None, config=None, provider_id=None, phase="GENERATE",
          on_failure="ABORT"):
    return {
        "phase": phase, "step_type": step_type,
        "name": name or step_type, "sort": sort,
        "provider_id": provider_id, "config_json": config, "on_failure": on_failure,
    }


def _task_seed_row(db, status="PENDING", name="seed"):
    """往 sandbox 表插一行种子数据，返回 id。"""
    result = db.execute(
        text("INSERT INTO td_sandbox_task (status, name) VALUES (:s, :n) RETURNING id"),
        {"s": status, "n": name},
    )
    row_id = result.scalar()
    db.commit()
    return int(row_id)


def _task_status(db, row_id):
    return db.execute(
        text("SELECT status FROM td_sandbox_task WHERE id = :i"), {"i": row_id}
    ).scalar()


# --------------------------------------------------------------------------- SUCCESS_TASK


class TestSuccessTask:
    """验收标准一：拿到声明的 task_id，中间步骤变量不出契约。"""

    def test_contract_exposes_only_declared_outputs(self, api, admin, db):
        with StubServer() as stub:
            stub.add("POST", "/tasks", 200, {
                "code": 0, "message": "ok",
                "data": {"task_id": 12345, "name": "demo-task", "password": "p@ss"},
            })
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            api_id = iface("POST", "/tasks", "创建任务")

            task_iface_id = api_id
            api_create_config = {
                "api_id": task_iface_id,
                "input_mappings": [
                    {"target": "seed", "location": "BODY",
                     "expression": "${runtime.intermediate}"},
                    {"target": "title", "location": "BODY", "expression": "${faker.name}"},
                ],
                "output_mappings": [
                    {"name": "task_id", "expression": "$.data.task_id"},
                    {"name": "task_name", "expression": "$.data.name"},
                ],
            }
            fixture = _make_fixture(
                api, admin, pid,
                key="SUCCESS_TASK",
                steps=[
                    # 中间变量：写入私有上下文，但**不**声明进输出契约。
                    _step("STATIC", 10, name="中间变量",
                          config={"values": {"intermediate": "not-in-contract"}}),
                    _step("API", 20, name="创建任务",
                          config=api_create_config),
                ],
                outputs=[
                    # 两种 source_path 写法并存：裸映射名 / JSON 路径。
                    {"name": "task_id", "value_type": "INTEGER", "source_path": "task_id", "sort": 1},
                    {"name": "task_name", "value_type": "STRING", "source_path": "$.data.name", "sort": 2},
                ],
            )

            r = _generate(api, admin, fixture["id"], env_id)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "READY", body
            assert body["error_code"] is None
            assert body["scope"] == "CASE"
            assert body["environment_id"] == env_id
            assert body["fixture_key_count"] == 1
            assert body["provider_step_count"] == 2
            assert body["test_run_id"] is None and body["case_execution_id"] is None

            # 契约输出：只有声明过的两个键，中间变量不在契约里。
            assert len(body["fixture_executions"]) == 1
            fx = body["fixture_executions"][0]
            assert fx["status"] == "READY"
            assert fx["fixture_key"] == "SUCCESS_TASK"
            assert fx["output_snapshot"] == {"task_id": 12345, "task_name": "demo-task"}
            assert "intermediate" not in fx["output_snapshot"]

            # 中间变量确实存在（落在静态步骤的输出快照里），只是不进契约。
            static_rec = next(p for p in fx["provider_executions"] if p["provider_type"] == "STATIC")
            api_rec = next(p for p in fx["provider_executions"] if p["provider_type"] == "API_CREATE")
            assert static_rec["status"] == "SUCCESS"
            assert static_rec["output_snapshot"] == {"intermediate": "not-in-contract"}
            assert "intermediate" not in fx["output_snapshot"]

            # API 步骤：input 快照是配置模板，output 快照含完整响应体且已脱敏。
            assert api_rec["status"] == "SUCCESS"
            assert api_rec["error_code"] is None
            assert api_rec["error_message"] is None
            assert api_rec["input_snapshot"]["output_mappings"][0]["name"] == "task_id"
            response_body = api_rec["output_snapshot"].get("_response")
            assert response_body["data"]["task_id"] == 12345
            assert response_body["data"]["password"] == "******", response_body
            assert "_response" not in fx["output_snapshot"]

            # 执行记录详情接口也能看到同样的每步明细。
            detail = api.get(f"/data-executions/{body['id']}", username=admin)
            assert detail.status_code == 200
            d = detail.json()
            assert len(d["fixture_executions"][0]["provider_executions"]) == 2
            assert d["provider_executions"] == []

    def test_missing_declared_output_fails_generation(self, api, admin, db):
        """声明的输出取不到值 → DATA_RESOLVE_FAILED，记录落成 FAILED。"""
        with StubServer() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"task_id": 1}})
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            fixture = _make_fixture(
                api, admin, pid, key="BROKEN_TASK",
                steps=[
                    _step("STATIC", 10, name="中间变量",
                          config={"values": {"intermediate": "x"}}),
                ],
                outputs=[
                    {"name": "task_id", "value_type": "INTEGER", "source_path": "task_id", "sort": 1},
                ],
            )
            r = _generate(api, admin, fixture["id"], env_id)
            assert r.status_code == 400, r.text
            assert r.json().get("code") == "DATA_RESOLVE_FAILED"


# --------------------------------------------------------------------------- FAKER


class TestFaker:
    """验收标准四：必须真调生成器，不能回退成配置字面量。"""

    def test_phone_is_generated_not_literal(self, api, admin, db):
        with StubServer() as stub:
            pid, env_id, _aid, _iface = _stub_env(api, admin, db, stub)
            fixture = _make_fixture(
                api, admin, pid, key="FAKER_PHONE",
                steps=[
                    _step("FAKER", 10, name="手机号",
                          config={"generator": "phone", "locale": "zh_CN", "output_key": "phone"}),
                ],
                outputs=[
                    {"name": "phone", "value_type": "STRING", "source_path": "phone", "sort": 1},
                ],
            )
            values = []
            for _ in range(2):
                r = _generate(api, admin, fixture["id"], env_id)
                assert r.status_code == 200, r.text
                body = r.json()
                assert body["status"] == "READY", body
                values.append(body["fixture_executions"][0]["output_snapshot"]["phone"])

            for value in values:
                assert value != "phone", "必须是生成值，不是配置字面量"
                assert isinstance(value, str) and len(value) >= 5
                assert re.search(r"\d", value), f"phone 生成器应产出带数字的值，收到 {value!r}"
            # 两次不要求不相等（随机可能碰撞），但要允许相等。
            assert isinstance(values[0], str) and isinstance(values[1], str)

    def test_illegal_generator_is_config_error(self, api, admin, db):
        with StubServer() as stub:
            pid, env_id, _aid, _iface = _stub_env(api, admin, db, stub)
            fixture = _make_fixture(
                api, admin, pid, key="FAKER_BAD",
                steps=[_step("FAKER", 10, name="坏生成器",
                             config={"generator": "drop_table"})],
                outputs=[{"name": "v", "value_type": "STRING", "source_path": "v", "sort": 1}],
            )
            r = _generate(api, admin, fixture["id"], env_id)
            assert r.status_code == 400
            assert r.json().get("code") == "VARIABLE_RESOLVE_FAILED"


# --------------------------------------------------------------------------- 预留步骤


class TestReservedStep:
    """验收标准五：预留类型只保存不执行。"""

    def test_wait_step_fails_with_unsupported(self, api, admin, db):
        with StubServer() as stub:
            pid, env_id, _aid, _iface = _stub_env(api, admin, db, stub)
            fixture = _make_fixture(
                api, admin, pid, key="WAIT_FIX",
                steps=[
                    _step("STATIC", 10, name="准备", config={"values": {"ok": "1"}}),
                    _step("WAIT", 20, name="等一会儿", config={"seconds": 3}),
                    _step("STATIC", 30, name="不会被执行", config={"values": {"never": "run"}}),
                ],
                outputs=[{"name": "ok", "value_type": "STRING", "source_path": "ok", "sort": 1}],
            )
            r = _generate(api, admin, fixture["id"], env_id)
            assert r.status_code == 400, r.text
            assert r.json().get("code") == "FIXTURE_STEP_UNSUPPORTED"

            # 记录已落 FAILED，并保留原错误码。
            executions = api.get(
                f"/projects/{pid}/data-executions", username=admin, params={"status": "FAILED"},
            ).json()
            rec = executions["items"][0]
            detail = api.get(f"/data-executions/{rec['id']}", username=admin).json()
            assert detail["status"] == "FAILED"
            assert detail["error_code"] == "FIXTURE_STEP_UNSUPPORTED"
            assert "只保存不执行" in (detail["error_message"] or "")
            fx = detail["fixture_executions"][0]
            assert fx["status"] == "FAILED"
            assert fx["error_code"] == "FIXTURE_STEP_UNSUPPORTED"
            assert fx["output_snapshot"] is None
            # WAIT 步骤落 SKIPPED 记录；排在其后的步骤根本没跑。
            types = [p["provider_type"] for p in fx["provider_executions"]]
            assert "WAIT" in types
            assert "WAIT" == types[-1], f"WAIT 之后的步骤不该执行：{types}"
            wait_rec = next(p for p in fx["provider_executions"] if p["provider_type"] == "WAIT")
            assert wait_rec["status"] == "SKIPPED"
            assert wait_rec["error_code"] == "FIXTURE_STEP_UNSUPPORTED"


# --------------------------------------------------------------------------- 依赖链


class TestDependencyChain:
    """依赖先于自己被生成，中间变量在依赖间传递但不出契约。"""

    def test_dependency_generates_first_and_injects(self, api, admin, db):
        with StubServer() as stub:
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            project_iface = iface("POST", "/projects", "创建项目")

            base = _make_fixture(
                api, admin, pid, key="BASE_PROJECT",
                steps=[
                    _step("API", 10, name="创建项目", config={
                        "api_id": project_iface,
                        "output_mappings": [{"name": "project_id", "expression": "$.data.id"}],
                    }),
                ],
                outputs=[{"name": "project_id", "value_type": "INTEGER",
                          "source_path": "project_id", "sort": 1}],
            )
            stub.add("POST", "/projects", 200, {"code": 0, "data": {"id": 101}})
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"task_id": 202}})

            task = _make_fixture(
                api, admin, pid, key="SUCCESS_TASK", dependencies=[base["id"]],
                steps=[
                    _step("API", 10, name="创建任务", config={
                        "api_id": iface("POST", "/tasks", "创建任务"),
                        "input_mappings": [{"target": "project_id", "location": "BODY",
                                            "expression": "${fixture.BASE_PROJECT.project_id}"}],
                        "output_mappings": [{"name": "task_id", "expression": "$.data.task_id"}],
                    }),
                ],
                outputs=[{"name": "task_id", "value_type": "INTEGER", "source_path": "task_id", "sort": 1}],
            )

            r = _generate(api, admin, task["id"], env_id)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "READY", body
            # 依赖链两个 Fixture 都生成成功，且依赖在前。
            keys = [f["fixture_key"] for f in body["fixture_executions"]]
            assert keys == ["BASE_PROJECT", "SUCCESS_TASK"], keys
            assert body["fixture_key_count"] == 2

            # 依赖的输出被注入进被依赖方的上下文，且不进入自己的契约。
            task_fx = body["fixture_executions"][1]
            assert task_fx["output_snapshot"] == {"task_id": 202}
            assert "project_id" not in task_fx["output_snapshot"]
            api_rec = task_fx["provider_executions"][0]
            assert api_rec["status"] == "SUCCESS"
            assert api_rec["input_snapshot"]["input_mappings"][0]["expression"] == \
                "${fixture.BASE_PROJECT.project_id}"

    def test_disabled_dependency_fails_generation(self, api, admin, db):
        with StubServer() as stub:
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            base = _make_fixture(
                api, admin, pid, key="OFF_PROJECT", status="DISABLED",
                steps=[_step("STATIC", 10, name="s", config={"values": {"x": "1"}})],
                outputs=[{"name": "x", "value_type": "STRING", "source_path": "x", "sort": 1}],
            )
            task = _make_fixture(
                api, admin, pid, key="DEP_ON_OFF", dependencies=[base["id"]],
                steps=[_step("STATIC", 10, name="s", config={"values": {"y": "2"}})],
                outputs=[{"name": "y", "value_type": "STRING", "source_path": "y", "sort": 1}],
            )
            r = _generate(api, admin, task["id"], env_id)
            assert r.status_code == 400
            assert r.json().get("code") == "FIXTURE_DISABLED"


# --------------------------------------------------------------------------- 数据库 Provider


class TestDatabasePatch:
    """验收标准二：DATABASE_PATCH 只在白名单环境改 sandbox 表。"""

    def test_patch_updates_only_whitelisted_sandbox_row(self, api, admin, db):
        env_id = _dev_env(db, "dev")
        pid = _create_project(api, admin)
        conn_id = _db_connection(api, admin, pid, env_id)
        _db_policy(api, admin, pid, env_id, ["td_sandbox_task"], ["INSERT", "UPDATE"])

        seed_id = _task_seed_row(db)
        before_count = db.execute(text("SELECT count(*) FROM td_sandbox_task")).scalar()

        provider = _make_provider(
            api, admin, pid, provider_type="DATABASE_PATCH",
            config_json={
                "connection_id": conn_id, "table": "td_sandbox_task",
                "operation": "UPDATE", "values": {"status": "PATCHED"},
                "where": {"id": seed_id},
            },
        )
        fixture = _make_fixture(
            api, admin, pid, key="PATCH_TASK",
            steps=[_step("DATABASE_PATCH", 10, name="打补丁", provider_id=provider["id"])],
            outputs=[{"name": "affected_rows", "value_type": "INTEGER",
                      "source_path": "affected_rows", "sort": 1}],
        )

        r = _generate(api, admin, fixture["id"], env_id)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "READY", body
        assert body["fixture_executions"][0]["output_snapshot"] == {"affected_rows": 1}

        rec = body["fixture_executions"][0]["provider_executions"][0]
        assert rec["status"] == "SUCCESS"
        # input 快照是 Provider 配置（脱敏），能看到表名与操作。
        assert rec["input_snapshot"]["table"] == "td_sandbox_task"
        assert rec["input_snapshot"]["operation"] == "UPDATE"
        assert rec["output_snapshot"]["affected_rows"] == 1

        # 只有目标行被改动，行数不变。
        assert _task_status(db, seed_id) == "PATCHED"
        after_count = db.execute(text("SELECT count(*) FROM td_sandbox_task")).scalar()
        assert after_count == before_count

    def test_non_whitelisted_table_rejected_and_recorded(self, api, admin, db):
        env_id = _dev_env(db, "dev")
        pid = _create_project(api, admin)
        conn_id = _db_connection(api, admin, pid, env_id)
        _db_policy(api, admin, pid, env_id, ["td_sandbox_task"], ["UPDATE"])

        fixture = _make_fixture(
            api, admin, pid, key="PATCH_OUTSIDE",
            steps=[_step("DATABASE_PATCH", 10, name="越界表", config={
                "connection_id": conn_id, "table": "environment",
                "operation": "UPDATE", "values": {"is_active": False},
                "where": {"id": 1},
            })],
            outputs=[{"name": "affected_rows", "value_type": "INTEGER",
                      "source_path": "affected_rows", "sort": 1}],
        )
        r = _generate(api, admin, fixture["id"], env_id)
        assert r.status_code == 400, r.text
        assert r.json().get("code") == "DATABASE_TABLE_NOT_ALLOWED"

        executions = api.get(
            f"/projects/{pid}/data-executions", username=admin,
        ).json()
        assert executions["items"][0]["status"] == "FAILED"
        detail = api.get(
            f"/data-executions/{executions['items'][0]['id']}", username=admin,
        ).json()
        assert detail["status"] == "FAILED"
        assert detail["error_code"] == "DATABASE_TABLE_NOT_ALLOWED"
        assert detail["fixture_executions"][0]["output_snapshot"] is None
        provider_rec = detail["fixture_executions"][0]["provider_executions"][0]
        assert provider_rec["status"] == "FAILED"
        assert provider_rec["error_code"] == "DATABASE_TABLE_NOT_ALLOWED"

    def test_unreachable_connection_env_refused(self, api, admin, db):
        """连接绑定的环境必须等于本次运行环境。"""
        dev_env_id = _dev_env(db, "dev")
        staging_env_id = _dev_env(db, "staging")
        pid = _create_project(api, admin)
        conn_id = _db_connection(api, admin, pid, dev_env_id)
        _db_policy(api, admin, pid, dev_env_id, ["td_sandbox_task"], ["UPDATE"])
        _db_policy(api, admin, pid, staging_env_id, ["td_sandbox_task"], ["UPDATE"])

        fixture = _make_fixture(
            api, admin, pid, key="PATCH_WRONG_ENV",
            steps=[_step("DATABASE_PATCH", 10, name="串环境", config={
                "connection_id": conn_id, "table": "td_sandbox_task",
                "operation": "UPDATE", "values": {"status": "X"}, "where": {"id": 1},
            })],
            outputs=[{"name": "affected_rows", "value_type": "INTEGER",
                      "source_path": "affected_rows", "sort": 1}],
        )
        r = _generate(api, admin, fixture["id"], staging_env_id)
        assert r.status_code == 400, r.text
        assert r.json().get("code") == "DATABASE_ENVIRONMENT_FORBIDDEN"


class TestDatabaseInsert:
    """DATABASE_INSERT 走白名单，插入 sandbox 表并返回主键。"""

    def test_insert_returns_id_and_appends_one_row(self, api, admin, db):
        env_id = _dev_env(db, "dev")
        pid = _create_project(api, admin)
        conn_id = _db_connection(api, admin, pid, env_id)
        _db_policy(api, admin, pid, env_id, ["td_sandbox_task"], ["INSERT"])

        before = db.execute(text("SELECT count(*) FROM td_sandbox_task")).scalar()
        new_id = 99_000_001
        fixture = _make_fixture(
            api, admin, pid, key="INSERT_TASK",
            steps=[_step("DATABASE_INSERT", 10, name="插入任务", config={
                "connection_id": conn_id, "table": "td_sandbox_task",
                "operation": "INSERT", "columns": ["id", "status", "name"],
                # id 进 columns 才有 RETURNING id —— 否则 builder 不返回主键。
                "values": {"id": new_id, "status": "PENDING", "name": "${runtime.title}"},
            })],
            outputs=[{"name": "inserted_id", "value_type": "INTEGER",
                      "source_path": "inserted_id", "sort": 1}],
        )
        r = _generate(api, admin, fixture["id"], env_id, variables={"title": "插进来的任务"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "READY", body
        inserted = body["fixture_executions"][0]["output_snapshot"]["inserted_id"]
        assert isinstance(inserted, int) and inserted > 0

        after = db.execute(text("SELECT count(*) FROM td_sandbox_task")).scalar()
        assert after == before + 1
        # 变量真的进了行数据（走占位符，不是拼进 SQL）。
        name = db.execute(
            text("SELECT name FROM td_sandbox_task WHERE id = :i"), {"i": inserted},
        ).scalar()
        assert name == "插进来的任务"
        # input 快照保留模板，不保留解析后的值。
        snapshot = body["fixture_executions"][0]["provider_executions"][0]["input_snapshot"]
        assert snapshot["values"]["name"] == "${runtime.title}"

    def test_delete_forbidden_by_default(self, api, admin, db):
        """DELETE 三重确认：策略没放 DELETE 就拒绝，行数不变。"""
        env_id = _dev_env(db, "dev")
        pid = _create_project(api, admin)
        conn_id = _db_connection(api, admin, pid, env_id)
        _db_policy(api, admin, pid, env_id, ["td_sandbox_task"], ["UPDATE"])
        row_id = _task_seed_row(db)
        before = db.execute(text("SELECT count(*) FROM td_sandbox_task")).scalar()

        fixture = _make_fixture(
            api, admin, pid, key="DELETE_TASK",
            steps=[_step("DATABASE_PATCH", 10, name="删任务", config={
                "connection_id": conn_id, "table": "td_sandbox_task",
                "operation": "DELETE", "where": {"id": row_id},
                "allow_delete": True,
            })],
            outputs=[{"name": "affected_rows", "value_type": "INTEGER",
                      "source_path": "affected_rows", "sort": 1}],
        )
        r = _generate(api, admin, fixture["id"], env_id)
        assert r.status_code == 400
        assert r.json().get("code") == "DATABASE_OPERATION_FORBIDDEN"
        assert db.execute(text("SELECT count(*) FROM td_sandbox_task")).scalar() == before


class TestProductionBlocked:
    """验收标准三：生产环境试跑数据库 Provider 失败且表不变。"""

    def test_production_refuses_and_leaves_table_untouched(self, api, admin, db):
        prod_env_id = _dev_env(db, "production")
        pid = _create_project(api, admin)
        conn_id = _db_connection(api, admin, pid, prod_env_id)

        # 生产环境的策略行创建不出来（路由层就拒绝），所以库里根本没有策略。
        r_pol = api.put(
            f"/projects/{pid}/database-policies/{prod_env_id}", username=admin,
            json={"enabled": True, "allowed_tables": ["td_sandbox_task"],
                  "allowed_operations": ["UPDATE"]},
        )
        assert r_pol.status_code == 400
        assert r_pol.json().get("code") == "DATABASE_ENVIRONMENT_FORBIDDEN"

        seed_id = _task_seed_row(db, status="PENDING")
        fixture = _make_fixture(
            api, admin, pid, key="PROD_PATCH",
            steps=[_step("DATABASE_PATCH", 10, name="生产打补丁", config={
                "connection_id": conn_id, "table": "td_sandbox_task",
                "operation": "UPDATE", "values": {"status": "PATCHED"},
                "where": {"id": seed_id},
            })],
            outputs=[{"name": "affected_rows", "value_type": "INTEGER",
                      "source_path": "affected_rows", "sort": 1}],
        )
        r = _generate(api, admin, fixture["id"], prod_env_id)
        assert r.status_code == 400, r.text
        assert r.json().get("code") == "DATABASE_ENVIRONMENT_FORBIDDEN"

        # 表原样不动。
        assert _task_status(db, seed_id) == "PENDING"
        executions = api.get(f"/projects/{pid}/data-executions", username=admin).json()
        detail = api.get(f"/data-executions/{executions['items'][0]['id']}", username=admin).json()
        assert detail["status"] == "FAILED"
        assert detail["error_code"] == "DATABASE_ENVIRONMENT_FORBIDDEN"


# --------------------------------------------------------------------------- Cleanup


class TestCleanup:
    """验收标准：Cleanup 失败不得覆盖原错误码。"""

    def test_cleanup_failure_keeps_generation_error_code(self, api, admin, db):
        with StubServer() as stub:
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"task_id": 7, "name": "t"}})
            # 清理句柄命中这条：DELETE /tasks/7 → 200（证明句柄真的解析并执行了）。
            deleted: list[str] = []
            stub.add_fn(
                "DELETE", "/tasks/7",
                lambda h, body: (deleted.append(body) or (200, {"code": 0, "message": "deleted"})),
            )
            create_iface = iface("POST", "/tasks", "创建任务")
            cleanup_iface = iface("POST", "/tasks/nope", "清理接口")

            # Provider 带 API 清理句柄：只存路径模板，执行清理时再次解析。
            create_provider = _make_provider(
                api, admin, pid, provider_type="API_CREATE",
                config_json={
                    "api_id": create_iface,
                    "output_mappings": [{"name": "task_id", "expression": "$.data.task_id"}],
                    "cleanup": {
                        "method": "DELETE",
                        "path": "/tasks/${fixture.CLEANUP_FIX.task_id}",
                    },
                },
            )
            # 显式 CLEANUP 步骤指向一个 404 的接口：清理必须失败。
            cleanup_provider = _make_provider(
                api, admin, pid, provider_type="API_CREATE",
                config_json={"api_id": cleanup_iface},
            )
            fixture = _make_fixture(
                api, admin, pid, key="CLEANUP_FIX", cleanup_policy="AFTER_CASE",
                steps=[
                    _step("API", 10, name="创建任务", provider_id=create_provider["id"]),
                    _step("API", 10, name="清不掉的步骤", provider_id=cleanup_provider["id"],
                          phase="CLEANUP"),
                ],
                outputs=[{"name": "task_id", "value_type": "INTEGER", "source_path": "task_id", "sort": 1}],
            )

            r = _generate(api, admin, fixture["id"], env_id)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "READY", body
            # 关键：造数成功，清理失败，错误码不能互相覆盖。
            assert body["error_code"] is None, body
            assert body["error_message"] is None
            assert body["cleanup_status"] == "FAILED"
            assert body["cleanup_error_code"] == "CLEANUP_FAILED"
            assert body["cleanup_error_message"]

            message = body["cleanup_error_message"]
            # CLEANUP 步骤失败被记账。
            assert "清理接口" in message or "步骤" in message, message
            # 句柄那条不该失败：它解析出 /tasks/7 并成功删除。
            assert "清理接口 HTTP 404" not in message, message
            assert deleted, "API 清理句柄没有真正发出 DELETE 请求"

            # Fixture 级记录同样只写 cleanup_* 列。
            fx = body["fixture_executions"][0]
            assert fx["status"] == "READY"
            assert fx["error_code"] is None
            assert fx["cleanup_status"] == "FAILED"
            assert fx["output_snapshot"] == {"task_id": 7}

            # 手工清理接口单独返回清理记录。
            r2 = api.post(f"/fixtures/{fixture['id']}/cleanup", username=admin)
            assert r2.status_code == 200, r2.text
            cbody = r2.json()
            assert cbody["status"] == "FAILED"
            assert cbody["cleanup_status"] == "FAILED"

    def test_generation_failure_survives_cleanup_attempt(self, api, admin, db):
        """造数失败 + cleanup_policy=AFTER_CASE：FAILED 不被 cleanup 状态覆盖。"""
        with StubServer() as stub:
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            create_iface = iface("POST", "/tasks")
            stub.add("POST", "/tasks", 500, {"code": 1, "message": "boom"})
            fixture = _make_fixture(
                api, admin, pid, key="FAIL_FIX", cleanup_policy="AFTER_CASE",
                steps=[_step("API", 10, name="创建任务", config={
                    "api_id": create_iface,
                    "output_mappings": [{"name": "task_id", "expression": "$.data.task_id"}],
                })],
                outputs=[{"name": "task_id", "value_type": "INTEGER", "source_path": "task_id", "sort": 1}],
            )
            r = _generate(api, admin, fixture["id"], env_id)
            assert r.status_code == 400
            assert r.json().get("code") == "HTTP_REQUEST_FAILED"

            executions = api.get(f"/projects/{pid}/data-executions", username=admin).json()
            rec = executions["items"][0]
            assert rec["status"] == "FAILED"
            assert rec["error_code"] == "HTTP_REQUEST_FAILED"
            detail = api.get(f"/data-executions/{rec['id']}", username=admin).json()
            assert detail["status"] == "FAILED"
            assert detail["error_code"] == "HTTP_REQUEST_FAILED"


# --------------------------------------------------------------------------- Provider 试跑


class TestProviderTestEndpoint:
    def test_static_provider_test_returns_detail(self, api, admin, db):
        with StubServer() as stub:
            pid, env_id, _aid, _iface = _stub_env(api, admin, db, stub)
            prov = _make_provider(
                api, admin, pid, provider_type="STATIC",
                config_json={"values": {"const": "v1", "secret": "s3cr3t"}},
            )
            r = api.post(
                f"/data-providers/{prov['id']}/test", username=admin,
                json={"environment_id": env_id, "variables": {}},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "READY"
            assert body["fixture_executions"] == []
            # 单 Provider 试跑没有 Fixture 归属，记录挂在 data_execution 层。
            assert len(body["provider_executions"]) == 1
            rec = body["provider_executions"][0]
            assert rec["provider_type"] == "STATIC"
            assert rec["status"] == "SUCCESS"
            assert rec["fixture_execution_id"] is None
            assert rec["data_execution_id"] == body["id"]
            assert rec["output_snapshot"]["const"] == "v1"
            assert rec["output_snapshot"]["secret"] == "******", rec["output_snapshot"]

    def test_disabled_provider_test_refused(self, api, admin, db):
        with StubServer() as stub:
            pid, env_id, _aid, _iface = _stub_env(api, admin, db, stub)
            prov = _make_provider(
                api, admin, pid, provider_type="STATIC",
                config_json={"values": {"a": "b"}}, enabled=False,
            )
            r = api.post(
                f"/data-providers/{prov['id']}/test", username=admin,
                json={"environment_id": env_id, "variables": {}},
            )
            assert r.status_code == 400
            assert r.json().get("code") == "PROVIDER_DISABLED"

    def test_api_provider_test_masks_credentials(self, api, admin, db):
        """API_CREATE 试跑：成功返回提取值，请求/响应快照里的凭证已脱敏。"""
        with StubServer() as stub:
            stub.add("POST", "/login", 200, {
                "code": 0, "data": {"token": "tok-plain-123", "user_id": 9},
            })
            pid, env_id, _aid, iface = _stub_env(api, admin, db, stub)
            login_iface = iface("POST", "/login", "登录")
            prov = _make_provider(
                api, admin, pid, provider_type="API_CREATE",
                config_json={
                    "api_id": login_iface,
                    "body": {"username": "alice"},
                    "headers": {"Authorization": "***"},
                    "output_mappings": [
                        {"name": "token", "expression": "$.data.token"},
                        {"name": "user_id", "expression": "$.data.user_id"},
                    ],
                },
            )
            r = api.post(
                f"/data-providers/{prov['id']}/test", username=admin,
                json={"environment_id": env_id, "variables": {}},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "READY", body
            rec = body["provider_executions"][0]
            assert rec["status"] == "SUCCESS"
            assert rec["output_snapshot"]["user_id"] == 9
            # token 是敏感键：快照里必须脱敏。
            assert rec["output_snapshot"]["token"] == "******", rec["output_snapshot"]

    def test_business_flow_provider_reads_non_sensitive_variables(self, api, admin, db):
        """验收标准：调 execute_flow 后能读到非敏感变量。"""
        with StubServer() as stub:
            stub.add("POST", "/login", 200, {"code": 0, "data": {"token": "tok-flow", "user_id": 1}})
            stub.add("POST", "/projects", 200, {"code": 0, "data": {"id": 101, "name": "demo"}})
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"id": 2001, "title": "t1"}})
            stub.add_pattern("GET", re.compile(r"^/tasks/(\d+)$"),
                             lambda h, body, m: (200, {"code": 0, "data": {"id": int(m.group(1))}}))
            pid, env_id, admin_id, iface = _stub_env(api, admin, db, stub)
            ifaces = {
                "login": iface("POST", "/login", "登录"),
                "projects": iface("POST", "/projects", "创建项目"),
                "tasks": iface("POST", "/tasks", "创建任务"),
                "tasks_get": iface("GET", "/tasks/{id}", "查询任务"),
            }
            flow_id, _ = _build_login_flow(db, pid, ifaces)

            prov = _make_provider(
                api, admin, pid, provider_type="BUSINESS_FLOW",
                config_json={"business_flow_id": flow_id, "input_variables": {"task_seed": "seed-1"}},
            )
            r = api.post(
                f"/data-providers/{prov['id']}/test", username=admin,
                json={"environment_id": env_id, "variables": {}},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "READY", body
            rec = body["provider_executions"][0]
            assert rec["provider_type"] == "BUSINESS_FLOW"
            assert rec["status"] == "SUCCESS"
            outputs = rec["output_snapshot"] or {}
            # 非敏感变量读得回来。
            assert outputs["task_seed"] == "seed-1", outputs
            assert outputs["project_id"] == 101, outputs
            assert outputs["task_id"] == 2001, outputs
            assert outputs["flow_execution_id"], outputs
            # token 被脱敏，不该以明文出现在执行记录里。
            assert outputs.get("token") in ("******", None), outputs

    def test_business_action_provider_reads_outputs(self, api, admin, db):
        """BUSINESS_ACTION 走 run_action（不跑整条流程）。"""
        with StubServer() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"id": 3001, "title": "t"}})
            pid, env_id, admin_id, iface = _stub_env(api, admin, db, stub)
            task_iface = iface("POST", "/tasks", "创建任务")

            from app.features.business.models.business_domain import BusinessDomain
            from app.features.business.models.business_flow import BusinessFlow

            domain = BusinessDomain(project_id=pid, name=unique("domain"), status="ACTIVE")
            db.add(domain)
            db.flush()
            flow = BusinessFlow(project_id=pid, domain_id=domain.id,
                                name=unique("flow"), status="ACTIVE")
            db.add(flow)
            db.flush()
            action = _add_action(db, flow.id, "创建任务", "CREATE_TASK", 10)
            binding = _add_binding(db, action.id, task_iface)
            _add_mapping(db, binding.id, "OUTPUT", "task_id", "RESPONSE", expr="$.data.id")
            _add_output_var(db, action.id, "task_id")
            db.commit()

            prov = _make_provider(
                api, admin, pid, provider_type="BUSINESS_ACTION",
                config_json={"flow_id": flow.id, "action_key": "CREATE_TASK"},
            )
            r = api.post(
                f"/data-providers/{prov['id']}/test", username=admin,
                json={"environment_id": env_id, "variables": {}},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "READY", body
            rec = body["provider_executions"][0]
            assert rec["provider_type"] == "BUSINESS_ACTION"
            assert rec["status"] == "SUCCESS"
            assert (rec["output_snapshot"] or {}).get("task_id") == 3001, rec["output_snapshot"]
