"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from app.features.web_testing.models import PageObject
from app.features.web_testing.schemas import PageInput
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.http.errors import bad_request, conflict, not_found
from app.features.web_testing.services.access_service import get_row
from app.features.web_testing.services.response_mapper import list_result
from app.features.web_testing.services.response_mapper import page_response


def list_pages(db, project_id, actor, *, page=1, page_size=200):
    """读取当前项目页面对象。"""
    get_project_or_404(db, project_id, actor)
    return list_result(db.query(PageObject).filter_by(project_id=project_id).order_by(PageObject.id.desc()), page_response, page, page_size)


def save_page(db, project_id, body: PageInput, actor, page_id=None):
    """新增或按 revision 更新页面；所有引用该页面的旧确认自然失效。"""
    require_writable_project(db, project_id, actor)
    if page_id:
        row = get_row(db, PageObject, page_id, actor, write=True)
        if row.project_id != project_id:
            raise not_found("页面对象不存在")
        row = db.query(PageObject).filter_by(id=page_id).with_for_update().populate_existing().one()
        if body.revision != row.revision:
            raise conflict("页面已被修改，请刷新")
        row.revision += 1
    else:
        row = PageObject(project_id=project_id)
        db.add(row)
    row.name, row.path = body.name.strip(), body.path
    row.elements = [e.model_dump() for e in body.elements]
    if not row.name:
        raise bad_request("页面名称不能为空")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise conflict("项目内页面名称已存在") from exc
    return page_response(row)


def delete_page(db, page_id, actor):
    """删除页面，引用它的用例将显示未确认并在执行前失败。"""
    db.delete(get_row(db, PageObject, page_id, actor, write=True))
    db.commit()
