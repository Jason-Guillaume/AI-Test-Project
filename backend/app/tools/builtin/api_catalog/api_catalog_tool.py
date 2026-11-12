"""Agent Tool 层：接口目录检索（§32 只读）。

复用 `ApiService`，不新增 Api Catalog 公共方法。所有查询携带 project_id + user，
经 `get_project_or_404` 校验项目可见性（viewer+）；实体额外校验 `project_id` 归属，
跨项目访问统一 404（§33，隐藏资源存在性）。

返回 `dict`（`model_dump(mode="json")`）：节点可直接序列化进 prompt，datetime 自动
转 ISO 字符串，避免下游再做一次序列化。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.api_catalog.services.api_service import ApiService
from app.platform.projects.services.access_service import get_project_or_404
from app.core.models.identity import User
from app.core.http.errors import not_found


_API = ApiService()


def search_api(
    db: Session,
    project_id: int,
    user: User,
    *,
    keyword: str | None = None,
    method: str | None = None,
    page_size: int = 20,
) -> dict:
    """按关键词 / HTTP 方法检索接口候选（供 IntentNode 解析 target_ids）。

    返回 `{items, total, page, page_size}`；items 为接口概要（id/name/method/path），
    仅含 ID 级信息，不含请求体——细节由 `get_api` 按需拉取，避免整库灌入。
    """
    get_project_or_404(db, project_id, user)
    resp = _API.list_interfaces(
        db, project_id, user, keyword=keyword, method=method, page=1, page_size=page_size,
    )
    return resp.model_dump(mode="json")


def get_api(db: Session, api_id: int, user: User, *, project_id: int) -> dict:
    """取接口详情（含 parameters / body / responses / auth_type / status）。

    除可见性外额外校验 `api.project_id == project_id`：用户可能是多个项目的 viewer，
    仅校验「可见」不足以阻止把别的项目的接口细节泄漏进本会话上下文（§33）。
    """
    get_project_or_404(db, project_id, user)
    api = db.get(ApiInterface, api_id)
    if api is None or api.project_id != project_id:
        raise not_found("接口不存在")
    return _API.get_interface(db, api_id, user).model_dump(mode="json")


from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    'search_api': ('api_catalog.search_api', 'read'),
    'get_api': ('runtime.api_catalog.get_api', 'read'),
})
