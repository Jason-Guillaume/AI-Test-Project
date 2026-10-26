"""Web UI 一期验收：权限、确认指纹、加密凭据、真实 Chromium、隔离与既有报告链路。"""
from __future__ import annotations
import base64
import io
import json
import threading
import zipfile
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4
import pytest
from sqlalchemy import text
from tests.conftest import unique

HTML = b'''<!doctype html><title>Web UI Demo</title>
<label>User<input data-testid="username"></label><label>Password<input data-testid="password" type="password"></label>
<button data-testid="login" onclick="fetch('/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.querySelector('[data-testid=username]').value,password:document.querySelector('[data-testid=password]').value})}).then(r=>{if(r.ok){localStorage.setItem('logged','yes');document.querySelector('[data-testid=status]').textContent='Logged in'}})">Login</button>
<p data-testid="status">Ready</p><select data-testid="choice"><option value="a">A</option><option value="b">B</option></select>
<input data-testid="file" type="file"><p data-testid="output">Report ready</p>
<p data-testid="jwt-status">No JWT</p><p data-testid="cookie-status">No Cookie</p>
<script>document.querySelector('[data-testid=jwt-status]').textContent=localStorage.getItem('access_token')==='Jwt-Session-Only-1234'?'JWT ready':'No JWT';document.querySelector('[data-testid=cookie-status]').textContent=document.cookie.includes('test_cookie=Cookie-Session-Only-1234')?'Cookie ready':'No Cookie';document.querySelector('[data-testid=status]').textContent=localStorage.getItem('logged')==='yes'?'Logged in':'Ready';</script>'''


@pytest.fixture(scope="module")
def target_server():
    """独立被测系统，允许登录、LocalStorage 和重定向测试；退出时释放监听。"""
    class Handler(BaseHTTPRequestHandler):
        """固定 HTML 测试目标，不运行调用者提交的代码。"""
        def do_GET(self):
            """返回固定页面或跳到未授权端口的重定向。"""
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "http://127.0.0.1:9/blocked")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(HTML)
        def do_POST(self):
            """验证演示测试账号，成功后建立真实 HTTP Cookie 会话。"""
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            valid = self.path == "/login" and body == {"username": "tester", "password": "Super-Secret-abc123"}
            self.send_response(200 if valid else 401)
            self.send_header("Content-Type", "application/json")
            if valid:
                self.send_header("Set-Cookie", "session=test-session; HttpOnly; Path=/")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": valid}).encode())
        def log_message(self, *_args):
            """测试服务不输出请求与凭据。"""
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_port
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


@pytest.fixture()
def web_setup(api, admin, db, target_server):
    """创建授权项目与环境，不修改开发数据库或 ZAP 资源。"""
    from app.models.configuration import Environment
    response = api.post("/projects", username=admin, json={"name": unique("web")})
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    env = Environment(name=unique("web-env"), display_name="浏览器验收环境", base_url=f"http://127.0.0.1:{target_server}", is_active=True)
    db.add(env)
    db.commit()
    allowed = api.post(f"/projects/{project_id}/targets", username=admin,
        json={"scheme": "http", "host": "127.0.0.1", "port": target_server, "enabled": True})
    assert allowed.status_code == 201, allowed.text
    return project_id, env.id


def step(operation, value=None, locator=None, **kwargs):
    """生成显式结构化步骤，便于测试各操作。"""
    result = {"name": operation, "operation": operation, **kwargs}
    if value is not None:
        result["value"] = value
    if locator:
        result["locator"] = {"strategy": "TEST_ID", "value": locator}
    return result


def create_case(api, admin, project_id, steps=None, **kwargs):
    """经 API 创建未确认 Web 用例。"""
    response = api.post(f"/projects/{project_id}/web-cases", username=admin, json={
        "name": unique("browser-case"), "steps": steps or [step("NAVIGATE", "/")], **kwargs})
    assert response.status_code == 201, response.text
    return response.json()


def confirm(api, admin, case):
    """模拟人工审核按钮，版本号必须与保存结果相同。"""
    response = api.post(f"/web-cases/{case['id']}/confirm", username=admin, json={"revision": case["revision"]})
    assert response.status_code == 200, response.text
    assert response.json()["confirmed"]


def test_migration_and_web_asset_storage(api, admin, db, web_setup):
    """0012 新表存在，用例和步骤使用旧表；原始脚本和非法操作被拒绝。"""
    project, _ = web_setup
    assert db.execute(text("select version_num from alembic_version")).scalar() == "0016"
    case = create_case(api, admin, project)
    from app.features.test_management.models.test_case import TestCase
    from app.features.test_management.models.test_step import TestStep
    assert db.get(TestCase, case["id"]).target_type == "WEB"
    assert "web_encrypted" in db.query(TestStep).filter_by(test_case_id=case["id"]).one().config_json
    response = api.post(f"/projects/{project}/web-cases", username=admin, json={"name": "unsafe", "steps": [{"name": "x", "operation": "EVALUATE", "script": "fetch('http://evil')"}]})
    assert response.status_code == 422
    response = api.post(f"/projects/{project}/web-cases", username=admin, json={"name": "unsafe", "steps": [step("NAVIGATE", "file:///etc/passwd")]})
    assert response.status_code == 422


def test_confirmation_revision_and_page_change(api, admin, web_setup):
    """未确认不能调试，页面元素变更使旧指纹失效，过期 revision 返回 409。"""
    project, env = web_setup
    page = api.post(f"/projects/{project}/web-pages", username=admin, json={"name": unique("login-page"), "path": "/", "elements": [{"key": "login", "locator": {"strategy": "TEST_ID", "value": "login"}}]}).json()
    case = create_case(api, admin, project, [step("NAVIGATE", "/"), step("CLICK", page_object_id=page["id"], element_key="login")])
    assert api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env}).status_code == 409
    assert api.post(f"/web-cases/{case['id']}/confirm", username=admin, json={"revision": 999}).status_code == 409
    confirm(api, admin, case)
    changed = api.put(f"/projects/{project}/web-pages/{page['id']}", username=admin, json={"name": page["name"], "path": "/", "revision": page["revision"], "elements": [{"key": "login", "locator": {"strategy": "ROLE", "value": "button", "name": "Login"}}]})
    assert changed.status_code == 200, changed.text
    assert not api.get(f"/web-cases/{case['id']}", username=admin).json()["confirmed"]


def test_credentials_encryption_and_scope(api, admin, db, web_setup):
    """密码、Cookie、LocalStorage/JWT 只写密文；外域与过期登录态不能保存。"""
    project, env = web_setup
    body = {"name": "测试账号", "environment_id": env, "username": "tester", "password": "Unique-Secret-abc123",
        "jwt": "jwt-secret-value", "storage_state": {"cookies": [], "origins": []},
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}
    response = api.post(f"/projects/{project}/web-auth-profiles", username=admin, json=body)
    assert response.status_code == 201, response.text
    assert "Unique-Secret" not in response.text and "jwt-secret" not in response.text
    from app.features.web_ui.models import WebAuthProfile
    row = db.get(WebAuthProfile, response.json()["id"])
    assert "Unique-Secret" not in row.secret_encrypted
    bad = {**body, "storage_state": {"cookies": [], "origins": [{"origin": "https://outside.invalid", "localStorage": []}]}}
    assert api.post(f"/projects/{project}/web-auth-profiles", username=admin, json=bad).status_code == 400
    bad = {**body, "expires_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()}
    assert api.post(f"/projects/{project}/web-auth-profiles", username=admin, json=bad).status_code == 400


def test_real_browser_login_operations_failure_report(api, admin, db, web_setup):
    """完整验收：登录、操作、断言失败、截图/Trace、既有执行与报告。真实 Chromium。"""
    project, env = web_setup
    auth = api.post(f"/projects/{project}/web-auth-profiles", username=admin, json={
        "name": "浏览器测试账号", "environment_id": env, "username": "tester",
        "password": "Super-Secret-abc123", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}).json()
    steps = [step("NAVIGATE", "/"), step("FILL", "${data.auth_username}", "username"),
        step("FILL", "${data.auth_password}", "password", sensitive=True), step("CLICK", locator="login"),
        step("WAIT", locator="status"), step("SELECT", "b", "choice"),
        step("UPLOAD", locator="file", upload={"name": "sample.txt", "content_base64": base64.b64encode(b"sample").decode()}),
        step("ASSERT", locator="status", expected="Logged in"),
        step("ASSERT", locator="output", expected="deliberate mismatch", timeout_ms=100)]
    case = create_case(api, admin, project, steps, auth_profile_id=auth["id"], timeout_ms=2000)
    confirm(api, admin, case)
    response = api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["failed"] == 1 and run["error"] == 0, run
    history = api.get(f"/projects/{project}/web-executions", username=admin).json()["items"]
    execution = history[0]
    assert execution["status"] == "FAILED" and execution["error_code"] == "WEB_ASSERTION_FAILED"
    assert "Super-Secret" not in json.dumps(execution)
    artifacts = execution["response_snapshot"]["web"]["artifacts"]
    assert {a["kind"] for a in artifacts} == {"FAILURE_SCREENSHOT", "TRACE"}, execution
    for item in artifacts:
        attachment = api.get(f"/web-artifacts/{item['id']}", username=admin)
        assert attachment.status_code == 200
        if item["kind"] == "TRACE":
            with zipfile.ZipFile(io.BytesIO(attachment.content)) as trace:
                assert any(n.endswith(".trace") for n in trace.namelist())
                assert all("Super-Secret" not in trace.read(n).decode(errors="ignore") for n in trace.namelist())
        else:
            assert attachment.content.startswith(b"\x89PNG")
    report = api.post(f"/test-runs/{run['id']}/report", username=admin, json={"generate_ai_summary": False})
    assert report.status_code in (200, 201), report.text
    report_id = report.json()["report_id"]
    detail = api.get(f"/reports/{report_id}", username=admin).json()
    assert detail["case_executions"][0]["response_snapshot"]["web"]["artifacts"]


def test_browser_session_isolation_and_manual_storage(api, admin, web_setup, target_server):
    """人工扫码后导入的 LocalStorage 可复用，但每个执行上下文互相隔离。"""
    project, env = web_setup
    auth = api.post(f"/projects/{project}/web-auth-profiles", username=admin, json={
        "name": "扫码后人工会话", "environment_id": env,
        "storage_state": {"cookies": [], "origins": [{"origin": f"http://127.0.0.1:{target_server}", "localStorage": [{"name": "logged", "value": "yes"}]}]},
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}).json()
    for profile, expected in ((auth["id"], "Logged in"), (None, "Ready")):
        case = create_case(api, admin, project, [step("NAVIGATE", "/"), step("ASSERT", locator="status", expected=expected)], auth_profile_id=profile)
        confirm(api, admin, case)
        result = api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env})
        assert result.status_code == 200 and result.json()["passed"] == 1, result.text


def test_outbound_redirect_and_no_authorization(api, admin, web_setup):
    """跳转到未授权端口不能访问，直接外部导航被拒绝。"""
    project, env = web_setup
    for path in ("/redirect", "http://127.0.0.1:9/no"):
        case = create_case(api, admin, project, [step("NAVIGATE", path)], timeout_ms=1000)
        confirm(api, admin, case)
        result = api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env})
        assert result.status_code == 200 and result.json()["error"] == 1, result.text


def test_cross_project_and_viewer_permissions(api, admin, web_setup):
    """外部用户读写均 404，viewer 不可创建或确认用例。"""
    project, _ = web_setup
    case = create_case(api, admin, project)
    outsider = unique("web-outsider")
    uid = api.register(outsider).json()["user"]["id"]
    api.login(outsider)
    assert api.get(f"/web-cases/{case['id']}", username=outsider).status_code == 404
    assert api.post(f"/projects/{project}/web-pages", username=outsider, json={"name": "x", "path": "/"}).status_code == 404
    api.put(f"/projects/{project}/members/{uid}", username=admin, json={"user_id": uid, "role": "viewer"})
    api.login(outsider)
    assert api.post(f"/web-cases/{case['id']}/confirm", username=outsider, json={"revision": case["revision"]}).status_code == 403


def test_fixture_factory_and_mock_lifecycle(api, admin, db, web_setup):
    """Web 调试消费真实 STATIC Fixture，并激活/关闭原有 MockContext。"""
    from tests.test_19_data_factory import _make_fixture, _step
    from tests.test_20_test_data_lifecycle import _declare_fixtures
    from tests.test_21_mock_management import _create_service, _create_endpoint, _create_scenario, _skey
    from app.features.mock_management.models import MockContext
    from app.features.test_data.models.execution import DataExecution
    project, env = web_setup
    _make_fixture(api, admin, project, key="WEB_DATA", steps=[_step("STATIC", 1, config={"values": {"username": "Factory-user"}})],
                  outputs=[{"name": "username", "value_type": "STRING", "source_path": "username"}])
    case = create_case(api, admin, project, [step("NAVIGATE", "/"), step("FILL", "${fixture.WEB_DATA.username}", "username"),
        step("ASSERT", locator="username", assertion="VALUE", expected="Factory-user")])
    _declare_fixtures(api, admin, case["id"], "WEB_DATA")
    svc = _create_service(api, admin, project, _skey())
    endpoint = _create_endpoint(api, admin, svc["service"]["id"], path="/web-dependency")
    scenario = _create_scenario(api, admin, endpoint["id"], _skey(), is_default=True, body={"ok": True})
    response = api.put(f"/test-cases/{case['id']}/mocks", username=admin, json={"mocks": [{
        "mock_service_id": svc["service"]["id"], "mock_endpoint_id": endpoint["id"],
        "mock_scenario_id": scenario["id"], "scope": "EXECUTION", "sort": 0}]})
    assert response.status_code == 200, response.text
    confirm(api, admin, case)
    response = api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env})
    assert response.status_code == 200 and response.json()["passed"] == 1, response.text
    run_id = response.json()["id"]
    assert db.query(DataExecution).filter_by(test_run_id=run_id).count() == 1
    context = db.query(MockContext).filter_by(test_run_id=run_id).one()
    assert context.status == "CLOSED"


def test_mixed_api_web_flow_and_report(api, admin, db, web_setup):
    """同一 Business Flow 顺序执行 API + WEB，动作输出写 RuntimeContext、附件进入旧报告。"""
    from tests.test_15_test_executor import _add_action, _add_binding, _make_iface, _build_plan_with_cases
    from app.features.business.models.business_domain import BusinessDomain
    from app.features.business.models.business_flow import BusinessFlow
    from app.features.business.models.execution import ActionExecution
    project, env = web_setup
    domain = BusinessDomain(project_id=project, name=unique("web-domain"))
    db.add(domain)
    db.flush()
    flow = BusinessFlow(project_id=project, domain_id=domain.id, name=unique("mixed"), status="ACTIVE")
    db.add(flow)
    db.flush()
    api_action = _add_action(db, flow.id, "API 读取目标", "OPEN", 1)
    interface = _make_iface(db, project, "GET", "/", "页面健康 API")
    _add_binding(db, api_action.id, interface)
    web_action = _add_action(db, flow.id, "Web 验证页面", "CHECK_WEB", 2)
    db.commit()
    ui_case = create_case(api, admin, project, [step("NAVIGATE", "/"), step("ASSERT", locator="output", expected="Report ready", output_variable="web_text")])
    confirm(api, admin, ui_case)
    response = api.post(f"/business-actions/{web_action.id}/web-binding", username=admin, json={"web_case_id": ui_case["id"]})
    assert response.status_code == 201, response.text
    outer = api.post(f"/projects/{project}/test-cases", username=admin, json={"name": unique("混合业务用例"), "target_type": "BUSINESS_FLOW", "business_flow_id": flow.id})
    assert outer.status_code == 201, outer.text
    plan = _build_plan_with_cases(api, admin, project, [outer.json()["id"]], env)
    run = api.post(f"/test-plans/{plan}/runs", username=admin, json={"environment_id": env})
    assert run.status_code == 200 and run.json()["passed"] == 1, run.text
    executions = api.get(f"/test-runs/{run.json()['id']}/cases", username=admin).json()["items"]
    assert executions[0]["response_snapshot"]["web"]["artifacts"]
    actions = db.query(ActionExecution).order_by(ActionExecution.id.desc()).limit(2).all()
    assert {r.status for r in actions} == {"SUCCESS"}
    assert any((r.output_context or {}).get("web_text") == "Report ready" for r in actions)


def test_agent_draft_requires_human_review(api, admin, db, web_setup, monkeypatch):
    """Agent 使用平台 Provider，页面上下文可用但凭据不进 prompt；生成不自动执行。"""
    from app.features.agent.tools import web_ui_tool
    project, env = web_setup
    page = api.post(f"/projects/{project}/web-pages", username=admin, json={"name": "页面", "path": "/", "elements": []})
    assert page.status_code == 201
    captured = []
    class Provider:
        """可控结构化模型，验证协议而不依赖外部模型网络。"""
        def generate_structured(self, system, user_content, **_kwargs):
            """返回结构化步骤，记录上下文供断言。"""
            captured.append(user_content)
            return {"name": unique("ai-web"), "steps": [step("NAVIGATE", "/")]}
    monkeypatch.setattr(web_ui_tool, "ProductionLLMProvider", lambda _db: Provider())
    generated = api.post(f"/projects/{project}/web-agent/draft", username=admin, json={"instruction": "检查页面", "page_object_ids": [page.json()["id"]]})
    assert generated.status_code == 201, generated.text
    case = generated.json()
    assert case["source_type"] == "AI" and not case["confirmed"]
    assert '"pages"' in captured[0] and 'secret_encrypted' not in captured[0]
    assert api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env}).status_code == 409
    confirm(api, admin, case)
    class BadProvider:
        """模拟 LLM 试图生成脚本。"""
        def generate_structured(self, *_args, **_kwargs):
            """恶意字段应被 Pydantic 拒绝。"""
            return {"name": "bad", "steps": [{"name": "bad", "operation": "EVALUATE", "script": "os.system('bad')"}]}
    monkeypatch.setattr(web_ui_tool, "ProductionLLMProvider", lambda _db: BadProvider())
    assert api.post(f"/projects/{project}/web-agent/draft", username=admin, json={"instruction": "生成脚本"}).status_code == 400


def test_timeout_releases_browser_slot(api, admin, web_setup):
    """元素缺失触发超时后，后续浏览器仍可执行，不泄漏资源配额。"""
    project, env = web_setup
    failed = create_case(api, admin, project, [step("NAVIGATE", "/"), step("CLICK", locator="missing-element", timeout_ms=100)], total_timeout_ms=1000)
    confirm(api, admin, failed)
    result = api.post(f"/web-cases/{failed['id']}/debug", username=admin, json={"environment_id": env})
    assert result.status_code == 200 and result.json()["error"] == 1, result.text
    passed = create_case(api, admin, project)
    confirm(api, admin, passed)
    result = api.post(f"/web-cases/{passed['id']}/debug", username=admin, json={"environment_id": env})
    assert result.status_code == 200 and result.json()["passed"] == 1, result.text


def test_attachment_access_and_auth_revocation(api, admin, web_setup):
    """附件不能跨项目下载；撤销认证后用例不能静默以匿名状态执行。"""
    project, env = web_setup
    auth = api.post(f"/projects/{project}/web-auth-profiles", username=admin, json={"name": "临时", "environment_id": env,
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}).json()
    case = create_case(api, admin, project, auth_profile_id=auth["id"])
    confirm(api, admin, case)
    run = api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env})
    assert run.status_code == 200 and run.json()["passed"] == 1
    item = api.get(f"/projects/{project}/web-executions", username=admin).json()["items"][0]
    artifact = item["response_snapshot"]["web"]["artifacts"][0]
    outsider = unique("attachment-outsider")
    api.register(outsider)
    api.login(outsider)
    assert api.get(f"/web-artifacts/{artifact['id']}", username=outsider).status_code == 404
    assert api.get(f"/web-artifacts/{artifact['id']}").status_code == 401
    assert api.delete(f"/web-auth-profiles/{auth['id']}", username=admin).status_code == 204
    assert api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env}).status_code == 409


def test_independent_browser_concurrency(db, web_setup, target_server):
    """两个真实 Chromium 并发运行，storage_state 和浏览器资源互不共享。"""
    from concurrent.futures import ThreadPoolExecutor
    from app.features.web_ui.runtime.playwright_executor import PlaywrightExecutor
    from app.features.web_ui.runtime.policy import TargetPolicy
    project, _ = web_setup
    policy1, policy2 = TargetPolicy(db, project), TargetPolicy(db, project)
    def run(policy, logged):
        """线程内创建和关闭自己的 Playwright 驱动与 BrowserContext。"""
        state = {"cookies": [], "origins": [{"origin": f"http://127.0.0.1:{target_server}", "localStorage": [{"name": "logged", "value": "yes"}]}]} if logged else None
        return PlaywrightExecutor().execute(steps=[step("NAVIGATE", "/"), step("ASSERT", locator="status", expected="Logged in" if logged else "Ready")],
            policy=policy, base_url=f"http://127.0.0.1:{target_server}", storage_state=state, timeout_ms=2000)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(run, policy1, True), pool.submit(run, policy2, False)
        assert first.result(timeout=30).status == "PASSED"
        assert second.result(timeout=30).status == "PASSED"


def test_migration_downgrade_preserves_existing_contracts(db):
    """回滚只删除四张 Web 扩展表；既有测试、安全、Mock、业务和报告表仍在。"""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from tests.conftest import TEST_DSN, BACKEND_DIR
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", TEST_DSN)
    db.rollback()
    try:
        command.downgrade(config, "0011")
        tables = set(inspect(db.bind).get_table_names())
        assert not {"web_case", "web_auth_profile", "web_artifact", "web_page_object"} & tables
        assert {"test_case", "test_step", "case_execution", "test_run", "test_report", "security_case", "mock_service"} <= tables
    finally:
        command.upgrade(config, "head")
    assert db.execute(text("select version_num from alembic_version")).scalar() == "0016"


def test_cookie_and_jwt_are_used_by_real_browser(api, admin, web_setup, target_server):
    """Cookie 和 JWT 以已授权环境为作用域注入真实 Context；测试值不进入步骤日志。"""
    from app.features.web_ui.runtime.playwright_executor import PlaywrightExecutor
    from app.features.web_ui.runtime.policy import TargetPolicy
    from app.features.web_ui.runtime.adapter import validate_storage_state
    from app.models.configuration import Environment
    project, env = web_setup
    auth = api.post(f"/projects/{project}/web-auth-profiles", username=admin, json={
        "name": "JWT 与 Cookie", "environment_id": env, "jwt": "Jwt-Session-Only-1234",
        "storage_state": {"cookies": [{"name": "test_cookie", "value": "Cookie-Session-Only-1234", "url": f"http://127.0.0.1:{target_server}"}], "origins": []},
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    assert auth.status_code == 201, auth.text
    # 页面对象中的固定 HTML 会显示客户端存储状态；账号仍由适配器解密注入。
    case = create_case(api, admin, project, [step("NAVIGATE", "/"), step("ASSERT", locator="jwt-status", expected="JWT ready"),
        step("ASSERT", locator="cookie-status", expected="Cookie ready")], auth_profile_id=auth.json()["id"])
    confirm(api, admin, case)
    result = api.post(f"/web-cases/{case['id']}/debug", username=admin, json={"environment_id": env})
    assert result.status_code == 200 and result.json()["passed"] == 1, result.text
    execution = api.get(f"/projects/{project}/web-executions", username=admin).json()["items"][0]
    assert "Session-Only" not in json.dumps(execution)


def test_step_reorder_and_generic_execution_cannot_bypass_review(api, admin, db, web_setup, monkeypatch):
    """步骤编辑与排序使用原 TestStep；通用计划执行入口同样执行人工确认门禁。"""
    from app.features.web_ui.runtime.playwright_executor import PlaywrightExecutor
    from tests.test_15_test_executor import _build_plan_with_cases
    from app.features.test_management.models.test_step import TestStep
    project, env = web_setup
    case = create_case(api, admin, project, [step("NAVIGATE", "/"), step("ASSERT", assertion="TITLE", expected="Web UI Demo")])
    changed = api.put(f"/projects/{project}/web-cases/{case['id']}", username=admin, json={
        "name": case["name"], "revision": case["revision"], "steps": [step("NAVIGATE", "/?updated=1"), step("ASSERT", locator="output", expected="Report ready")]})
    assert changed.status_code == 200, changed.text
    assert changed.json()["revision"] == case["revision"] + 1
    rows = db.query(TestStep).filter_by(test_case_id=case["id"]).order_by(TestStep.sort).all()
    assert [r.sort for r in rows] == [0, 1]
    assert api.put(f"/projects/{project}/web-cases/{case['id']}", username=admin, json={
        "name": case["name"], "revision": case["revision"], "steps": case["steps"]}).status_code == 409
    def forbidden_execute(*_args, **_kwargs):
        """门禁应在启动 Chromium 之前失败。"""
        raise AssertionError("未确认步骤不允许启动浏览器")
    monkeypatch.setattr(PlaywrightExecutor, "execute", forbidden_execute)
    plan = _build_plan_with_cases(api, admin, project, [case["id"]], env)
    run = api.post(f"/test-plans/{plan}/runs", username=admin, json={"environment_id": env})
    assert run.status_code == 200 and run.json()["error"] == 1, run.text
    record = api.get(f"/test-runs/{run.json()['id']}/cases", username=admin).json()["items"][0]
    assert record["error_code"] == "WEB_REVIEW_REQUIRED"


def test_semantic_and_fallback_locators(db, web_setup, target_server):
    """Role、Label、Text、CSS、XPath 都经过固定 Playwright 定位 API。"""
    from app.features.web_ui.runtime.playwright_executor import PlaywrightExecutor
    from app.features.web_ui.runtime.policy import TargetPolicy
    project, _ = web_setup
    steps = [step("NAVIGATE", "/")]
    for strategy, value, extra in (("ROLE", "button", {"name": "Login"}), ("LABEL", "User", {}),
                                    ("TEXT", "Report ready", {}), ("CSS", "[data-testid=output]", {}),
                                    ("XPATH", "//*[@data-testid='output']", {})):
        steps.append({"name": strategy, "operation": "ASSERT", "locator": {"strategy": strategy, "value": value, **extra},
                      "assertion": "COUNT", "operator": "EQ", "expected": "1"})
    result = PlaywrightExecutor().execute(steps=steps, base_url=f"http://127.0.0.1:{target_server}", policy=TargetPolicy(db, project), timeout_ms=1000)
    assert result.status == "PASSED", result


def test_business_action_web_binding_keeps_outer_assertions(api, admin, db, web_setup):
    """WEB 内部成功也不能跳过外层 BUSINESS_ACTION TestCase 的断言。"""
    from tests.test_15_test_executor import _add_action, _build_plan_with_cases
    from app.features.business.models.business_domain import BusinessDomain
    from app.features.business.models.business_flow import BusinessFlow
    project, env = web_setup
    domain = BusinessDomain(project_id=project, name=unique("outer-assert"))
    db.add(domain)
    db.flush()
    flow = BusinessFlow(project_id=project, domain_id=domain.id, name=unique("outer-flow"), status="ACTIVE")
    db.add(flow)
    db.flush()
    action = _add_action(db, flow.id, "检查页面", "WEB_CHECK", 1)
    db.commit()
    ui_case = create_case(api, admin, project, [step("NAVIGATE", "/"), step("ASSERT", locator="output", expected="Report ready", output_variable="web_text")])
    confirm(api, admin, ui_case)
    assert api.post(f"/business-actions/{action.id}/web-binding", username=admin, json={"web_case_id": ui_case["id"]}).status_code == 201
    outer = api.post(f"/projects/{project}/test-cases", username=admin, json={"name": unique("outer-case"), "target_type": "BUSINESS_ACTION", "business_action_id": action.id}).json()
    assertion = api.post(f"/test-cases/{outer['id']}/assertions", username=admin, json={"assertion_type": "JSON_PATH", "path": "$.web_text", "operator": "EQ", "expected_value": "wrong", "required": True})
    assert assertion.status_code == 201, assertion.text
    plan = _build_plan_with_cases(api, admin, project, [outer["id"]], env)
    response = api.post(f"/test-plans/{plan}/runs", username=admin, json={"environment_id": env})
    assert response.status_code == 200 and response.json()["failed"] == 1, response.text
    record = api.get(f"/test-runs/{response.json()['id']}/cases", username=admin).json()["items"][0]
    assert record["error_code"] == "ASSERTION_FAILED"
    assert record["assertion_results"][0]["passed"] is False
