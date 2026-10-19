"""Chromium 声明式执行器：隔离 Browser/Context，固定步骤白名单，所有退出路径释放资源。

不接收脚本、不 eval、不连接用户浏览器。并发限额仅属于 Web 模块；敏感填入值不写日志，
截图遮罩全部输入和显式敏感元素，Trace 禁止 DOM/源码/网络正文，附件由调用方加密保存。
"""
from __future__ import annotations
import base64
import io
import json
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin
from app.features.agent.providers.sanitizer import sanitize_context
from app.features.business.executors.sensitive import is_sensitive_key
from app.features.test_management.executors.assertion_engine import evaluate_operator
from app.features.web_ui.schemas import WebStep

# 独立于 Security/ZAP 的资源池，进程内最多两个浏览器；每次执行仍创建全新进程和上下文。
_SLOTS = threading.BoundedSemaphore(2)


@dataclass
class BrowserResult:
    """纯内存结果，交给 TestCaseExecutor/BusinessExecutor 写入既有记录。"""
    status: str = "PASSED"
    logs: list = field(default_factory=list)
    assertions: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)
    outputs: dict = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


def locate(page, locator):
    """只分派到固定定位 API；strict 行为阻止多元素误点。"""
    strategy, value = locator["strategy"], locator["value"]
    if strategy == "TEST_ID":
        return page.get_by_test_id(value)
    if strategy == "ROLE":
        return page.get_by_role(value, name=locator.get("name"), exact=locator.get("exact", True))
    if strategy == "LABEL":
        return page.get_by_label(value, exact=locator.get("exact", True))
    if strategy == "TEXT":
        return page.get_by_text(value, exact=locator.get("exact", True))
    if strategy == "XPATH":
        return page.locator("xpath=" + value)
    if strategy == "CSS":
        return page.locator("css=" + value)
    raise ValueError("不支持的定位方式")


def scrub(value, secrets):
    """先按字段名脱敏，再替换执行时收集的具体输入值，阻止错误/Trace 泄露。"""
    if isinstance(value, dict):
        value = dict(value)
        # Playwright 把 HTTP 头表示为 name/value 数组，复用平台的敏感头名判定。
        if isinstance(value.get("name"), str) and is_sensitive_key(value["name"]) and "value" in value:
            value["value"] = "***"
        for key in ("headers", "cookies", "storageState"):
            if key in value:
                value[key] = "***"
        return {k: scrub(v, secrets) for k, v in sanitize_context(value).items()}
    if isinstance(value, list):
        return [scrub(v, secrets) for v in value]
    if isinstance(value, str):
        known = {str(s) for s in secrets if s}
        if value in known:
            return "***"
        for secret in sorted((s for s in known if len(s) >= 4), key=len, reverse=True):
            value = value.replace(secret, "***")
    return value


def safe_trace(path, secrets):
    """保留可供本地 Trace Viewer 读取的动作时序，移除网络文件、DOM、源码及密钥值。"""
    output = io.BytesIO()
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as dest:
        for name in source.namelist():
            if not name.endswith(".trace"):
                continue
            events = []
            for line in source.read(name).decode("utf-8").splitlines():
                event = json.loads(line)
                if event.get("type") in ("frame-snapshot", "screencast-frame", "resource-snapshot"):
                    continue
                # 脱敏后留动作定位与耗时；不保留请求头和页面正文。
                if event.get("method") in ("fill", "selectOption", "setInputFiles"):
                    event["params"] = {"value": "***"}
                events.append(json.dumps(scrub(event, secrets), ensure_ascii=False))
            dest.writestr(name, "\n".join(events))
    return output.getvalue()


class PlaywrightExecutor:
    """无共享浏览器的同步执行器；调用方已校验权限、步骤、凭据与变量。"""
    def execute(self, *, steps, base_url, policy, storage_state=None, headers=None,
                timeout_ms=30000, total_timeout_ms=120000, secrets=None):
        """运行结构化步骤；超时、断言失败、浏览器异常都返回结果且关闭上下文。"""
        result = BrowserResult()
        secrets = list(secrets or [])
        if not _SLOTS.acquire(timeout=1):
            result.status, result.error_code, result.error_message = "ERROR", "WEB_BUSY", "Web 浏览器资源已满，请稍后重试"
            return result
        browser = context = page = None
        deadline = time.monotonic() + total_timeout_ms / 1000
        policy.deadline = deadline
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as playwright, tempfile.TemporaryDirectory(prefix="web-ui-") as temp:
                try:
                    args = ["--no-proxy-server", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"]
                    if policy.resolver_rules:
                        args.append("--host-resolver-rules=" + ", ".join(policy.resolver_rules))
                    browser = playwright.chromium.launch(headless=True, timeout=min(30000, total_timeout_ms), args=args)
                    context = browser.new_context(
                        storage_state=storage_state or {"cookies": [], "origins": []},
                        service_workers="block", accept_downloads=False,
                    )
                    context.route("**/*", policy.route)
                    # 一期不开放长连接，避免 WebSocket 绕过 HTTP 目标检查。
                    context.route_web_socket("**/*", lambda ws: ws.close())
                    # 认证头只在环境 origin 注入，避免发给其他授权静态资源域。
                    policy.request_headers = headers or {}
                    policy.header_origin = base_url
                    context.tracing.start(screenshots=False, snapshots=False, sources=False)
                    page = context.new_page()
                    page.on("console", lambda msg: result.logs.append({"event": "console", "level": msg.type}) if len(result.logs) < 300 else None)
                    for index, raw in enumerate(steps):
                        step = WebStep.model_validate(raw, context={"resolved": True})
                        remaining = int((deadline - time.monotonic()) * 1000)
                        if remaining <= 0:
                            raise TimeoutError("Web 用例总时长超限")
                        page.set_default_timeout(min(step.timeout_ms or timeout_ms, remaining))
                        page.set_default_navigation_timeout(min(step.timeout_ms or timeout_ms, remaining))
                        began = time.monotonic()
                        entry = {"step": index + 1, "name": step.name, "operation": step.operation,
                                 "locator": step.locator.model_dump() if step.locator else None}
                        result.logs.append(entry)
                        try:
                            self._step(page, step, base_url, policy, result, secrets, min(deadline, began + (step.timeout_ms or timeout_ms) / 1000))
                            entry["status"] = "PASSED"
                        except Exception as exc:
                            # 不返回 Playwright 原始调用日志，它包含填入值、URL 查询参数等敏感数据。
                            entry["status"] = "FAILED" if isinstance(exc, AssertionError) else "ERROR"
                            result.status = entry["status"]
                            result.error_code = "WEB_ASSERTION_FAILED" if isinstance(exc, AssertionError) else ("WEB_TIMEOUT" if "Timeout" in type(exc).__name__ else "WEB_STEP_FAILED")
                            result.error_message = f"第 {index + 1} 步「{step.name}」{('断言失败' if isinstance(exc, AssertionError) else '操作失败')}（{type(exc).__name__}）"
                            break
                        finally:
                            entry["duration_ms"] = int((time.monotonic() - began) * 1000)
                    # 截图遮蔽全部输入；显式敏感的 Text/Label/CSS 元素同样遮蔽。
                    masks = [page.locator("input, textarea, iframe, [contenteditable=true], [data-sensitive]")]
                    masks += [locate(page, s["locator"]) for s in steps if s.get("sensitive") and s.get("locator")]
                    masks += [page.get_by_text(str(secret), exact=False) for secret in secrets if len(str(secret)) >= 3]
                    try:
                        image = page.screenshot(mask=masks, timeout=3000, full_page=False)
                        result.artifacts.append(("FAILURE_SCREENSHOT" if result.status != "PASSED" else "SCREENSHOT", image))
                    except Exception:
                        result.logs.append({"event": "截图未采集", "status": "ERROR"})
                finally:
                    if context:
                        try:
                            trace_path = str(Path(temp) / "trace.zip")
                            context.tracing.stop(path=trace_path)
                            result.artifacts.append(("TRACE", safe_trace(trace_path, secrets)))
                        except Exception:
                            result.logs.append({"event": "Trace 未采集", "status": "ERROR"})
                        finally:
                            try:
                                context.close()
                            finally:
                                if browser:
                                    browser.close()
                    elif browser:
                        browser.close()
        except Exception as exc:
            result.status, result.error_code = "ERROR", "WEB_BROWSER_ERROR"
            result.error_message = f"浏览器执行失败（{type(exc).__name__}），请检查 Chromium 安装和授权目标"
        finally:
            _SLOTS.release()
        result.logs = scrub(result.logs, secrets)
        result.assertions = scrub(result.assertions, secrets)
        # outputs 仅用于本次业务流内存变量；落库时由适配器脱敏。
        return result

    def _step(self, page, step, base_url, policy, result, secrets, deadline):
        """将单步分派到固定 Playwright API，ASSERT 复用平台 Assertion Engine 比较。"""
        locator = locate(page, step.locator.model_dump()) if step.locator else None
        if step.operation == "NAVIGATE":
            page.goto(policy.require(urljoin(base_url.rstrip("/") + "/", step.value)), wait_until="domcontentloaded")
        elif step.operation == "CLICK":
            locator.click()
        elif step.operation == "FILL":
            secrets.append(step.value)
            locator.fill(step.value)
        elif step.operation == "SELECT":
            secrets.append(step.value)
            locator.select_option(value=step.value)
        elif step.operation == "UPLOAD":
            locator.set_input_files({"name": step.upload.name, "mimeType": step.upload.mime_type,
                                     "buffer": base64.b64decode(step.upload.content_base64)})
        elif step.operation == "WAIT":
            locator.wait_for(state=step.wait_state)
        elif step.operation == "ASSERT":
            actual, passed = None, False
            expected = step.expected if step.expected is not None else "True"
            while time.monotonic() < deadline:
                if step.assertion == "URL":
                    actual = page.url
                elif step.assertion == "TITLE":
                    actual = page.title()
                elif step.assertion == "VISIBLE":
                    actual = locator.is_visible()
                elif step.assertion == "COUNT":
                    actual = locator.count()
                elif step.assertion == "VALUE":
                    actual = locator.input_value()
                else:
                    actual = locator.inner_text()
                expected = step.expected if step.expected is not None else "True"
                passed = evaluate_operator(actual, expected, step.operator)
                if passed:
                    break
                # 断言支持短暂的页面异步刷新，但不突破步骤与用例总时限。
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining > 0:
                    page.wait_for_timeout(min(100, remaining))
            result.assertions.append({"id": len(result.assertions) + 1, "assertion_type": "WEB_" + step.assertion,
                                      "operator": step.operator, "passed": passed, "actual": str(actual),
                                      "expected": expected, "required": True, "message": "页面断言通过" if passed else "页面断言失败"})
            if not passed:
                raise AssertionError("页面断言失败")
            if step.output_variable:
                result.outputs[step.output_variable] = actual
