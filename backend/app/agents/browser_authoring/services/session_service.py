"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy.orm import Session

from app.features.web_testing.models import WebAuthProfile
from app.agents.models.browser_authoring import WebAgentSession, WebAgentStep
from app.features.web_testing.schemas import SessionStartInput
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.core.security.crypto import encrypt_secret, decrypt_secret
from app.core.http.errors import bad_request, conflict, not_found
from app.features.web_testing.services.access_service import get_row
from app.features.web_testing.services.response_mapper import json_dump
from app.features.web_testing.services.response_mapper import list_result


class TaskBindingValidator(Protocol):
    """由编排层注入的任务浏览器会话绑定校验。"""

    def __call__(
        self,
        db: Session,
        *,
        project_id: int,
        environment_id: int,
        task_run_id: int,
        task_agent_instance_id: int,
    ) -> None: ...


def session_response(row):
    """返回当前进程可用状态；丢失句柄后不声称浏览器仍然运行。"""
    from app.execution.browser.session_manager import registry
    from sqlalchemy.orm import object_session
    browser = registry.get_session(row.id)
    session = object_session(row)
    recorded_count = session.query(WebAgentStep).filter_by(session_id=row.id).count() if session else 0
    disconnected = row.status == "ACTIVE" and browser is None
    return {"id": row.id, "project_id": row.project_id, "environment_id": row.environment_id,
            "auth_profile_id": row.auth_profile_id, "base_url": row.base_url,
            "target_page_path": row.target_page_path, "status": "FAILED" if disconnected else row.status,
            "status_reason": "浏览器句柄不可用，请重新启动会话" if disconnected else None,
            "step_budget": row.step_budget, "step_count": browser.step_count if browser else recorded_count,
            "created_at": row.created_at}


def get_session_row(db, session_id, actor, *, write=False, allow_task_bound=False):
    """按资源归属判权限；跨项目和不存在均返回 404。"""
    row = get_row(db, WebAgentSession, session_id, actor, write=write)
    if row.task_run_id is not None and not allow_task_bound:
        raise not_found("Web 资源不存在")
    return row


def start_session(db, project_id, body: SessionStartInput, actor, *,
    task_run_id: int | None = None, task_agent_instance_id: int | None = None,
    task_binding_validator: TaskBindingValidator | None = None,
):
    """启动受控浏览器会话：验证环境、登录态与目标页，创建会话记录并打开浏览器。"""
    require_writable_project(db, project_id, actor)
    environment = resolve_project_environment(db, project_id, body.environment_id)
    if (task_run_id is None) != (task_agent_instance_id is None):
        raise bad_request("任务浏览器会话必须同时绑定运行与 UI Worker")
    if task_run_id is not None:
        if task_binding_validator is None:
            raise not_found("任务 Web 工作区不存在")
        task_binding_validator(
            db,
            project_id=project_id,
            environment_id=environment.id,
            task_run_id=task_run_id,
            task_agent_instance_id=task_agent_instance_id,
        )
        from app.execution.browser.session_manager import registry

        prior = db.query(WebAgentSession).filter(
            WebAgentSession.task_run_id == task_run_id,
        ).order_by(WebAgentSession.id.desc()).first()
        if prior is not None:
            if prior.status == "ACTIVE" and registry.get_session(prior.id) is not None:
                return session_response(prior)
            if prior.status == "ACTIVE":
                prior.status = "FAILED"
                prior.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                db.commit()
            if prior.status not in {"FAILED", "CLOSED"}:
                raise conflict("任务已有未结束的浏览器会话")
    from app.features.web_testing.services.target_policy_service import build_target_policy
    from app.execution.http.request_builder import get_environment_headers
    policy = build_target_policy(db, project_id)
    base_url = (environment.base_url or "").rstrip("/") + (environment.gateway_prefix or "")
    policy.require(base_url)
    state = {"cookies": [], "origins": []}
    secret_values = []
    if body.auth_profile_id:
        profile = get_row(db, WebAuthProfile, body.auth_profile_id, actor)
        if profile.project_id != project_id or profile.environment_id != environment.id:
            raise bad_request("认证配置与项目或执行环境不匹配")
        if profile.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None):
            raise bad_request("登录态已过期，请重新登录并导入")
        raw = decrypt_secret(profile.secret_encrypted)
        if not raw:
            raise bad_request("认证密文无法解密，请重新配置")
        from app.features.web_testing.services.execution_adapter import validate_storage_state, _all_strings
        auth = json.loads(raw)
        state = validate_storage_state(auth.get("storage_state") or {}, policy, environment)
        secret_values += _all_strings(auth)
    session_row = WebAgentSession(project_id=project_id, environment_id=environment.id,
        auth_profile_id=body.auth_profile_id, base_url=base_url,
        target_page_path=body.target_page_path, status="ACTIVE",
        step_budget=body.step_budget, created_by=actor.id,
        task_run_id=task_run_id, task_agent_instance_id=task_agent_instance_id)
    db.add(session_row)
    db.flush()
    headers = get_environment_headers(environment)
    # 默认请求头会被注入 Chromium；把敏感头值也加入运行时脱敏集合，避免目标页面回显
    # Authorization / API Key 等凭据后进入语义树、截图遮罩或 Agent prompt。
    from app.core.security.sensitive import is_sensitive_key
    secret_values.extend(
        value for key, value in headers.items()
        if is_sensitive_key(key) and value
    )
    from app.execution.browser.session_manager import registry
    try:
        registry.open_session(session_row.id, base_url=base_url, storage_state=state,
            headers=headers, policy=policy, target_page_path=body.target_page_path,
            step_budget=body.step_budget, initial_secrets=secret_values)
    except Exception:
        session_row.status = "FAILED"
        db.commit()
        raise
    db.commit()
    return session_response(session_row)


def get_session(db, session_id, actor, *, task_run_id: int | None = None):
    """读取会话元信息与当前步数。"""
    row = get_session_row(db, session_id, actor, allow_task_bound=task_run_id is not None)
    if task_run_id is not None and row.task_run_id != task_run_id:
        raise not_found("Web 资源不存在")
    return session_response(row)


def list_sessions(db, project_id, actor, *, page=1, page_size=20):
    """列出项目内的浏览器会话。"""
    get_project_or_404(db, project_id, actor)
    query = db.query(WebAgentSession).filter_by(project_id=project_id, task_run_id=None).order_by(WebAgentSession.id.desc())
    return list_result(query, lambda row: session_response(row), page, page_size)


def observe_session(db, session_id, actor, *, task_run_id: int | None = None):
    """观察会话当前页面：脱敏语义树与遮罩截图，不持久化（由 Phase B 决定落库时机）。

    写权限：观测会推进共享浏览器上下文，并在句柄失效时改写会话状态为 FAILED，
    因此 viewer 不能驱动别人的会话，也不能用观测把成员会话置为失败。
    """
    row = get_session_row(db, session_id, actor, write=True, allow_task_bound=task_run_id is not None)
    if task_run_id is not None and row.task_run_id != task_run_id:
        raise not_found("Web 资源不存在")
    if row.status != "ACTIVE":
        raise conflict("会话已关闭或失败，请先重新启动会话")
    from app.execution.browser.session_manager import registry
    browser = registry.get_session(row.id)
    if browser is None:
        row.status = "FAILED"
        row.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()
        raise conflict("浏览器会话已断开，请重新启动会话")
    return browser.observe()


def record_agent_step(db, session_id, *, sort, step, result, status, actor):
    """记录智能体已执行的一步：步骤与结果加密落库，供追溯与 promote 提升。

    由 agent 节点调用（service 层负责 commit）；跨项目会话统一 404。
    status 只允许 ACCEPTED / FAILED：提案未执行前不能创建步骤行，
    在写入侧收窄词表，避免未执行的步骤被误标成已接受而进入正式用例。
    """
    if status not in AGENT_STEP_STATUSES:
        raise bad_request(f"非法的智能体步骤状态：{status}")
    row = get_session_row(db, session_id, actor, write=True, allow_task_bound=True)
    db.add(WebAgentStep(
        session_id=row.id, sort=sort,
        step_encrypted=encrypt_secret(json_dump(step)),
        observation_encrypted=encrypt_secret(json_dump(result)),
        status=status, source="AI",
    ))
    db.commit()
    return {"session_id": row.id, "sort": sort, "status": status}


def close_session(db, session_id, actor, *, task_run_id: int | None = None):
    """关闭会话并释放浏览器资源。"""
    row = get_session_row(db, session_id, actor, write=True, allow_task_bound=task_run_id is not None)
    if task_run_id is not None and row.task_run_id != task_run_id:
        raise not_found("Web 资源不存在")
    from app.execution.browser.session_manager import registry
    registry.close_session(row.id)
    row.status = "CLOSED"
    row.closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return session_response(row)


AGENT_STEP_STATUSES = frozenset({"ACCEPTED", "FAILED"})
