"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.schemas import (
    API_STATUSES,
    HTTP_METHODS,
    ApiInterfaceCreate,
    ApiInterfaceDetailResponse,
    ApiInterfaceListResponse,
    ApiInterfaceUpdate,
)
from app.features.api_catalog.services.hash import compute_source_hash
from app.features.api_catalog.services.request_store import (
    load_interface_request_body,
    load_interface_request_params,
)
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict
from app.platform.projects.services.access_service import check_writable
from app.features.api_catalog.services.response_loader import detail_response
from app.features.api_catalog.services.access_service import get_interface_or_404
from app.platform.projects.services.access_service import get_project_or_404
from app.features.api_catalog.services.access_service import get_writable_interface_or_404
from app.features.api_catalog.services.response_mapper import interface_response
from app.features.api_catalog.services.response_mapper import interface_to_internal_schema
from app.features.api_catalog.services.request_store import load_interface_request_body
from app.features.api_catalog.services.request_store import load_interface_request_params
from app.features.api_catalog.services.request_store import load_responses
from app.features.api_catalog.services.queries import module_name_map
from app.features.api_catalog.services.change_service import recompute_hash_and_log
from app.features.api_catalog.services.request_store import replace_body
from app.features.api_catalog.services.request_store import replace_params
from app.features.api_catalog.services.request_store import replace_responses
from app.features.api_catalog.services.module_service import resolve_module_for_interface
from app.features.api_catalog.services.change_service import write_change_log


def list_interfaces(db: Session,
    project_id: int,
    user: User,
    *,
    keyword: str | None = None,
    method: str | None = None,
    module_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> ApiInterfaceListResponse:
    """列出`interfaces`。"""
    get_project_or_404(db, project_id, user)
    query = db.query(ApiInterface).filter(ApiInterface.project_id == project_id)
    kw = (keyword or "").strip()
    if kw:
        from sqlalchemy import or_

        query = query.filter(
            or_(ApiInterface.name.ilike(f"%{kw}%"), ApiInterface.path.ilike(f"%{kw}%"))
        )
    if method:
        method = method.upper()
        if method not in HTTP_METHODS:
            raise bad_request("HTTP 方法取值非法")
        query = query.filter(ApiInterface.method == method)
    if module_id is not None:
        query = query.filter(ApiInterface.module_id == module_id)
    if status:
        # 与上面的 method 过滤同一写法：先归一大写再校验。前端枚举值是大写，
        # 归一化兜住手输小写的直连调用；校验而非静默返回空集，否则拼错状态码
        # 会得到「0 条」这种看不出原因的假阴性。
        status = status.upper()
        if status not in API_STATUSES:
            raise bad_request("接口状态取值非法")
        query = query.filter(ApiInterface.status == status)
    total = int(query.count())
    items = (
        query.order_by(ApiInterface.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    module_map = module_name_map(db, [i.module_id for i in items if i.module_id])
    return ApiInterfaceListResponse(
        items=[interface_response(i, module_map) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


def create_interface(db: Session, project_id: int, body: ApiInterfaceCreate, *, actor: User
) -> ApiInterfaceDetailResponse:
    """创建接口。"""
    project = get_project_or_404(db, project_id, actor)
    check_writable(db, project, actor)
    if body.method.upper() not in HTTP_METHODS:
        raise bad_request("HTTP 方法取值非法")
    module_id = resolve_module_for_interface(db, project_id, body.module_id)
    ensure_unique_interface(db, project_id, body.method, body.path)
    iface = ApiInterface(
        project_id=project_id,
        module_id=module_id,
        name=body.name.strip(),
        description=body.description,
        method=body.method.upper(),
        path=body.path,
        auth_type=body.auth_type or "none",
        content_type=body.content_type or "application/json",
        status=body.status,
        source_type="MANUAL",
        version=1,
    )
    db.add(iface)
    db.flush()
    replace_params(db, iface.id, body.parameters)
    replace_body(db, iface.id, body.body)
    replace_responses(db, iface.id, body.responses)
    # 计算 source_hash 并写创建日志。
    params = load_interface_request_params(db, iface.id)
    body_obj = load_interface_request_body(db, iface.id)
    responses = load_responses(db, iface.id)
    schema = interface_to_internal_schema(iface, params, body_obj, responses)
    iface.source_hash = compute_source_hash(schema)
    write_change_log(
        db, iface, "CREATED",
        source_hash_after=iface.source_hash,
        summary=f"创建接口 {iface.method} {iface.path}",
        actor=actor,
    )
    db.commit()
    db.refresh(iface)
    return detail_response(db, iface)


def get_interface(db: Session, api_id: int, user: User) -> ApiInterfaceDetailResponse:
    """获取接口。"""
    iface = get_interface_or_404(db, api_id, user)
    return detail_response(db, iface)


def update_interface(db: Session, api_id: int, body: ApiInterfaceUpdate, *, actor: User
) -> ApiInterfaceDetailResponse:
    """更新接口。"""
    iface = get_writable_interface_or_404(db, api_id, actor)
    data = body.model_dump(exclude_unset=True)
    structural = False
    if "method" in data and data["method"] is not None:
        data["method"] = data["method"].upper()
        if data["method"] not in HTTP_METHODS:
            raise bad_request("HTTP 方法取值非法")
    if ("method" in data and data["method"] is not None and data["method"] != iface.method) or (
        "path" in data and data["path"] is not None and data["path"] != iface.path
    ):
        # method/path 变更需重新校验唯一性。
        new_method = data.get("method") or iface.method
        new_path = data.get("path") or iface.path
        ensure_unique_interface(db, iface.project_id, new_method, new_path, exclude_id=iface.id)
    module_changed = False
    for field, value in data.items():
        if field == "module_id":
            module_changed = value != iface.module_id
            iface.module_id = resolve_module_for_interface(db, iface.project_id, value)
            continue
        if field in {"method", "path", "auth_type", "content_type"} and value is not None:
            if getattr(iface, field) != value:
                structural = True
        setattr(iface, field, value)
    db.flush()
    # 结构字段变更 → 重算 hash + UPDATED 日志；模块移动单独记 MODULE_CHANGED。
    if structural:
        recompute_hash_and_log(
            db, iface, change_type="UPDATED",
            summary=f"更新接口 {iface.method} {iface.path}", actor=actor,
        )
    if module_changed:
        write_change_log(
            db, iface, "MODULE_CHANGED",
            diff_json={"module_id": data.get("module_id")},
            summary="移动接口到其他模块", actor=actor,
        )
    db.commit()
    db.refresh(iface)
    return detail_response(db, iface)


def move_interface(db: Session, api_id: int, body, *, actor: User
) -> ApiInterfaceDetailResponse:
    """移动接口。"""
    iface = get_writable_interface_or_404(db, api_id, actor)
    new_module_id = resolve_module_for_interface(db, iface.project_id, body.module_id)
    if new_module_id != iface.module_id:
        iface.module_id = new_module_id
        write_change_log(
            db, iface, "MODULE_CHANGED",
            diff_json={"module_id": new_module_id},
            summary="移动接口到其他模块", actor=actor,
        )
    db.flush()
    db.commit()
    db.refresh(iface)
    return detail_response(db, iface)


def delete_interface(db: Session, api_id: int, *, actor: User) -> None:
    """删除接口。"""
    iface = get_writable_interface_or_404(db, api_id, actor)
    db.delete(iface)
    db.commit()


def ensure_unique_interface(
    db: Session, project_id: int, method: str, path: str, *, exclude_id: int | None = None
) -> None:
    """确保`unique`接口。"""
    query = db.query(ApiInterface).filter(
        ApiInterface.project_id == project_id,
        ApiInterface.method == method.upper(),
        ApiInterface.path == path,
    )
    if exclude_id is not None:
        query = query.filter(ApiInterface.id != exclude_id)
    if query.first() is not None:
        raise conflict("同项目下已存在相同 method+path 的接口")
