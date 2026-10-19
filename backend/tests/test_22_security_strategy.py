"""验收项 22：Security Testing Phase A —— 迁移、系统模板、设置与策略/规则 CRUD。

覆盖开发计划 §12 Phase A 与 §16.1：
- 迁移：head==0011、7 张 feature-local 表、两个部分唯一索引、ORM 与建表逐列对齐
- 降级：只删安全表，Mock（0010）表与数据保留，Mock API 继续可用
- 系统模板：8 套 SYSTEM 策略与规则由 0011 幂等插入，重复 upgrade 不重复插；
  预留攻击类不插可执行规则
- 项目设置：没有行则返回默认值且不插库；allow_production 存了也不生效
- 策略 CRUD：创建/列表筛选/详情带规则/修改（乐观锁）/删除级联
- 预留攻击类可以保存但 enabled 强制 false，不能重新启用
- 规则 CRUD：脚本键 400、未知键 400、期望与算子不匹配 400、状态码越界 400
- 系统内置策略与规则不可改不可删（403）
- 权限：viewer 只读、member 不能改策略、editor 可改、跨平台项目 404
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import inspect, text

from tests.conftest import (
    BACKEND_DIR,
    TEST_DSN,
    TEST_DATABASE_NAME,
    unique,
)

API = "/api/v1"

# 0011 建出的 7 张表。
SECURITY_TABLES = frozenset(
    {
        "security_project_setting",
        "security_strategy",
        "security_mutation_rule",
        "security_plan",
        "security_case",
        "security_execution",
        "security_finding",
    }
)

# 0010 建的 Mock 表：降级 0011 后必须原样保留。
MOCK_TABLES = frozenset(
    {
        "mock_service",
        "mock_endpoint",
        "mock_scenario",
        "mock_matcher",
        "mock_context",
        "mock_execution",
        "test_case_mock",
    }
)

# 系统模板清单：strategy_key → (category, 规则条数)。
BUILTIN_STRATEGIES = {
    "AUTH_BASIC": ("AUTHENTICATION", 6),
    "AUTHORIZATION_BASIC": ("AUTHORIZATION", 2),
    "IDOR_BASIC": ("IDOR", 1),
    "PARAMETER_BASIC": ("PARAMETER", 10),
    "HEADER_BASIC": ("HEADER", 4),
    "METHOD_BASIC": ("METHOD", 1),
    "REPLAY_BASIC": ("REPLAY", 1),
    "BUSINESS_STATE_BASIC": ("BUSINESS_STATE", 1),
}


# --------------------------------------------------------------------------- 公共辅助


def _create_project(api, admin, name=None):
    r = api.post(
        "/projects", username=admin,
        json={"name": name or unique("sec-proj"), "description": "security project"},
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _register(api, username):
    """注册并登录，返回 user_id；username 同时是 api 调用键。"""
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


def _user(api, admin, project_id, prefix, role="member"):
    """注册一个新用户并加进项目，返回登录用户名（同时也是 api 调用键）。"""
    username = unique(prefix)
    _register(api, username)
    _add_member(api, admin, project_id, _user_id(username), role)
    return username


def _user_id(username):
    """按用户名取 user_id：注册接口只在 201 时返回一次，这里回查一遍。"""
    from app.models.identity import User
    from app.shared.database import SessionLocal

    with SessionLocal() as session:
        return session.query(User).filter(User.username == username).one().id


def _skey(prefix="PROJ"):
    """strategy_key：^[A-Z][A-Z0-9_]{0,99}$。"""
    return f"{prefix}_{uuid4().hex[:8].upper()}"


def _rule_body(
    *,
    name=None,
    mutation_type="REMOVE_TOKEN",
    target_location="HEADER",
    target_field="Authorization",
    mutation_config=None,
    expected=None,
    codes=None,
    severity="MEDIUM",
    enabled=True,
    confirmation_required=False,
):
    """一条合法的安全变异规则请求体。"""
    return {
        "name": name or f"规则-{mutation_type}",
        "mutation_type": mutation_type,
        "target_location": target_location,
        "target_field": target_field,
        "mutation_config": mutation_config or {},
        "expected_security_behavior": expected,
        "expected_status_codes": codes if codes is not None else [401, 403],
        "severity": severity,
        "enabled": enabled,
        "confirmation_required": confirmation_required,
    }


def _create_strategy(api, actor, project_id, *, key=None, category="AUTHENTICATION",
                     rules=None, enabled=True, name=None, risk_level="MEDIUM"):
    body = {
        "name": name or (key or unique("sec")),
        "strategy_key": key or _skey(),
        "category": category,
        "description": "Phase A 测试策略",
        "enabled": enabled,
        "risk_level": risk_level,
        "rules": rules if rules is not None else [_rule_body()],
    }
    r = api.post(
        f"/projects/{project_id}/security-strategies", username=actor, json=body,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _tables(db):
    return {
        row[0]
        for row in db.execute(
            text(
                "select table_name from information_schema.tables "
                "where table_schema = 'public'"
            )
        )
    }


def _indexes(db):
    return {
        row[0]
        for row in db.execute(text("select indexname from pg_indexes where schemaname='public'"))
    }


def _alembic(config=None):
    """返回一个指向隔离测试库的 Alembic 配置，供用例自己升降级。"""
    from alembic.config import Config

    if config is not None:
        return config
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", TEST_DSN)
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return config


# --------------------------------------------------------------------------- 迁移与模板


class TestMigration:
    def test_head_is_0011_and_tables_created(self, db):
        head = db.execute(text("select version_num from alembic_version")).scalar()
        assert head == "0012"
        assert SECURITY_TABLES.issubset(_tables(db))

    def test_partial_unique_indexes(self, db):
        """部分唯一索引：SYSTEM strategy_key 唯一；OPEN/CONFIRMED fingerprint 唯一。"""
        indexes = _indexes(db)
        assert "uq_security_strategy_system_key" in indexes
        assert "uq_security_finding_open_fingerprint" in indexes
        assert "uq_security_setting_project" in indexes
        assert "uq_security_strategy_project_key" in indexes
        assert "uq_security_case_test_case" in indexes
        assert "uq_security_execution_case" in indexes

    def test_orm_matches_migrated_schema(self, db):
        """ORM 模型与迁移逐列对齐：feature-local 表不进 models/__init__，靠这个断言防漂移。"""
        from app.features.security_testing.models import (
            SecurityCase,
            SecurityExecution,
            SecurityFinding,
            SecurityMutationRule,
            SecurityPlan,
            SecurityProjectSetting,
            SecurityStrategy,
        )

        models = {
            SecurityProjectSetting, SecurityStrategy, SecurityMutationRule,
            SecurityPlan, SecurityCase, SecurityExecution, SecurityFinding,
        }
        inspector = inspect(db.bind)
        live_indexes = _indexes(db)
        for model in models:
            table = model.__table__
            assert table.name in SECURITY_TABLES
            assert {c["name"] for c in inspector.get_columns(table.name)} == {
                c.name for c in table.columns
            }
            expected = {
                constraint.name for constraint in table.constraints if constraint.name
            } | {index.name for index in table.indexes if index.name}
            missing = expected - live_indexes
            assert not missing, f"{table.name} 缺索引: {sorted(missing)}"

    def test_models_not_reexported_from_app_models(self):
        """红线 17：安全模型不得被 app/models/__init__.py 反向 import。"""
        from pathlib import Path

        init_source = Path("app/models/__init__.py").read_text(encoding="utf-8")
        assert "security_testing" not in init_source
        for table in SECURITY_TABLES:
            assert table not in init_source

    def test_downgrade_removes_only_security_tables(self, db):
        """downgrade -1 只删 7 张安全表：Mock 表与数据保留，升级后 head 回到 0011。"""
        from alembic import command

        config = _alembic()
        try:
            command.downgrade(config, "0010")
            tables = _tables(db)
            assert not (SECURITY_TABLES & tables), tables
            assert MOCK_TABLES.issubset(tables), tables
            head = db.execute(text("select version_num from alembic_version")).scalar()
            assert head == "0010"
        finally:
            command.upgrade(config, "head")

        assert _tables(db) >= SECURITY_TABLES
        assert db.execute(text("select version_num from alembic_version")).scalar() == "0012"


class TestBuiltinStrategies:
    def test_builtin_strategies_seeded(self, db):
        rows = db.execute(
            text("select strategy_key, category, scope, builtin, enabled, project_id "
                 "from security_strategy where project_id is null order by strategy_key")
        ).fetchall()
        assert {r[0]: (r[1], r[2], r[3], r[4], r[5]) for r in rows} == {
            key: (category, "SYSTEM", True, True, None)
            for key, (category, _count) in BUILTIN_STRATEGIES.items()
        }
        assert len(rows) == len(BUILTIN_STRATEGIES)

    def test_builtin_rule_counts(self, db):
        got = {
            s_key: count
            for s_key, count in db.execute(
                text(
                    "select s.strategy_key, count(r.id) from security_strategy s "
                    "join security_mutation_rule r on r.strategy_id = s.id "
                    "where s.project_id is null group by s.strategy_key"
                )
            )
        }
        assert got == {key: count for key, (_c, count) in BUILTIN_STRATEGIES.items()}

    def test_reserved_categories_get_no_builtin_strategy_or_rule(self, db):
        """预留攻击类只保留枚举位，不插系统策略，也不插任何可执行规则。"""
        reserved = ("INJECTION", "RATE_LIMIT", "UPLOAD", "SSRF")
        keys = db.execute(
            text("select category from security_strategy where project_id is null")
        ).fetchall()
        assert not {k[0] for k in keys} & set(reserved)
        assert db.execute(
            text("select count(*) from security_mutation_rule where strategy_id in "
                 "(select id from security_strategy where category in "
                 "('INJECTION','RATE_LIMIT','UPLOAD','SSRF'))")
        ).scalar() == 0

    def test_parameter_basic_rules_are_fieldless_templates(self, db):
        """PARAMETER_BASIC 的规则 target_field 为空：执行前按 Schema 展开，不在模板里写死字段。"""
        rows = db.execute(
            text("select target_field from security_mutation_rule where strategy_id = "
                 "(select id from security_strategy where strategy_key='PARAMETER_BASIC')")
        ).fetchall()
        assert rows and all(r[0] is None for r in rows)

    def test_migration_insert_is_idempotent(self, db):
        from app.features.security_testing.builtins import ensure_builtin_strategies

        before = db.execute(text("select count(*) from security_strategy")).scalar()
        before_rules = db.execute(text("select count(*) from security_mutation_rule")).scalar()
        db.commit()

        with db.bind.begin() as conn:
            assert ensure_builtin_strategies(conn) == 0
        assert db.execute(text("select count(*) from security_strategy")).scalar() == before
        assert db.execute(text("select count(*) from security_mutation_rule")).scalar() == before_rules

    def test_builtin_rules_have_no_script_keys(self, db):
        rows = db.execute(
            text("select mutation_config from security_mutation_rule where strategy_id in "
                 "(select id from security_strategy where project_id is null)")
        ).fetchall()
        assert rows
        for (config,) in rows:
            assert not set(config or {}) & {"script", "python", "sql", "shell", "command"}


# --------------------------------------------------------------------------- 项目设置


class TestSecuritySetting:
    def test_get_returns_defaults_without_insert(self, api, admin, db):
        pid = _create_project(api, admin)
        assert db.execute(
            text("select count(*) from security_project_setting")
        ).scalar() == 0

        r = api.get(f"/projects/{pid}/security-setting", username=admin)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["project_id"] == pid
        assert body["allow_dev"] is True
        assert body["allow_test"] is True
        assert body["allow_staging"] is False
        assert body["allow_production"] is False
        assert body["production_enforced"] is False
        # 只读请求不能偷偷留下配置行。
        assert db.execute(
            text("select count(*) from security_project_setting")
        ).scalar() == 0

    def test_update_then_conflict_on_stale_revision(self, api, admin):
        pid = _create_project(api, admin)
        r = api.put(
            f"/projects/{pid}/security-setting", username=admin,
            json={"allow_staging": True},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["allow_staging"] is True
        assert body["revision"] == 2

        stale = api.put(
            f"/projects/{pid}/security-setting", username=admin,
            json={"allow_staging": False, "revision": 1},
        )
        assert stale.status_code == 409

        ok = api.put(
            f"/projects/{pid}/security-setting", username=admin,
            json={"allow_staging": False, "revision": 2},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["allow_staging"] is False
        assert ok.json()["revision"] == 3

    def test_allow_production_stored_but_never_effective(self, api, admin, db):
        """allow_production 照存但永不生效：响应始终 production_enforced=false。"""
        pid = _create_project(api, admin)
        r = api.put(
            f"/projects/{pid}/security-setting", username=admin,
            json={"allow_production": True},
        )
        assert r.status_code == 200, r.text
        assert r.json()["allow_production"] is True
        assert r.json()["production_enforced"] is False

        stored = db.execute(
            text("select allow_production from security_project_setting where project_id=:p"),
            {"p": pid},
        ).scalar_one()
        assert stored is True
        assert api.get(
            f"/projects/{pid}/security-setting", username=admin
        ).json()["production_enforced"] is False

    def test_viewer_cannot_update_setting(self, api, admin):
        pid = _create_project(api, admin)
        viewer = _user(api, admin, pid, "sec-viewer", "viewer")
        r = api.put(
            f"/projects/{pid}/security-setting", username=viewer,
            json={"allow_staging": True},
        )
        assert r.status_code == 403


# --------------------------------------------------------------------------- 策略 CRUD


class TestStrategyCrud:
    def test_create_list_get_update_delete(self, api, admin):
        pid = _create_project(api, admin)
        key = _skey()
        created = _create_strategy(
            api, admin, pid, key=key, category="AUTHORIZATION",
            rules=[_rule_body(mutation_type="CROSS_USER", target_field="Authorization"),
                   _rule_body(name="参数边界", mutation_type="REMOVE_FIELD",
                              target_location="BODY", target_field="title",
                              expected="EXPECTED_VALIDATION_ERROR", codes=[400, 422])],
        )
        assert created["scope"] == "PROJECT"
        assert created["project_id"] == pid
        assert created["builtin"] is False
        assert created["revision"] == 1
        assert len(created["rules"]) == 2
        # 期望缺省时按算子推导。
        assert created["rules"][0]["expected_security_behavior"] == "EXPECTED_DENY"

        listed = api.get(f"/projects/{pid}/security-strategies", username=admin)
        assert listed.status_code == 200, listed.text
        assert any(s["id"] == created["id"] for s in listed.json()["items"])

        got = api.get(f"/security-strategies/{created['id']}", username=admin)
        assert got.status_code == 200
        assert got.json()["rules"][1]["name"] == "参数边界"

        updated = api.patch(
            f"/security-strategies/{created['id']}", username=admin,
            json={"enabled": False, "risk_level": "LOW", "revision": 1},
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["enabled"] is False and body["risk_level"] == "LOW"
        assert body["revision"] == 2

        # 删除策略同时级联删掉规则。
        deleted = api.delete(f"/security-strategies/{created['id']}", username=admin)
        assert deleted.status_code == 204
        assert api.get(f"/security-strategies/{created['id']}", username=admin).status_code == 404

    def test_list_filters(self, api, admin):
        pid = _create_project(api, admin)
        _create_strategy(api, admin, pid, category="AUTHENTICATION")
        _create_strategy(api, admin, pid, category="PARAMETER", enabled=False)

        by_category = api.get(
            f"/projects/{pid}/security-strategies", username=admin,
            params={"category": "PARAMETER"},
        )
        assert by_category.status_code == 200
        items = [i for i in by_category.json()["items"] if i["project_id"] == pid]
        assert items and all(i["category"] == "PARAMETER" for i in items)

        by_enabled = api.get(
            f"/projects/{pid}/security-strategies", username=admin,
            params={"enabled": "false"},
        )
        assert by_enabled.status_code == 200
        own = [i for i in by_enabled.json()["items"] if i["project_id"] == pid]
        assert own and all(i["enabled"] is False for i in own)

    def test_list_includes_system_templates(self, api, admin):
        pid = _create_project(api, admin)
        _create_strategy(api, admin, pid, category="AUTHENTICATION")
        items = api.get(f"/projects/{pid}/security-strategies", username=admin,
                        params={"page_size": 100}).json()["items"]
        assert {s["strategy_key"] for s in items} >= set(BUILTIN_STRATEGIES)
        assert {s["scope"] for s in items} >= {"SYSTEM", "PROJECT"}

    def test_duplicate_strategy_key_conflict(self, api, admin):
        pid = _create_project(api, admin)
        key = _skey()
        _create_strategy(api, admin, pid, key=key)
        r = api.post(
            f"/projects/{pid}/security-strategies", username=admin,
            json={"name": "重复", "strategy_key": key, "category": "AUTHENTICATION"},
        )
        assert r.status_code == 409

    def test_stale_revision_conflict(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid)
        r = api.patch(
            f"/security-strategies/{created['id']}", username=admin,
            json={"revision": 99, "name": "改不动"},
        )
        assert r.status_code == 409

    def test_empty_patch_is_noop(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid)
        r = api.patch(f"/security-strategies/{created['id']}", username=admin, json={})
        assert r.status_code == 200, r.text
        assert r.json()["revision"] == created["revision"]


class TestReservedCategory:
    def test_create_reserved_forces_enabled_false(self, api, admin, db):
        pid = _create_project(api, admin)
        created = _create_strategy(
            api, admin, pid, category="INJECTION", enabled=True,
            rules=[_rule_body(mutation_type="METHOD_MUTATION", target_location="METHOD",
                              target_field=None)],
        )
        assert created["enabled"] is False
        assert created["rules"][0]["enabled"] is False

        row = db.execute(
            text("select enabled from security_strategy where id=:i"), {"i": created["id"]}
        ).scalar_one()
        assert row is False

    def test_reserved_strategy_cannot_be_enabled(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid, category="SSRF", enabled=False)
        r = api.patch(
            f"/security-strategies/{created['id']}", username=admin,
            json={"enabled": True, "revision": created["revision"]},
        )
        assert r.status_code == 403

    def test_reserved_rule_cannot_be_enabled(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid, category="RATE_LIMIT", enabled=False)
        rule = created["rules"][0]
        r = api.patch(
            f"/security-rules/{rule['id']}", username=admin,
            json={"enabled": True},
        )
        assert r.status_code == 403

    def test_reserved_rule_can_be_disabled(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid, category="UPLOAD")
        rule = created["rules"][0]
        r = api.patch(
            f"/security-rules/{rule['id']}", username=admin,
            json={"enabled": False},
        )
        assert r.status_code == 200, r.text
        assert r.json()["enabled"] is False

    def test_builtin_adds_no_rule_to_reserved_strategy(self, api, admin):
        """预留类别策略是用户自己建的，系统不会往里补规则。"""
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid, category="INJECTION", rules=[])
        assert created["rules"] == []


# --------------------------------------------------------------------------- 规则 CRUD


class TestRuleCrud:
    def test_create_rule_under_strategy(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        r = api.post(
            f"/security-strategies/{strategy['id']}/rules", username=admin,
            json=_rule_body(mutation_type="INVALID_TOKEN", expected="EXPECTED_DENY"),
        )
        assert r.status_code == 201, r.text
        rule = r.json()
        assert rule["project_id"] == pid
        assert rule["strategy_id"] == strategy["id"]
        assert rule["operator"] == "INVALID_TOKEN"
        assert rule["mutation_config"] == {}

        detail = api.get(f"/security-strategies/{strategy['id']}", username=admin).json()
        assert len(detail["rules"]) == 1

    def test_script_keys_rejected(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        for bad in ("script", "python", "sql", "shell", "command", "payload_file"):
            r = api.post(
                f"/security-strategies/{strategy['id']}/rules", username=admin,
                json=_rule_body(mutation_config={bad: "select * from user"}),
            )
            assert r.status_code == 400, (bad, r.text)
            assert r.json()["code"] == "SECURITY_MUTATION_INVALID"

    def test_nested_script_key_rejected(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        r = api.post(
            f"/security-strategies/{strategy['id']}/rules", username=admin,
            json=_rule_body(mutation_config={"token_source": {"script": "x"}}),
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_MUTATION_INVALID"

    def test_unknown_config_key_rejected(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        r = api.post(
            f"/security-strategies/{strategy['id']}/rules", username=admin,
            json=_rule_body(mutation_config={"not_a_real_key": 1}),
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_MUTATION_INVALID"

    def test_unsupported_mutation_type_rejected(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        r = api.post(
            f"/security-strategies/{strategy['id']}/rules", username=admin,
            json=_rule_body(mutation_type="SOMETHING_NEW"),
        )
        assert r.status_code == 422, r.text

    def test_expectation_mismatch_rejected(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        r = api.post(
            f"/security-strategies/{strategy['id']}/rules", username=admin,
            json=_rule_body(mutation_type="REMOVE_TOKEN",
                            expected="EXPECTED_IDEMPOTENT"),
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_EXPECTATION_INVALID"

    def test_unknown_expectation_rejected(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        r = api.post(
            f"/security-strategies/{strategy['id']}/rules", username=admin,
            json=_rule_body(mutation_type="REMOVE_TOKEN", expected="VOLNERABLE"),
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_EXPECTATION_INVALID"

    def test_status_code_out_of_range_rejected(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        r = api.post(
            f"/security-strategies/{strategy['id']}/rules", username=admin,
            json=_rule_body(codes=[99]),
        )
        assert r.status_code == 422, r.text

    def test_replay_count_capped(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid, rules=[])
        for bad in (1, 4, 100):
            r = api.post(
                f"/security-strategies/{strategy['id']}/rules", username=admin,
                json=_rule_body(mutation_type="REPLAY_SAME_REQUEST",
                                target_location="REQUEST", target_field=None,
                                codes=[200, 409],
                                mutation_config={"replay_count": bad}),
            )
            assert r.status_code == 400, (bad, r.text)

    def test_update_and_delete_rule(self, api, admin):
        pid = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid)
        rule_id = strategy["rules"][0]["id"]

        updated = api.patch(
            f"/security-rules/{rule_id}", username=admin,
            json={"name": "改名", "enabled": False, "sort": 5},
        )
        assert updated.status_code == 200, updated.text
        body = updated.json()
        assert body["name"] == "改名" and body["enabled"] is False and body["sort"] == 5

        assert api.delete(f"/security-rules/{rule_id}", username=admin).status_code == 204
        assert api.patch(
            f"/security-rules/{rule_id}", username=admin, json={"name": "再来一次"}
        ).status_code == 404

    def test_update_rule_validation_follows_final_type(self, api, admin):
        """改 mutation_type 之后，期望按新算子校验。"""
        pid = _create_project(api, admin)
        strategy = _create_strategy(
            api, admin, pid,
            rules=[_rule_body(mutation_type="REMOVE_TOKEN", target_field="Authorization")],
        )
        rule_id = strategy["rules"][0]["id"]
        r = api.patch(
            f"/security-rules/{rule_id}", username=admin,
            json={"mutation_type": "REPLAY_SAME_REQUEST",
                  "expected_security_behavior": "EXPECTED_DENY"},
        )
        assert r.status_code == 400, r.text
        assert r.json()["code"] == "SECURITY_EXPECTATION_INVALID"


# --------------------------------------------------------------------------- 系统模板只读


class TestBuiltinReadonly:
    def test_builtin_strategy_is_read_only(self, api, admin, db):
        strategy_id = db.execute(
            text("select id from security_strategy where strategy_key='AUTH_BASIC'")
        ).scalar_one()
        assert api.get(f"/security-strategies/{strategy_id}", username=admin).status_code == 200

        patch = api.patch(
            f"/security-strategies/{strategy_id}", username=admin,
            json={"name": "改系统模板", "revision": 1},
        )
        assert patch.status_code == 403
        delete = api.delete(f"/security-strategies/{strategy_id}", username=admin)
        assert delete.status_code == 403
        add_rule = api.post(
            f"/security-strategies/{strategy_id}/rules", username=admin,
            json=_rule_body(),
        )
        assert add_rule.status_code == 403

        # 行还在，内容没被改。
        assert db.execute(
            text("select name, builtin from security_strategy where id=:i"),
            {"i": strategy_id},
        ).one()[:2] == ("认证基础检查", True)

    def test_builtin_rule_is_read_only(self, api, admin, db):
        rule_id = db.execute(
            text("select r.id from security_mutation_rule r "
                 "join security_strategy s on s.id = r.strategy_id "
                 "where s.strategy_key='AUTH_BASIC' order by r.id limit 1")
        ).scalar_one()
        patch = api.patch(f"/security-rules/{rule_id}", username=admin, json={"enabled": False})
        assert patch.status_code == 403
        assert api.delete(f"/security-rules/{rule_id}", username=admin).status_code == 403
        assert db.execute(
            text("select enabled from security_mutation_rule where id=:i"),
            {"i": rule_id},
        ).scalar_one() is True


# --------------------------------------------------------------------------- 权限与隔离


class TestPermissions:
    def test_viewer_can_read_not_write(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid)
        viewer = _user(api, admin, pid, "sec-viewer", "viewer")

        assert api.get(f"/projects/{pid}/security-strategies", username=viewer).status_code == 200
        assert api.get(f"/security-strategies/{created['id']}", username=viewer).status_code == 200
        assert api.post(
            f"/projects/{pid}/security-strategies", username=viewer,
            json={"name": "x", "strategy_key": _skey(), "category": "AUTHENTICATION"},
        ).status_code == 403
        assert api.patch(
            f"/security-strategies/{created['id']}", username=viewer, json={"enabled": False}
        ).status_code == 403
        assert api.delete(f"/security-strategies/{created['id']}", username=viewer).status_code == 403

    def test_member_can_read_but_not_manage(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid)
        member = _user(api, admin, pid, "sec-member", "member")

        assert api.get(f"/security-strategies/{created['id']}", username=member).status_code == 200
        assert api.post(
            f"/projects/{pid}/security-strategies", username=member,
            json={"name": "x", "strategy_key": _skey(), "category": "AUTHENTICATION"},
        ).status_code == 403
        assert api.patch(
            f"/security-strategies/{created['id']}", username=member, json={"enabled": False}
        ).status_code == 403
        assert api.delete(f"/security-strategies/{created['id']}", username=member).status_code == 403
        assert api.patch(
            f"/security-rules/{created['rules'][0]['id']}", username=member,
            json={"enabled": False},
        ).status_code == 403

    def test_editor_can_manage(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid)
        editor = _user(api, admin, pid, "sec-editor", "editor")

        made = api.post(
            f"/projects/{pid}/security-strategies", username=editor,
            json={"name": "编辑者的策略", "strategy_key": _skey(), "category": "PARAMETER"},
        )
        assert made.status_code == 201, made.text
        assert api.patch(
            f"/security-strategies/{created['id']}", username=editor,
            json={"enabled": False, "revision": created["revision"]},
        ).status_code == 200
        assert api.patch(
            f"/security-rules/{created['rules'][0]['id']}", username=editor,
            json={"enabled": False},
        ).status_code == 200

    def test_platform_admin_can_manage_any_project(self, api, admin):
        pid = _create_project(api, admin)
        created = _create_strategy(api, admin, pid)
        r = api.patch(
            f"/security-strategies/{created['id']}", username=admin,
            json={"revision": created["revision"], "description": "平台管理员改"},
        )
        assert r.status_code == 200, r.text

    def test_cross_project_is_hidden_as_not_found(self, api, admin):
        pid_a = _create_project(api, admin)
        pid_b = _create_project(api, admin)
        strategy = _create_strategy(api, admin, pid_a)
        outsider = _user(api, admin, pid_b, "sec-outsider", "editor")

        assert api.get(
            f"/security-strategies/{strategy['id']}", username=outsider
        ).status_code == 404
        assert api.patch(
            f"/security-strategies/{strategy['id']}", username=outsider,
            json={"enabled": False},
        ).status_code == 404
        assert api.delete(
            f"/security-strategies/{strategy['id']}", username=outsider
        ).status_code == 404
        assert api.patch(
            f"/security-rules/{strategy['rules'][0]['id']}", username=outsider,
            json={"enabled": False},
        ).status_code == 404
        assert api.delete(
            f"/security-rules/{strategy['rules'][0]['id']}", username=outsider
        ).status_code == 404
        assert api.get(
            f"/projects/{pid_a}/security-strategies", username=outsider
        ).status_code == 404
        assert api.put(
            f"/projects/{pid_a}/security-setting", username=outsider,
            json={"allow_staging": True},
        ).status_code == 404

    def test_delete_isolated_per_project(self, api, admin):
        """删 A 项目的策略不会动 B 项目的策略与规则。"""
        pid_a = _create_project(api, admin)
        pid_b = _create_project(api, admin)
        sa_ = _create_strategy(api, admin, pid_a)
        sb = _create_strategy(api, admin, pid_b)
        assert api.delete(f"/security-strategies/{sa_['id']}", username=admin).status_code == 204
        detail = api.get(f"/security-strategies/{sb['id']}", username=admin)
        assert detail.status_code == 200
        assert len(detail.json()["rules"]) == 1


# --------------------------------------------------------------------------- 校验失败与错误码


class TestValidation:
    def test_invalid_category_rejected(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/security-strategies", username=admin,
            json={"name": "x", "strategy_key": _skey(), "category": "CROSS_SIDE_SCRIPTING"},
        )
        assert r.status_code == 422, r.text

    def test_bad_strategy_key_rejected(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/security-strategies", username=admin,
            json={"name": "x", "strategy_key": "lower_case", "category": "AUTHENTICATION"},
        )
        assert r.status_code == 422, r.text

    def test_bad_risk_level_rejected(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/security-strategies", username=admin,
            json={"name": "x", "strategy_key": _skey(), "category": "AUTHENTICATION",
                  "risk_level": "EXTREME"},
        )
        assert r.status_code == 422, r.text

    def test_bad_target_location_rejected(self, api, admin):
        pid = _create_project(api, admin)
        r = api.post(
            f"/projects/{pid}/security-strategies", username=admin,
            json={"name": "x", "strategy_key": _skey(), "category": "HEADER",
                  "rules": [_rule_body(target_location="COOKIE")]},
        )
        assert r.status_code == 422, r.text

    def test_missing_ids_are_not_found(self, api, admin):
        assert api.get("/projects/999999/security-strategies", username=admin).status_code == 404
        assert api.get("/security-strategies/999999", username=admin).status_code == 404
        assert api.patch(
            "/security-strategies/999999", username=admin, json={"enabled": False}
        ).status_code == 404
        assert api.patch(
            "/security-rules/999999", username=admin, json={"enabled": False}
        ).status_code == 404

    def test_unauthenticated_rejected(self, api):
        assert api.get("/projects/1/security-strategies").status_code == 401

    def test_finding_partial_index_only_covers_open_status(self, db):
        """fingerprint 唯一索引只覆盖 OPEN/CONFIRMED：关闭后不再阻塞同指纹的新 Finding。"""
        index_def = db.execute(
            text(
                "select indexdef from pg_indexes "
                "where indexname='uq_security_finding_open_fingerprint'"
            )
        ).scalar_one()
        lowered = index_def.lower()
        assert "where" in lowered
        assert "'open'" in lowered and "'confirmed'" in lowered
