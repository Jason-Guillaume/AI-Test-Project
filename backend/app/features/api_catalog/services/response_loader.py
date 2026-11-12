"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule
from app.features.api_catalog.schemas import ApiInterfaceDetailResponse
from app.features.api_catalog.services.request_store import (
    load_interface_request_body,
    load_interface_request_params,
)
from app.features.api_catalog.services.response_mapper import body_response
from app.features.api_catalog.services.response_mapper import interface_response
from app.features.api_catalog.services.request_store import load_interface_request_body
from app.features.api_catalog.services.request_store import load_interface_request_params
from app.features.api_catalog.services.request_store import load_responses
from app.features.api_catalog.services.response_mapper import param_response
from app.features.api_catalog.services.response_mapper import response_response


def detail_response(db: Session, iface: ApiInterface) -> ApiInterfaceDetailResponse:
    """构造`detail`响应数据。"""
    params = load_interface_request_params(db, iface.id)
    body = load_interface_request_body(db, iface.id)
    responses = load_responses(db, iface.id)
    module_map: dict[int, str] = {}
    if iface.module_id:
        mod = db.get(ApiModule, iface.module_id)
        if mod is not None:
            module_map[iface.module_id] = mod.name
    base = interface_response(iface, module_map)
    return ApiInterfaceDetailResponse(
        **base.model_dump(),
        parameters=[param_response(p) for p in params],
        body=body_response(body, iface.id) if body else None,
        responses=[response_response(r) for r in responses],
    )
