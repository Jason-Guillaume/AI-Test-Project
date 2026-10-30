"""接口导入服务：parse → ModuleResolver → 去重 → 预览 → 确认入库。

流程（spec §14）：
- preview：解析为 InternalApiSchema 列表，逐条跑 ModuleResolver（dry，不落库）+ 去重
  （project_id+method+path）+ hash 比对，分类 NEW/CHANGED/UNCHANGED，返回预览不入库。
- confirm：重新解析（幂等，不信任预览缓存）→ 对 NEW+CHANGED 且勾选项入库；
  CHANGED 替换参数/body/响应子表、version+1、source_hash 更新、写变更日志；
  写 api_import_record 聚合计数。单事务提交（service owns commit）。

去重键：project_id + method + path（DB 唯一约束兜底）。
source_hash：compute_source_hash（结构字段 sha256），UNCHANGED 跳过。"""

from __future__ import annotations

import hashlib
from sqlalchemy.orm import Session
from app.features.api_catalog.models.api_change_log import ApiChangeLog
from app.features.api_catalog.models.api_import_record import ApiImportRecord
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.parsers import parse_curl
from app.features.api_catalog.parsers.document_parser import parse_api_document
from app.features.api_catalog.schemas import (
    ImportConfirmRequest,
    ImportConfirmResponse,
    ImportPreviewItem,
    ImportPreviewRequest,
    ImportPreviewResponse,
    InternalApiSchema,
    ApiBodyIn,
    ApiParameterIn,
    ApiResponseIn,
)
from app.features.api_catalog.services.request_store import load_responses
from app.features.api_catalog.services.request_store import replace_body
from app.features.api_catalog.services.request_store import replace_params
from app.features.api_catalog.services.request_store import replace_responses
from app.features.api_catalog.services.response_mapper import interface_to_internal_schema
from app.features.api_catalog.services.request_service import (
    load_interface_request_body,
    load_interface_request_params,
)
from app.features.api_catalog.services.hash import compute_source_hash
from app.features.api_catalog.services.module_resolver import ModuleResolver
from app.core.models.identity import User
from app.core.http.errors import bad_request, forbidden
from app.core.security.roles import PROJECT_ROLE_MEMBER, has_project_role, project_role_for


_resolver = ModuleResolver()


def _current_structure_hash(db: Session, iface: ApiInterface) -> str:
    """Compare against stored structure, including rows with a stale historical hash."""
    return compute_source_hash(interface_to_internal_schema(
        iface, load_interface_request_params(db, iface.id),
        load_interface_request_body(db, iface.id), load_responses(db, iface.id),
    ))


class ImportService:
    """接口导入：预览 + 确认。无状态。"""

    # ---------------------------------------------------------------- 预览

    def preview(
        self, db: Session, project_id: int, body: ImportPreviewRequest, *, actor: User
    ) -> ImportPreviewResponse:
        """预览对应数据。"""
        self._assert_writable(db, project_id, actor)
        schemas = _parse(body.source_type, body.content)
        items: list[ImportPreviewItem] = []
        counts = {"NEW": 0, "CHANGED": 0, "UNCHANGED": 0}
        for schema in schemas:
            schema.source_hash = compute_source_hash(schema)
            existing = _find_existing(db, project_id, schema.method, schema.path)
            if existing is None:
                classification = "NEW"
                existing_id = None
                diff = None
            elif _current_structure_hash(db, existing) == schema.source_hash:
                classification = "UNCHANGED"
                existing_id = existing.id
                diff = None
            else:
                classification = "CHANGED"
                existing_id = existing.id
                diff = _compute_import_diff(db, existing, schema)
            proposed_module_id, proposed_module_name = _resolver.resolve_dry(
                db, project_id, schema,
                user_module_id=body.user_module_id,
                tag_to_module_map=body.tag_to_module_map,
            )
            counts[classification] += 1
            items.append(ImportPreviewItem(
                classification=classification,
                schema=schema,
                proposed_module_id=proposed_module_id,
                proposed_module_name=proposed_module_name,
                existing_interface_id=existing_id,
                diff_summary=diff,
            ))
        return ImportPreviewResponse(
            project_id=project_id,
            source_type=_parsed_source_type(schemas, body.source_type),
            source_hash=None,
            total=len(schemas),
            new_count=counts["NEW"],
            existing_count=counts["CHANGED"] + counts["UNCHANGED"],
            changed_count=counts["CHANGED"],
            unchanged_count=counts["UNCHANGED"],
            items=items,
        )

    # ---------------------------------------------------------------- 确认

    def confirm(
        self, db: Session, project_id: int, body: ImportConfirmRequest, *, actor: User
    ) -> ImportConfirmResponse:
        """确认对应数据。"""
        self._assert_writable(db, project_id, actor)
        schemas = _parse(body.source_type, body.content)
        # 重新解析后按与预览相同的键去重；不信任预览缓存（幂等）。
        created = updated = skipped = 0
        per_schema_hashes: list[str] = []
        for idx, schema in enumerate(schemas):
            schema.source_hash = compute_source_hash(schema)
            per_schema_hashes.append(schema.source_hash)
            if body.selected_items is not None and idx not in body.selected_items:
                skipped += 1
                continue
            existing = _find_existing(db, project_id, schema.method, schema.path)
            if existing is None:
                self._create_from_schema(db, project_id, schema, actor, body.user_module_id, body.tag_to_module_map)
                created += 1
            elif _current_structure_hash(db, existing) == schema.source_hash:
                skipped += 1
            else:
                if not body.overwrite_changed:
                    skipped += 1
                    continue
                self._update_from_schema(db, existing, schema, actor)
                updated += 1
        batch_hash = _batch_hash(per_schema_hashes)
        record = ApiImportRecord(
            project_id=project_id,
            source_type=_parsed_source_type(schemas, body.source_type),
            file_name=body.file_name,
            source_hash=batch_hash,
            total=len(schemas),
            created_count=created,
            updated_count=updated,
            skipped_count=skipped,
            created_by=actor.id,
        )
        db.add(record)
        db.flush()
        db.commit()
        db.refresh(record)
        return ImportConfirmResponse(
            record_id=record.id,
            total=len(schemas),
            created_count=created,
            updated_count=updated,
            skipped_count=skipped,
            source_hash=batch_hash,
        )

    # ---------------------------------------------------------------- 内部

    def _assert_writable(self, db: Session, project_id: int, actor: User) -> None:
        """断言可写。"""
        from app.core.models.project import Project

        project = db.get(Project, project_id)
        if project is None:
            raise bad_request("项目不存在")
        if not has_project_role(project_role_for(db, project, actor), PROJECT_ROLE_MEMBER):
            raise forbidden("需要项目成员权限")

    def _create_from_schema(
        self, db: Session, project_id: int, schema: InternalApiSchema, actor: User,
        user_module_id: int | None, tag_to_module_map: dict[str, int] | None,
    ) -> ApiInterface:
        """创建从结构定义。"""
        module_id = _resolver.resolve(
            db, project_id, schema, user_module_id=user_module_id, tag_to_module_map=tag_to_module_map
        )
        iface = ApiInterface(
            project_id=project_id,
            module_id=module_id,
            name=schema.name[:200],
            description=schema.description,
            method=schema.method,
            path=schema.path,
            auth_type=schema.auth_type or "none",
            content_type=schema.content_type or "application/json",
            status="DRAFT",
            source_type=schema.source_type,
            version=1,
            source_hash=schema.source_hash,
        )
        db.add(iface)
        db.flush()
        _apply_schema_children(db, iface.id, schema)
        db.flush()
        db.add(ApiChangeLog(
            interface_id=iface.id,
            change_type="CREATED",
            source_hash_after=schema.source_hash,
            summary=f"导入创建接口 {schema.method} {schema.path}",
            created_by=actor.id,
        ))
        db.flush()
        return iface

    def _update_from_schema(
        self, db: Session, iface: ApiInterface, schema: InternalApiSchema, actor: User
    ) -> None:
        """更新从结构定义。"""
        diff = _compute_import_diff(db, iface, schema)
        # 字段更新（保留 module_id 除非 resolver 重新解析到不同模块；这里不移动模块，避免误改用户归类）。
        iface.name = schema.name[:200]
        iface.description = schema.description
        iface.auth_type = schema.auth_type or "none"
        iface.content_type = schema.content_type or "application/json"
        iface.source_type = schema.source_type
        iface.version = (iface.version or 1) + 1
        before_hash = iface.source_hash
        iface.source_hash = schema.source_hash
        _apply_schema_children(db, iface.id, schema)
        db.flush()
        # 汇总 UPDATED 日志 + 按类别补细粒度日志（每类至多一条，控制行数）。
        db.add(ApiChangeLog(
            interface_id=iface.id,
            change_type="UPDATED",
            diff_json=diff,
            source_hash_before=before_hash,
            source_hash_after=schema.source_hash,
            summary=f"导入更新接口 {schema.method} {schema.path}",
            created_by=actor.id,
        ))
        _write_granular_logs(db, iface.id, diff, actor)
        db.flush()


def _parse(source_type: str, content: str) -> list[InternalApiSchema]:
    """自动识别常见接口文档；cURL 保持单条解析。"""
    st = (source_type or "").upper()
    try:
        if st == "CURL":
            detected = parse_api_document(content, required=False)
            if detected is not None:
                return detected
            return [parse_curl(content)]
        if st in {"OPENAPI", "SWAGGER", "POSTMAN", "APIFOX"}:
            return parse_api_document(content) or []
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    raise bad_request(f"暂不支持的导入来源：{source_type}")


def _parsed_source_type(schemas: list[InternalApiSchema], fallback: str) -> str:
    """用解析结果标记实际格式，避免用户选错来源时导入记录留下错误类型。"""
    return schemas[0].source_type if schemas else fallback


def _find_existing(db: Session, project_id: int, method: str, path: str) -> ApiInterface | None:
    """查找`existing`。"""
    return (
        db.query(ApiInterface)
        .filter(
            ApiInterface.project_id == project_id,
            ApiInterface.method == method.upper(),
            ApiInterface.path == path,
        )
        .one_or_none()
    )


def _apply_schema_children(db: Session, interface_id: int, schema: InternalApiSchema) -> None:
    """把 schema 的参数/body/响应写入子表（整体替换）。"""
    params = [ApiParameterIn(**p.model_dump()) for p in schema.parameters]
    body = ApiBodyIn(**schema.body.model_dump())
    responses = [ApiResponseIn(**r.model_dump()) for r in schema.responses]
    replace_params(db, interface_id, params)
    replace_body(db, interface_id, body)
    replace_responses(db, interface_id, responses)


def _compute_import_diff(
    db: Session, iface: ApiInterface, schema: InternalApiSchema
) -> dict:
    """计算已有接口与导入 schema 的结构 diff（参数/响应/关键字段）。"""
    old_params = load_interface_request_params(db, iface.id)
    old_body = load_interface_request_body(db, iface.id)
    old_responses = load_responses(db, iface.id)

    old_param_map = {p.name: (p.type, bool(p.required)) for p in old_params}
    new_param_map = {p.name: (p.type or "string", bool(p.required)) for p in schema.parameters}
    added = [n for n in new_param_map if n not in old_param_map]
    removed = [n for n in old_param_map if n not in new_param_map]
    type_changed = []
    required_changed = []
    for n in new_param_map:
        if n in old_param_map:
            if old_param_map[n][0] != new_param_map[n][0]:
                type_changed.append(n)
            if old_param_map[n][1] != new_param_map[n][1]:
                required_changed.append(n)

    old_codes = {r.status_code for r in old_responses}
    new_codes = {r.status_code for r in schema.responses}
    resp_added = sorted(c for c in new_codes if c not in old_codes)
    resp_removed = sorted(c for c in old_codes if c not in new_codes)

    body_changed = (
        old_body is None
        or (old_body.body_type or "none") != schema.body.body_type
        or (old_body.content_type or None) != (schema.body.content_type or None)
    )
    return {
        "params": {"added": added, "removed": removed, "type_changed": type_changed, "required_changed": required_changed},
        "responses": {"added": resp_added, "removed": resp_removed},
        "body_changed": body_changed,
    }


def _write_granular_logs(db: Session, interface_id: int, diff: dict, actor: User) -> None:
    """按 diff 类别补细粒度变更日志（每类至多一条）。"""
    params = diff.get("params", {})
    if params.get("added"):
        db.add(ApiChangeLog(interface_id=interface_id, change_type="PARAM_ADDED",
                            diff_json={"names": params["added"]}, summary="导入新增参数", created_by=actor.id))
    if params.get("removed"):
        db.add(ApiChangeLog(interface_id=interface_id, change_type="PARAM_REMOVED",
                            diff_json={"names": params["removed"]}, summary="导入移除参数", created_by=actor.id))
    if params.get("type_changed"):
        db.add(ApiChangeLog(interface_id=interface_id, change_type="PARAM_TYPE_CHANGED",
                            diff_json={"names": params["type_changed"]}, summary="导入参数类型变更", created_by=actor.id))
    if params.get("required_changed"):
        db.add(ApiChangeLog(interface_id=interface_id, change_type="REQUIRED_CHANGED",
                            diff_json={"names": params["required_changed"]}, summary="导入参数必填变更", created_by=actor.id))
    responses = diff.get("responses", {})
    if responses.get("added") or responses.get("removed"):
        db.add(ApiChangeLog(interface_id=interface_id, change_type="RESPONSE_CHANGED",
                            diff_json=responses, summary="导入响应结构变更", created_by=actor.id))


def _batch_hash(per_schema_hashes: list[str]) -> str:
    """整批 source_hash：对逐条 hash 排序后拼接再 sha256。"""
    joined = "".join(sorted(per_schema_hashes))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


__all__ = [
    'ImportService',
]
