"""验收项 18：测试数据中心 Phase A —— CRUD / 依赖 / 环检测 / 项目隔离 / DB 安全。

覆盖 §6.1–6.6 管理面（运行时执行见验收项 19）：
- Fixture CRUD + 步骤/输出契约 + 依赖边派生 + 环检测（A→B→C→A 失败、库中无环）
- 自依赖拒绝；输出契约唯一；跨项目私有 404；GLOBAL ACTIVE 可被引用
- Data Provider：config extra=forbid→422、顶层密码键→400、DATABASE_* 需平台管理员
- 测试数据目录 value_json 脱敏；数据池 payload 脱敏 + 占用/释放（service 层）
- 被测库连接：password 不回显；ping 只 SELECT 1；member 创建 403
- 数据库策略：PRODUCTION enabled=true → 400 DATABASE_ENVIRONMENT_FORBIDDEN
- 执行记录只读列表为空；head==0014

权限约定：读 viewer+，写 member+，DB 连接/策略写仅平台管理员；越权与不存在共用 404。
"""

from __future__ import annotations

from uuid import uuid4

from tests.conftest import (
    TEST_DB_HOST,
    TEST_DB_PASSWORD,
    TEST_DB_PORT,
    TEST_DB_USER,
    TEST_DATABASE_NAME,
    unique,
)

API = "/api/v1"


# --------------------------------------------------------------------------- 公共辅助


def _create_project(api, admin, name=None):
    r = api.post(
        "/projects", username=admin,
        json={"name": name or unique("proj"), "description": "test-data project"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _register_and_login(api, username):
    r = api.register(username)
    assert r.status_code == 201, r.text
    api.login(username, "Init-Password-123")
    return r.json()["user"]["id"]


def _add_member(api, admin, project_id, user_id, role="member"):
    r = api.put(
        f"/projects/{project_id}/members/{user_id}", username=admin,
        json={"user_id": user_id, "role": role},
    )
    assert r.status_code == 200, r.text


def _gkey(prefix: str) -> str:
    """全局唯一的 GLOBAL fixture_key：大写字母+数字+下划线，匹配 ^[A-Z][A-Z0-9_]{0,99}$。"""
    return f"{prefix}_{uuid4().hex[:8].upper()}"


def _make_fixture(api, admin, project_id, *, key, name=None, entity_type="USER",
                  scope="PROJECT", status="ACTIVE", steps=None, outputs=None,
                  dependencies=None):
    body = {
        "name": name or key, "fixture_key": key, "entity_type": entity_type,
        "scope": scope, "status": status, "cache_enabled": True,
        "cleanup_policy": "AFTER_CASE",
        "steps": steps or [], "outputs": outputs or [],
        "dependencies": dependencies or [],
    }
    r = api.post(f"/projects/{project_id}/fixtures", username=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _admin_id(db):
    from app.models.identity import User
    return db.query(User).filter(User.username == "platform_admin").first().id


def _get_or_create_env(db, name, admin_id):
    from app.models.configuration import Environment
    env = db.query(Environment).filter(Environment.name == name).first()
    if env is not None:
        return env.id
    env = Environment(
        name=name, display_name=name, base_url="https://example.com",
        gateway_prefix="", default_headers={}, is_active=True, created_by=admin_id,
    )
    db.add(env)
    db.commit()
    db.refresh(env)
    return env.id


# --------------------------------------------------------------------------- head & 表


class TestSchema:
    def test_head_is_0014_and_tables_present(self, db):
        from sqlalchemy import text
        head = db.execute(text("select version_num from alembic_version")).scalar()
        assert head == "0014"
        tables = {
            row[0]
            for row in db.execute(
                text(
                    "select table_name from information_schema.tables "
                    "where table_schema='public' and table_type='BASE TABLE'"
                )
            )
        }
        for t in (
            "fixture", "fixture_dependency", "fixture_step", "fixture_output",
            "data_provider", "test_data_asset", "data_pool", "data_pool_item",
            "data_pool_lease", "target_database_connection", "database_access_policy",
            "data_execution", "fixture_execution", "provider_execution",
            "fixture_cache", "test_case_fixture", "td_sandbox_task",
        ):
            assert t in tables, f"缺少表 {t}"


# --------------------------------------------------------------------------- Fixture CRUD


class TestFixtureCrud:
    def test_create_success_task_definition(self, api, admin):
        """SUCCESS_TASK 依赖 NORMAL_USER → ACTIVE_PROJECT；步骤只存 JSON 不执行。"""
        pid = _create_project(api, admin)
        _make_fixture(
            api, admin, pid, key="NORMAL_USER", entity_type="USER",
            outputs=[{"name": "user_id", "value_type": "INTEGER", "source_path": "$.data.id"}],
        )
        _make_fixture(
            api, admin, pid, key="ACTIVE_PROJECT", entity_type="PROJECT",
            outputs=[{"name": "project_id", "value_type": "INTEGER", "source_path": "$.data.id"}],
        )
        detail = _make_fixture(
            api, admin, pid, key="SUCCESS_TASK", entity_type="TASK",
            steps=[
                {"phase": "GENERATE", "step_type": "FIXTURE", "name": "need user",
                 "config_json": {"fixture_key": "NORMAL_USER"}},
                {"phase": "GENERATE", "step_type": "FIXTURE", "name": "need project",
                 "config_json": {"fixture_key": "ACTIVE_PROJECT"}},
            ],
            outputs=[{"name": "task_id", "value_type": "INTEGER", "source_path": "$.data.id"}],
        )
        # 两条 FIXTURE 步骤派生出两条依赖边。
        assert detail["dependency_count"] == 2
        assert {d["depends_on_key"] for d in detail["dependencies"]} == {"NORMAL_USER", "ACTIVE_PROJECT"}
        assert detail["generate_step_count"] == 2
        assert detail["output_names"] == ["task_id"]
        assert detail["referenced_case_count"] == 0

        # 列表里能找到。
        listed = api.get(f"/projects/{pid}/fixtures", username=admin).json()
        assert any(f["fixture_key"] == "SUCCESS_TASK" for f in listed["items"])

        # PATCH 改名。
        fid = detail["id"]
        patched = api.patch(
            f"/fixtures/{fid}", username=admin, json={"name": "成功任务v2"},
        ).json()
        assert patched["name"] == "成功任务v2"

    def test_duplicate_key_conflict(self, api, admin):
        pid = _create_project(api, admin)
        _make_fixture(api, admin, pid, key="DUP_KEY")
        r = api.post(
            f"/projects/{pid}/fixtures", username=admin,
            json={"name": "again", "fixture_key": "DUP_KEY", "entity_type": "USER"},
        )
        assert r.status_code == 409

    def test_bad_key_rejected(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/fixtures", username=admin,
            json={"name": "bad", "fixture_key": "lower_case", "entity_type": "USER"},
        )
        # Pydantic field_validator 在 422 拦下非法 key。
        assert r.status_code == 422

    def test_cross_project_private_fixture_404(self, api, admin):
        """B 项目的 viewer 访问 A 的私有 Fixture → 404（隐藏存在性）。"""
        pa = _create_project(api, admin)
        pb = _create_project(api, admin)
        detail = _make_fixture(api, admin, pa, key="A_FIXTURE")
        # bob 仅在 B 项目。
        bob_name = unique("bob")
        bob = _register_and_login(api, bob_name)
        _add_member(api, admin, pb, bob, role="viewer")
        r = api.get(f"/fixtures/{detail['id']}", username=bob_name)
        assert r.status_code == 404

    def test_global_fixture_visible_by_key_in_other_project(self, api, admin):
        """A 项目的 GLOBAL ACTIVE Fixture 可被 B 项目的 FIXTURE 步骤按 key 引用。"""
        pa = _create_project(api, admin)
        gkey = _gkey("GRO")
        _make_fixture(
            api, admin, pa, key=gkey, scope="GLOBAL", status="ACTIVE",
            outputs=[{"name": "gid", "value_type": "STRING", "source_path": "$.data.id"}],
        )
        pb = _create_project(api, admin)
        # B 里建一个 Fixture，FIXTURE 步骤引用 A 的 GLOBAL 键 → 成功。
        detail = _make_fixture(
            api, admin, pb, key="B_USES_GLOBAL", entity_type="TASK",
            steps=[{"phase": "GENERATE", "step_type": "FIXTURE", "name": "use global",
                    "config_json": {"fixture_key": gkey}}],
        )
        assert detail["dependency_count"] == 1
        assert detail["dependencies"][0]["depends_on_key"] == gkey

        # B 里引用 A 的「私有 CASE」Fixture → 404。
        priv = _make_fixture(api, admin, pa, key="A_PRIVATE", scope="CASE", status="ACTIVE")
        r = api.post(
            f"/projects/{pb}/fixtures", username=admin,
            json={
                "name": "uses private", "fixture_key": "B_USES_PRIVATE", "entity_type": "TASK",
                "steps": [{"phase": "GENERATE", "step_type": "FIXTURE", "name": "x",
                           "config_json": {"fixture_key": "A_PRIVATE"}}],
            },
        )
        assert r.status_code == 404
        assert r.json().get("code") == "FIXTURE_NOT_FOUND"

    def test_delete_blocked_when_referenced(self, api, admin):
        """被依赖的 Fixture 删除 → 409。"""
        pid = _create_project(api, admin)
        a = _make_fixture(api, admin, pid, key="DEP_A")
        b = _make_fixture(
            api, admin, pid, key="DEP_B",
            steps=[{"phase": "GENERATE", "step_type": "FIXTURE", "name": "x",
                    "config_json": {"fixture_key": "DEP_A"}}],
        )
        # DEP_B 依赖 DEP_A，删除 DEP_A → 409。
        assert api.delete(f"/fixtures/{a['id']}", username=admin).status_code == 409
        # 删掉 DEP_B 后再删 DEP_A → 204。
        assert api.delete(f"/fixtures/{b['id']}", username=admin).status_code == 204
        assert api.delete(f"/fixtures/{a['id']}", username=admin).status_code == 204


# --------------------------------------------------------------------------- 环检测


class TestFixtureCycle:
    def _abc(self, api, admin, pid):
        """建 A→B→C 合法链（C 无依赖、B 依赖 C、A 依赖 B）。"""
        _make_fixture(api, admin, pid, key="C_NODE")
        _make_fixture(
            api, admin, pid, key="B_NODE",
            steps=[{"phase": "GENERATE", "step_type": "FIXTURE", "name": "c",
                    "config_json": {"fixture_key": "C_NODE"}}],
        )
        a = _make_fixture(
            api, admin, pid, key="A_NODE",
            steps=[{"phase": "GENERATE", "step_type": "FIXTURE", "name": "b",
                    "config_json": {"fixture_key": "B_NODE"}}],
        )
        return a

    def test_cycle_rejected_no_dirty_edge(self, api, admin):
        """A→B→C→A 保存失败，且 C 不残留指向 A 的边。"""
        pid = _create_project(api, admin)
        a = self._abc(api, admin, pid)
        cid = next(
            f["id"] for f in
            api.get(f"/projects/{pid}/fixtures", username=admin).json()["items"]
            if f["fixture_key"] == "C_NODE"
        )
        # 让 C 反向依赖 A → 成环。
        r = api.put(
            f"/fixtures/{cid}/steps", username=admin,
            json={"steps": [
                {"phase": "GENERATE", "step_type": "FIXTURE", "name": "back to a",
                 "config_json": {"fixture_key": "A_NODE"}},
            ]},
        )
        assert r.status_code == 400
        body = r.json()
        assert body.get("code") == "FIXTURE_DEPENDENCY_CYCLE"
        msg = body.get("message", "")
        # 环上三个 key 都出现，且首尾重复。
        for key in ("A_NODE", "B_NODE", "C_NODE"):
            assert key in msg, msg
        # 库中无环：C 的依赖数仍为 0。
        c_detail = api.get(f"/fixtures/{cid}", username=admin).json()
        assert c_detail["dependency_count"] == 0

    def test_self_dependency_rejected(self, api, admin):
        pid = _create_project(api, admin)
        # 自引用必须 ACTIVE 才进得了「依赖目标需 ACTIVE」这道关，随后被自依赖环检测拦下。
        r = api.post(
            f"/projects/{pid}/fixtures", username=admin,
            json={
                "name": "self", "fixture_key": "SELF_NODE", "entity_type": "USER",
                "status": "ACTIVE",
                "steps": [{"phase": "GENERATE", "step_type": "FIXTURE", "name": "self",
                           "config_json": {"fixture_key": "SELF_NODE"}}],
            },
        )
        assert r.status_code == 400
        assert r.json().get("code") == "FIXTURE_DEPENDENCY_CYCLE"

    def test_dependency_tree_rendered(self, api, admin):
        pid = _create_project(api, admin)
        self._abc(api, admin, pid)
        aid = next(
            f["id"] for f in
            api.get(f"/projects/{pid}/fixtures", username=admin).json()["items"]
            if f["fixture_key"] == "A_NODE"
        )
        tree = api.get(f"/fixtures/{aid}/dependencies", username=admin).json()
        assert tree[0]["fixture_key"] == "A_NODE"
        # A → B → C
        assert tree[0]["children"][0]["fixture_key"] == "B_NODE"
        assert tree[0]["children"][0]["children"][0]["fixture_key"] == "C_NODE"


# --------------------------------------------------------------------------- 输出契约


class TestFixtureOutputs:
    def test_output_uniqueness(self, api, admin):
        pid = _create_project(api, admin)
        detail = _make_fixture(api, admin, pid, key="OUT_DUP")
        r = api.put(
            f"/fixtures/{detail['id']}/outputs", username=admin,
            json={"outputs": [
                {"name": "dup", "value_type": "STRING", "source_path": "$.a"},
                {"name": "dup", "value_type": "STRING", "source_path": "$.b"},
            ]},
        )
        assert r.status_code == 409

    def test_replace_outputs(self, api, admin):
        pid = _create_project(api, admin)
        detail = _make_fixture(api, admin, pid, key="OUT_OK")
        r = api.put(
            f"/fixtures/{detail['id']}/outputs", username=admin,
            json={"outputs": [
                {"name": "id", "value_type": "INTEGER", "source_path": "$.data.id"},
                {"name": "token", "value_type": "STRING", "source_path": "$.data.token"},
            ]},
        )
        assert r.status_code == 200
        names = {o["name"] for o in r.json()["outputs"]}
        assert names == {"id", "token"}


# --------------------------------------------------------------------------- Data Provider


class TestProvider:
    def test_static_provider_crud(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/data-providers", username=admin,
            json={"name": unique("prov"), "provider_type": "STATIC",
                  "config_json": {"values": {"a": 1}}, "enabled": True},
        )
        assert r.status_code == 201, r.text
        pid_ = r.json()["id"]
        # config 不含密码字段。
        assert "password" not in r.json()["config_json"]
        assert api.get(f"/data-providers/{pid_}", username=admin).status_code == 200
        assert api.post(f"/data-providers/{pid_}/disable", username=admin).status_code == 200
        assert api.post(f"/data-providers/{pid_}/enable", username=admin).status_code == 200
        assert api.delete(f"/data-providers/{pid_}", username=admin).status_code == 204

    def test_config_extra_key_rejected_422(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/data-providers", username=admin,
            json={"name": unique("prov"), "provider_type": "STATIC",
                  "config_json": {"values": {}, "sql": "SELECT 1"}, "enabled": True},
        )
        assert r.status_code == 422

    def test_config_top_level_password_rejected_400(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/data-providers", username=admin,
            json={"name": unique("prov"), "provider_type": "STATIC",
                  "config_json": {"values": {}, "password": "secret"}, "enabled": True},
        )
        assert r.status_code == 400

    def test_database_provider_requires_platform_admin(self, api, admin):
        pid = _create_project(api, admin)
        # 普通 member 建 DATABASE_INSERT → 403。
        bob_name = unique("bob")
        bob = _register_and_login(api, bob_name)
        _add_member(api, admin, pid, bob, role="member")
        r = api.post(
            f"/projects/{pid}/data-providers", username=bob_name,
            json={"name": unique("dbprov"), "provider_type": "DATABASE_INSERT",
                  "config_json": {"connection_id": 1, "table": "t", "operation": "INSERT"},
                  "enabled": True},
        )
        assert r.status_code == 403

    def test_provider_test_refuses_unknown_environment(self, api, admin):
        """环境不存在 → 404，而不是 400 stub（试跑逻辑见验收项 19）。"""
        pid = _create_project(api, admin)
        prov = api.post(
            f"/projects/{pid}/data-providers", username=admin,
            json={"name": unique("prov"), "provider_type": "STATIC",
                  "config_json": {"values": {}}, "enabled": True},
        ).json()
        r = api.post(
            f"/data-providers/{prov['id']}/test", username=admin,
            json={"environment_id": 999_999_999, "variables": {}},
        )
        assert r.status_code == 404


# --------------------------------------------------------------------------- 测试数据目录


class TestAsset:
    def test_value_masked_on_read(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/test-data-assets", username=admin,
            json={"name": unique("asset"), "entity_type": "USER", "source": "STATIC",
                  "scope": "PROJECT", "status": "ACTIVE",
                  "value_json": {"username": "alice", "password": "p@ss", "token": "xyz"}},
        )
        assert r.status_code == 201, r.text
        aid = r.json()["id"]
        body = api.get(f"/test-data-assets/{aid}", username=admin).json()
        assert body["value_json"]["password"] == "******"
        assert body["value_json"]["token"] == "******"
        assert body["value_json"]["username"] == "alice"

    def test_delete_asset(self, api, admin):
        pid = _create_project(api, admin)
        aid = api.post(
            f"/projects/{pid}/test-data-assets", username=admin,
            json={"name": unique("asset"), "entity_type": "USER", "source": "STATIC"},
        ).json()["id"]
        assert api.delete(f"/test-data-assets/{aid}", username=admin).status_code == 204
        assert api.get(f"/test-data-assets/{aid}", username=admin).status_code == 404


# --------------------------------------------------------------------------- 数据池


class TestPool:
    def test_pool_and_item_crud_with_masking(self, api, admin):
        pid = _create_project(api, admin)
        pool = api.post(
            f"/projects/{pid}/data-pools", username=admin,
            json={"name": unique("pool"), "pool_key": _gkey("POOL"),
                  "scope": "PROJECT", "max_concurrency": 1, "lease_ttl_seconds": 60,
                  "status": "ACTIVE"},
        ).json()
        # 加一条带密码的条目。
        item = api.post(
            f"/data-pools/{pool['id']}/items", username=admin,
            json={"payload_json": {"token": "secret", "ok": True}, "status": "AVAILABLE"},
        ).json()
        assert item["payload_json"]["token"] == "******"
        assert item["payload_json"]["ok"] is True
        # 列表脱敏。
        listed = api.get(f"/data-pools/{pool['id']}/items", username=admin).json()
        assert listed["items"][0]["payload_json"]["token"] == "******"
        # 池响应计数。
        pool_resp = api.get(f"/data-pools/{pool['id']}", username=admin).json()
        assert pool_resp["item_count"] == 1
        assert pool_resp["available_count"] == 1
        # 删除条目 → 池空。
        assert api.delete(f"/data-pool-items/{item['id']}", username=admin).status_code == 204
        assert api.delete(f"/data-pools/{pool['id']}", username=admin).status_code == 204

    def test_item_cannot_be_created_occupied(self, api, admin):
        pid = _create_project(api, admin)
        pool = api.post(
            f"/projects/{pid}/data-pools", username=admin,
            json={"name": unique("pool"), "pool_key": _gkey("POOL"), "status": "ACTIVE"},
        ).json()
        r = api.post(
            f"/data-pools/{pool['id']}/items", username=admin,
            json={"payload_json": {}, "status": "OCCUPIED"},
        )
        assert r.status_code == 400

    def test_acquire_release_and_exhaustion(self, db, admin):
        """service 层：占用/释放/耗尽，并发安全由行级锁保证。"""
        from app.features.test_data.models.pool import DataPool, DataPoolItem
        from app.features.test_data.services.pool_service import PoolService

        # 复用 platform_admin 拥有的项目：先建项目（直接 ORM，避免 HTTP 往返）。
        from app.models.identity import User, Organization
        from app.models.project import Project
        admin_user = db.query(User).filter(User.username == "platform_admin").first()
        org = db.query(Organization).filter(Organization.owner_id == admin_user.id).first()
        proj = Project(name=unique("proj"), organization_id=org.id if org else None,
                       owner_id=admin_user.id)
        db.add(proj)
        db.flush()
        db.commit()
        db.refresh(proj)

        pkey = _gkey("POOL")
        pool = DataPool(
            project_id=proj.id, pool_key=pkey, name="acquire test",
            scope="PROJECT", max_concurrency=1, lease_ttl_seconds=60, status="ACTIVE",
        )
        db.add(pool)
        db.commit()
        db.refresh(pool)
        db.add(DataPoolItem(pool_id=pool.id, status="AVAILABLE",
                            payload_json={"k": "v"}, occupied_count=0))
        db.commit()

        svc = PoolService()
        item_id, lease_id, payload = svc.acquire(
            db, project_id=proj.id, pool_key=pkey,
            test_run_id=None, case_execution_id=None,
        )
        assert payload == {"k": "v"}
        # 条目被占用，再 acquire → 耗尽 409。
        from app.shared.errors import AppError
        try:
            svc.acquire(db, project_id=proj.id, pool_key=pkey)
            raise AssertionError("应抛 DATA_POOL_EXHAUSTED")
        except AppError as exc:
            assert exc.status_code == 409
            assert exc.code == "DATA_POOL_EXHAUSTED"
        # 释放后可再次占用。
        svc.release(db, item_id=item_id, lease_id=lease_id)
        db.commit()
        item2_id, _, _ = svc.acquire(db, project_id=proj.id, pool_key=pkey)
        assert item2_id == item_id


# --------------------------------------------------------------------------- 被测库与策略


class TestTargetDbAndPolicy:
    def test_connection_password_not_echoed(self, api, admin, db):
        pid = _create_project(api, admin)
        env_id = _get_or_create_env(db, "dev", _admin_id(db))
        r = api.post(
            f"/projects/{pid}/target-databases", username=admin,
            json={
                "environment_id": env_id, "name": unique("conn"),
                "host": "127.0.0.1", "port": 5432, "database_name": "testplatform_dev",
                "username": "root", "password": "fangzhou123", "enabled": True,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert "password" not in body
        assert body["password_set"] is True
        assert body["environment_class"] == "DEV"
        # GET 也不回显。
        got = api.get(f"/target-databases/{body['id']}", username=admin).json()
        assert "password" not in got
        assert got["password_set"] is True

    def test_member_cannot_create_connection(self, api, admin, db):
        pid = _create_project(api, admin)
        env_id = _get_or_create_env(db, "dev", _admin_id(db))
        bob_name = unique("bob")
        bob = _register_and_login(api, bob_name)
        _add_member(api, admin, pid, bob, role="member")
        r = api.post(
            f"/projects/{pid}/target-databases", username=bob_name,
            json={"environment_id": env_id, "name": unique("conn"),
                  "host": "127.0.0.1", "port": 5432, "database_name": "x",
                  "username": "root", "password": "p"},
        )
        assert r.status_code == 403

    def test_ping_select_one(self, api, admin, db):
        pid = _create_project(api, admin)
        env_id = _get_or_create_env(db, "dev", _admin_id(db))
        # 指向测试夹具自身在用的库（必然可达），避免依赖容器是否初始化了 dev 库。
        conn = api.post(
            f"/projects/{pid}/target-databases", username=admin,
            json={"environment_id": env_id, "name": unique("conn"),
                  "host": TEST_DB_HOST, "port": int(TEST_DB_PORT),
                  "database_name": TEST_DATABASE_NAME,
                  "username": TEST_DB_USER, "password": TEST_DB_PASSWORD, "enabled": True},
        ).json()
        r = api.post(f"/target-databases/{conn['id']}/ping", username=admin)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert "latency_ms" in body

    def test_production_policy_refused(self, api, admin, db):
        pid = _create_project(api, admin)
        env_id = _get_or_create_env(db, "production", _admin_id(db))
        r = api.put(
            f"/projects/{pid}/database-policies/{env_id}", username=admin,
            json={"enabled": True, "allowed_tables": ["t"], "allowed_operations": ["INSERT"]},
        )
        assert r.status_code == 400
        assert r.json().get("code") == "DATABASE_ENVIRONMENT_FORBIDDEN"

    def test_dev_policy_upsert(self, api, admin, db):
        pid = _create_project(api, admin)
        env_id = _get_or_create_env(db, "dev", _admin_id(db))
        r = api.put(
            f"/projects/{pid}/database-policies/{env_id}", username=admin,
            json={"enabled": True, "allowed_tables": ["users", "orders"],
                  "allowed_operations": ["INSERT", "UPDATE", "SELECT"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["enabled"] is True
        assert body["environment_class"] == "DEV"
        assert set(body["allowed_tables"]) == {"users", "orders"}
        # 列表能查到。
        listed = api.get(f"/projects/{pid}/database-policies", username=admin).json()
        assert any(p["environment_class"] == "DEV" for p in listed["items"])


# --------------------------------------------------------------------------- 执行记录（只读）


class TestExecutionReadOnly:
    def test_list_empty(self, api, admin):
        pid = _create_project(api, admin)
        r = api.get(f"/projects/{pid}/data-executions", username=admin)
        assert r.status_code == 200
        assert r.json()["items"] == []
        assert r.json()["total"] == 0

    def test_get_not_found(self, api, admin):
        r = api.get("/data-executions/999999", username=admin)
        assert r.status_code == 404
