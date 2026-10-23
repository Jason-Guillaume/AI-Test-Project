"""Web UI 控制台真实浏览器验收：创建、编辑、人工确认、执行、历史与报告附件查看。"""
from __future__ import annotations
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
import httpx
from tests.conftest import DEFAULT_PASSWORD, unique
from tests.test_30_web_ui import target_server, web_setup


def free_port():
    """为隔离服务选择空闲端口，不触碰现有服务与 ZAP 资源。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_http(url, process):
    """等待临时后端或前端就绪，失败时及时终止。"""
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError("临时验收服务启动失败")
        try:
            if httpx.get(url, timeout=1, trust_env=False).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise AssertionError("临时验收服务启动超时")


def test_real_console_create_confirm_debug_report(api, admin, db, web_setup, tmp_path):
    """独立测试库和临时服务，真实 Chromium 点击控制台全链路。"""
    from playwright.sync_api import sync_playwright, expect
    project, env = web_setup
    root = Path(__file__).resolve().parents[2]
    back_port, front_port = free_port(), free_port()
    back = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(back_port)],
        cwd=root / "backend", env=dict(os.environ), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    front = None
    try:
        wait_http(f"http://127.0.0.1:{back_port}/healthz", back)
        front = subprocess.Popen(["npm", "run", "dev", "--", "--host", "127.0.0.1", "--port", str(front_port), "--strictPort"],
            cwd=root / "frontend", env={**os.environ, "VITE_API_PROXY_TARGET": f"http://127.0.0.1:{back_port}"}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        base = f"http://127.0.0.1:{front_port}"
        wait_http(base, front)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1600, "height": 1100})
            page.set_default_timeout(15000)
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(base + "/login")
            page.get_by_label("用户名", exact=True).fill(admin)
            page.get_by_label("密码", exact=True).fill(DEFAULT_PASSWORD)
            page.get_by_role("button", name=re.compile(r"登\s*录"), exact=True).click()
            page.wait_for_url("**/admin/dashboard")
            page.evaluate("id => localStorage.setItem('console.current_project_id', String(id))", project)
            page.goto(base + "/console/web-ui")
            expect(page.get_by_role("heading", name="Web UI 自动化", exact=True)).to_be_visible()
            page.get_by_role("button", name="新增 UI 用例").click()
            dialog = page.get_by_role("dialog")
            name = unique("控制台验收")
            dialog.get_by_label("用例名称", exact=True).fill(name)
            dialog.get_by_role("button", name="添加结构化步骤").click()
            dialog.locator("#steps_1_name").fill("检查页面文本")
            dialog.locator("#steps_1_operation").focus()
            dialog.locator("#steps_1_operation").press("ArrowDown")
            page.get_by_title("ASSERT", exact=True).click()
            dialog.locator("#steps_1_locator_value").fill("output")
            dialog.locator("#steps_1_expected").fill("Report ready")
            dialog.get_by_role("button", name="确 定").click()
            expect(page.get_by_role("cell", name=name, exact=True)).to_be_visible()
            row = page.get_by_role("row").filter(has=page.get_by_role("cell", name=name, exact=True))
            row.get_by_role("button", name="编辑步骤").click()
            dialog = page.get_by_role("dialog")
            expect(dialog.locator("#steps_1_locator_value")).to_have_value("output")
            dialog.get_by_role("button", name="确 定").click()
            expect(page.get_by_role("dialog")).to_have_count(0)
            row.get_by_role("button", name="人工确认").click()
            with page.expect_response(lambda r: r.url.endswith("/confirm") and r.request.method == "POST") as confirmed:
                page.get_by_role("button", name="确 定").click()
            assert confirmed.value.status == 200, confirmed.value.text()
            expect(row.get_by_text("已确认", exact=False)).to_be_visible()
            from app.models.configuration import Environment
            environment = db.get(Environment, env)
            env_name = f"{environment.display_name or environment.name}（{environment.name}）"
            page.get_by_role("combobox").last.fill(environment.name)
            page.get_by_title(env_name, exact=True).click()
            row.get_by_role("button", name="调试执行").click()
            expect(page.get_by_role("cell", name="PASSED", exact=True)).to_be_visible(timeout=30000)
            page.get_by_role("button", name="日志 / 截图 / Trace").first.click()
            dialog = page.get_by_role("dialog")
            dialog.get_by_role("button", name="执行截图").click()
            expect(page.get_by_alt_text("已遮蔽输入信息的浏览器截图")).to_be_visible()
            page.get_by_role("dialog").last.get_by_role("button", name="Close").click()
            expect(page.get_by_role("dialog")).to_have_count(1)
            page.get_by_role("dialog").get_by_role("button", name="查看 Trace").click()
            expect(page.get_by_text("Trace 动作时序", exact=False)).to_be_visible()
            page.get_by_role("dialog").last.get_by_role("button", name="Close").click()
            expect(page.get_by_role("dialog")).to_have_count(1)
            page.get_by_role("dialog").get_by_role("button", name="Close").click()
            page.get_by_role("button", name="查看报告").first.click()
            page.get_by_role("tab", name="用例结果", exact=False).click()
            page.get_by_role("button", name="详情", exact=True).first.click()
            expect(page.get_by_text("执行截图", exact=True)).to_be_visible()
            page.screenshot(path=str(tmp_path / "web-ui-report.png"), animations="disabled")
            assert not errors, errors
            browser.close()
    finally:
        for process in (front, back):
            if process:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
