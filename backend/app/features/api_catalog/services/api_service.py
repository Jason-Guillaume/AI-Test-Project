"""接口管理核心服务：模块/接口/参数/body/响应/关联/历史/导入记录 CRUD。

路由层只做参数、认证与响应映射；业务、权限与事务集中在此。

权限模型（复用 shared.roles）：
- 读（模块/接口/参数/响应/关联/历史/导入记录）：对该 project viewer+；不可见→404。
- 写（增/改/删/移动/参数/响应/关联/导入）：member+。
- 越权与不存在共用 404，隐藏存在性。

事务约定：service owns commit；router 不提交。db.flush() 取自增 ID。
变更记录：创建/更新/移动/参数替换/响应替换均写 api_change_log；source_hash 随结构变更重算。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_change_log import ApiChangeLog
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_import_record import ApiImportRecord
from app.features.api_catalog.models.api_module import ApiModule
from app.features.api_catalog.models.api_parameter import ApiParameter
from app.features.api_catalog.models.api_relation import ApiRelation
from app.features.api_catalog.models.api_request_body import ApiRequestBody
from app.features.api_catalog.models.api_response import ApiResponse
from app.features.api_catalog.schemas import (
    API_STATUSES,
    HTTP_METHODS,
    ApiBodyIn,
    ApiChangeLogResponse,
    ApiInterfaceCreate,
    ApiInterfaceDetailResponse,
    ApiInterfaceListResponse,
    ApiInterfaceResponse,
    ApiInterfaceUpdate,
    ApiModuleCreate,
    ApiModuleMove,
    ApiModuleResponse,
    ApiModuleUpdate,
    ApiParameterIn,
    ApiParameterResponse,
    ApiRelationCreate,
    ApiRelationResponse,
    ApiRequestBodyResponse,
    ApiRequestBundle,
    ApiRequestBundleResponse,
    ApiResponseIn,
    ApiResponseResponse,
    ApiResponsesBundle,
    ApiResponsesBundleResponse,
    InternalApiSchema,
    InternalBody,
    InternalParameter,
    InternalResponse,
)
from app.features.api_catalog.services.hash import compute_source_hash
from app.features.api_catalog.services.module_resolver import (
    DEFAULT_MODULE_NAME,
    ModuleResolver,
)
from app.models.identity import User
from app.models.project import Project
from app.shared.errors import bad_request, conflict, forbidden, not_found
from app.shared.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    accessible_project_ids,
    has_project_role,
    project_role_for,
)

_resolver = ModuleResolver()


# ----------------------------------------------------------------------------- 结构 <-> Internal


def _param_to_internal(p: ApiParameter) -> InternalParameter:
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


def _body_to_internal(b: ApiRequestBody | None) -> InternalBody:
    """将请求体转换为内部数据结构。"""
    if b is None:
        return InternalBody(body_type="none")
    return InternalBody(
        body_type=b.body_type or "none",
        content_type=b.content_type,
        schema_json=b.schema_json,
        raw_text=b.raw_text,
    )


def _response_to_internal(r: ApiResponse) -> InternalResponse:
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
        parameters=[_param_to_internal(p) for p in params],
        body=_body_to_internal(body),
        responses=[_response_to_internal(r) for r in responses],
        tags=[],
        suggested_module=None,
        source_type=iface.source_type or "MANUAL",
    )


# ----------------------------------------------------------------------------- 服务


class ApiService:
    """接口管理核心服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 可见性

    def _get_project_or_404(self, db: Session, project_id: int, user: User) -> Project:
        """获取项目或。"""
        project = db.get(Project, project_id)
        if project is None:
            raise not_found("项目不存在")
        if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
            raise not_found("项目不存在")
        return project

    def _check_writable(self, db: Session, project: Project, actor: User) -> None:
        """检查可写。"""
        role = project_role_for(db, project, actor)
        if not has_project_role(role, PROJECT_ROLE_MEMBER):
            raise forbidden("需要项目成员权限")

    def _get_interface_or_404(self, db: Session, api_id: int, user: User) -> ApiInterface:
        """获取接口或。"""
        iface = db.get(ApiInterface, api_id)
        if iface is None:
            raise not_found("接口不存在")
        visible_ids = accessible_project_ids(db, user)
        if visible_ids is not None and iface.project_id not in visible_ids:
            raise not_found("接口不存在")
        return iface

    def _get_writable_interface_or_404(self, db: Session, api_id: int, user: User) -> ApiInterface:
        """获取可写接口或。"""
        iface = self._get_interface_or_404(db, api_id, user)
        project = db.get(Project, iface.project_id)
        if project is None:
            raise not_found("项目不存在")
        self._check_writable(db, project, user)
        return iface

    def _get_module_or_404(self, db: Session, module_id: int, user: User) -> ApiModule:
        """获取`module`或。"""
        mod = db.get(ApiModule, module_id)
        if mod is None:
            raise not_found("模块不存在")
        project = db.get(Project, mod.project_id)
        if project is None or not has_project_role(
            project_role_for(db, project, user), PROJECT_ROLE_VIEWER
        ):
            raise not_found("模块不存在")
        return mod

    def _get_writable_module_or_404(self, db: Session, module_id: int, user: User) -> ApiModule:
        """获取可写`module`或。"""
        mod = self._get_module_or_404(db, module_id, user)
        project = db.get(Project, mod.project_id)
        if project is None:
            raise not_found("项目不存在")
        self._check_writable(db, project, user)
        return mod

    # ---------------------------------------------------------------- 变更记录

    def _write_change_log(
        self,
        db: Session,
        iface: ApiInterface,
        change_type: str,
        *,
        diff_json: dict | None = None,
        source_hash_before: str | None = None,
        source_hash_after: str | None = None,
        summary: str | None = None,
        actor: User,
    ) -> None:
        """写入`change``log`。"""
        log = ApiChangeLog(
            interface_id=iface.id,
            change_type=change_type,
            diff_json=diff_json,
            source_hash_before=source_hash_before,
            source_hash_after=source_hash_after,
            summary=summary,
            created_by=actor.id,
        )
        db.add(log)
        db.flush()

    def _recompute_hash_and_log(
        self,
        db: Session,
        iface: ApiInterface,
        *,
        change_type: str,
        summary: str,
        actor: User,
    ) -> str:
        """重算 source_hash；若变化则写 change_log，返回新 hash。"""
        before = iface.source_hash
        params = _load_params(db, iface.id)
        body = _load_body(db, iface.id)
        responses = _load_responses(db, iface.id)
        schema = interface_to_internal_schema(iface, params, body, responses)
        after = compute_source_hash(schema)
        if before != after:
            self._write_change_log(
                db, iface, change_type,
                diff_json={"before": before, "after": after},
                source_hash_before=before,
                source_hash_after=after,
                summary=summary,
                actor=actor,
            )
            iface.source_hash = after
        return after

    # ---------------------------------------------------------------- 模块

    def list_modules(self, db: Session, project_id: int, user: User) -> list[ApiModuleResponse]:
        """列出`modules`。"""
        self._get_project_or_404(db, project_id, user)
        # 确保未分类存在，前端树始终能展示。读端点必须提交，否则 get_db 关闭会话时
        # 仅 flush 的默认模块会被回滚，导致后续按 id 访问模块找不到（404）。
        _resolver.ensure_default_module(db, project_id)
        db.flush()
        db.commit()
        modules = (
            db.query(ApiModule)
            .filter(ApiModule.project_id == project_id)
            .order_by(ApiModule.sort.asc(), ApiModule.id.asc())
            .all()
        )
        counts = _module_interface_counts(db, project_id)
        return [_module_response(m, counts.get(m.id, 0)) for m in modules]

    def create_module(
        self, db: Session, project_id: int, body: ApiModuleCreate, *, actor: User
    ) -> ApiModuleResponse:
        """创建`module`。"""
        project = self._get_project_or_404(db, project_id, actor)
        self._check_writable(db, project, actor)
        name = (body.name or "").strip()
        if not name:
            raise bad_request("模块名不能为空")
        if name == DEFAULT_MODULE_NAME:
            # 「未分类」由 ensure_default_module 独占维护（按 is_default=True 查找，不看名字）。
            # 这里若允许手工建同名模块，后续 ensure_default_module 再插入 is_default 行就会撞
            # uq_api_module_project_name 唯一约束 → 500，且整个项目从此无法再建接口。
            raise bad_request(f"「{DEFAULT_MODULE_NAME}」是系统保留模块名，不能手工创建")
        _ensure_unique_module_name(db, project_id, name)
        parent = self._resolve_parent_for_create(db, project, body.parent_id)
        mod = ApiModule(
            project_id=project_id,
            name=name,
            parent_id=parent.id if parent else None,
            sort=body.sort or 0,
            is_default=False,
        )
        db.add(mod)
        db.flush()
        db.commit()
        db.refresh(mod)
        return _module_response(mod, 0)

    def update_module(
        self, db: Session, module_id: int, body: ApiModuleUpdate, *, actor: User
    ) -> ApiModuleResponse:
        """更新`module`。"""
        mod = self._get_writable_module_or_404(db, module_id, actor)
        data = body.model_dump(exclude_unset=True)
        if "name" in data and data["name"] is not None:
            new_name = data["name"].strip()
            if not new_name:
                raise bad_request("模块名不能为空")
            if mod.is_default and new_name != DEFAULT_MODULE_NAME:
                raise bad_request("未分类模块不可改名")
            if new_name != mod.name:
                _ensure_unique_module_name(db, mod.project_id, new_name, exclude_id=mod.id)
                mod.name = new_name
        if "sort" in data and data["sort"] is not None:
            mod.sort = data["sort"]
        db.flush()
        db.commit()
        db.refresh(mod)
        counts = _module_interface_counts(db, mod.project_id)
        return _module_response(mod, counts.get(mod.id, 0))

    def move_module(
        self, db: Session, module_id: int, body: ApiModuleMove, *, actor: User
    ) -> ApiModuleResponse:
        """移动模块。"""
        mod = self._get_writable_module_or_404(db, module_id, actor)
        if mod.is_default:
            raise bad_request("未分类模块不可移动")
        # 模块最多两级：带子模块的模块再挂到别的父下会产生第三级。
        if body.parent_id is not None:
            has_children = (
                db.query(ApiModule.id)
                .filter(ApiModule.parent_id == mod.id)
                .first()
                is not None
            )
            if has_children:
                raise bad_request("该模块有子模块，不能移动到另一个模块下；请先移动或删除子模块，或挂回根（parent_id=null）")
        parent = self._resolve_parent_for_create(db, db.get(Project, mod.project_id), body.parent_id)
        # 不能把自己挂到自己（或后代）下。
        new_parent_id = parent.id if parent else None
        if new_parent_id == mod.id:
            raise bad_request("不能将模块挂到自身下")
        if new_parent_id is not None:
            # 简单环检测：新父不能是本模块的后代。
            walker = db.get(ApiModule, new_parent_id)
            while walker is not None and walker.parent_id is not None:
                if walker.parent_id == mod.id:
                    raise bad_request("不能将模块挂到自身后代下")
                walker = db.get(ApiModule, walker.parent_id)
        mod.parent_id = new_parent_id
        db.flush()
        db.commit()
        db.refresh(mod)
        counts = _module_interface_counts(db, mod.project_id)
        return _module_response(mod, counts.get(mod.id, 0))

    def delete_module(self, db: Session, module_id: int, *, actor: User) -> None:
        """删除`module`。"""
        mod = self._get_writable_module_or_404(db, module_id, actor)
        if mod.is_default:
            raise bad_request("未分类模块不可删除")
        children = (
            db.query(ApiModule)
            .filter(ApiModule.parent_id == mod.id)
            .count()
        )
        if children:
            raise bad_request("请先删除或移动子模块")
        # 子接口归入未分类。
        default = _resolver.ensure_default_module(db, mod.project_id)
        db.flush()
        db.query(ApiInterface).filter(ApiInterface.module_id == mod.id).update(
            {ApiInterface.module_id: default.id}
        )
        db.delete(mod)
        db.commit()

    def _resolve_parent_for_create(
        self, db: Session, project: Project, parent_id: int | None
    ) -> ApiModule | None:
        """校验父模块：必须属于本项目、非未分类、且为一级（其 parent 为 None）。"""
        if parent_id is None:
            return None
        parent = db.get(ApiModule, parent_id)
        if parent is None or parent.project_id != project.id:
            raise bad_request("父模块不存在或不属于当前项目")
        if parent.is_default:
            raise bad_request("未分类模块不能作为父模块")
        if parent.parent_id is not None:
            raise bad_request("模块最多两级，不能嵌套到第三级")
        return parent

    # ---------------------------------------------------------------- 接口

    def list_interfaces(
        self,
        db: Session,
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
        self._get_project_or_404(db, project_id, user)
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
        module_map = _module_name_map(db, [i.module_id for i in items if i.module_id])
        return ApiInterfaceListResponse(
            items=[_interface_response(i, module_map) for i in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def create_interface(
        self, db: Session, project_id: int, body: ApiInterfaceCreate, *, actor: User
    ) -> ApiInterfaceDetailResponse:
        """创建接口。"""
        project = self._get_project_or_404(db, project_id, actor)
        self._check_writable(db, project, actor)
        if body.method.upper() not in HTTP_METHODS:
            raise bad_request("HTTP 方法取值非法")
        module_id = self._resolve_module_for_interface(db, project_id, body.module_id)
        _ensure_unique_interface(db, project_id, body.method, body.path)
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
        _replace_params(db, iface.id, body.parameters)
        _replace_body(db, iface.id, body.body)
        _replace_responses(db, iface.id, body.responses)
        # 计算 source_hash 并写创建日志。
        params = _load_params(db, iface.id)
        body_obj = _load_body(db, iface.id)
        responses = _load_responses(db, iface.id)
        schema = interface_to_internal_schema(iface, params, body_obj, responses)
        iface.source_hash = compute_source_hash(schema)
        self._write_change_log(
            db, iface, "CREATED",
            source_hash_after=iface.source_hash,
            summary=f"创建接口 {iface.method} {iface.path}",
            actor=actor,
        )
        db.commit()
        db.refresh(iface)
        return _detail_response(db, iface)

    def get_interface(self, db: Session, api_id: int, user: User) -> ApiInterfaceDetailResponse:
        """获取接口。"""
        iface = self._get_interface_or_404(db, api_id, user)
        return _detail_response(db, iface)

    def update_interface(
        self, db: Session, api_id: int, body: ApiInterfaceUpdate, *, actor: User
    ) -> ApiInterfaceDetailResponse:
        """更新接口。"""
        iface = self._get_writable_interface_or_404(db, api_id, actor)
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
            _ensure_unique_interface(db, iface.project_id, new_method, new_path, exclude_id=iface.id)
        module_changed = False
        for field, value in data.items():
            if field == "module_id":
                module_changed = value != iface.module_id
                iface.module_id = self._resolve_module_for_interface(db, iface.project_id, value)
                continue
            if field in {"method", "path", "auth_type", "content_type"} and value is not None:
                if getattr(iface, field) != value:
                    structural = True
            setattr(iface, field, value)
        db.flush()
        # 结构字段变更 → 重算 hash + UPDATED 日志；模块移动单独记 MODULE_CHANGED。
        if structural:
            self._recompute_hash_and_log(
                db, iface, change_type="UPDATED",
                summary=f"更新接口 {iface.method} {iface.path}", actor=actor,
            )
        if module_changed:
            self._write_change_log(
                db, iface, "MODULE_CHANGED",
                diff_json={"module_id": data.get("module_id")},
                summary="移动接口到其他模块", actor=actor,
            )
        db.commit()
        db.refresh(iface)
        return _detail_response(db, iface)

    def move_interface(
        self, db: Session, api_id: int, body, *, actor: User
    ) -> ApiInterfaceDetailResponse:
        """移动接口。"""
        iface = self._get_writable_interface_or_404(db, api_id, actor)
        new_module_id = self._resolve_module_for_interface(db, iface.project_id, body.module_id)
        if new_module_id != iface.module_id:
            iface.module_id = new_module_id
            self._write_change_log(
                db, iface, "MODULE_CHANGED",
                diff_json={"module_id": new_module_id},
                summary="移动接口到其他模块", actor=actor,
            )
        db.flush()
        db.commit()
        db.refresh(iface)
        return _detail_response(db, iface)

    def delete_interface(self, db: Session, api_id: int, *, actor: User) -> None:
        """删除接口。"""
        iface = self._get_writable_interface_or_404(db, api_id, actor)
        db.delete(iface)
        db.commit()

    def _resolve_module_for_interface(
        self, db: Session, project_id: int, module_id: int | None
    ) -> int:
        """接口的 module_id：None 或不属于本项目 → 未分类。"""
        if module_id is None:
            return _resolver.ensure_default_module(db, project_id).id
        mod = db.get(ApiModule, module_id)
        if mod is None or mod.project_id != project_id:
            return _resolver.ensure_default_module(db, project_id).id
        return mod.id

    # ---------------------------------------------------------------- 请求参数/body

    def get_request(self, db: Session, api_id: int, user: User) -> ApiRequestBundleResponse:
        """获取请求。"""
        iface = self._get_interface_or_404(db, api_id, user)
        params = _load_params(db, iface.id)
        body = _load_body(db, iface.id)
        return ApiRequestBundleResponse(
            parameters=[_param_response(p) for p in params],
            body=_body_response(body, iface.id) if body else None,
        )

    def save_request(
        self, db: Session, api_id: int, body: ApiRequestBundle, *, actor: User
    ) -> ApiRequestBundleResponse:
        """保存请求。"""
        iface = self._get_writable_interface_or_404(db, api_id, actor)
        old_params = _load_params(db, iface.id)
        old_body = _load_body(db, iface.id)
        _replace_params(db, iface.id, body.parameters)
        _replace_body(db, iface.id, body.body)
        diff = _diff_params(old_params, body.parameters) | _diff_body(old_body, body.body)
        if diff:
            self._write_change_log(
                db, iface, "UPDATED",
                diff_json={"request": diff},
                summary="替换请求参数/请求体", actor=actor,
            )
        self._recompute_hash_and_log(
            db, iface, change_type="UPDATED",
            summary="请求结构变更导致 source_hash 更新", actor=actor,
        )
        db.commit()
        return self.get_request(db, api_id, actor)  # 复用读路径构造响应

    # ---------------------------------------------------------------- 响应

    def get_responses(self, db: Session, api_id: int, user: User) -> ApiResponsesBundleResponse:
        """获取`responses`。"""
        iface = self._get_interface_or_404(db, api_id, user)
        responses = _load_responses(db, iface.id)
        return ApiResponsesBundleResponse(
            responses=[_response_response(r) for r in responses]
        )

    def save_responses(
        self, db: Session, api_id: int, body: ApiResponsesBundle, *, actor: User
    ) -> ApiResponsesBundleResponse:
        """保存`responses`。"""
        iface = self._get_writable_interface_or_404(db, api_id, actor)
        old_responses = _load_responses(db, iface.id)
        _replace_responses(db, iface.id, body.responses)
        diff = _diff_responses(old_responses, body.responses)
        if diff:
            self._write_change_log(
                db, iface, "RESPONSE_CHANGED",
                diff_json={"responses": diff},
                summary="替换响应结构", actor=actor,
            )
        self._recompute_hash_and_log(
            db, iface, change_type="RESPONSE_CHANGED",
            summary="响应结构变更导致 source_hash 更新", actor=actor,
        )
        db.commit()
        return self.get_responses(db, api_id, actor)

    # ---------------------------------------------------------------- 关联

    def list_relations(self, db: Session, api_id: int, user: User) -> list[ApiRelationResponse]:
        """列出`relations`。"""
        iface = self._get_interface_or_404(db, api_id, user)
        rels = (
            db.query(ApiRelation)
            .filter(
                (ApiRelation.source_api_id == iface.id) | (ApiRelation.target_api_id == iface.id)
            )
            .order_by(ApiRelation.id.asc())
            .all()
        )
        names = _interface_name_map(db, [r.source_api_id for r in rels] + [r.target_api_id for r in rels])
        return [_relation_response(r, names) for r in rels]

    def create_relation(
        self, db: Session, api_id: int, body: ApiRelationCreate, *, actor: User
    ) -> ApiRelationResponse:
        """创建`relation`。"""
        iface = self._get_writable_interface_or_404(db, api_id, actor)
        if body.source_api_id != iface.id and body.target_api_id != iface.id:
            raise bad_request("关联必须涉及当前接口")
        source = db.get(ApiInterface, body.source_api_id)
        target = db.get(ApiInterface, body.target_api_id)
        if source is None or target is None:
            raise not_found("关联接口不存在")
        if source.project_id != iface.project_id or target.project_id != iface.project_id:
            raise bad_request("关联接口必须属于同一项目")
        if body.source_api_id == body.target_api_id:
            raise bad_request("不能关联接口自身")
        existing = (
            db.query(ApiRelation)
            .filter(
                ApiRelation.source_api_id == body.source_api_id,
                ApiRelation.target_api_id == body.target_api_id,
                ApiRelation.relation_type == body.relation_type,
                ApiRelation.variable_name == body.variable_name,
            )
            .first()
        )
        if existing is not None:
            raise conflict("该关联已存在")
        rel = ApiRelation(
            project_id=iface.project_id,
            source_api_id=body.source_api_id,
            target_api_id=body.target_api_id,
            relation_type=body.relation_type,
            variable_name=body.variable_name,
            extract_path=body.extract_path,
        )
        db.add(rel)
        db.flush()
        db.commit()
        db.refresh(rel)
        names = _interface_name_map(db, [rel.source_api_id, rel.target_api_id])
        return _relation_response(rel, names)

    def delete_relation(self, db: Session, relation_id: int, *, actor: User) -> None:
        """删除`relation`。"""
        rel = db.get(ApiRelation, relation_id)
        if rel is None:
            raise not_found("关联不存在")
        project = db.get(Project, rel.project_id)
        if project is None or not has_project_role(
            project_role_for(db, project, actor), PROJECT_ROLE_MEMBER
        ):
            raise not_found("关联不存在")
        db.delete(rel)
        db.commit()

    # ---------------------------------------------------------------- 历史

    def list_history(
        self, db: Session, api_id: int, user: User, *, page: int = 1, page_size: int = 20
    ) -> tuple[list[ApiChangeLogResponse], int]:
        """列出`history`。"""
        iface = self._get_interface_or_404(db, api_id, user)
        query = db.query(ApiChangeLog).filter(ApiChangeLog.interface_id == iface.id)
        total = int(query.count())
        items = (
            query.order_by(ApiChangeLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return [ApiChangeLogResponse.model_validate(i) for i in items], total

    # ---------------------------------------------------------------- 导入记录

    def list_import_records(
        self, db: Session, project_id: int, user: User, *, page: int = 1, page_size: int = 20
    ) -> tuple[list, int]:
        """列出`import`记录。"""
        self._get_project_or_404(db, project_id, user)
        query = db.query(ApiImportRecord).filter(ApiImportRecord.project_id == project_id)
        total = int(query.count())
        items = (
            query.order_by(ApiImportRecord.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        from app.features.api_catalog.schemas import ApiImportRecordResponse

        return [ApiImportRecordResponse.model_validate(i) for i in items], total


# ----------------------------------------------------------------------------- 加载/替换/diff 辅助


def _load_params(db: Session, interface_id: int) -> list[ApiParameter]:
    """加载`params`。"""
    return (
        db.query(ApiParameter)
        .filter(ApiParameter.interface_id == interface_id)
        .order_by(ApiParameter.sort.asc(), ApiParameter.id.asc())
        .all()
    )


def _load_body(db: Session, interface_id: int) -> ApiRequestBody | None:
    """加载请求体。"""
    return (
        db.query(ApiRequestBody)
        .filter(ApiRequestBody.interface_id == interface_id)
        .one_or_none()
    )


def _load_responses(db: Session, interface_id: int) -> list[ApiResponse]:
    """加载`responses`。"""
    return (
        db.query(ApiResponse)
        .filter(ApiResponse.interface_id == interface_id)
        .order_by(ApiResponse.sort.asc(), ApiResponse.id.asc())
        .all()
    )


def _replace_params(db: Session, interface_id: int, params: list[ApiParameterIn]) -> None:
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


def _replace_body(db: Session, interface_id: int, body: ApiBodyIn) -> None:
    """替换请求体。"""
    existing = _load_body(db, interface_id)
    if existing is None:
        existing = ApiRequestBody(interface_id=interface_id)
        db.add(existing)
    existing.body_type = body.body_type
    existing.content_type = body.content_type
    existing.schema_json = body.schema_json
    existing.raw_text = body.raw_text
    db.flush()


def _replace_responses(db: Session, interface_id: int, responses: list[ApiResponseIn]) -> None:
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


def _diff_params(old: list[ApiParameter], new: list[ApiParameterIn]) -> dict:
    """计算 API 参数定义之间的差异。"""
    old_keys = {p.name: (p.type, bool(p.required)) for p in old}
    new_keys = {p.name: (p.type or "string", bool(p.required)) for p in new}
    added = [n for n in new_keys if n not in old_keys]
    removed = [n for n in old_keys if n not in new_keys]
    changed = []
    for n in new_keys:
        if n in old_keys and old_keys[n] != new_keys[n]:
            changed.append(n)
    if not (added or removed or changed):
        return {}
    return {"params": {"added": added, "removed": removed, "changed": changed}}


def _diff_body(old: ApiRequestBody | None, new: ApiBodyIn) -> dict:
    """计算 API 请求体定义之间的差异。"""
    if old is None:
        return {} if new.body_type == "none" else {"body": "added"}
    if (old.body_type, old.content_type) != (new.body_type, new.content_type):
        return {"body": {"before": old.body_type, "after": new.body_type}}
    return {}


def _diff_responses(old: list[ApiResponse], new: list[ApiResponseIn]) -> dict:
    """计算 API 响应定义之间的差异。"""
    old_codes = {r.status_code for r in old}
    new_codes = {r.status_code for r in new}
    added = sorted(c for c in new_codes if c not in old_codes)
    removed = sorted(c for c in old_codes if c not in new_codes)
    if not (added or removed):
        return {}
    return {"status_codes": {"added": added, "removed": removed}}


# ----------------------------------------------------------------------------- 响应构造


def _module_response(mod: ApiModule, interface_count: int) -> ApiModuleResponse:
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


def _interface_response(iface: ApiInterface, module_map: dict[int, str]) -> ApiInterfaceResponse:
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


def _detail_response(db: Session, iface: ApiInterface) -> ApiInterfaceDetailResponse:
    """构造`detail`响应数据。"""
    params = _load_params(db, iface.id)
    body = _load_body(db, iface.id)
    responses = _load_responses(db, iface.id)
    module_map: dict[int, str] = {}
    if iface.module_id:
        mod = db.get(ApiModule, iface.module_id)
        if mod is not None:
            module_map[iface.module_id] = mod.name
    base = _interface_response(iface, module_map)
    return ApiInterfaceDetailResponse(
        **base.model_dump(),
        parameters=[_param_response(p) for p in params],
        body=_body_response(body, iface.id) if body else None,
        responses=[_response_response(r) for r in responses],
    )


def _param_response(p: ApiParameter) -> ApiParameterResponse:
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


def _body_response(b: ApiRequestBody | None, interface_id: int) -> ApiRequestBodyResponse:
    """构造请求体响应数据。"""
    return ApiRequestBodyResponse(
        id=b.id if b else None,
        interface_id=interface_id,
        body_type=(b.body_type if b else "none"),
        content_type=(b.content_type if b else None),
        schema_json=(b.schema_json if b else None),
        raw_text=(b.raw_text if b else None),
    )


def _response_response(r: ApiResponse) -> ApiResponseResponse:
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


def _relation_response(rel: ApiRelation, names: dict[int, str]) -> ApiRelationResponse:
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


# ----------------------------------------------------------------------------- 查询辅助


def _module_interface_counts(db: Session, project_id: int) -> dict[int, int]:
    """统计模块接口数量。"""
    rows = (
        db.query(ApiInterface.module_id, func.count(ApiInterface.id))
        .filter(ApiInterface.project_id == project_id)
        .group_by(ApiInterface.module_id)
        .all()
    )
    return {int(mid): int(cnt) for mid, cnt in rows if mid is not None}


def _module_name_map(db: Session, module_ids: list[int | None]) -> dict[int, str]:
    """构建模块名称映射表。"""
    ids = [i for i in module_ids if i is not None]
    if not ids:
        return {}
    rows = db.query(ApiModule.id, ApiModule.name).filter(ApiModule.id.in_(ids)).all()
    return {int(mid): name for mid, name in rows}


def _interface_name_map(db: Session, api_ids: list[int | None]) -> dict[int, str]:
    """构建接口名称映射表。"""
    ids = [i for i in api_ids if i is not None]
    if not ids:
        return {}
    rows = db.query(ApiInterface.id, ApiInterface.name).filter(ApiInterface.id.in_(ids)).all()
    return {int(aid): name for aid, name in rows}


def _ensure_unique_module_name(
    db: Session, project_id: int, name: str, *, exclude_id: int | None = None
) -> None:
    """确保`unique``module`名称。"""
    query = db.query(ApiModule).filter(
        ApiModule.project_id == project_id, ApiModule.name == name
    )
    if exclude_id is not None:
        query = query.filter(ApiModule.id != exclude_id)
    if query.first() is not None:
        raise conflict("模块名已存在")


def _ensure_unique_interface(
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
