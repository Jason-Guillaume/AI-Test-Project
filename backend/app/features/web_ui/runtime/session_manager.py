"""受控浏览器会话管理：进程级会话注册表、空闲回收与并发控制。

安全约束：
- 每个会话独立 BrowserContext，不共享用户浏览器。
- 出站目标通过 TargetPolicy 的 DNS 冻结和 route 拦截控制。
- 会话空闲超时自动回收，并发上限 2。
- 不执行脚本、不 eval。
- 不进 AgentState，不可序列化，由 SessionRegistry 管理生命周期。
"""
from __future__ import annotations

import threading
import time
from queue import Queue
from datetime import datetime, timezone
from urllib.parse import urljoin

from app.features.web_ui.runtime.observer import _clean_url, observe as observe_page
from app.features.web_ui.runtime.playwright_executor import BrowserResult, PlaywrightExecutor, scrub
from app.features.web_ui.runtime.policy import TargetPolicy
from app.features.web_ui.schemas import WebStep
from app.shared.errors import conflict

# 进程内浏览器并发上限（独立于 Web 执行器）
_SLOTS = threading.BoundedSemaphore(2)
# 会话注册表锁
_LOCK = threading.Lock()
# 活动会话表：session_id -> BrowserSession
_SESSIONS: dict[int, "BrowserSession"] = {}
# 空闲超时（秒）
_IDLE_TIMEOUT = 600
# 回收间隔（秒）
_REAPER_INTERVAL = 60
# 回收线程启动标记
_REAPER_STARTED = False
_REAPER_LOCK = threading.Lock()


class BrowserSession:
    """单个受控浏览器会话句柄。不进入 AgentState，由 SessionRegistry 管理生命周期。"""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._policy: TargetPolicy | None = None
        self._base_url = ""
        self._secrets: list[str] = []
        self._sensitive_locators: list[dict] = []
        self._last_active = time.time()
        self._closed = False
        self._step_count = 0
        self._step_budget = 20
        self._slot_acquired = False
        # Playwright Python 的 API 不是 thread-safe。FastAPI 可以把每个请求
        # 分派到不同 worker，因此整个浏览器生命周期由专属线程串行驱动。
        self._commands: Queue = Queue()
        self._owner: threading.Thread | None = None
        self._owner_id: int | None = None
        # 关闭与排队共用锁，避免请求排在关闭命令及哨兵之后而永久等待。
        self._lifecycle_lock = threading.Lock()

    @classmethod
    def open(cls, *, base_url, storage_state, headers, policy, target_page_path="", step_budget=20, timeout_ms=30000, initial_secrets=None):
        """创建并打开浏览器会话。storage_state 和 policy 已由调用方验证。"""
        session = cls()
        session._base_url = base_url.rstrip("/")
        session._policy = policy
        session._step_budget = step_budget
        session._secrets = list(initial_secrets or [])
        # 设置策略属性：认证头与 origin 在会话打开时固定
        policy.request_headers = headers or {}
        policy.header_origin = base_url
        policy.deadline = time.monotonic() + timeout_ms / 1000
        # 获取并发槽
        session._slot_acquired = _SLOTS.acquire(timeout=10)
        if not session._slot_acquired:
            raise conflict("浏览器会话资源已满，请稍后重试")
        session._owner = threading.Thread(
            target=session._command_loop,
            daemon=True,
            name=f"web-agent-browser-{id(session)}",
        )
        try:
            session._owner.start()
            session._call(
                session._open_browser,
                storage_state,
                timeout_ms,
                target_page_path,
            )
            return session
        except Exception:
            session.close()
            raise

    def _command_loop(self):
        """在创建 Playwright 的线程中顺序处理所有浏览器操作。"""
        self._owner_id = threading.get_ident()
        while True:
            command = self._commands.get()
            if command is None:
                return
            callback, args, completed, outcome = command
            try:
                outcome["result"] = callback(*args)
            except BaseException as exc:  # 把异常原样交还调用请求线程
                outcome["error"] = exc
            finally:
                completed.set()

    def _call(self, callback, *args):
        """同步调用 owner 线程上的函数；来自多个 API worker 的请求在队列中串行化。"""
        if threading.get_ident() == self._owner_id:
            return callback(*args)
        completed = threading.Event()
        outcome: dict = {}
        # 与 close 使用同一把锁，确保已接受的操作排在资源清理之前。
        with self._lifecycle_lock:
            if self._closed or self._owner is None or not self._owner.is_alive():
                raise RuntimeError("浏览器会话已关闭")
            self._commands.put((callback, args, completed, outcome))
        completed.wait()
        if "error" in outcome:
            raise outcome["error"]
        return outcome.get("result")

    def _open_browser(self, storage_state, timeout_ms, target_page_path):
        """初始化 Playwright；只会在该会话的 owner 线程执行。"""
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        args = ["--no-proxy-server", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
        if self._policy.resolver_rules:
            args.append("--host-resolver-rules=" + ", ".join(self._policy.resolver_rules))
        self._browser = self._playwright.chromium.launch(
            headless=True, timeout=min(30000, timeout_ms), args=args
        )
        self._context = self._browser.new_context(
            storage_state=storage_state or {"cookies": [], "origins": []},
            service_workers="block", accept_downloads=False,
        )
        self._context.route("**/*", self._policy.route)
        self._context.route_web_socket("**/*", lambda ws: ws.close())
        self._page = self._context.new_page()
        if target_page_path:
            target_url = self._policy.require(urljoin(self._base_url + "/", target_page_path))
            self._page.set_default_timeout(timeout_ms)
            self._page.set_default_navigation_timeout(timeout_ms)
            self._page.goto(target_url, wait_until="domcontentloaded")
        self._touch()

    def _touch(self):
        """更新最后活动时间。"""
        self._last_active = time.time()

    @property
    def idle_seconds(self):
        """距上次操作的时间（秒）。"""
        return time.time() - self._last_active

    @property
    def step_count(self):
        """已执行步骤数。"""
        return self._step_count

    @property
    def step_budget(self):
        """步骤预算。"""
        return self._step_budget

    @property
    def page_url(self):
        """当前页面 URL（清理后）。"""
        if self._closed:
            return ""
        try:
            return self._call(self._page_url)
        except Exception:
            return ""

    def _page_url(self):
        return _clean_url(self._page.url) if self._page else ""

    def observe(self, timeout_ms=5000):
        """观察当前页面，返回脱敏语义树与遮罩截图。"""
        return self._call(self._observe, timeout_ms)

    def _observe(self, timeout_ms):
        self._touch()
        if self._closed or self._page is None:
            return {"url": "", "title": "", "accessibility_tree": "error:SESSION_CLOSED", "screenshot_b64": ""}
        return observe_page(self._page, secrets=self._secrets, sensitive_locators=self._sensitive_locators, timeout_ms=timeout_ms)

    def execute_step(self, step_dict):
        """执行单步操作。不过 confirmed_digest 门禁，TargetPolicy 在会话打开时已生效。"""
        return self._call(self._execute_step, step_dict)

    def _execute_step(self, step_dict):
        self._touch()
        if self._closed or self._page is None:
            return {"status": "ERROR", "error_code": "SESSION_CLOSED", "error_message": "会话已关闭"}
        if self._step_count >= self._step_budget:
            return {"status": "ERROR", "error_code": "STEP_BUDGET_EXCEEDED", "error_message": "步骤预算已耗尽"}
        try:
            step = WebStep.model_validate(step_dict, context={"resolved": True})
            result = BrowserResult()
            timeout = step.timeout_ms or 30000
            deadline = time.monotonic() + timeout / 1000
            self._policy.deadline = deadline
            self._page.set_default_timeout(timeout)
            self._page.set_default_navigation_timeout(timeout)
            executor = PlaywrightExecutor()
            executor._step(self._page, step, self._base_url, self._policy, result, self._secrets, deadline)
            self._step_count += 1
            return {
                "status": result.status,
                "error_code": result.error_code,
                "error_message": result.error_message,
                "logs": scrub(result.logs, self._secrets),
                "assertions": scrub(result.assertions, self._secrets),
            }
        except AssertionError as exc:
            self._step_count += 1
            return {"status": "FAILED", "error_code": "WEB_ASSERTION_FAILED", "error_message": str(exc)}
        except Exception as exc:
            self._step_count += 1
            return {"status": "ERROR", "error_code": "WEB_STEP_FAILED", "error_message": f"操作失败（{type(exc).__name__}）"}

    def close(self):
        """关闭会话，释放浏览器资源与并发槽。"""
        completed = None
        outcome: dict = {}
        # 先拒绝新操作，再把清理命令排在此前已接收的操作之后。
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            if self._owner and self._owner.is_alive():
                completed = threading.Event()
                self._commands.put((self._close_browser, (), completed, outcome))
        try:
            if completed is not None:
                completed.wait()
                self._commands.put(None)
                if threading.current_thread() is not self._owner:
                    self._owner.join()
        finally:
            if self._slot_acquired:
                _SLOTS.release()
                self._slot_acquired = False

    def _close_browser(self):
        """释放 Playwright 资源；只在 owner 线程执行。"""
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass


class SessionRegistry:
    """进程级会话注册表，管理浏览器会话生命周期与空闲回收。"""

    def open_session(self, session_id, *, base_url, storage_state, headers, policy, target_page_path="", step_budget=20, initial_secrets=None):
        """打开新的浏览器会话，返回 BrowserSession 句柄。"""
        with _LOCK:
            existing = _SESSIONS.get(session_id)
            if existing and not existing._closed:
                return existing
        session = BrowserSession.open(
            base_url=base_url, storage_state=storage_state, headers=headers,
            policy=policy, target_page_path=target_page_path, step_budget=step_budget,
            initial_secrets=initial_secrets
        )
        with _LOCK:
            old = _SESSIONS.pop(session_id, None)
            if old:
                old.close()
            _SESSIONS[session_id] = session
        _ensure_reaper()
        return session

    def get_session(self, session_id):
        """获取现有会话，不存在或已关闭返回 None。"""
        with _LOCK:
            session = _SESSIONS.get(session_id)
            if session and not session._closed:
                return session
        return None

    def close_session(self, session_id):
        """关闭指定会话，释放资源。"""
        with _LOCK:
            session = _SESSIONS.pop(session_id, None)
        if session:
            session.close()
        return session is not None

    def close_all(self):
        """关闭所有会话（用于测试清理或应用关闭）。"""
        with _LOCK:
            sessions = list(_SESSIONS.values())
            _SESSIONS.clear()
        for s in sessions:
            s.close()


def _ensure_reaper():
    """确保回收线程已启动。"""
    global _REAPER_STARTED
    with _REAPER_LOCK:
        if _REAPER_STARTED:
            return
        _REAPER_STARTED = True
        threading.Thread(target=_reaper_loop, daemon=True, name="web-agent-session-reaper").start()


def _reaper_loop():
    """后台回收空闲会话，更新数据库状态。"""
    while True:
        time.sleep(_REAPER_INTERVAL)
        with _LOCK:
            to_close = [sid for sid, s in _SESSIONS.items() if s.idle_seconds > _IDLE_TIMEOUT]
        for sid in to_close:
            with _LOCK:
                session = _SESSIONS.pop(sid, None)
            if session:
                session.close()
            # 更新数据库状态
            try:
                from app.shared.database import SessionLocal
                from app.features.web_ui.models import WebAgentSession
                with SessionLocal() as db:
                    db.query(WebAgentSession).filter_by(id=sid, status="ACTIVE").update(
                        {"status": "CLOSED", "closed_at": datetime.now(timezone.utc).replace(tzinfo=None)},
                        synchronize_session=False
                    )
                    db.commit()
            except Exception:
                pass


# 模块级单例
registry = SessionRegistry()
