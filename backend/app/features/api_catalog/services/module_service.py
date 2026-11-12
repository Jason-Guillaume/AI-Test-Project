"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session
from sqlalchemy import or_
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule
from app.features.api_catalog.schemas import (
    ApiModuleCreate,
    ApiModuleMove,
    ApiModuleDeletePreview,
    ApiModuleDeleteResponse,
    ApiModuleResponse,
    ApiModuleUpdate,
)
from app.features.api_catalog.services.module_resolver import DEFAULT_MODULE_NAME, ModuleResolver
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.http.errors import bad_request, conflict, not_found
from app.platform.projects.services.access_service import check_writable
from app.platform.projects.services.access_service import get_project_or_404
from app.features.api_catalog.services.access_service import get_writable_module_or_404
from app.features.api_catalog.services.queries import module_interface_counts
from app.features.api_catalog.models.api_relation import ApiRelation
from app.features.api_catalog.services.response_mapper import module_response


def list_modules(db: Session, project_id: int, user: User) -> list[ApiModuleResponse]:
    """列出`modules`。"""
    get_project_or_404(db, project_id, user)
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
    counts = module_interface_counts(db, project_id)
    return [module_response(m, counts.get(m.id, 0)) for m in modules]


def create_module(db: Session, project_id: int, body: ApiModuleCreate, *, actor: User
) -> ApiModuleResponse:
    """创建`module`。"""
    project = get_project_or_404(db, project_id, actor)
    check_writable(db, project, actor)
    name = (body.name or "").strip()
    if not name:
        raise bad_request("模块名不能为空")
    if name == DEFAULT_MODULE_NAME:
        # 「未分类」由 ensure_default_module 独占维护（按 is_default=True 查找，不看名字）。
        # 这里若允许手工建同名模块，后续 ensure_default_module 再插入 is_default 行就会撞
        # uq_api_module_project_name 唯一约束 → 500，且整个项目从此无法再建接口。
        raise bad_request(f"「{DEFAULT_MODULE_NAME}」是系统保留模块名，不能手工创建")
    ensure_unique_module_name(db, project_id, name)
    parent = resolve_parent_for_create(db, project, body.parent_id)
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
    return module_response(mod, 0)


def update_module(db: Session, module_id: int, body: ApiModuleUpdate, *, actor: User
) -> ApiModuleResponse:
    """更新`module`。"""
    mod = get_writable_module_or_404(db, module_id, actor)
    data = body.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        new_name = data["name"].strip()
        if not new_name:
            raise bad_request("模块名不能为空")
        if mod.is_default and new_name != DEFAULT_MODULE_NAME:
            raise bad_request("未分类模块不可改名")
        if new_name != mod.name:
            ensure_unique_module_name(db, mod.project_id, new_name, exclude_id=mod.id)
            mod.name = new_name
    if "sort" in data and data["sort"] is not None:
        mod.sort = data["sort"]
    db.flush()
    db.commit()
    db.refresh(mod)
    counts = module_interface_counts(db, mod.project_id)
    return module_response(mod, counts.get(mod.id, 0))


def move_module(db: Session, module_id: int, body: ApiModuleMove, *, actor: User
) -> ApiModuleResponse:
    """移动模块。"""
    mod = get_writable_module_or_404(db, module_id, actor)
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
    parent = resolve_parent_for_create(db, db.get(Project, mod.project_id), body.parent_id)
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
    counts = module_interface_counts(db, mod.project_id)
    return module_response(mod, counts.get(mod.id, 0))


def _module_delete_plan(
    db: Session, project_id: int, module_ids: list[int], *, actor: User,
) -> tuple[list[ApiModule], list[ApiModule], list[int]]:
    if not module_ids:
        raise bad_request("请至少选择一个模块")
    project = get_project_or_404(db, project_id, actor)
    check_writable(db, project, actor)
    modules = db.query(ApiModule).filter(ApiModule.project_id == project_id).all()
    by_id = {module.id: module for module in modules}
    selected = list(dict.fromkeys(module_ids))
    if any(module_id not in by_id for module_id in selected):
        raise not_found("模块不存在或不属于当前项目")
    if any(by_id[module_id].is_default for module_id in selected):
        raise bad_request("未分类模块不可删除")
    selected_set = set(selected)
    roots = [by_id[module_id] for module_id in selected if not _has_selected_ancestor(by_id[module_id], selected_set, by_id)]
    children: dict[int | None, list[ApiModule]] = {}
    for module in modules:
        children.setdefault(module.parent_id, []).append(module)
    target_ids: set[int] = set()
    stack = [module.id for module in roots]
    while stack:
        current = stack.pop()
        if current in target_ids:
            continue
        target_ids.add(current)
        stack.extend(child.id for child in children.get(current, []))
    targets = [by_id[module_id] for module_id in target_ids]
    interface_ids = [int(row[0]) for row in db.query(ApiInterface.id).filter(
        ApiInterface.project_id == project_id, ApiInterface.module_id.in_(target_ids),
    ).all()]
    targets.sort(key=lambda module: (-_module_depth(module, by_id), module.id))
    return roots, targets, interface_ids


def _has_selected_ancestor(module: ApiModule, selected: set[int], by_id: dict[int, ApiModule]) -> bool:
    parent_id = module.parent_id
    while parent_id is not None:
        if parent_id in selected:
            return True
        parent = by_id.get(parent_id)
        parent_id = parent.parent_id if parent else None
    return False


def _module_depth(module: ApiModule, by_id: dict[int, ApiModule]) -> int:
    depth = 0
    parent_id = module.parent_id
    while parent_id is not None:
        depth += 1
        parent = by_id.get(parent_id)
        parent_id = parent.parent_id if parent else None
    return depth


def preview_module_delete(
    db: Session, project_id: int, module_ids: list[int], *, actor: User,
) -> ApiModuleDeletePreview:
    roots, modules, interfaces = _module_delete_plan(db, project_id, module_ids, actor=actor)
    return ApiModuleDeletePreview(
        project_id=project_id, root_names=[module.name for module in roots],
        module_count=len(modules), interface_count=len(interfaces),
    )


def delete_modules(
    db: Session, project_id: int, module_ids: list[int], *, actor: User,
) -> ApiModuleDeleteResponse:
    """移除整棵选中模块子树；关联、接口与模块在同一回收站事务内提交。"""
    from app.lifecycle.service import soft_delete_object

    try:
        roots, modules, interface_ids = _module_delete_plan(db, project_id, module_ids, actor=actor)
        interfaces = db.query(ApiInterface).filter(
            ApiInterface.project_id == project_id, ApiInterface.id.in_(interface_ids),
        ).with_for_update().all() if interface_ids else []
        relations = db.query(ApiRelation).filter(or_(
            ApiRelation.source_api_id.in_(interface_ids), ApiRelation.target_api_id.in_(interface_ids),
        ), ApiRelation.project_id == project_id).with_for_update().all() if interface_ids else []
        batch_id = str(uuid4())
        receipt_ids: list[int] = []
        for row in relations:
            receipt_ids.append(soft_delete_object(
                db, "api_relation", row, actor=actor, reason="删除接口模块子树", batch_id=batch_id,
            ).id)
        for row in interfaces:
            receipt_ids.append(soft_delete_object(
                db, "api_interface", row, actor=actor, reason="删除接口模块子树", batch_id=batch_id,
            ).id)
        module_rows = db.query(ApiModule).filter(ApiModule.id.in_([module.id for module in modules])).with_for_update().all()
        module_rows.sort(key=lambda row: (-_module_depth(row, {m.id: m for m in modules}), row.id))
        for row in module_rows:
            receipt_ids.append(soft_delete_object(
                db, "api_module", row, actor=actor, reason="删除接口模块子树", batch_id=batch_id,
            ).id)
        db.commit()
        return ApiModuleDeleteResponse(
            project_id=project_id, root_names=[module.name for module in roots],
            module_count=len(modules), interface_count=len(interfaces),
            deleted_module_ids=[module.id for module in modules],
            deleted_interface_ids=[row.id for row in interfaces], recycle_bin_item_ids=receipt_ids,
        )
    except Exception:
        db.rollback()
        raise


def delete_module(db: Session, module_id: int, *, actor: User) -> ApiModuleDeleteResponse:
    module = get_writable_module_or_404(db, module_id, actor)
    return delete_modules(db, module.project_id, [module_id], actor=actor)


def resolve_parent_for_create(db: Session, project: Project, parent_id: int | None
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


def resolve_module_for_interface(db: Session, project_id: int, module_id: int | None
) -> int:
    """接口的 module_id：None 或不属于本项目 → 未分类。"""
    if module_id is None:
        return _resolver.ensure_default_module(db, project_id).id
    mod = db.get(ApiModule, module_id)
    if mod is None or mod.project_id != project_id:
        return _resolver.ensure_default_module(db, project_id).id
    return mod.id


_resolver = ModuleResolver()


def ensure_unique_module_name(
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
