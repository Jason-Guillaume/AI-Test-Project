"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule
from app.features.api_catalog.models.api_parameter import ApiParameter
from app.features.api_catalog.models.api_relation import ApiRelation
from app.features.api_catalog.models.api_request_body import ApiRequestBody
from app.features.api_catalog.models.api_response import ApiResponse
from app.features.api_catalog.schemas import (
    ApiInterfaceResponse,
    ApiModuleResponse,
    ApiParameterResponse,
    ApiRelationResponse,
    ApiRequestBodyResponse,
    ApiResponseResponse,
    InternalApiSchema,
    InternalBody,
    InternalParameter,
    InternalResponse,
)


def param_to_internal(p: ApiParameter) -> InternalParameter:
    """将参数转换为内部数据结构。"""
    return InternalParameter(
        name=p.name,
        location=p.location,
        type=p.type or "string",
        required=bool(p.required),
        description=p.description,
        example=p.example,
        default_value=p.default_value,
        schema_json=p.schema_json,
        sort=p.sort or 0,
    )


def body_to_internal(b: ApiRequestBody | None) -> InternalBody:
    """将请求体转换为内部数据结构。"""
    if b is None:
        return InternalBody(body_type="none")
    return InternalBody(
        body_type=b.body_type or "none",
        content_type=b.content_type,
        schema_json=b.schema_json,
        raw_text=b.raw_text,
    )


def response_to_internal(r: ApiResponse) -> InternalResponse:
    """将响应转换为内部数据结构。"""
    return InternalResponse(
        status_code=r.status_code,
        description=r.description,
        schema_json=r.schema_json,
        example_json=r.example_json,
        sort=r.sort or 0,
    )


def interface_to_internal_schema(
    iface: ApiInterface,
    params: list[ApiParameter],
    body: ApiRequestBody | None,
    responses: list[ApiResponse],
) -> InternalApiSchema:
    """由库中接口重建 InternalApiSchema，用于 source_hash 重算与导入对比。"""
    return InternalApiSchema(
        name=iface.name,
        description=iface.description,
        method=iface.method,
        path=iface.path,
        auth_type=iface.auth_type or "none",
        content_type=iface.content_type or "application/json",
        parameters=[param_to_internal(p) for p in params],
        body=body_to_internal(body),
        responses=[response_to_internal(r) for r in responses],
        tags=[],
        suggested_module=None,
        source_type=iface.source_type or "MANUAL",
    )


def module_response(mod: ApiModule, interface_count: int) -> ApiModuleResponse:
    """构造模块响应数据。"""
    return ApiModuleResponse(
        id=mod.id,
        project_id=mod.project_id,
        name=mod.name,
        parent_id=mod.parent_id,
        sort=mod.sort or 0,
        is_default=bool(mod.is_default),
        interface_count=interface_count,
        created_at=mod.created_at,
        updated_at=mod.updated_at,
    )


def interface_response(iface: ApiInterface, module_map: dict[int, str]) -> ApiInterfaceResponse:
    """构造接口响应数据。"""
    return ApiInterfaceResponse(
        id=iface.id,
        project_id=iface.project_id,
        module_id=iface.module_id,
        module_name=module_map.get(iface.module_id) if iface.module_id else None,
        name=iface.name,
        description=iface.description,
        method=iface.method,
        path=iface.path,
        auth_type=iface.auth_type,
        content_type=iface.content_type,
        status=iface.status,
        source_type=iface.source_type,
        version=iface.version,
        source_hash=iface.source_hash,
        created_at=iface.created_at,
        updated_at=iface.updated_at,
    )


def param_response(p: ApiParameter) -> ApiParameterResponse:
    """构造参数响应数据。"""
    return ApiParameterResponse(
        id=p.id,
        interface_id=p.interface_id,
        name=p.name,
        location=p.location,
        type=p.type or "string",
        required=bool(p.required),
        description=p.description,
        example=p.example,
        default_value=p.default_value,
        schema_json=p.schema_json,
        sort=p.sort or 0,
    )


def body_response(b: ApiRequestBody | None, interface_id: int) -> ApiRequestBodyResponse:
    """构造请求体响应数据。"""
    return ApiRequestBodyResponse(
        id=b.id if b else None,
        interface_id=interface_id,
        body_type=(b.body_type if b else "none"),
        content_type=(b.content_type if b else None),
        schema_json=(b.schema_json if b else None),
        raw_text=(b.raw_text if b else None),
    )


def response_response(r: ApiResponse) -> ApiResponseResponse:
    """构造响应响应数据。"""
    return ApiResponseResponse(
        id=r.id,
        interface_id=r.interface_id,
        status_code=r.status_code,
        description=r.description,
        schema_json=r.schema_json,
        example_json=r.example_json,
        sort=r.sort or 0,
    )


def relation_response(rel: ApiRelation, names: dict[int, str]) -> ApiRelationResponse:
    """构造关联关系响应数据。"""
    return ApiRelationResponse(
        id=rel.id,
        project_id=rel.project_id,
        source_api_id=rel.source_api_id,
        target_api_id=rel.target_api_id,
        source_api_name=names.get(rel.source_api_id),
        target_api_name=names.get(rel.target_api_id),
        relation_type=rel.relation_type,
        variable_name=rel.variable_name,
        extract_path=rel.extract_path,
        created_at=rel.created_at,
    )
