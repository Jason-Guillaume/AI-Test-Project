"""MockEndpoint 服务层：CRUD（§五 / §六）。

- (mock_service_id, method, path) 唯一（409）。
- api_id 可空关联 API Catalog（仅关联不复制定义）：归属校验，跨项目引用显示 404。
- 路径校验：非空，支持 ``{param}``（path_matcher 只认固定段 + 单段 {param}）。
- 删除：被 test_case_mock 引用时 409；否则级联删 scenario / matcher。

service owns commit。
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.mocking.models import (
    MockEndpoint,
    MockService,
    TestCaseMock,
)
from app.features.mocking.schemas import (
    MockEndpointCreate,
    MockEndpointListResponse,
    MockEndpointResponse,
    MockEndpointUpdate,
)
from app.features.mocking.services.access_service import resolve_endpoint_project_id, resolve_service_project_id
from app.platform.projects.services.access_service import get_project_or_404
from app.features.mocking.services._response import endpoint_response
from app.core.models.identity import User
from app.core.http.errors import bad_request, conflict, not_found
from app.core.http.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def _raise_not_found(message: str = "Mock 接口不存在") -> None:
    """资源不存在或不可见时抛出 404 错误。"""
    raise not_found(message)


class MockEndpointService:
    """MockEndpoint CRUD 服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 列表 / 详情

    def list_endpoints(
        self, db: Session, service_id: int, user: User, *,
        keyword: str | None = None, enabled: bool | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MockEndpointListResponse:
        """列出`endpoints`。"""
        service = self._get_service_or_404(db, service_id, user)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(MockEndpoint).filter(MockEndpoint.mock_service_id == service.id)
        if enabled is not None:
            q = q.filter(MockEndpoint.enabled.is_(enabled))
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(
                or_(
                    MockEndpoint.name.ilike(f"%{kw}%"),
                    MockEndpoint.path.ilike(f"%{kw}%"),
                )
            )
        total = int(q.count())
        items = (
            q.order_by(MockEndpoint.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return MockEndpointListResponse(
            items=[endpoint_response(db, e) for e in items],
            total=total, page=page, page_size=page_size,
        )

    def get_endpoint(self, db: Session, endpoint_id: int, user: User) -> MockEndpointResponse:
        """获取接口。"""
        row = self._get_or_404(db, endpoint_id, user)
        return endpoint_response(db, row)

    # ---------------------------------------------------------------- 创建 / 删除

    def create_endpoint(
        self, db: Session, service_id: int, body: MockEndpointCreate, *, actor: User,
    ) -> MockEndpointResponse:
        """创建接口。"""
        service = self._get_service_writable(db, service_id, actor)
        method = (body.method or "").strip().upper()
        if not method:
            raise bad_request("HTTP 方法不能为空")
        path = (body.path or "").strip()
        if not path:
            raise bad_request("路径不能为空")
        if not path.startswith("/"):
            path = "/" + path
        name = (body.name or "").strip()
        if not name:
            raise bad_request("接口名称不能为空")

        if (
            db.query(MockEndpoint)
            .filter(
                MockEndpoint.mock_service_id == service.id,
                MockEndpoint.method == method,
                MockEndpoint.path == path,
            )
            .first()
            is not None
        ):
            raise conflict("同服务下 method + path 已存在")

        # api_id 归属校验：跨项目引用显示 404。
        api_id = body.api_id
        if api_id is not None:
            iface = db.get(ApiInterface, api_id)
            if iface is None or iface.project_id != service.project_id:
                raise not_found("关联接口不存在或不属于本项目")

        endpoint = MockEndpoint(
            project_id=service.project_id,
            mock_service_id=service.id,
            api_id=api_id,
            name=name,
            method=method,
            path=path,
            description=(body.description or "").strip() or None,
            enabled=body.enabled,
        )
        db.add(endpoint)
        db.commit()
        db.refresh(endpoint)
        return endpoint_response(db, endpoint)

    def delete_endpoint(self, db: Session, endpoint_id: int, *, actor: User) -> None:
        """删除接口。"""
        endpoint = self._get_writable_or_404(db, endpoint_id, actor)
        ref_count = int(
            db.query(TestCaseMock.id).filter(TestCaseMock.mock_endpoint_id == endpoint.id).count()
        )
        if ref_count:
            raise conflict(f"该 Mock 接口正被 {ref_count} 条用例 Mock 依赖引用，请先在用例上移除")
        db.delete(endpoint)
        db.commit()

    # ---------------------------------------------------------------- 更新

    def update_endpoint(
        self, db: Session, endpoint_id: int, body: MockEndpointUpdate, *, actor: User,
    ) -> MockEndpointResponse:
        """更新接口。"""
        endpoint = self._get_writable_or_404(db, endpoint_id, actor)
        if body.revision != endpoint.revision:
            raise conflict("该 Mock 接口已被他人修改，请刷新后重试")
        data = body.model_dump(exclude_unset=True)
        if not data:
            return endpoint_response(db, endpoint)

        if (name := data.get("name")) is not None:
            name = name.strip()
            if not name:
                raise bad_request("接口名称不能为空")
            endpoint.name = name
        if (method := data.get("method")) is not None:
            method = method.strip().upper()
            if not method:
                raise bad_request("HTTP 方法不能为空")
            endpoint.method = method
        if (path := data.get("path")) is not None:
            path = path.strip()
            if not path:
                raise bad_request("路径不能为空")
            if not path.startswith("/"):
                path = "/" + path
            endpoint.path = path
        if data.get("description") is not None:
            endpoint.description = data["description"].strip() or None
        if data.get("enabled") is not None:
            endpoint.enabled = bool(data["enabled"])

        # method/path 变更后重新校验唯一。
        if "method" in data or "path" in data:
            clash = (
                db.query(MockEndpoint)
                .filter(
                    MockEndpoint.mock_service_id == endpoint.mock_service_id,
                    MockEndpoint.method == endpoint.method,
                    MockEndpoint.path == endpoint.path,
                    MockEndpoint.id != endpoint.id,
                )
                .first()
            )
            if clash is not None:
                raise conflict("同服务下 method + path 已存在")

        endpoint.revision = (endpoint.revision or 0) + 1
        db.commit()
        db.refresh(endpoint)
        return endpoint_response(db, endpoint)

    # ---------------------------------------------------------------- 内部

    def _get_service_or_404(self, db: Session, service_id: int, user: User) -> MockService:
        """获取服务或。"""
        service = db.get(MockService, service_id)
        if service is None:
            raise not_found("Mock 服务不存在")
        get_project_or_404(db, service.project_id, user)
        return service

    def _get_service_writable(self, db: Session, service_id: int, actor: User) -> MockService:
        """获取服务可写。"""
        from app.platform.projects.services.access_service import require_writable_project

        service = db.get(MockService, service_id)
        if service is None:
            raise not_found("Mock 服务不存在")
        require_writable_project(db, resolve_service_project_id(db, service_id), actor)
        return service

    def _get_or_404(self, db: Session, endpoint_id: int, user: User) -> MockEndpoint:
        """获取或。"""
        row = db.get(MockEndpoint, endpoint_id)
        if row is None:
            _raise_not_found()
        get_project_or_404(db, row.project_id, user)
        return row

    def _get_writable_or_404(self, db: Session, endpoint_id: int, actor: User) -> MockEndpoint:
        """获取可写或。"""
        from app.platform.projects.services.access_service import require_writable_project

        row = db.get(MockEndpoint, endpoint_id)
        if row is None:
            _raise_not_found()
        require_writable_project(db, resolve_endpoint_project_id(db, endpoint_id), actor)
        return row


__all__ = ["MockEndpointService"]
