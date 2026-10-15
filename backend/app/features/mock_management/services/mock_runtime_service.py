"""Mock Runtime Service：执行作用域激活 + 请求匹配流程（§十七 / §二十三-§二十七）。

职责：
- activate_context / deactivate_context：CaseExecution 创建 MockContext，承载 scenario_overrides，
  支持并发隔离（§二十四：绝不改全局默认场景，只在本 Context 内覆盖）。
- handle_request：Mock Runtime 的核心流程——解析 Service / 鉴权 / 匹配 Endpoint /
  选 Scenario（Context Override > Explicit Matcher > Default Scenario，§二十五）/
  构造 Response / 记录 MockExecution。
- expire_stale_contexts：把超过 expires_at 的 ACTIVE Context 标记 EXPIRED（§二十六）。

匹配优先级与排序（§九 / §二十五）：
    1. Context Override（X-Mock-Context 命中且覆盖该 Endpoint）→ 直接用该 Scenario（须启用）
    2. 启用 Scenario 按 priority DESC, id ASC 评估 Matcher，首个全通过者选中
    3. 未匹配 → 该 Endpoint 的 is_default Scenario（须启用）
    4. 都没有 → MOCK_SCENARIO_NOT_MATCHED（404）

并发安全：Context 是行级隔离的，不同 Case 的 override 互不可见；不写 Service / Scenario
的全局状态。延迟 / 超时由路由层 async sleep（本服务只返回 delay_ms）。
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.features.business.executors.sensitive import mask_body, mask_headers
from app.features.mock_management.matchers import RequestSnapshot, evaluate_matchers, match_path
from app.features.mock_management.models import (
    MockContext,
    MockEndpoint,
    MockExecution,
    MockMatcher,
    MockScenario,
    MockService,
)
from app.features.mock_management.runtime.response_builder import build_response
from app.features.mock_management.services.token_service import verify_token
from app.features.test_data.runtime.variable_resolver import RequestContext
from app.shared.errors import (
    CODE_MOCK_CONTEXT_EXPIRED,
    CODE_MOCK_CONTEXT_NOT_FOUND,
    CODE_MOCK_RUNTIME_DISABLED,
    CODE_MOCK_RUNTIME_UNAUTHORIZED,
    CODE_MOCK_SCENARIO_DISABLED,
    CODE_MOCK_SCENARIO_NOT_FOUND,
    CODE_MOCK_SCENARIO_NOT_MATCHED,
    CODE_MOCK_SERVICE_NOT_FOUND,
    AppError,
)

# 默认 Context TTL（§二十六）。
DEFAULT_CONTEXT_TTL_MINUTES = 30

# X-Mock-Token / X-Mock-Context 头名（大小写不敏感读取）。
MOCK_TOKEN_HEADER = "X-Mock-Token"
MOCK_CONTEXT_HEADER = "X-Mock-Context"


@dataclass
class RuntimeResponse:
    """Runtime 一次请求的处理结果（路由层据此构造 HTTP 响应并应用延迟）。"""

    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    body: Any = None
    matched: bool = False
    scenario_id: int | None = None
    delay_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    # 命中的实体 ID，供记录 MockExecution。
    project_id: int | None = None
    service_id: int | None = None
    endpoint_id: int | None = None
    context_id: str | None = None
    test_run_id: int | None = None
    case_execution_id: int | None = None


class MockRuntimeService:
    """Mock Runtime 服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 执行作用域

    def activate_context(
        self,
        db: Session,
        *,
        project_id: int,
        test_run_id: int | None,
        case_execution_id: int | None,
        overrides: dict[int, int],
        ttl_minutes: int = DEFAULT_CONTEXT_TTL_MINUTES,
    ) -> MockContext:
        """为一次 CaseExecution 创建 MockContext（§二十三 / §二十四）。

        Args:
            overrides: {endpoint_id: scenario_id}，本 Case 期间的场景覆盖。
            ttl_minutes: 过期时间，默认 30 分钟（§二十六）。
        """
        # 校验覆盖指向的 Scenario 存在、启用、归属正确（不存在 → MOCK_SCENARIO_NOT_FOUND）。
        validated: dict[int, int] = {}
        for endpoint_id, scenario_id in (overrides or {}).items():
            scenario = db.get(MockScenario, scenario_id)
            if scenario is None or scenario.project_id != project_id:
                raise AppError(
                    f"Mock 场景不存在：{scenario_id}", status_code=404,
                    code=CODE_MOCK_SCENARIO_NOT_FOUND,
                )
            if scenario.mock_endpoint_id != endpoint_id:
                raise AppError(
                    f"Mock 场景 {scenario_id} 不属于接口 {endpoint_id}", status_code=400,
                    code=CODE_MOCK_SCENARIO_NOT_FOUND,
                )
            if not scenario.enabled:
                raise AppError(
                    f"Mock 场景 {scenario.scenario_key} 已停用", status_code=400,
                    code=CODE_MOCK_SCENARIO_DISABLED,
                )
            validated[endpoint_id] = scenario_id

        context = MockContext(
            context_id=uuid.uuid4().hex,
            project_id=project_id,
            test_run_id=test_run_id,
            case_execution_id=case_execution_id,
            scenario_overrides=validated or None,
            status="ACTIVE",
            # 与全库约定一致用 naive 本地时间；DB 列为 timestamp（无时区），
            # 跨会话读回也是 naive，与 datetime.now() 比较不会触发 naive vs aware TypeError。
            expires_at=datetime.now() + timedelta(minutes=max(1, ttl_minutes)),
        )
        db.add(context)
        db.flush()
        return context

    def deactivate_context(self, db: Session, context_id: str) -> None:
        """关闭 MockContext（§二十七：finally 必须关闭）。幂等。"""
        ctx = self._get_context(db, context_id)
        if ctx is None:
            return
        if ctx.status == "ACTIVE":
            ctx.status = "CLOSED"
            ctx.closed_at = datetime.now()
            db.flush()

    def expire_stale_contexts(self, db: Session) -> int:
        """把超过 expires_at 的 ACTIVE Context 标记 EXPIRED（§二十六）。返回过期数量。"""
        now = datetime.now()
        rows = (
            db.query(MockContext)
            .filter(MockContext.status == "ACTIVE", MockContext.expires_at < now)
            .all()
        )
        for ctx in rows:
            ctx.status = "EXPIRED"
        if rows:
            db.flush()
        return len(rows)

    def _get_context(self, db: Session, context_id: str) -> MockContext | None:
        if not context_id:
            return None
        return (
            db.query(MockContext)
            .filter(MockContext.context_id == context_id)
            .first()
        )

    # ---------------------------------------------------------------- 请求处理

    def handle_request(
        self,
        db: Session,
        *,
        project_id: int,
        service_key: str,
        method: str,
        path: str,
        query: dict[str, Any],
        headers: dict[str, str],
        body: Any,
        request_id: str,
        started_perf: float,
    ) -> RuntimeResponse:
        """Mock Runtime 核心流程（§十七）。不 sleep，延迟由路由层应用。"""
        # 顺手清理过期 Context（惰性回收，避免长期污染）。
        self.expire_stale_contexts(db)

        service = self._load_service(db, project_id, service_key)
        if service is None:
            return self._fail(
                db, "Mock 服务不存在", CODE_MOCK_SERVICE_NOT_FOUND, 404,
                request_id=request_id, method=method, path=path, started_perf=started_perf,
                project_id=project_id, query=query, headers=headers, body=body, ctx=None,
            )
        if not service.enabled:
            return self._fail(
                db, "Mock 服务已停用", CODE_MOCK_RUNTIME_DISABLED, 503,
                request_id=request_id, method=method, path=path, started_perf=started_perf,
                project_id=project_id, query=query, headers=headers, body=body, ctx=None,
                service_id=service.id,
            )

        # 鉴权（§十五）：public_runtime 放行，否则校验 X-Mock-Token。
        auth_ok = service.public_runtime or verify_token(
            _header_lookup(headers, MOCK_TOKEN_HEADER), service.runtime_token_hash
        )
        if not auth_ok:
            return self._fail(
                db, "Mock Runtime 未授权", CODE_MOCK_RUNTIME_UNAUTHORIZED, 401,
                request_id=request_id, method=method, path=path, started_perf=started_perf,
                project_id=project_id, query=query, headers=headers, body=body, ctx=None,
                service_id=service.id,
            )

        # 解析 X-Mock-Context（§二十四 / §二十五）。
        ctx = self._resolve_context(db, _header_lookup(headers, MOCK_CONTEXT_HEADER))

        # 匹配 Endpoint（method + path）。
        endpoint, path_params = self._match_endpoint(db, service.id, method, path)
        if endpoint is None:
            return self._record_and_fail(
                db, project_id, service.id, None, None, ctx,
                "无 Mock 接口匹配", CODE_MOCK_SCENARIO_NOT_MATCHED, 404,
                request_id=request_id, method=method, path=path, query=query,
                headers=headers, body=body, started_perf=started_perf,
            )

        # 选 Scenario：Context Override > Explicit Matcher > Default。
        match_snapshot = RequestSnapshot(
            method=method, path=path, path_params=path_params,
            query=query, headers=headers, body=body,
        )
        scenario, matched_by = self._select_scenario(db, endpoint.id, ctx, match_snapshot)
        if scenario is None:
            return self._record_and_fail(
                db, project_id, service.id, endpoint.id, None, ctx,
                "无 Mock 场景匹配", CODE_MOCK_SCENARIO_NOT_MATCHED, 404,
                request_id=request_id, method=method, path=path, query=query,
                headers=headers, body=body, started_perf=started_perf,
            )

        # 构造响应（resolve_template 解析 ${request.*} / ${runtime.*}）。
        request_context = RequestContext(
            path_params=path_params, query=query,
            headers={k: v for k, v in headers.items() if k.lower() not in (MOCK_TOKEN_HEADER.lower(),)},
            body=body,
        )
        built = build_response(
            scenario, request=request_context, request_id=request_id,
            timestamp=int(datetime.now().timestamp()),
        )

        # 记录 MockExecution（敏感脱敏，§五十）。
        duration_ms = int((time.perf_counter() - started_perf) * 1000) + built.delay_ms
        self._record_execution(
            db, project_id=project_id, service_id=service.id, endpoint_id=endpoint.id,
            scenario_id=scenario.id, ctx=ctx, request_id=request_id, method=method, path=path,
            query=query, headers=headers, body=body,
            response_status=built.status_code, response_headers=built.headers,
            response_body=built.body, matched=True, duration_ms=duration_ms,
        )

        return RuntimeResponse(
            status_code=built.status_code, headers=built.headers, body=built.body,
            matched=True, scenario_id=scenario.id, delay_ms=built.delay_ms,
            service_id=service.id, endpoint_id=endpoint.id,
            context_id=ctx.context_id if ctx else None,
            test_run_id=ctx.test_run_id if ctx else None,
            case_execution_id=ctx.case_execution_id if ctx else None,
        )

    # ---------------------------------------------------------------- 内部：加载 / 匹配

    def _load_service(self, db: Session, project_id: int, service_key: str) -> MockService | None:
        return (
            db.query(MockService)
            .filter(
                MockService.project_id == project_id,
                MockService.service_key == service_key,
            )
            .first()
        )

    def _resolve_context(self, db: Session, context_id: str) -> MockContext | None:
        """读取 X-Mock-Context 对应的 Context；过期或已关闭按 None 处理（§二十六）。"""
        ctx = self._get_context(db, context_id)
        if ctx is None:
            return None
        if ctx.status != "ACTIVE":
            return None
        if ctx.expires_at < datetime.now():
            if ctx.status == "ACTIVE":
                ctx.status = "EXPIRED"
                db.flush()
            return None
        return ctx

    def _match_endpoint(
        self, db: Session, service_id: int, method: str, path: str,
    ) -> tuple[MockEndpoint | None, dict[str, str]]:
        """按 method + path 模式匹配 Endpoint（§十）。返回 (Endpoint, path_params)。"""
        endpoints = (
            db.query(MockEndpoint)
            .filter(MockEndpoint.mock_service_id == service_id, MockEndpoint.enabled.is_(True))
            .all()
        )
        upper_method = (method or "").upper()
        # 优先精确 method 匹配；找不到时回退通配（method 模式存 '*' 视为任意）。
        candidates = [e for e in endpoints if (e.method or "").upper() == upper_method]
        if not candidates:
            candidates = [e for e in endpoints if (e.method or "").upper() in ("*", "ANY")]
        for endpoint in candidates:
            ok, params = match_path(endpoint.path, path)
            if ok:
                return endpoint, params
        return None, {}

    def _select_scenario(
        self, db: Session, endpoint_id: int, ctx: MockContext | None,
        snapshot: RequestSnapshot,
    ) -> tuple[MockScenario | None, str]:
        """选 Scenario：Context Override > Explicit Matcher > Default（§二十五）。"""
        # 1. Context Override：本 Context 显式覆盖该 Endpoint 的 Scenario。
        if ctx is not None and isinstance(ctx.scenario_overrides, dict):
            overrides = ctx.scenario_overrides
            override_id = overrides.get(str(endpoint_id)) or overrides.get(endpoint_id)
            if override_id:
                scenario = db.get(MockScenario, int(override_id))
                if scenario is not None and scenario.enabled:
                    return scenario, "context_override"

        # 2. 加载启用 Scenario（priority DESC, id ASC）+ 各自 Matcher。
        scenarios = (
            db.query(MockScenario)
            .filter(MockScenario.mock_endpoint_id == endpoint_id, MockScenario.enabled.is_(True))
            .order_by(MockScenario.priority.desc(), MockScenario.id.asc())
            .all()
        )
        if not scenarios:
            return None, "none"

        scenario_ids = [s.id for s in scenarios]
        matchers_by_scenario: dict[int, list[MockMatcher]] = {}
        if scenario_ids:
            rows = (
                db.query(MockMatcher)
                .filter(MockMatcher.scenario_id.in_(scenario_ids), MockMatcher.enabled.is_(True))
                .order_by(MockMatcher.priority.asc(), MockMatcher.id.asc())
                .all()
            )
            for m in rows:
                matchers_by_scenario.setdefault(m.scenario_id, []).append(m)

        # 3. 逐 Scenario 评估 Matcher，首个全通过者选中（无规则者直接命中）。
        for scenario in scenarios:
            matchers = matchers_by_scenario.get(scenario.id, [])
            if not matchers:
                return scenario, "no_matcher"
            if evaluate_matchers(snapshot, matchers):
                return scenario, "matcher"

        # 4. 兜底：is_default Scenario（须启用，已在 scenarios 内）。
        for scenario in scenarios:
            if scenario.is_default:
                return scenario, "default"
        return None, "none"

    # ---------------------------------------------------------------- 记录

    def _record_execution(
        self, db: Session, *, project_id: int, service_id: int | None, endpoint_id: int | None,
        scenario_id: int | None, ctx: MockContext | None, request_id: str, method: str, path: str,
        query: dict[str, Any], headers: dict[str, str], body: Any,
        response_status: int | None, response_headers: dict[str, str], response_body: Any,
        matched: bool, duration_ms: int,
    ) -> None:
        """记录 MockExecution（快照经 SensitiveDataMasker 脱敏，§十八 / §五十）。"""
        masked_query = {
            k: ("******" if _is_sensitive(k) else v) for k, v in (query or {}).items()
        }
        execution = MockExecution(
            project_id=project_id,
            mock_service_id=service_id,
            mock_endpoint_id=endpoint_id,
            mock_scenario_id=scenario_id,
            request_id=request_id,
            method=(method or "").upper(),
            path=path,
            query_snapshot=masked_query or None,
            header_snapshot=mask_headers(headers) or None,
            body_snapshot=mask_body(body) if body is not None else None,
            response_status=response_status,
            response_header_snapshot=mask_headers(response_headers) or None,
            response_body_snapshot=mask_body(response_body) if response_body is not None else None,
            matched=matched,
            duration_ms=duration_ms,
            test_run_id=ctx.test_run_id if ctx else None,
            case_execution_id=ctx.case_execution_id if ctx else None,
            mock_context_id=ctx.context_id if ctx else None,
        )
        db.add(execution)
        db.flush()

    def _record_and_fail(
        self, db: Session, project_id: int, service_id: int | None, endpoint_id: int | None,
        scenario_id: int | None, ctx: MockContext | None, message: str, code: str, status: int, *,
        request_id: str, method: str, path: str, query: dict[str, Any],
        headers: dict[str, str], body: Any, started_perf: float,
    ) -> RuntimeResponse:
        """记录一次失败调用并返回失败 RuntimeResponse（仍脱敏）。"""
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        self._record_execution(
            db, project_id=project_id, service_id=service_id, endpoint_id=endpoint_id,
            scenario_id=scenario_id, ctx=ctx, request_id=request_id, method=method, path=path,
            query=query, headers=headers, body=body,
            response_status=status, response_headers={}, response_body=None,
            matched=False, duration_ms=duration_ms,
        )
        return RuntimeResponse(
            status_code=status, headers={}, body=_error_body(code, message),
            matched=False, error_code=code, error_message=message,
            service_id=service_id, endpoint_id=endpoint_id,
            context_id=ctx.context_id if ctx else None,
            test_run_id=ctx.test_run_id if ctx else None,
            case_execution_id=ctx.case_execution_id if ctx else None,
        )

    def _fail(
        self, db: Session, message: str, code: str, status: int, *,
        request_id: str, method: str, path: str, started_perf: float,
        project_id: int, query: dict[str, Any], headers: dict[str, str], body: Any,
        ctx: MockContext | None, service_id: int | None = None,
    ) -> RuntimeResponse:
        """未到匹配阶段的失败（Service 不存在 / 停用 / 未授权）。

        §十八 要求所有调用都落一条 MockExecution：project_id 来自 URL 参数（合法），
        service_id 已知则带上。ctx 此时尚未解析（None），故 context/run/case 均为空。
        """
        duration_ms = int((time.perf_counter() - started_perf) * 1000)
        self._record_execution(
            db, project_id=project_id, service_id=service_id, endpoint_id=None,
            scenario_id=None, ctx=ctx, request_id=request_id, method=method, path=path,
            query=query, headers=headers, body=body,
            response_status=status, response_headers={}, response_body=None,
            matched=False, duration_ms=duration_ms,
        )
        return RuntimeResponse(
            status_code=status, headers={}, body=_error_body(code, message),
            matched=False, error_code=code, error_message=message,
            service_id=service_id, project_id=project_id,
        )


def _header_lookup(headers: dict[str, str], name: str) -> str:
    """大小写不敏感取请求头值。"""
    target = name.lower()
    for key, value in headers.items():
        if key.lower() == target:
            return str(value)
    return ""


def _is_sensitive(key: str) -> bool:
    """复用 SensitiveDataMasker 的敏感键判定（避免 query 参数泄密）。"""
    from app.features.business.executors.sensitive import is_sensitive_key

    return is_sensitive_key(key)


def _error_body(code: str, message: str) -> dict[str, str]:
    """Mock Runtime 的错误信封（§九：MOCK_SCENARIO_NOT_MATCHED 等）。"""
    return {"code": code, "message": message}


__all__ = [
    "DEFAULT_CONTEXT_TTL_MINUTES",
    "MOCK_CONTEXT_HEADER",
    "MOCK_TOKEN_HEADER",
    "RuntimeResponse",
    "MockRuntimeService",
]
