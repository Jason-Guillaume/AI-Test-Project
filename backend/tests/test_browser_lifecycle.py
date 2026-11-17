"""Playwright 浏览器生命周期、容器参数与并发槽位释放验收测试。"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from app.execution.browser import playwright_executor, session_manager
from app.execution.browser.playwright_executor import (
    PlaywrightExecutor,
    chromium_launch_args,
    classify_browser_error,
)
from app.execution.browser.policy import TargetPolicy
from app.execution.browser.session_manager import BrowserSession, SessionRegistry


def test_chromium_launch_args_include_container_flags_on_linux(monkeypatch):
    monkeypatch.setattr(playwright_executor.sys, "platform", "linux")
    monkeypatch.setenv("PLAYWRIGHT_NO_SANDBOX", "1")
    policy = SimpleNamespace(resolver_rules=["MAP app.test 127.0.0.1"])

    args = chromium_launch_args(policy)

    assert "--disable-dev-shm-usage" in args
    assert "--no-sandbox" in args
    assert "--disable-setuid-sandbox" in args
    assert "--host-resolver-rules=MAP app.test 127.0.0.1" in args


def test_classify_browser_error_distinguishes_missing_chromium_and_timeout():
    missing_code, missing_msg = classify_browser_error(
        RuntimeError("Executable doesn't exist at /home/runner/.cache/ms-playwright/chrome-headless-shell")
    )
    assert missing_code == "WEB_BROWSER_ERROR"
    assert "playwright install --with-deps chromium" in missing_msg

    timeout_code, timeout_msg = classify_browser_error(TimeoutError("browser start timed out"))
    assert timeout_code == "WEB_TIMEOUT"
    assert "超时" in timeout_msg


def test_playwright_executor_timeout_and_error_always_release_slot(monkeypatch):
    class RaisingPlaywright:
        def __init__(self, exc: BaseException):
            self._exc = exc

        def __enter__(self):
            raise self._exc

        def __exit__(self, *_args):
            return False

    initial_slots = playwright_executor._SLOTS._value
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: RaisingPlaywright(TimeoutError("navigation timed out")),
    )
    timeout_result = PlaywrightExecutor().execute(
        steps=[{"name": "open", "operation": "NAVIGATE", "value": "/"}],
        base_url="http://127.0.0.1:8000",
        policy=TargetPolicy([]),
    )
    assert timeout_result.status == "ERROR"
    assert timeout_result.error_code == "WEB_TIMEOUT"
    assert playwright_executor._SLOTS._value == initial_slots

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: RaisingPlaywright(RuntimeError("Executable doesn't exist at /ms-playwright/chrome")),
    )
    missing_result = PlaywrightExecutor().execute(
        steps=[{"name": "open", "operation": "NAVIGATE", "value": "/"}],
        base_url="http://127.0.0.1:8000",
        policy=TargetPolicy([]),
    )
    assert missing_result.status == "ERROR"
    assert missing_result.error_code == "WEB_BROWSER_ERROR"
    assert "playwright install --with-deps chromium" in (missing_result.error_message or "")
    assert playwright_executor._SLOTS._value == initial_slots


def test_session_close_releases_slot_even_when_worker_hangs(monkeypatch):
    initial_slots = session_manager._SLOTS._value
    monkeypatch.setattr(session_manager, "_CLOSE_WAIT_SECONDS", 0.05)

    class HungBrowserSession(BrowserSession):
        def _open_browser(self, storage_state, timeout_ms, target_page_path):
            return {"url": self._base_url}

        def _close_browser(self):
            time.sleep(0.3)

    session = HungBrowserSession.open(
        base_url="http://127.0.0.1:8000",
        storage_state=None,
        headers={},
        policy=TargetPolicy([]),
    )
    assert session_manager._SLOTS._value == initial_slots - 1

    session.close()
    assert session_manager._SLOTS._value == initial_slots


def test_session_registry_concurrent_open_same_id_uses_single_slot(monkeypatch):
    initial_slots = session_manager._SLOTS._value
    opened = []

    class FakeSession(BrowserSession):
        def _open_browser(self, storage_state, timeout_ms, target_page_path):
            opened.append(self._base_url)
            time.sleep(0.05)
            return {"url": self._base_url}

        def _close_browser(self):
            return None

    monkeypatch.setattr(session_manager, "BrowserSession", FakeSession)
    registry = SessionRegistry()
    results = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait(timeout=2)
        results.append(
            registry.open_session(
                987654,
                base_url="http://127.0.0.1:8000",
                storage_state=None,
                headers={},
                policy=TargetPolicy([]),
            )
        )

    try:
        threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert len(results) == 2
        assert results[0] is results[1]
        assert len(opened) == 1
        assert session_manager._SLOTS._value == initial_slots - 1
    finally:
        registry.close_all()
        assert session_manager._SLOTS._value == initial_slots
