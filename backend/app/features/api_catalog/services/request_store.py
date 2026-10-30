"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.api_catalog.models.api_parameter import ApiParameter
from app.features.api_catalog.models.api_request_body import ApiRequestBody
from app.features.api_catalog.models.api_response import ApiResponse
from app.features.api_catalog.schemas import ApiBodyIn, ApiParameterIn, ApiResponseIn


def load_interface_request_params(db: Session, interface_id: int) -> list[ApiParameter]:
    """按既有 sort、id 顺序加载接口参数。"""
    return (
        db.query(ApiParameter)
        .filter(ApiParameter.interface_id == interface_id)
        .order_by(ApiParameter.sort.asc(), ApiParameter.id.asc())
        .all()
    )


def load_interface_request_body(db: Session, interface_id: int) -> ApiRequestBody | None:
    """加载接口唯一请求体；缺少记录时返回 None。"""
    return (
        db.query(ApiRequestBody)
        .filter(ApiRequestBody.interface_id == interface_id)
        .one_or_none()
    )


def load_responses(db: Session, interface_id: int) -> list[ApiResponse]:
    """加载`responses`。"""
    return (
        db.query(ApiResponse)
        .filter(ApiResponse.interface_id == interface_id)
        .order_by(ApiResponse.sort.asc(), ApiResponse.id.asc())
        .all()
    )


def replace_params(db: Session, interface_id: int, params: list[ApiParameterIn]) -> None:
    """替换参数。"""
    db.query(ApiParameter).filter(ApiParameter.interface_id == interface_id).delete()
    for idx, p in enumerate(params):
        db.add(ApiParameter(
            interface_id=interface_id,
            name=p.name,
            location=p.location,
            type=p.type or "string",
            required=p.required,
            description=p.description,
            example=p.example,
            default_value=p.default_value,
            schema_json=p.schema_json,
            sort=p.sort if p.sort is not None else idx,
        ))
    db.flush()


def replace_body(db: Session, interface_id: int, body: ApiBodyIn) -> None:
    """替换请求体。"""
    existing = load_interface_request_body(db, interface_id)
    if existing is None:
        existing = ApiRequestBody(interface_id=interface_id)
        db.add(existing)
    existing.body_type = body.body_type
    existing.content_type = body.content_type
    existing.schema_json = body.schema_json
    existing.raw_text = body.raw_text
    db.flush()


def replace_responses(db: Session, interface_id: int, responses: list[ApiResponseIn]) -> None:
    """替换`responses`。"""
    db.query(ApiResponse).filter(ApiResponse.interface_id == interface_id).delete()
    for idx, r in enumerate(responses):
        db.add(ApiResponse(
            interface_id=interface_id,
            status_code=r.status_code,
            description=r.description,
            schema_json=r.schema_json,
            example_json=r.example_json,
            sort=r.sort if r.sort is not None else idx,
        ))
    db.flush()
