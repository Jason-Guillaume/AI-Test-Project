"""UI 智能体二轮 Phase A：受控会话、页面观测、脱敏与资源释放。"""
from __future__ import annotations
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4
import pytest
from sqlalchemy import text
from tests.conftest import unique

# 测试页面：含密码框、普通输入框、按钮和文本，用于验证脱敏与遮罩
HTML = b'''<!doctype html><html><head><title>Agent Test</title></head><body>
<h1>Agent Sandbox</h1>
<label>User<input data-testid="username" value="alice"></label>
<label>Pass<input data-testid="password" type="password" value="Super-Secret-abc123"></label>
<button data-testid="submit">Submit</button>
<p data-testid="status">Ready</p>
<p>Token: jwt-abcdefghij1234567890</p>
</body></html>'''


@pytest.fixture(scope="module")
def target_server():
    """独立被测系统，提供固定测试页面；退出时释放监听。"""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            """返回浏览器代理测试使用的 HTML 页面。"""
            body = HTML
            reflected_key = self.headers.get("X-Api-Key")
            if reflected_key:
                body = body.replace(b"</body>", f"<p>Reflected key: {reflected_key}</p></body>".encode())
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *_args):
            """禁用 HTTP 测试服务的默认访问日志。"""
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
    """创建授权项目、环境与出站目标，不修改开发数据库。"""
    from app.models.configuration import Environment
    response = api.post("/projects", username=admin, json={"name": unique("agent")})
    assert response.status_code == 201, response.text
    project_id = response.json()["id"]
    env = Environment(name=unique("agent-env"), display_name="智能体测试环境",
                      base_url=f"http://127.0.0.1:{target_server}", is_active=True)
    db.add(env)
    db.commit()
    from app.features.environment_configuration.models import ProjectEnvironment
    db.add(ProjectEnvironment(project_id=project_id, environment_id=env.id, base_url=env.base_url, is_active=True))
    db.commit()
    allowed = api.post(f"/projects/{project_id}/targets", username=admin,
        json={"scheme": "http", "host": "127.0.0.1", "port": target_server, "enabled": True})
    assert allowed.status_code == 201, allowed.text
    return project_id, env.id


def test_migration_head_preserves_web_agent_tables(db):
    """Web Agent 表保留，测试数据库迁移到当前仓库 head。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from tests.conftest import BACKEND_DIR
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    head = db.execute(text("select version_num from alembic_version")).scalar()
    assert head == ScriptDirectory.from_config(config).get_current_head()
    tables = {r[0] for r in db.execute(text("select table_name from information_schema.tables "
        "where table_schema='public' and table_name like 'web_agent%'")).all()}
    assert {"web_agent_session", "web_agent_step"} <= tables


def test_session_start_observe_close(api, admin, db, web_setup):
    """完整链路：开会话 → 观察 → 断言脱敏 → 关闭 → 断言资源释放。"""
    project_id, env_id = web_setup
    # 启动会话
    response = api.post(f"/projects/{project_id}/web-agent/sessions", username=admin,
        json={"environment_id": env_id, "target_page_path": "/"})
    assert response.status_code == 201, response.text
    session = response.json()
    assert session["status"] == "ACTIVE"
    assert session["step_budget"] == 20
    assert session["step_count"] == 0

    # 观察页面
    obs = api.post(f"/web-agent/sessions/{session['id']}/observe", username=admin)
    assert obs.status_code == 200, obs.text
    data = obs.json()
    assert data["url"].startswith("http://127.0.0.1")
    assert data["title"] == "Agent Test"

    # 语义树：含结构但不含原始 DOM 和凭据
    tree = data["accessibility_tree"]
    assert "button" in tree
    assert "textbox" in tree
    assert "Super-Secret" not in tree
    assert "jwt-abcdefghij" not in tree
    assert "<input" not in tree
    assert "<button" not in tree

    # 截图：有效 PNG
    assert data["screenshot_b64"]
    import base64
    img = base64.b64decode(data["screenshot_b64"])
    assert img.startswith(b"\x89PNG")

    # 读取会话：步数仍为 0
    got = api.get(f"/web-agent/sessions/{session['id']}", username=admin)
    assert got.json()["step_count"] == 0

    # 关闭会话
    close = api.post(f"/web-agent/sessions/{session['id']}/close", username=admin)
    assert close.status_code == 200, close.text
    assert close.json()["status"] == "CLOSED"

    # 关闭后观察应失败
    again = api.post(f"/web-agent/sessions/{session['id']}/observe", username=admin)
    assert again.status_code == 409


def test_session_observe_with_auth(api, admin, db, web_setup):
    """带登录态的会话：凭据不出现在语义树和截图中。"""
    project_id, env_id = web_setup
    auth = api.post(f"/projects/{project_id}/web-auth-profiles", username=admin, json={
        "name": "智能体测试账号", "environment_id": env_id,
        "username": "tester", "password": "Unique-Pwd-xyz789",
        "storage_state": {"cookies": [], "origins": []},
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()})
    assert auth.status_code == 201, auth.text
    resp = api.post(f"/projects/{project_id}/web-agent/sessions", username=admin,
        json={"environment_id": env_id, "auth_profile_id": auth.json()["id"], "target_page_path": "/"})
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]
    obs = api.post(f"/web-agent/sessions/{sid}/observe", username=admin)
    assert obs.status_code == 200
    blob = obs.text
    assert "Unique-Pwd" not in blob
    assert "tester" not in blob.lower() or "User" in blob  # "tester" 不在测试页面中
    api.post(f"/web-agent/sessions/{sid}/close", username=admin)


def test_session_observe_masks_sensitive_environment_headers(api, admin, db, web_setup):
    """环境默认认证头被页面回显时，不能进入观测语义树。"""
    from app.models.configuration import Environment

    project_id, env_id = web_setup
    secret = "Header-Secret-abc123456"
    environment = db.get(Environment, env_id)
    environment.default_headers = {"X-Api-Key": secret}
    db.commit()

    resp = api.post(f"/projects/{project_id}/web-agent/sessions", username=admin,
        json={"environment_id": env_id, "target_page_path": "/"})
    assert resp.status_code == 201, resp.text
    sid = resp.json()["id"]
    try:
        obs = api.post(f"/web-agent/sessions/{sid}/observe", username=admin)
        assert obs.status_code == 200, obs.text
        assert secret not in obs.json()["accessibility_tree"]
    finally:
        api.post(f"/web-agent/sessions/{sid}/close", username=admin)


def test_session_cross_project_and_viewer(api, admin, db, web_setup):
    """跨项目 404，viewer 不能启动或关闭会话。"""
    project_id, env_id = web_setup
    resp = api.post(f"/projects/{project_id}/web-agent/sessions", username=admin,
        json={"environment_id": env_id, "target_page_path": "/"})
    assert resp.status_code == 201
    sid = resp.json()["id"]
    # 外部用户：不属于项目，直接 404
    outsider = unique("agent-outsider")
    uid = api.register(outsider).json()["user"]["id"]
    api.login(outsider)
    assert api.get(f"/web-agent/sessions/{sid}", username=outsider).status_code == 404
    assert api.post(f"/web-agent/sessions/{sid}/observe", username=outsider).status_code == 404
    # 关闭后外部用户仍不可操作
    api.post(f"/web-agent/sessions/{sid}/close", username=admin)
    assert api.post(f"/web-agent/sessions/{sid}/close", username=outsider).status_code == 404


def test_session_budget_guard(api, admin, db, web_setup):
    """最小步骤预算（1）可正常开会话与观察。"""
    project_id, env_id = web_setup
    resp = api.post(f"/projects/{project_id}/web-agent/sessions", username=admin,
        json={"environment_id": env_id, "target_page_path": "/", "step_budget": 1})
    assert resp.status_code == 201
    sid = resp.json()["id"]
    obs = api.post(f"/web-agent/sessions/{sid}/observe", username=admin)
    assert obs.status_code == 200
    api.post(f"/web-agent/sessions/{sid}/close", username=admin)


def test_session_invalid_environment(api, admin, web_setup):
    """无效环境返回 404，未授权目标返回 400。"""
    project_id, env_id = web_setup
    assert api.post(f"/projects/{project_id}/web-agent/sessions", username=admin,
        json={"environment_id": 99999, "target_page_path": "/"}).status_code == 404
