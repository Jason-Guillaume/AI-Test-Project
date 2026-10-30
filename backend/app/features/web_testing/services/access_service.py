"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.http.errors import not_found


def get_row(db, model, row_id, actor, *, write=False):
    """按资源归属判权限；跨项目和不存在均返回 404。"""
    row = db.get(model, row_id)
    if row is None:
        raise not_found("Web 资源不存在")
    project_id = row.project_id
    (require_writable_project if write else get_project_or_404)(db, project_id, actor)
    return row
