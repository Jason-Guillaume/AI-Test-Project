"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session
from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.models.api_module import ApiModule


def module_interface_counts(db: Session, project_id: int) -> dict[int, int]:
    """统计模块接口数量。"""
    rows = (
        db.query(ApiInterface.module_id, func.count(ApiInterface.id))
        .filter(ApiInterface.project_id == project_id)
        .group_by(ApiInterface.module_id)
        .all()
    )
    return {int(mid): int(cnt) for mid, cnt in rows if mid is not None}


def module_name_map(db: Session, module_ids: list[int | None]) -> dict[int, str]:
    """构建模块名称映射表。"""
    ids = [i for i in module_ids if i is not None]
    if not ids:
        return {}
    rows = db.query(ApiModule.id, ApiModule.name).filter(ApiModule.id.in_(ids)).all()
    return {int(mid): name for mid, name in rows}


def interface_name_map(db: Session, api_ids: list[int | None]) -> dict[int, str]:
    """构建接口名称映射表。"""
    ids = [i for i in api_ids if i is not None]
    if not ids:
        return {}
    rows = db.query(ApiInterface.id, ApiInterface.name).filter(ApiInterface.id.in_(ids)).all()
    return {int(aid): name for aid, name in rows}
