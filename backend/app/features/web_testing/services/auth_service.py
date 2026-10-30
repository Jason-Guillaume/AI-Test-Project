"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from app.features.web_testing.models import WebAuthProfile, WebCase
from app.features.web_testing.schemas import AuthInput
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.platform.environment_configuration.services.environment_service import resolve_project_environment
from app.core.security.crypto import encrypt_secret
from app.core.http.errors import bad_request, not_found
from app.features.web_testing.services.response_mapper import auth_response
from app.features.web_testing.services.access_service import get_row
from app.features.web_testing.services.response_mapper import json_dump
from app.features.web_testing.services.response_mapper import list_result


def list_auth(db, project_id, actor, *, page=1, page_size=200):
    """列出凭据元信息，永不返回 Cookie/Token/密码。"""
    get_project_or_404(db, project_id, actor)
    return list_result(db.query(WebAuthProfile).filter_by(project_id=project_id).order_by(WebAuthProfile.id.desc()), auth_response, page, page_size)


def save_auth(db, project_id, body: AuthInput, actor, auth_id=None):
    """加密保存账号与人工扫码后的 storage_state；限定最长 30 天有效期。"""
    require_writable_project(db, project_id, actor)
    environment = resolve_project_environment(db, project_id, body.environment_id)
    expires = body.expires_at.replace(tzinfo=timezone.utc) if body.expires_at.tzinfo is None else body.expires_at.astimezone(timezone.utc)
    if not datetime.now(timezone.utc) < expires <= datetime.now(timezone.utc) + timedelta(days=30):
        raise bad_request("认证有效期必须在未来 30 天内")
    from app.features.web_testing.services.execution_adapter import validate_storage_state
    from app.features.web_testing.services.target_policy_service import build_target_policy
    state = validate_storage_state(body.storage_state, build_target_policy(db, project_id), environment)
    payload = {"username": body.username, "password": body.password, "jwt": body.jwt,
               "jwt_storage_key": body.jwt_storage_key, "storage_state": state}
    if auth_id:
        row = get_row(db, WebAuthProfile, auth_id, actor, write=True)
        if row.project_id != project_id:
            raise not_found("认证配置不存在")
    else:
        row = WebAuthProfile(project_id=project_id, created_by=actor.id)
        db.add(row)
    row.name, row.environment_id = body.name, body.environment_id
    row.secret_encrypted, row.expires_at = encrypt_secret(json_dump(payload)), expires.replace(tzinfo=None)
    db.commit()
    return auth_response(row)


def delete_auth(db, auth_id, actor):
    """撤销认证配置，清除引用用例的人工确认，避免静默变为匿名执行。"""
    row = get_row(db, WebAuthProfile, auth_id, actor, write=True)
    db.query(WebCase).filter_by(auth_profile_id=auth_id).update({"confirmed_digest": None}, synchronize_session=False)
    db.delete(row)
    db.commit()
