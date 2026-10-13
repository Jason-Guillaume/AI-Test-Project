"""验收项 15：测试执行引擎 + §32 两个验收场景 + §33 执行覆盖。

覆盖：
- AssertionEngine 纯逻辑：全断言类型 / 全操作符 / NOT_CONTAINS 修复 / 软断言（required=False 不阻断）
- §32(1)：单接口测试 POST /login，断言 STATUS_CODE==200 + $.code==0 → PASSED
- §32(2)：业务流测试 login→create project→create task→query task → PASSED
- §16 路由：API→ApiRequestExecutor / BUSINESS_FLOW→execute_flow / BUSINESS_ACTION→复用动作默认绑定
- 负向：断言失败→FAILED ASSERTION_FAILED；HTTP 500→FAILED HTTP_REQUEST_FAILED；超时→ERROR HTTP_TIMEOUT
- §25 跨项目触发执行 → 404
- 敏感数据脱敏：请求快照 password/token → ******；响应快照 token → ******
- VariableRef 端到端（不同 source/target 名，验证修复）

复用契约（§29）：TestCaseExecutor 路由到 ApiRequestExecutor / execute_flow / SensitiveDataMasker；
出站白名单（ProjectOutboundTarget）对 127.0.0.1 环回地址同样强制（§SSRF）。
"""

from __future__ import annotations

import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.features.test_management.executors.assertion_engine import (
    _extract_actual,
    evaluate_operator,
    required_all_passed,
    run_assertions,
)
from tests.conftest import unique

API = "/api/v1"


# ============================================================ Stub HTTP 服务


class _StubHandler(BaseHTTPRequestHandler):
    """按 (method, path) 精确路由 + 正则模板路由的 stub。"""

    def do_GET(self): self._dispatch("GET")
    def do_POST(self): self._dispatch("POST")
    def do_DELETE(self): self._dispatch("DELETE")
    def do_PUT(self): self._dispatch("PUT")

    def _dispatch(self, method):
        try:
            body = self._read_body()
            responder = self.server.resolve(method, self.path)
            if responder is None:
                self._write(404, {"code": 404, "message": "no route", "data": None})
                return
            status, payload = responder(self, body)
            self._write(status, payload)
        except Exception as exc:  # noqa: BLE001
            self._write(500, {"code": 500, "message": f"stub error: {exc}", "data": None})

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length <= 0:
            return ""
        return self.rfile.read(length).decode("utf-8", "ignore")

    def _write(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # 静默默认 stderr
        pass


class StubServer:
    """线程化 stub：直接绑定 0 端口取可用端口，无竞态。"""

    def __init__(self):
        self.exact = {}        # (method, path) -> responder
        self.patterns = []     # [(method, compiled_regex, responder)]
        self._server = None
        self.port = None

    def add(self, method, path, status, payload):
        self.exact[(method.upper(), path)] = lambda h, body: (status, payload)

    def add_fn(self, method, path, fn):
        self.exact[(method.upper(), path)] = fn

    def add_pattern(self, method, regex, fn):
        self.patterns.append((method.upper(), regex, fn))

    def resolve(self, method, full_path):
        path = full_path.split("?", 1)[0]
        fn = self.exact.get((method, path))
        if fn:
            return fn
        for m, pat, rsp in self.patterns:
            if m == method:
                mt = pat.match(path)
                if mt:
                    return lambda h, body, r=rsp, g=mt: r(h, body, g)
        return None

    def __enter__(self):
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
        self._server.resolve = self.resolve
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *a):
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"


# ============================================================ DB 基础设施辅助


def _admin_id(db):
    from app.models.identity import User
    return db.query(User).filter(User.username == "platform_admin").first().id


def _make_env(db, base_url, admin_id, name=None):
    from app.models.configuration import Environment
    env = Environment(
        name=name or unique("env"), display_name="stub env",
        base_url=base_url, gateway_prefix="", default_headers={},
        is_active=True, created_by=admin_id,
    )
    db.add(env)
    db.flush()
    db.commit()
    db.refresh(env)
    return env.id


def _whitelist(db, project_id, port, admin_id):
    from app.models.project import ProjectOutboundTarget
    db.add(ProjectOutboundTarget(
        project_id=project_id, scheme="http", host="127.0.0.1", port=port,
        is_production=False, enabled=True, approved_by=admin_id,
    ))
    db.commit()


def _make_iface(db, project_id, method, path, name=None):
    from app.features.api_catalog.models.api_interface import ApiInterface
    iface = ApiInterface(
        project_id=project_id, name=name or unique("iface"),
        method=method, path=path, auth_type="none",
        content_type="application/json", status="ACTIVE", source_type="MANUAL",
    )
    db.add(iface)
    db.flush()
    db.commit()
    db.refresh(iface)
    return iface.id


# ============================================================ 测试用例构建辅助


def _create_project(api, admin):
    name = unique("proj")
    r = api.post("/projects", username=admin, json={"name": name, "description": "executor project"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_case(api, admin, project_id, *, name, target_type="API", api_id=None,
                 business_flow_id=None, business_action_id=None, data=None, assertions=None):
    body = {"name": name, "target_type": target_type, "enabled": True}
    if api_id is not None: body["api_id"] = api_id
    if business_flow_id is not None: body["business_flow_id"] = business_flow_id
    if business_action_id is not None: body["business_action_id"] = business_action_id
    r = api.post(f"/projects/{project_id}/test-cases", username=admin, json=body)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    for d in data or []:
        assert api.post(f"/test-cases/{cid}/data", username=admin, json=d).status_code == 201
    for a in assertions or []:
        assert api.post(f"/test-cases/{cid}/assertions", username=admin, json=a).status_code == 201
    return cid


def _build_plan_with_cases(api, admin, project_id, case_ids, env_id):
    suite_id = api.post(f"/projects/{project_id}/test-suites", username=admin,
                        json={"name": unique("suite")}).json()["id"]
    for i, cid in enumerate(case_ids):
        api.post(f"/test-suites/{suite_id}/cases", username=admin,
                 json={"test_case_id": cid, "sort": i, "enabled": True})
    plan_id = api.post(f"/projects/{project_id}/test-plans", username=admin,
                       json={"name": unique("plan"), "environment_id": env_id}).json()["id"]
    api.post(f"/test-plans/{plan_id}/suites", username=admin,
             json={"suite_id": suite_id, "sort": 0})
    return plan_id


def _run(api, admin, plan_id, env_id):
    r = api.post(f"/test-plans/{plan_id}/runs", username=admin, json={"environment_id": env_id})
    assert r.status_code == 200, r.text
    return r.json()


def _case_execs(api, admin, run_id):
    r = api.get(f"/test-runs/{run_id}/cases", username=admin)
    assert r.status_code == 200, r.text
    return r.json()["items"]


# ============================================================ AssertionEngine 单元测试


class TestAssertionEngine:
    """纯逻辑，无 DB/HTTP。"""

    RESP = {
        "status_code": 200,
        "headers": {"Content-Type": "application/json", "X-Trace": "abc-123"},
        "body": {"code": 0, "data": {"id": 42, "name": "Alice"}},
        "raw_body": '{"code":0,"data":{"id":42,"name":"Alice"}}',
        "response_time_ms": 120,
    }

    # ---- evaluate_operator

    def test_eq_ne(self):
        assert evaluate_operator(200, 200, "EQ") is True
        assert evaluate_operator(200, 201, "EQ") is False
        assert evaluate_operator(200, 201, "NE") is True

    def test_numeric_operators(self):
        assert evaluate_operator(200, 100, "GT") is True
        assert evaluate_operator(200, 200, "GE") is True
        assert evaluate_operator(50, 100, "LT") is True
        assert evaluate_operator(100, 100, "LE") is True

    def test_numeric_string_fallback(self):
        # 无法转数值时退化为字符串比较。
        assert evaluate_operator("b", "a", "GT") is True
        assert evaluate_operator("a", "b", "LT") is True

    def test_in_operator(self):
        assert evaluate_operator("admin", "admin,user,guest", "IN") is True
        assert evaluate_operator("x", "admin,user", "IN") is False

    def test_contains_operator(self):
        assert evaluate_operator("hello world", "world", "CONTAINS") is True
        assert evaluate_operator("hello", "world", "CONTAINS") is False

    def test_exists_not_exists(self):
        assert evaluate_operator("x", None, "EXISTS") is True
        assert evaluate_operator(None, None, "EXISTS") is False
        assert evaluate_operator(None, None, "NOT_EXISTS") is True
        assert evaluate_operator("x", None, "NOT_EXISTS") is False

    # ---- _extract_actual

    def test_extract_status_code(self):
        assert _extract_actual(self.RESP, {"assertion_type": "STATUS_CODE"}) == 200

    def test_extract_json_path(self):
        assert _extract_actual(self.RESP, {"assertion_type": "JSON_PATH", "path": "$.code"}) == 0
        assert _extract_actual(self.RESP, {"assertion_type": "JSON_PATH", "path": "$.data.id"}) == 42

    def test_extract_header_case_insensitive(self):
        assert _extract_actual(self.RESP, {"assertion_type": "HEADER", "source": "X-Trace"}) == "abc-123"
        assert _extract_actual(self.RESP, {"assertion_type": "HEADER", "source": "x-trace"}) == "abc-123"

    def test_extract_response_time(self):
        assert _extract_actual(self.RESP, {"assertion_type": "RESPONSE_TIME"}) == 120

    def test_extract_contains_raw_body(self):
        assert _extract_actual(self.RESP, {"assertion_type": "CONTAINS"}) == self.RESP["raw_body"]

    # ---- run_assertions（端到端）

    def test_run_status_code(self):
        a = {"assertion_type": "STATUS_CODE", "operator": "EQ", "expected_value": "200", "required": True}
        results = run_assertions([a], self.RESP)
        assert results[0]["passed"] is True
        assert results[0]["actual"] == "200"

    def test_run_json_path_code(self):
        a = {"assertion_type": "JSON_PATH", "path": "$.code", "operator": "EQ", "expected_value": "0"}
        assert run_assertions([a], self.RESP)[0]["passed"] is True
        a2 = {"assertion_type": "JSON_PATH", "path": "$.code", "operator": "EQ", "expected_value": "1"}
        assert run_assertions([a2], self.RESP)[0]["passed"] is False

    def test_run_header_assertion(self):
        a = {"assertion_type": "HEADER", "source": "X-Trace", "operator": "EQ", "expected_value": "abc-123"}
        assert run_assertions([a], self.RESP)[0]["passed"] is True

    def test_run_contains_type(self):
        a = {"assertion_type": "CONTAINS", "expected_value": "Alice"}
        assert run_assertions([a], self.RESP)[0]["passed"] is True
        a2 = {"assertion_type": "CONTAINS", "expected_value": "Bob"}
        assert run_assertions([a2], self.RESP)[0]["passed"] is False

    def test_run_not_contains_type(self):
        """NOT_CONTAINS 是断言类型语义：body 不含期望串 → 通过（修复后）。"""
        a = {"assertion_type": "NOT_CONTAINS", "expected_value": "error"}
        assert run_assertions([a], self.RESP)[0]["passed"] is True
        a2 = {"assertion_type": "NOT_CONTAINS", "expected_value": "code"}
        assert run_assertions([a2], self.RESP)[0]["passed"] is False

    def test_required_all_passed(self):
        rs = [
            {"passed": True, "required": True},
            {"passed": False, "required": False},  # 软断言失败不阻断
        ]
        assert required_all_passed(rs) is True
        rs2 = [{"passed": False, "required": True}]
        assert required_all_passed(rs2) is False


# ============================================================ 业务流构建辅助


def _add_action(db, flow_id, name, key, sort):
    from app.features.business.models.business_action import BusinessAction
    a = BusinessAction(flow_id=flow_id, name=name, action_key=key, sort=sort, action_type="NORMAL")
    db.add(a)
    db.flush()
    return a


def _add_binding(db, action_id, api_id):
    from app.features.business.models.business_binding import BusinessBinding
    b = BusinessBinding(action_id=action_id, binding_type="API", api_id=api_id,
                        is_default=True, enabled=True)
    db.add(b)
    db.flush()
    return b


def _add_mapping(db, binding_id, direction, bvar, loc, field=None, expr=None):
    from app.features.business.models.business_api_mapping import BusinessApiMapping
    db.add(BusinessApiMapping(
        binding_id=binding_id, direction=direction, business_variable=bvar,
        api_location=loc, api_field=field, expression=expr,
    ))
    db.flush()


def _add_output_var(db, action_id, name):
    from app.features.business.models.business_variable import BusinessVariable
    db.add(BusinessVariable(action_id=action_id, direction="OUTPUT", name=name,
                            data_type="INTEGER", required=False))


def _build_login_flow(db, project_id, ifaces):
    """4 动作业务流：login→create project→create task→query task。

    ifaces: dict with keys login/projects/tasks/tasks_get (iface ids)。
    变量经 ctx.variables 同名传递（OUTPUT 写入 → 下一动作 INPUT 读取）。
    """
    from app.features.business.models.business_domain import BusinessDomain
    from app.features.business.models.business_flow import BusinessFlow

    domain = BusinessDomain(project_id=project_id, name=unique("domain"), status="ACTIVE")
    db.add(domain)
    db.flush()
    flow = BusinessFlow(project_id=project_id, domain_id=domain.id,
                       name=unique("flow"), status="ACTIVE")
    db.add(flow)
    db.flush()

    login = _add_action(db, flow.id, "登录", "LOGIN", 10)
    cproj = _add_action(db, flow.id, "创建项目", "CREATE_PROJECT", 20)
    ctask = _add_action(db, flow.id, "创建任务", "CREATE_TASK", 30)
    qtask = _add_action(db, flow.id, "查询任务", "QUERY_TASK", 40)

    # LOGIN: 无输入；输出 token / user_id。
    b = _add_binding(db, login.id, ifaces["login"])
    _add_mapping(db, b.id, "OUTPUT", "token", "RESPONSE", expr="$.data.token")
    _add_mapping(db, b.id, "OUTPUT", "user_id", "RESPONSE", expr="$.data.user_id")
    _add_output_var(db, login.id, "token")
    _add_output_var(db, login.id, "user_id")

    # CREATE_PROJECT: 输入 token→Header.Authorization / user_id→Body.user_id；输出 project_id。
    b = _add_binding(db, cproj.id, ifaces["projects"])
    _add_mapping(db, b.id, "INPUT", "token", "HEADER", field="Authorization")
    _add_mapping(db, b.id, "INPUT", "user_id", "BODY", field="user_id")
    _add_mapping(db, b.id, "OUTPUT", "project_id", "RESPONSE", expr="$.data.id")
    _add_output_var(db, cproj.id, "project_id")

    # CREATE_TASK: 输入 project_id→Body.project_id / token→Header.Authorization；输出 task_id。
    b = _add_binding(db, ctask.id, ifaces["tasks"])
    _add_mapping(db, b.id, "INPUT", "project_id", "BODY", field="project_id")
    _add_mapping(db, b.id, "INPUT", "token", "HEADER", field="Authorization")
    _add_mapping(db, b.id, "OUTPUT", "task_id", "RESPONSE", expr="$.data.id")
    _add_output_var(db, ctask.id, "task_id")

    # QUERY_TASK: 输入 task_id→Path.id / token→Header.Authorization。
    b = _add_binding(db, qtask.id, ifaces["tasks_get"])
    _add_mapping(db, b.id, "INPUT", "task_id", "PATH", field="id")
    _add_mapping(db, b.id, "INPUT", "token", "HEADER", field="Authorization")

    db.commit()
    return flow.id, {"LOGIN": login.id, "CREATE_PROJECT": cproj.id,
                     "CREATE_TASK": ctask.id, "QUERY_TASK": qtask.id}


def _build_varref_flow(db, project_id, produce_iface, consume_iface):
    """2 动作流：PRODUCE 输出 produced_id；VariableRef 映射 produced_id→consumed_id；CONSUME 读 consumed_id。

    source/target 不同名，必须经 VariableRef 传递；stub /consume 仅在 body.value==999 时 200。
    """
    from app.features.business.models.business_domain import BusinessDomain
    from app.features.business.models.business_flow import BusinessFlow
    from app.features.business.models.business_variable import BusinessVariable
    from app.features.business.models.business_variable_ref import BusinessVariableRef

    domain = BusinessDomain(project_id=project_id, name=unique("domain"), status="ACTIVE")
    db.add(domain)
    db.flush()
    flow = BusinessFlow(project_id=project_id, domain_id=domain.id,
                       name=unique("flow"), status="ACTIVE")
    db.add(flow)
    db.flush()

    produce = _add_action(db, flow.id, "生产", "PRODUCE", 10)
    consume = _add_action(db, flow.id, "消费", "CONSUME", 20)

    bp = _add_binding(db, produce.id, produce_iface)
    _add_mapping(db, bp.id, "OUTPUT", "produced_id", "RESPONSE", expr="$.data.id")
    _add_output_var(db, produce.id, "produced_id")

    bc = _add_binding(db, consume.id, consume_iface)
    _add_mapping(db, bc.id, "INPUT", "consumed_id", "BODY", field="value")
    db.add(BusinessVariable(action_id=consume.id, direction="INPUT", name="consumed_id",
                            data_type="INTEGER", required=False))

    # VariableRef：produce.produced_id → consume.consumed_id。
    db.add(BusinessVariableRef(
        flow_id=flow.id, source_action_id=produce.id, source_variable="produced_id",
        target_action_id=consume.id, target_variable="consumed_id",
    ))
    db.commit()
    return flow.id


# ============================================================ §32(1) 单接口测试


class TestAcceptanceSingleApi:
    """§32(1)：POST /login，断言 STATUS_CODE==200 + $.code==0。"""

    def test_login_passes_and_masks_sensitive(self, api, admin, db):
        with StubServer() as stub:
            stub.add("POST", "/login", 200,
                     {"code": 0, "message": "ok", "data": {"token": "tok-secret-abc", "user_id": 1}})
            admin_id = _admin_id(db)
            env_id = _make_env(db, stub.base_url, admin_id)
            project_id = _create_project(api, admin)
            _whitelist(db, project_id, stub.port, admin_id)
            login_iface = _make_iface(db, project_id, "POST", "/login", "登录接口")

            cid = _create_case(api, admin, project_id, name="登录正向",
                api_id=login_iface,
                data=[
                    {"name": "username", "value": "admin", "value_type": "STRING", "source_type": "STATIC", "sort": 0},
                    {"name": "password", "value": "secret", "value_type": "STRING", "source_type": "STATIC", "sort": 1},
                ],
                assertions=[
                    {"assertion_type": "STATUS_CODE", "operator": "EQ", "expected_value": "200", "required": True, "sort": 0},
                    {"assertion_type": "JSON_PATH", "path": "$.code", "operator": "EQ", "expected_value": "0", "required": True, "sort": 1},
                ],
            )
            plan_id = _build_plan_with_cases(api, admin, project_id, [cid], env_id)
            run = _run(api, admin, plan_id, env_id)

            assert run["status"] == "SUCCESS", run
            assert run["total"] == 1 and run["passed"] == 1 and run["failed"] == 0

            ce = _case_execs(api, admin, run["id"])[0]
            assert ce["status"] == "PASSED"
            assert ce["executor_type"] == "API"
            # 断言全部通过。
            assert ce["assertion_results"] and all(r["passed"] for r in ce["assertion_results"])
            # 响应快照：code==0，token 被脱敏。
            assert ce["response_snapshot"]["body"]["code"] == 0
            assert ce["response_snapshot"]["body"]["data"]["token"] == "******"
            # 请求快照：username 原值，password 被脱敏。
            assert ce["request_snapshot"]["body"]["username"] == "admin"
            assert ce["request_snapshot"]["body"]["password"] == "******"


# ============================================================ §32(2) 业务流测试


class TestAcceptanceBusinessFlow:
    """§32(2)：login→create project→create task→query task。"""

    def test_flow_passes_end_to_end(self, api, admin, db):
        with StubServer() as stub:
            stub.add("POST", "/login", 200, {"code": 0, "data": {"token": "tok-flow-xyz", "user_id": 1}})
            stub.add("POST", "/projects", 200, {"code": 0, "data": {"id": 101, "name": "demo"}})
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"id": 2001, "title": "t1"}})
            stub.add_pattern("GET", re.compile(r"^/tasks/(\d+)$"),
                             lambda h, body, m: (200, {"code": 0, "data": {"id": int(m.group(1)), "status": "DONE"}}))

            admin_id = _admin_id(db)
            env_id = _make_env(db, stub.base_url, admin_id)
            project_id = _create_project(api, admin)
            _whitelist(db, project_id, stub.port, admin_id)
            ifaces = {
                "login": _make_iface(db, project_id, "POST", "/login", "登录"),
                "projects": _make_iface(db, project_id, "POST", "/projects", "创建项目"),
                "tasks": _make_iface(db, project_id, "POST", "/tasks", "创建任务"),
                "tasks_get": _make_iface(db, project_id, "GET", "/tasks/{id}", "查询任务"),
            }
            flow_id, _ = _build_login_flow(db, project_id, ifaces)

            cid = _create_case(api, admin, project_id, name="登录建项建任务查任务",
                target_type="BUSINESS_FLOW", business_flow_id=flow_id,
                assertions=[
                    {"assertion_type": "STATUS_CODE", "operator": "EQ", "expected_value": "200", "required": True},
                ],
            )
            plan_id = _build_plan_with_cases(api, admin, project_id, [cid], env_id)
            run = _run(api, admin, plan_id, env_id)

            assert run["status"] == "SUCCESS", run
            assert run["passed"] == 1

            ce = _case_execs(api, admin, run["id"])[0]
            assert ce["status"] == "PASSED"
            assert ce["executor_type"] == "BUSINESS_FLOW"
            actions = ce["response_snapshot"]["actions"]
            assert len(actions) == 4
            assert all(a["status"] == "SUCCESS" for a in actions)
            assert ce["response_snapshot"]["status"] == "SUCCESS"
            # 上下文中的 token 被脱敏（敏感数据）。
            ctx = ce["context_json"]
            assert ctx["variables"]["token"] == "******"
            assert ctx["variables"]["project_id"] == 101
            assert ctx["variables"]["task_id"] == 2001


# ============================================================ §16 BUSINESS_ACTION 路由


class TestBusinessActionExecutor:
    """§16：BUSINESS_ACTION 复用动作默认绑定 + INPUT 映射 + ApiRequestExecutor。"""

    def test_single_action_passes(self, api, admin, db):
        with StubServer() as stub:
            stub.add("POST", "/tasks", 200, {"code": 0, "data": {"id": 2001, "title": "t1"}})
            admin_id = _admin_id(db)
            env_id = _make_env(db, stub.base_url, admin_id)
            project_id = _create_project(api, admin)
            _whitelist(db, project_id, stub.port, admin_id)
            ifaces = {
                "login": _make_iface(db, project_id, "POST", "/login", "登录"),
                "projects": _make_iface(db, project_id, "POST", "/projects", "创建项目"),
                "tasks": _make_iface(db, project_id, "POST", "/tasks", "创建任务"),
                "tasks_get": _make_iface(db, project_id, "GET", "/tasks/{id}", "查询任务"),
            }
            _, actions = _build_login_flow(db, project_id, ifaces)

            cid = _create_case(api, admin, project_id, name="单动作-创建任务",
                target_type="BUSINESS_ACTION", business_action_id=actions["CREATE_TASK"],
                data=[{"name": "project_id", "value": "101", "value_type": "INTEGER", "source_type": "STATIC", "sort": 0}],
                assertions=[
                    {"assertion_type": "STATUS_CODE", "operator": "EQ", "expected_value": "200"},
                    {"assertion_type": "JSON_PATH", "path": "$.code", "operator": "EQ", "expected_value": "0"},
                ],
            )
            plan_id = _build_plan_with_cases(api, admin, project_id, [cid], env_id)
            run = _run(api, admin, plan_id, env_id)
            assert run["status"] == "SUCCESS", run
            ce = _case_execs(api, admin, run["id"])[0]
            assert ce["status"] == "PASSED"
            assert ce["executor_type"] == "BUSINESS_ACTION"
            # 请求体由 INPUT 映射构造：project_id=101。
            assert ce["request_snapshot"]["body"]["project_id"] == 101


# ============================================================ 负向：断言失败 / HTTP 失败 / 超时


class TestNegativeExecution:
    """断言失败、HTTP 5xx、超时分别映射到 FAILED/ERROR。"""

    def test_assertion_failure_marks_failed(self, api, admin, db):
        with StubServer() as stub:
            stub.add("POST", "/login", 200, {"code": 0, "data": {"token": "t", "user_id": 1}})
            admin_id = _admin_id(db)
            env_id = _make_env(db, stub.base_url, admin_id)
            project_id = _create_project(api, admin)
            _whitelist(db, project_id, stub.port, admin_id)
            iface = _make_iface(db, project_id, "POST", "/login", "登录")
            # 故意断言 STATUS_CODE==500（实际 200）→ 断言失败。
            cid = _create_case(api, admin, project_id, name="断言失败",
                api_id=iface,
                data=[{"name": "username", "value": "a", "source_type": "STATIC", "sort": 0}],
                assertions=[{"assertion_type": "STATUS_CODE", "operator": "EQ", "expected_value": "500"}],
            )
            plan_id = _build_plan_with_cases(api, admin, project_id, [cid], env_id)
            run = _run(api, admin, plan_id, env_id)
            assert run["status"] == "FAILED"
            assert run["failed"] == 1
            ce = _case_execs(api, admin, run["id"])[0]
            assert ce["status"] == "FAILED"
            assert ce["error_code"] == "ASSERTION_FAILED"

    def test_http_5xx_marks_failed(self, api, admin, db):
        with StubServer() as stub:
            stub.add("POST", "/fail", 500, {"code": 500, "message": "boom"})
            admin_id = _admin_id(db)
            env_id = _make_env(db, stub.base_url, admin_id)
            project_id = _create_project(api, admin)
            _whitelist(db, project_id, stub.port, admin_id)
            iface = _make_iface(db, project_id, "POST", "/fail", "失败接口")
            cid = _create_case(api, admin, project_id, name="HTTP失败",
                api_id=iface, assertions=[{"assertion_type": "STATUS_CODE", "operator": "EQ", "expected_value": "200"}],
            )
            plan_id = _build_plan_with_cases(api, admin, project_id, [cid], env_id)
            run = _run(api, admin, plan_id, env_id)
            assert run["status"] == "FAILED"
            ce = _case_execs(api, admin, run["id"])[0]
            assert ce["status"] == "FAILED"
            assert ce["error_code"] == "HTTP_REQUEST_FAILED"

    def test_timeout_marks_error(self, api, admin, db):
        with StubServer() as stub:
            def slow(h, body):
                time.sleep(2)
                return 200, {"code": 0}
            stub.add_fn("POST", "/slow", slow)
            admin_id = _admin_id(db)
            env_id = _make_env(db, stub.base_url, admin_id)
            project_id = _create_project(api, admin)
            _whitelist(db, project_id, stub.port, admin_id)
            iface = _make_iface(db, project_id, "POST", "/slow", "慢接口")
            cid = _create_case(api, admin, project_id, name="超时",
                api_id=iface,
                # 通过步骤 config_json 设短超时。
                assertions=[],
            )
            # 加一个 ACTION 步骤设置 timeout=1。
            api.post(f"/test-cases/{cid}/steps", username=admin,
                     json={"name": "发请求", "step_type": "ACTION", "config_json": {"timeout": 1}, "sort": 0})
            plan_id = _build_plan_with_cases(api, admin, project_id, [cid], env_id)
            run = _run(api, admin, plan_id, env_id)
            assert run["status"] == "FAILED"  # 1 个 error → run FAILED
            assert run["error"] == 1
            ce = _case_execs(api, admin, run["id"])[0]
            assert ce["status"] == "ERROR"
            assert ce["error_code"] == "HTTP_TIMEOUT"


# ============================================================ §25 跨项目执行 404


class TestCrossProjectRun:
    """跨项目触发执行 → 404（项目不可见即不存在）。"""

    def test_run_hidden_as_404(self, api, admin, db):
        observer = unique("observer")
        api.register(observer)
        api.login(observer, "Init-Password-123")

        with StubServer() as stub:
            stub.add("POST", "/login", 200, {"code": 0, "data": {"token": "t", "user_id": 1}})
            admin_id = _admin_id(db)
            env_id = _make_env(db, stub.base_url, admin_id)
            project_id = _create_project(api, admin)
            _whitelist(db, project_id, stub.port, admin_id)
            iface = _make_iface(db, project_id, "POST", "/login", "登录")
            cid = _create_case(api, admin, project_id, name="跨项目",
                api_id=iface, assertions=[{"assertion_type": "STATUS_CODE", "operator": "EQ", "expected_value": "200"}])
            plan_id = _build_plan_with_cases(api, admin, project_id, [cid], env_id)

            # 观察者不在项目里 → 触发执行 404。
            r = api.post(f"/test-plans/{plan_id}/runs", username=observer, json={"environment_id": env_id})
            assert r.status_code == 404


# ============================================================ VariableRef 端到端（验证修复）


class TestVariableRefEndToEnd:
    """不同 source/target 名经 VariableRef 传递；source_variable_name 修复后生效。"""

    def test_ref_passes_value_between_actions(self, api, admin, db):
        with StubServer() as stub:
            stub.add("POST", "/produce", 200, {"code": 0, "data": {"id": 999}})
            # /consume 仅在 body.value==999 时 200，否则 400 → 证明 ref 传递了值。
            def consume(h, body):
                try:
                    payload = json.loads(body) if body else {}
                except json.JSONDecodeError:
                    payload = {}
                if payload.get("value") == 999:
                    return 200, {"code": 0, "data": {"ok": True}}
                return 400, {"code": 400, "message": "bad value"}
            stub.add_fn("POST", "/consume", consume)

            admin_id = _admin_id(db)
            env_id = _make_env(db, stub.base_url, admin_id)
            project_id = _create_project(api, admin)
            _whitelist(db, project_id, stub.port, admin_id)
            produce_iface = _make_iface(db, project_id, "POST", "/produce", "生产")
            consume_iface = _make_iface(db, project_id, "POST", "/consume", "消费")
            flow_id = _build_varref_flow(db, project_id, produce_iface, consume_iface)

            cid = _create_case(api, admin, project_id, name="变量引用",
                target_type="BUSINESS_FLOW", business_flow_id=flow_id,
                assertions=[{"assertion_type": "STATUS_CODE", "operator": "EQ", "expected_value": "200"}],
            )
            plan_id = _build_plan_with_cases(api, admin, project_id, [cid], env_id)
            run = _run(api, admin, plan_id, env_id)
            # ref 把 produced_id(999) 传成 consumed_id → /consume 收到 value=999 → 200 → 流 SUCCESS。
            assert run["status"] == "SUCCESS", run
            ce = _case_execs(api, admin, run["id"])[0]
            assert ce["status"] == "PASSED"
            assert all(a["status"] == "SUCCESS" for a in ce["response_snapshot"]["actions"])
