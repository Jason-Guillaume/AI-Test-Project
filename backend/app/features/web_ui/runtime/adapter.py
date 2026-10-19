"""Web 运行适配器：复用测试数据解析、RuntimeContext、断言与执行结果，不提交事务。"""
from __future__ import annotations
import base64
import json
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4
from app.features.agent.providers.sanitizer import sanitize_context
from app.features.web_ui.models import WebAuthProfile, WebArtifact, WebCase
from app.features.web_ui.runtime.playwright_executor import PlaywrightExecutor, scrub
from app.features.web_ui.runtime.policy import TargetPolicy
from app.features.web_ui.services.web_ui_service import case_digest, expand_steps, json_dump, load_steps
from app.features.test_data.runtime.variable_resolver import ResolveScope, resolve_template
from app.features.test_management.models.test_case import TestCase
from app.shared.crypto import decrypt_secret, encrypt_secret
from app.shared.errors import AppError, bad_request, conflict, not_found


def validate_storage_state(state, policy, environment):
    """校验 Cookie/LocalStorage 的域、字段及大小，拒绝项目外会话和可执行配置。"""
    if not isinstance(state, dict) or set(state) - {"cookies", "origins"}:
        raise bad_request("storage_state 只允许 cookies 和 origins")
    if len(json_dump(state)) > 200000:
        raise bad_request("登录态不能超过 200KB")
    state = json.loads(json_dump(state))
    cookies, origins = state.get("cookies", []), state.get("origins", [])
    if not isinstance(cookies, list) or not isinstance(origins, list) or len(cookies) > 100 or len(origins) > 20:
        raise bad_request("登录态结构或数量非法")
    for cookie in cookies:
        if not isinstance(cookie, dict) or set(cookie) - {"name", "value", "url", "domain", "path", "expires", "httpOnly", "secure", "sameSite"}:
            raise bad_request("Cookie 字段非法")
        if not isinstance(cookie.get("name"), str) or not isinstance(cookie.get("value"), str):
            raise bad_request("Cookie 必须有 name 和 value")
        if cookie.get("url"):
            policy.require(cookie["url"])
            parsed = urlsplit(cookie.pop("url"))
            cookie["domain"] = parsed.hostname
            cookie["path"] = "/"
            cookie.setdefault("secure", parsed.scheme == "https")
        else:
            domain = cookie.get("domain", "").lstrip(".").lower()
            if not any(host == domain for _, host, _ in policy.targets):
                raise bad_request("Cookie 域不属于项目授权目标")
            if not isinstance(cookie.get("path"), str):
                raise bad_request("Cookie 必须指定 path")
        cookie.setdefault("expires", -1)
        cookie.setdefault("httpOnly", False)
        cookie.setdefault("secure", False)
        cookie.setdefault("sameSite", "Lax")
        if not isinstance(cookie["expires"], (int, float)) or cookie["sameSite"] not in ("Strict", "Lax", "None"):
            raise bad_request("Cookie 到期时间或 sameSite 非法")
        if not all(isinstance(cookie[k], bool) for k in ("httpOnly", "secure")):
            raise bad_request("Cookie secure/httpOnly 必须是布尔值")
    for origin in origins:
        if not isinstance(origin, dict) or set(origin) - {"origin", "localStorage"}:
            raise bad_request("Origin 字段非法")
        policy.require(origin.get("origin", ""))
        parsed = urlsplit(origin["origin"])
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise bad_request("Origin 必须是协议、主机和端口")
        origin["origin"] = f"{parsed.scheme}://{parsed.netloc}"
        storage = origin.get("localStorage", [])
        if not isinstance(storage, list) or len(storage) > 100:
            raise bad_request("Local Storage 格式非法")
        if any(not isinstance(x, dict) or set(x) != {"name", "value"} or not all(isinstance(v, str) for v in x.values()) for x in storage):
            raise bad_request("Local Storage 仅允许字符串 name/value")
    return {"cookies": cookies, "origins": origins}


def _all_strings(value):
    """收集凭据与运行时数据中的值，用于自由文本和动作 Trace 的精确脱敏。"""
    if isinstance(value, dict):
        return [s for v in value.values() for s in _all_strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _all_strings(v)]
    return [value] if isinstance(value, str) and value else []


def run_web_case(db, case, *, environment, actor, fixture_outputs=None, variables=None,
                 extra_headers=None, case_execution_id=None):
    """校验确认指纹后调用 Playwright；返回既有 CaseExecutionResult，保持原签名契约。"""
    from app.features.test_management.executors.test_case_executor import CaseExecutionResult, _load_assertions, _load_data_values
    from app.features.test_management.executors.assertion_engine import required_all_passed, run_assertions
    from app.features.business.executors.api_executor import ApiRequestExecutor
    config = db.get(WebCase, case.id)
    if config is None or case.target_type != "WEB" or not case.enabled:
        raise not_found("Web 用例不存在或已停用")
    steps = load_steps(db, case.id)
    if not config.confirmed_digest or config.confirmed_digest != case_digest(db, case, config, steps):
        raise AppError("Web 用例或依赖已变更，必须人工确认当前版本后执行", status_code=409, code="WEB_REVIEW_REQUIRED")
    policy = TargetPolicy(db, case.project_id)
    base_url = (environment.base_url or "").rstrip("/") + (environment.gateway_prefix or "")
    policy.require(base_url)
    state, auth_values, secret_values = {"cookies": [], "origins": []}, {}, []
    if config.auth_profile_id:
        profile = db.get(WebAuthProfile, config.auth_profile_id)
        if profile is None or profile.project_id != case.project_id or profile.environment_id != environment.id:
            raise bad_request("认证配置与项目或执行环境不匹配")
        if profile.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise bad_request("登录态已过期，请重新登录并导入")
        raw = decrypt_secret(profile.secret_encrypted)
        if not raw:
            raise bad_request("认证密文无法解密，请重新配置")
        auth = json.loads(raw)
        state = validate_storage_state(auth.get("storage_state") or {}, policy, environment)
        auth_values = {"auth_username": auth.get("username") or "", "auth_password": auth.get("password") or "", "auth_jwt": auth.get("jwt") or ""}
        secret_values += _all_strings(auth)
        if auth.get("jwt"):
            parsed = urlsplit(base_url)
            origin_url = f"{parsed.scheme}://{parsed.netloc}"
            origin = next((x for x in state["origins"] if x["origin"].rstrip("/") == origin_url), None)
            if origin is None:
                origin = {"origin": origin_url, "localStorage": []}
                state["origins"].append(origin)
            key = auth.get("jwt_storage_key") or "access_token"
            origin["localStorage"] = [s for s in origin["localStorage"] if s["name"] != key] + [{"name": key, "value": auth["jwt"]}]
    data, _ = _load_data_values(db, case.id, environment, fixture_outputs or {})
    data.update(auth_values)
    runtime = dict(variables or {})
    runtime.update(fixture_outputs or {})
    scope = ResolveScope(variables=runtime, data_values=data, environment=environment)
    resolved = []
    for step in expand_steps(db, case.project_id, steps):
        # 只解析数据字段；不能用变量注入操作名称、定位策略或脚本。
        for key in ("value", "expected"):
            if step.get(key) is not None:
                step[key] = str(resolve_template(step[key], scope, required=True))
        resolved.append(step)
    headers = ApiRequestExecutor.get_environment_headers(environment)
    headers.update(extra_headers or {})
    secret_values += _all_strings(data) + _all_strings(runtime) + _all_strings(headers)
    secret_values += [s.get("value") for s in resolved if s["operation"] in ("FILL", "SELECT") and s.get("value")]
    started = time.monotonic()
    result = PlaywrightExecutor().execute(steps=resolved, base_url=base_url, policy=policy,
        storage_state=state, headers=headers, timeout_ms=config.timeout_ms,
        total_timeout_ms=config.total_timeout_ms, secrets=secret_values)
    artifacts = []
    for kind, content in result.artifacts:
        if len(content) > 10000000:
            result.logs.append({"event": "附件超过 10MB，未保存", "kind": kind})
            continue
        artifact_id = str(uuid4())
        db.add(WebArtifact(id=artifact_id, project_id=case.project_id, test_case_id=case.id,
            case_execution_id=case_execution_id, kind=kind,
            content_encrypted=encrypt_secret(base64.b64encode(content).decode())))
        artifacts.append({"id": artifact_id, "kind": kind, "url": f"/api/v1/web-artifacts/{artifact_id}"})
    generic_assertions = run_assertions(_load_assertions(db, case.id), {
        "status_code": 200 if result.status == "PASSED" else 500, "headers": {},
        "body": result.outputs, "raw_body": json_dump(result.outputs),
        "response_time_ms": int((time.monotonic() - started) * 1000)})
    assertions = result.assertions + scrub(generic_assertions, secret_values)
    status = result.status
    if status == "PASSED" and not required_all_passed(assertions):
        status, result.error_code, result.error_message = "FAILED", "ASSERTION_FAILED", "页面结果断言失败"
    execution_result = CaseExecutionResult(status=status, executor_type="WEB", request_snapshot={"step_count": len(steps)},
        response_snapshot={"web": {"steps": result.logs, "artifacts": artifacts, "outputs": scrub(result.outputs, secret_values)}},
        assertion_results=assertions, context_json={"web": {"outputs": scrub(result.outputs, secret_values)}},
        duration_ms=int((time.monotonic() - started) * 1000), error_code=result.error_code, error_message=result.error_message)
    # 明文输出只在本轮内存中传给业务动作，持久化字段始终使用脱敏版本。
    execution_result.web_outputs = result.outputs
    execution_result.web_secrets = secret_values
    return execution_result


def run_web_binding(db, binding, *, environment, ctx, project_id, extra_headers=None):
    """业务动作的 WEB 通道，返回现有 ActionRunResult；变量通过既有 ExecutionContext 传递。"""
    from app.features.business.executors.business_flow_executor import ActionRunResult
    case_id = (binding.config_json or {}).get("web_case_id")
    case = db.get(TestCase, case_id) if type(case_id) is int else None
    if case is None or case.project_id != project_id:
        return ActionRunResult(error_code="WEB_CASE_NOT_FOUND", error_message="绑定的 Web 用例不存在或不属于本项目")
    # 业务流入口已完成权限校验；浏览器适配器仍复核确认、环境、目标与凭据。
    result = run_web_case(db, case, environment=environment, actor=None, variables=ctx.variables,
                          extra_headers=extra_headers or ctx.get("__web_headers"))
    outputs = getattr(result, "web_outputs", {})
    for key, value in outputs.items():
        ctx.set(key, value)
    ctx.set("__web_sensitive_values", list(set(ctx.get("__web_sensitive_values", []) + getattr(result, "web_secrets", []))))
    return ActionRunResult(status="SUCCESS" if result.status == "PASSED" else "FAILED", binding_id=binding.id,
        error_code=result.error_code, error_message=result.error_message, duration_ms=result.duration_ms,
        outputs=outputs, output_context=scrub(outputs, getattr(result, "web_secrets", [])), request_snapshot=result.request_snapshot,
        response_snapshot=result.response_snapshot)
