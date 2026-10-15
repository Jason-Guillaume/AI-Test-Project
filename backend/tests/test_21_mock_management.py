"""验收项 21：Mock Management Phase 1 —— 接口 Mock 与依赖异常模拟。

覆盖 spec §四–§三十四 的管理与执行面：
- Mock Service CRUD + Runtime Token（一次性明文 / 只存哈希 / 重置失效 / 乐观锁 / 权限）
- Mock Endpoint CRUD + (method,path) 唯一 + 跨项目 404
- Mock Scenario + Matcher CRUD + 默认场景唯一 + 复制 + 试跑
- 全部行为类型：正常返回 / 4xx / 5xx / 空体 / 延迟 / 超时 / 响应头差异 / 模板占位符
- 匹配优先级：Context Override > Explicit Matcher > Default Scenario
- 并发隔离：MockContext 行级隔离，不同 Case 互不可见；关闭后回退
- 执行面分离：X-Mock-Token 鉴权（不要求平台 JWT）/ public_runtime / 每次调用落记录
- 敏感脱敏：调用记录的请求头 / 请求体敏感字段掩码
- API Catalog 一键创建 Mock（复用 / 多模板 / NORMAL 设默认）
- 禁止任意代码执行：只做结构化占位符替换，注入串不被求值
- TestCaseMock 声明 CRUD + 跨项目归属校验

权限约定：读 viewer+，写 member+，MockService 创建/删除/重置 Token 需 editor+；
越权与不存在共用 404。执行面 catch-all 不要求平台 JWT，鉴权走 X-Mock-Token。
"""

from __future__ import annotations

import time
from uuid import uuid4

from tests.conftest import unique

API = "/api/v1"


# --------------------------------------------------------------------------- 公共辅助


def _create_project(api, admin, name=None):
    r = api.post(
        "/projects", username=admin,
        json={"name": name or unique("proj"), "description": "mock project"},
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


def _skey(prefix="SVC"):
    """service_key / scenario_key：^[A-Z][A-Z0-9_]{0,99}$。"""
    return f"{prefix}_{uuid4().hex[:6].upper()}"


def _create_service(api, admin, project_id, key, *, public_runtime=False, token=None, name=None):
    body = {"name": name or key, "service_key": key, "public_runtime": public_runtime}
    if token is not None:
        body["runtime_token"] = token
    r = api.post(f"/projects/{project_id}/mock-services", username=admin, json=body)
    assert r.status_code == 201, r.text
    return r.json()  # {service, runtime_token}


def _create_endpoint(api, admin, service_id, *, method="GET", path="/items", name=None):
    r = api.post(
        f"/mock-services/{service_id}/endpoints", username=admin,
        json={"name": name or path, "method": method, "path": path},
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_scenario(
    api, admin, endpoint_id, key, *,
    behavior_type="STATIC_RESPONSE", status_code=200, body=None, template=None,
    delay_ms=None, headers=None, matchers=None, is_default=False, priority=0,
):
    payload = {
        "name": key, "scenario_key": key, "behavior_type": behavior_type,
        "status_code": status_code, "is_default": is_default, "priority": priority,
    }
    if body is not None:
        payload["response_body"] = body
    if template is not None:
        payload["response_template"] = template
    if delay_ms is not None:
        payload["delay_ms"] = delay_ms
    if headers is not None:
        payload["response_headers"] = headers
    if matchers is not None:
        payload["matchers"] = matchers
    r = api.post(f"/mock-endpoints/{endpoint_id}/scenarios", username=admin, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _runtime(
    api, project_id, service_key, path, *,
    method="GET", token=None, context=None, json_body=None, params=None, headers=None,
):
    """执行面调用：走 /api/v1/mock/{project}/{service}/{path}，不携带平台 JWT。"""
    url = f"{API}/mock/{project_id}/{service_key}/{path.lstrip('/')}"
    h = dict(headers or {})
    if token is not None:
        h["X-Mock-Token"] = token
    if context is not None:
        h["X-Mock-Context"] = context
    kwargs = {"headers": h}
    if params is not None:
        kwargs["params"] = params
    if json_body is not None:
        kwargs["json"] = json_body
    return api.client.request(method, url, **kwargs)


def _matcher(source, field, operator, expected=None, **kw):
    m = {"source": source, "field": field, "operator": operator}
    if expected is not None:
        m["expected_value"] = expected
    m.update(kw)
    return m


def _header_ci(headers_map, name):
    """大小写不敏感取响应/快照头值。"""
    target = name.lower()
    for k, v in (headers_map or {}).items():
        if k.lower() == target:
            return v
    return None


# --------------------------------------------------------------------------- 1. Service + Token


def test_mock_service_crud_token_and_permissions(api, admin, db):
    project_id = _create_project(api, admin)
    key = _skey("PAY")

    # 创建：一次性明文 token + service（runtime_token_set=True，不回显 hash/明文）。
    created = _create_service(api, admin, project_id, key, token="mtk_secret_token_001")
    token = created["runtime_token"]
    svc = created["service"]
    assert token == "mtk_secret_token_001"  # 用户传入明文原样返回一次
    assert svc["runtime_token_set"] is True
    assert svc["runtime_url"] == f"{API}/mock/{project_id}/{key}"
    assert "runtime_token_hash" not in svc
    assert "runtime_token" not in svc
    service_id = svc["id"]

    # 库里只存哈希：明文不入库，哈希可校验。
    from app.features.mock_management.models import MockService
    from app.features.mock_management.services.token_service import verify_token

    row = db.get(MockService, service_id)
    assert row.runtime_token_hash
    assert row.runtime_token_hash != token  # 哈希非明文
    assert verify_token(token, row.runtime_token_hash) is True

    # 详情：只暴露 runtime_token_set，无明文。
    got = api.get(f"/mock-services/{service_id}", username=admin).json()
    assert got["runtime_token_set"] is True
    assert "runtime_token" not in got

    # 列表包含。
    lst = api.get(f"/projects/{project_id}/mock-services", username=admin).json()
    assert any(s["id"] == service_id for s in lst["items"])

    # 乐观锁更新 + 旧 revision 409。
    rev = got["revision"]
    up = api.patch(
        f"/mock-services/{service_id}", username=admin,
        json={"name": "renamed", "revision": rev},
    )
    assert up.status_code == 200, up.text
    assert up.json()["name"] == "renamed"
    assert up.json()["revision"] == rev + 1
    bad = api.patch(
        f"/mock-services/{service_id}", username=admin,
        json={"name": "x", "revision": rev},
    )
    assert bad.status_code == 409

    # 重置 token：新明文一次性返回，与旧不同；旧 token 在 runtime 面失效（401）。
    rst = api.post(f"/mock-services/{service_id}/reset-token", username=admin)
    assert rst.status_code == 200, rst.text
    new_token = rst.json()["runtime_token"]
    assert new_token != token
    r_old = _runtime(api, project_id, key, "/nope", token=token)
    assert r_old.status_code == 401  # 旧 token 失效
    r_new = _runtime(api, project_id, key, "/nope", token=new_token)
    assert r_new.status_code == 404  # 鉴权通过，无接口匹配

    # member（非 editor）不可创建 / 不可重置 → 403。
    mbr = unique("mbr")
    mbr_id = _register(api, mbr)
    _add_member(api, admin, project_id, mbr_id, role="member")
    r_m = api.post(
        f"/projects/{project_id}/mock-services", username=mbr,
        json={"name": "nope", "service_key": _skey("NOPE")},
    )
    assert r_m.status_code == 403
    assert api.post(f"/mock-services/{service_id}/reset-token", username=mbr).status_code == 403

    # editor 可创建。
    edt = unique("edt")
    edt_id = _register(api, edt)
    _add_member(api, admin, project_id, edt_id, role="editor")
    r_e = api.post(
        f"/projects/{project_id}/mock-services", username=edt,
        json={"name": "by-editor", "service_key": _skey("EDT")},
    )
    assert r_e.status_code == 201, r_e.text

    # 跨项目不可见 → 404。
    stranger = unique("str")
    _register(api, stranger)
    assert api.get(f"/mock-services/{service_id}", username=stranger).status_code == 404

    # 重复 service_key → 409。
    r_dup = api.post(
        f"/projects/{project_id}/mock-services", username=admin,
        json={"name": key, "service_key": key},
    )
    assert r_dup.status_code == 409


# --------------------------------------------------------------------------- 2. Endpoint


def test_mock_endpoint_crud(api, admin):
    project_id = _create_project(api, admin)
    svc = _create_service(api, admin, project_id, _skey("EP"))
    service_id = svc["service"]["id"]

    ep = _create_endpoint(api, admin, service_id, method="GET", path="/items/{id}")
    endpoint_id = ep["id"]
    assert ep["method"] == "GET"
    assert ep["path"] == "/items/{id}"
    assert ep["scenario_count"] == 0

    # (method+path) 唯一 → 409。
    r = api.post(
        f"/mock-services/{service_id}/endpoints", username=admin,
        json={"name": "dup", "method": "GET", "path": "/items/{id}"},
    )
    assert r.status_code == 409

    # 列表。
    lst = api.get(f"/mock-services/{service_id}/endpoints", username=admin).json()
    assert any(e["id"] == endpoint_id for e in lst["items"])

    # 乐观锁更新 + 旧 revision 409。
    rev = ep["revision"]
    up = api.patch(
        f"/mock-endpoints/{endpoint_id}", username=admin,
        json={"name": "items v2", "revision": rev},
    )
    assert up.status_code == 200
    assert up.json()["name"] == "items v2"
    assert api.patch(
        f"/mock-endpoints/{endpoint_id}", username=admin, json={"name": "x", "revision": rev}
    ).status_code == 409

    # 跨项目不可见 → 404。
    stranger = unique("str")
    _register(api, stranger)
    assert api.get(f"/mock-endpoints/{endpoint_id}", username=stranger).status_code == 404

    # 删除（无场景引用）→ 204，再查 404。
    assert api.delete(f"/mock-endpoints/{endpoint_id}", username=admin).status_code == 204
    assert api.get(f"/mock-endpoints/{endpoint_id}", username=admin).status_code == 404


# --------------------------------------------------------------------------- 3. Scenario + Matcher + 默认 + 复制 + 试跑


def test_mock_scenario_matcher_default_duplicate_test(api, admin):
    project_id = _create_project(api, admin)
    svc = _create_service(api, admin, project_id, _skey("SC"))
    service_id = svc["service"]["id"]
    ep = _create_endpoint(api, admin, service_id, method="POST", path="/orders")
    endpoint_id = ep["id"]

    # 创建带 Matcher 的场景。
    sc = _create_scenario(
        api, admin, endpoint_id, _skey("NORM"),
        is_default=True, body={"code": 0},
        matchers=[_matcher("QUERY", "env", "EQ", "prod"), _matcher("HEADER", "X-Trace", "EXISTS")],
    )
    scenario_id = sc["id"]
    assert len(sc["matchers"]) == 2
    assert sc["is_default"] is True

    # 同接口下 is_default 唯一：再设默认先清旧。
    sc2 = _create_scenario(api, admin, endpoint_id, _skey("ALT"), body={"code": 1})
    alt_id = sc2["id"]
    assert api.post(f"/mock-scenarios/{alt_id}/set-default", username=admin).status_code == 200
    refreshed = api.get(f"/mock-scenarios/{scenario_id}", username=admin).json()
    assert refreshed["is_default"] is False  # 旧默认被清
    assert api.get(f"/mock-scenarios/{alt_id}", username=admin).json()["is_default"] is True

    # 整体替换 Matcher（重建）。
    replaced = api.put(
        f"/mock-scenarios/{scenario_id}/matchers", username=admin,
        json={"matchers": [_matcher("QUERY", "env", "EQ", "dev")]},
    )
    assert replaced.status_code == 200, replaced.text
    assert len(replaced.json()["matchers"]) == 1
    assert replaced.json()["matchers"][0]["field"] == "env"

    # 复制场景（含 matchers，新 key）。
    new_key = _skey("COPY")
    dup = api.post(
        f"/mock-scenarios/{scenario_id}/duplicate", username=admin, params={"new_key": new_key},
    )
    assert dup.status_code == 200, dup.text
    assert dup.json()["scenario_key"] == new_key
    assert len(dup.json()["matchers"]) == 1
    assert dup.json()["is_default"] is False  # 副本不当默认

    # 重复 key 复制 → 409。
    assert api.post(
        f"/mock-scenarios/{scenario_id}/duplicate", username=admin, params={"new_key": new_key}
    ).status_code == 409

    # 试跑（§三十三）：匹配 → matched + 响应；不匹配 → matched=False。
    ok = api.post(
        f"/mock-scenarios/{scenario_id}/test", username=admin,
        json={"method": "POST", "path": "/orders", "query": {"env": "dev"}},
    )
    assert ok.status_code == 200
    assert ok.json()["matched"] is True
    assert ok.json()["status_code"] == 200
    assert ok.json()["body"] == {"code": 0}
    miss = api.post(
        f"/mock-scenarios/{scenario_id}/test", username=admin,
        json={"method": "POST", "path": "/orders", "query": {"env": "other"}},
    )
    assert miss.json()["matched"] is False

    # 删除：被用例引用前可删。
    assert api.delete(f"/mock-scenarios/{scenario_id}", username=admin).status_code == 204


# --------------------------------------------------------------------------- 4. 行为类型 + 模板


def test_mock_runtime_behavior_types_and_template(api, admin):
    project_id = _create_project(api, admin)
    svc = _create_service(api, admin, project_id, _skey("BHVR"))
    token = svc["runtime_token"]
    service_id = svc["service"]["id"]
    ep = _create_endpoint(api, admin, service_id, method="GET", path="/items/{id}")
    endpoint_id = ep["id"]

    # 默认场景：正常返回 + 响应头差异。
    _create_scenario(
        api, admin, endpoint_id, _skey("NORM"),
        is_default=True, status_code=200, body={"ok": True},
        headers={"X-Mock-Trace": "normal"},
    )
    # 各异常 / 边界场景，用 QUERY case 路由（priority 高于默认）。
    _create_scenario(
        api, admin, endpoint_id, _skey("BAD"), priority=10, status_code=400,
        body={"err": "bad_request"},
        matchers=[_matcher("QUERY", "case", "EQ", "400")],
    )
    _create_scenario(
        api, admin, endpoint_id, _skey("SRV"), priority=10, status_code=500,
        body={"err": "internal"},
        matchers=[_matcher("QUERY", "case", "EQ", "500")],
    )
    _create_scenario(
        api, admin, endpoint_id, _skey("EMPT"), priority=10,
        behavior_type="EMPTY_RESPONSE", status_code=200,
        matchers=[_matcher("QUERY", "case", "EQ", "empty")],
    )
    _create_scenario(
        api, admin, endpoint_id, _skey("DLY"), priority=10,
        behavior_type="DELAY_RESPONSE", delay_ms=300, status_code=200, body={"ok": True},
        matchers=[_matcher("QUERY", "case", "EQ", "delay")],
    )
    _create_scenario(
        api, admin, endpoint_id, _skey("TMO"), priority=10,
        behavior_type="TIMEOUT", delay_ms=300, status_code=504,
        matchers=[_matcher("QUERY", "case", "EQ", "timeout")],
    )
    # 模板占位符场景：${request.path.id} / ${runtime.request_id}。
    _create_scenario(
        api, admin, endpoint_id, _skey("TPL"), priority=10, status_code=200,
        template={"id": "${request.path.id}", "rid": "${runtime.request_id}"},
        matchers=[_matcher("QUERY", "case", "EQ", "tpl")],
    )

    skey = svc["service"]["service_key"]
    base = "/items/42"

    # 正常 + 响应头差异。
    r = _runtime(api, project_id, skey, base, token=token)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert r.headers["x-mock-trace"] == "normal"

    # 4xx。
    r = _runtime(api, project_id, skey, base, token=token, params={"case": "400"})
    assert r.status_code == 400
    assert r.json() == {"err": "bad_request"}

    # 5xx。
    r = _runtime(api, project_id, skey, base, token=token, params={"case": "500"})
    assert r.status_code == 500
    assert r.json()["err"] == "internal"

    # 空体。
    r = _runtime(api, project_id, skey, base, token=token, params={"case": "empty"})
    assert r.status_code == 200
    assert r.json() is None

    # 延迟：返回配置体，且耗时 >= delay。
    t0 = time.perf_counter()
    r = _runtime(api, project_id, skey, base, token=token, params={"case": "delay"})
    elapsed = time.perf_counter() - t0
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert elapsed >= 0.25, f"延迟未生效：{elapsed:.3f}s"

    # 超时：504 空体 + 耗时 >= delay。
    t0 = time.perf_counter()
    r = _runtime(api, project_id, skey, base, token=token, params={"case": "timeout"})
    elapsed = time.perf_counter() - t0
    assert r.status_code == 504
    assert r.json() is None
    assert elapsed >= 0.25, f"超时延迟未生效：{elapsed:.3f}s"

    # 模板占位符解析（结构化替换，非代码求值）。
    r = _runtime(api, project_id, skey, base, token=token, params={"case": "tpl"})
    assert r.status_code == 200
    assert r.json()["id"] == "42"  # ${request.path.id}
    assert r.json()["rid"]  # ${runtime.request_id} 非空


# --------------------------------------------------------------------------- 5. 匹配优先级 + 并发隔离


def test_mock_matching_priority_and_concurrency_isolation(api, admin, db):
    project_id = _create_project(api, admin)
    svc = _create_service(api, admin, project_id, _skey("ISO"))
    token = svc["runtime_token"]
    skey = svc["service"]["service_key"]
    service_id = svc["service"]["id"]
    ep = _create_endpoint(api, admin, service_id, method="GET", path="/orders/{id}")
    endpoint_id = ep["id"]

    # A：默认兜底（priority 0，无 matcher）。
    a = _create_scenario(
        api, admin, endpoint_id, _skey("A"), is_default=True, body={"who": "A"},
    )
    # B：显式 Matcher（priority 10，?env=B）。
    b = _create_scenario(
        api, admin, endpoint_id, _skey("B"), priority=10, body={"who": "B"},
        matchers=[_matcher("QUERY", "env", "EQ", "B")],
    )
    # C：显式 Matcher（priority 10，?env=C）；用于 Context Override 覆盖 B。
    c = _create_scenario(
        api, admin, endpoint_id, _skey("C"), priority=10, body={"who": "C"},
        matchers=[_matcher("QUERY", "env", "EQ", "C")],
    )
    a_id, b_id, c_id = a["id"], b["id"], c["id"]

    # 基线：Explicit Matcher > Default。
    r_b = _runtime(api, project_id, skey, "/orders/1", token=token, params={"env": "B"})
    assert r_b.status_code == 200 and r_b.json() == {"who": "B"}
    r_def = _runtime(api, project_id, skey, "/orders/1", token=token)  # 无 env → 默认 A
    assert r_def.json() == {"who": "A"}

    # Context Override > Explicit Matcher：覆盖到 C，即使 ?env=B 也返回 C。
    from app.features.mock_management.services.mock_runtime_service import MockRuntimeService

    rt = MockRuntimeService()
    ctx_c = rt.activate_context(
        db, project_id=project_id, test_run_id=None, case_execution_id=None,
        overrides={endpoint_id: c_id},
    )
    db.commit()  # 必须提交，Runtime 的独立会话才看得到
    cid_c = ctx_c.context_id

    r_ovr = _runtime(
        api, project_id, skey, "/orders/1", token=token,
        params={"env": "B"}, context=cid_c,
    )
    assert r_ovr.json() == {"who": "C"}  # Override 压过 B 的 Matcher

    # 并发隔离：另一个 Context 覆盖到 B，与 cid_c 互不可见。
    ctx_b = rt.activate_context(
        db, project_id=project_id, test_run_id=None, case_execution_id=None,
        overrides={endpoint_id: b_id},
    )
    db.commit()
    cid_b = ctx_b.context_id

    r_b_ctx = _runtime(
        api, project_id, skey, "/orders/1", token=token,
        params={"env": "X"}, context=cid_b,  # 无 env=B 命中，但 Override 直接给 B
    )
    assert r_b_ctx.json() == {"who": "B"}
    r_c_ctx = _runtime(
        api, project_id, skey, "/orders/1", token=token,
        params={"env": "B"}, context=cid_c,  # 仍只看到 C
    )
    assert r_c_ctx.json() == {"who": "C"}

    # 关闭 Context 后回退到正常匹配（Matcher / Default）。
    rt.deactivate_context(db, cid_c)
    db.commit()
    r_closed = _runtime(
        api, project_id, skey, "/orders/1", token=token,
        params={"env": "B"}, context=cid_c,
    )
    assert r_closed.json() == {"who": "B"}  # Override 消失，Matcher 接管


# --------------------------------------------------------------------------- 6. 执行面分离 + 脱敏 + 调用记录


def test_mock_execution_plane_separation_and_masking(api, admin):
    project_id = _create_project(api, admin)
    # 私有服务（需 token）+ 公共服务（无需 token）。
    priv = _create_service(api, admin, project_id, _skey("PRIV"))
    priv_token = priv["runtime_token"]
    priv_skey = priv["service"]["service_key"]
    pub = _create_service(api, admin, project_id, _skey("PUB"), public_runtime=True)
    pub_skey = pub["service"]["service_key"]
    pub_service_id = pub["service"]["id"]

    # 各建一个接口 + 默认场景。
    priv_ep = _create_endpoint(api, admin, priv["service"]["id"], method="POST", path="/pay")
    _create_scenario(
        api, admin, priv_ep["id"], _skey("OK"), is_default=True,
        status_code=200, body={"code": 0},
    )
    pub_ep = _create_endpoint(api, admin, pub_service_id, method="GET", path="/info")
    _create_scenario(
        api, admin, pub_ep["id"], _skey("OK"), is_default=True,
        status_code=200, body={"code": 0},
    )

    # 无 token → 401（私有）。
    r_no = _runtime(api, project_id, priv_skey, "/pay", method="POST")
    assert r_no.status_code == 401
    # 错 token → 401。
    r_bad = _runtime(api, project_id, priv_skey, "/pay", method="POST", token="mtk_wrong_token_x")
    assert r_bad.status_code == 401
    # 正确 token → 200。
    r_ok = _runtime(
        api, project_id, priv_skey, "/pay", method="POST", token=priv_token,
        json_body={"username": "bob", "password": "p@ss", "profile": {"token": "t1"}},
        headers={"Authorization": "Bearer sekret", "X-Api-Key": "key123", "X-Trace": "t"},
    )
    assert r_ok.status_code == 200

    # public_runtime：无 token 也能调用。
    r_pub = _runtime(api, project_id, pub_skey, "/info")
    assert r_pub.status_code == 200
    assert r_pub.json() == {"code": 0}

    # 每次调用都落一条 MockExecution（含未鉴权 / 未匹配）。
    exes = api.get(f"/projects/{project_id}/mock-executions", username=admin).json()
    assert exes["total"] >= 4
    # 未匹配 / 未鉴权的记录 matched=False。
    assert any(e["matched"] is False for e in exes["items"])

    # 敏感脱敏：Authorization / X-Api-Key / password / profile.token 掩码，非敏感保留。
    hit = next(
        e for e in exes["items"]
        if e["matched"] and e["service_key"] == priv_skey
    )
    hs = hit["header_snapshot"] or {}
    assert _header_ci(hs, "Authorization") == "******"
    assert _header_ci(hs, "X-Api-Key") == "******"
    assert _header_ci(hs, "X-Trace") == "t"  # 非敏感保留
    bs = hit["body_snapshot"] or {}
    assert bs["password"] == "******"
    assert bs["profile"]["token"] == "******"
    assert bs["username"] == "bob"  # 非敏感保留

    # 服务不存在 → 404 + 仍记录一条执行。
    before = api.get(f"/projects/{project_id}/mock-executions", username=admin).json()["total"]
    r_missing = _runtime(api, project_id, "NOPE_SERVICE", "/x", token="mtk_any_token_xx")
    assert r_missing.status_code == 404
    after = api.get(f"/projects/{project_id}/mock-executions", username=admin).json()["total"]
    assert after == before + 1


# --------------------------------------------------------------------------- 7. API Catalog 一键创建


def test_mock_api_catalog_one_click_create(api, admin):
    project_id = _create_project(api, admin)

    # 先建一个 API 接口（method+path 取自它）。
    api_r = api.post(
        f"/projects/{project_id}/apis", username=admin,
        json={"name": "创建订单", "method": "POST", "path": "/api/v1/orders"},
    )
    assert api_r.status_code == 201, api_r.text
    api_id = api_r.json()["id"]

    skey = _skey("ORDER")
    r = api.post(
        f"/projects/{project_id}/mock-from-api/{api_id}", username=admin,
        json={"service_key": skey, "service_name": "订单 Mock",
              "templates": ["NORMAL", "BAD_REQUEST_400", "SERVER_ERROR_500", "EMPTY_DATA"]},
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["endpoint_id"]
    assert len(out["scenario_ids"]) == 4
    assert out["runtime_token"]  # 新建服务一次性返回明文
    service_id = out["service"]["id"]
    token = out["runtime_token"]

    # NORMAL 设为默认：未匹配请求 → 200。
    r_run = _runtime(
        api, project_id, skey, "/api/v1/orders", method="POST", token=token,
        json_body={"x": 1},
    )
    assert r_run.status_code == 200
    assert r_run.json() == {"code": 0, "message": "ok"}

    # 接口 method+path 取自 ApiInterface（POST /api/v1/orders）。
    ep = api.get(f"/mock-services/{service_id}/endpoints", username=admin).json()["items"][0]
    assert ep["method"] == "POST"
    assert ep["path"] == "/api/v1/orders"
    assert ep["api_id"] == api_id

    # 场景已建（含 4xx/5xx/空体），可按 scenario_key 取到。
    scs = api.get(f"/mock-endpoints/{ep['id']}/scenarios", username=admin).json()["items"]
    keys = {s["scenario_key"] for s in scs}
    assert {"NORMAL", "BAD_REQUEST_400", "SERVER_ERROR_500", "EMPTY_DATA"} <= keys
    assert [s for s in scs if s["is_default"]][0]["scenario_key"] == "NORMAL"

    # 跨项目接口 → 404。
    other = _create_project(api, admin)
    assert api.post(
        f"/projects/{other}/mock-from-api/{api_id}", username=admin,
        json={"service_key": _skey("X")},
    ).status_code == 404


# --------------------------------------------------------------------------- 8. 禁止任意代码执行


def test_mock_no_arbitrary_code_execution(api, admin):
    """Mock Response 只做结构化占位符替换，不执行任意代码（§十三）。

    - 合法占位符 ${request.path.id} 解析为请求路径参数（结构化数据绑定）。
    - 形如 ${__import__('os')} / ${os.system('...')} 的注入串不被求值，
      原样作为字面量返回（regex 不匹配非法命名空间 / 非法 path 字符）。
    """
    project_id = _create_project(api, admin)
    svc = _create_service(api, admin, project_id, _skey("NOEX"))
    token = svc["runtime_token"]
    skey = svc["service"]["service_key"]
    ep = _create_endpoint(api, admin, svc["service"]["id"], method="GET", path="/x/{id}")
    # 模板：合法占位符 + 两段注入串（下划线开头命名空间 / 带括号 path 均不匹配）。
    _create_scenario(
        api, admin, ep["id"], _skey("INJ"), is_default=True, status_code=200,
        template={
            "id": "${request.path.id}",
            "inj1": "${__import__('os').system('echo PWNED')}",
            "inj2": "${os.system('rm -rf /')}",
        },
    )

    r = _runtime(api, project_id, skey, "/x/42", token=token)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "42"  # 结构化绑定生效
    # 注入串原样返回，未被求值（无副作用、无插值结果）。
    assert "${" in body["inj1"]
    assert "${" in body["inj2"]


# --------------------------------------------------------------------------- 9. TestCaseMock 声明


def test_mock_case_mocks_crud_and_validation(api, admin):
    project_id = _create_project(api, admin)
    svc = _create_service(api, admin, project_id, _skey("TCM"))
    service_id = svc["service"]["id"]
    ep = _create_endpoint(api, admin, service_id, method="GET", path="/lookup/{id}")
    endpoint_id = ep["id"]
    sc = _create_scenario(
        api, admin, endpoint_id, _skey("D"), is_default=True, body={"who": "D"},
    )
    scenario_id = sc["id"]
    scenario_key = sc["scenario_key"]

    # 建一个测试用例。
    case_id = api.post(
        f"/projects/{project_id}/test-cases", username=admin,
        json={"name": unique("case")},
    ).json()["id"]

    # 列表初始为空。
    assert api.get(f"/test-cases/{case_id}/mocks", username=admin).json() == []

    # 整体替换声明。
    r = api.put(
        f"/test-cases/{case_id}/mocks", username=admin,
        json={"mocks": [{
            "mock_service_id": service_id, "mock_endpoint_id": endpoint_id,
            "mock_scenario_id": scenario_id, "scope": "EXECUTION", "sort": 0,
        }]},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["scenario_key"] == scenario_key
    assert rows[0]["endpoint_method"] == "GET"
    assert rows[0]["service_name"]  # join 冗余展示

    # 重建：清空。
    assert api.put(
        f"/test-cases/{case_id}/mocks", username=admin, json={"mocks": []},
    ).json() == []

    # 跨项目归属校验：用另一个项目的 service → 404。
    other = _create_project(api, admin)
    other_svc = _create_service(api, admin, other, _skey("OTHER"))
    other_ep = _create_endpoint(api, admin, other_svc["service"]["id"], path="/o")
    other_sc = _create_scenario(api, admin, other_ep["id"], _skey("O"), is_default=True, body={})
    r_cross = api.put(
        f"/test-cases/{case_id}/mocks", username=admin,
        json={"mocks": [{
            "mock_service_id": other_svc["service"]["id"],
            "mock_endpoint_id": other_ep["id"],
            "mock_scenario_id": other_sc["id"], "scope": "BOTH",
        }]},
    )
    assert r_cross.status_code == 404

    # scope 取值非法 → 422（Pydantic Literal 层拦截）/ 400（服务层兜底）。
    r_bad_scope = api.put(
        f"/test-cases/{case_id}/mocks", username=admin,
        json={"mocks": [{
            "mock_service_id": service_id, "mock_endpoint_id": endpoint_id,
            "mock_scenario_id": scenario_id, "scope": "WHATEVER",
        }]},
    )
    assert r_bad_scope.status_code in (400, 422)

    # 被用例引用的场景不可删 → 409。
    api.put(
        f"/test-cases/{case_id}/mocks", username=admin,
        json={"mocks": [{
            "mock_service_id": service_id, "mock_endpoint_id": endpoint_id,
            "mock_scenario_id": scenario_id, "scope": "SETUP",
        }]},
    )
    assert api.delete(f"/mock-scenarios/{scenario_id}", username=admin).status_code == 409
