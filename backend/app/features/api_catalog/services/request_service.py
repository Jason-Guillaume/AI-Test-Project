"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.api_catalog.schemas import (
    ApiRequestBundle,
    ApiRequestBundleResponse,
    ApiResponsesBundle,
    ApiResponsesBundleResponse,
)
from app.features.api_catalog.services.request_store import (
    load_interface_request_body,
    load_interface_request_params,
)
from app.core.models.identity import User
from app.features.api_catalog.services.response_mapper import body_response
from app.features.api_catalog.services.change_diff import diff_body
from app.features.api_catalog.services.change_diff import diff_params
from app.features.api_catalog.services.change_diff import diff_responses
from app.features.api_catalog.services.access_service import get_interface_or_404
from app.features.api_catalog.services.access_service import get_writable_interface_or_404
from app.features.api_catalog.services.request_store import load_interface_request_body
from app.features.api_catalog.services.request_store import load_interface_request_params
from app.features.api_catalog.services.request_store import load_responses
from app.features.api_catalog.services.response_mapper import param_response
from app.features.api_catalog.services.change_service import recompute_hash_and_log
from app.features.api_catalog.services.request_store import replace_body
from app.features.api_catalog.services.request_store import replace_params
from app.features.api_catalog.services.request_store import replace_responses
from app.features.api_catalog.services.response_mapper import response_response
from app.features.api_catalog.services.change_service import write_change_log


def get_request(db: Session, api_id: int, user: User) -> ApiRequestBundleResponse:
    """获取请求。"""
    iface = get_interface_or_404(db, api_id, user)
    params = load_interface_request_params(db, iface.id)
    body = load_interface_request_body(db, iface.id)
    return ApiRequestBundleResponse(
        parameters=[param_response(p) for p in params],
        body=body_response(body, iface.id) if body else None,
    )


def save_request(db: Session, api_id: int, body: ApiRequestBundle, *, actor: User
) -> ApiRequestBundleResponse:
    """保存请求。"""
    iface = get_writable_interface_or_404(db, api_id, actor)
    old_params = load_interface_request_params(db, iface.id)
    old_body = load_interface_request_body(db, iface.id)
    replace_params(db, iface.id, body.parameters)
    replace_body(db, iface.id, body.body)
    diff = diff_params(old_params, body.parameters) | diff_body(old_body, body.body)
    if diff:
        write_change_log(
            db, iface, "UPDATED",
            diff_json={"request": diff},
            summary="替换请求参数/请求体", actor=actor,
        )
    recompute_hash_and_log(
        db, iface, change_type="UPDATED",
        summary="请求结构变更导致 source_hash 更新", actor=actor,
    )
    db.commit()
    return get_request(db, api_id, actor)  # 复用读路径构造响应


def get_responses(db: Session, api_id: int, user: User) -> ApiResponsesBundleResponse:
    """获取`responses`。"""
    iface = get_interface_or_404(db, api_id, user)
    responses = load_responses(db, iface.id)
    return ApiResponsesBundleResponse(
        responses=[response_response(r) for r in responses]
    )


def save_responses(db: Session, api_id: int, body: ApiResponsesBundle, *, actor: User
) -> ApiResponsesBundleResponse:
    """保存`responses`。"""
    iface = get_writable_interface_or_404(db, api_id, actor)
    old_responses = load_responses(db, iface.id)
    replace_responses(db, iface.id, body.responses)
    diff = diff_responses(old_responses, body.responses)
    if diff:
        write_change_log(
            db, iface, "RESPONSE_CHANGED",
            diff_json={"responses": diff},
            summary="替换响应结构", actor=actor,
        )
    recompute_hash_and_log(
        db, iface, change_type="RESPONSE_CHANGED",
        summary="响应结构变更导致 source_hash 更新", actor=actor,
    )
    db.commit()
    return get_responses(db, api_id, actor)
