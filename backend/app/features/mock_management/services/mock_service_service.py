"""MockService 服务层：CRUD + Runtime Token 生命周期（§四 / §五十）。

- service_key ``^[A-Z][A-Z0-9_]{0,99}$``，同项目唯一（409），跨项目 404。
- Runtime Token：创建 / 重置时生成明文，库中只存 sha256+salt 哈希；明文只在
  ``MockServiceCreateResponse`` 里返回一次。响应只暴露 ``runtime_token_set`` 布尔，
  绝不回显哈希（§五十）。
- 管理 MockService / 重置 Token 需 editor+（§三十四）。
- 删除：被 test_case_mock 引用时 409；否则级联删 endpoint / scenario / matcher。

service owns commit。
"""

from __future__ import annotations

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.mock_management.models import (
    MockService,
    TestCaseMock,
)
from app.features.mock_management.schemas import (
    SERVICE_KEY_PATTERN,
    MockServiceCreate,
    MockServiceCreateResponse,
    MockServiceListResponse,
    MockServiceUpdate,
)
from app.features.mock_management.services._access import (
    get_project_or_404,
    require_manage_project,
    resolve_service_project_id,
)
from app.features.mock_management.services._response import service_response
from app.features.mock_management.services.token_service import (
    generate_runtime_token,
    hash_token,
)
from app.models.identity import User
from app.shared.errors import conflict, not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE


def _raise_not_found(message: str = "Mock 服务不存在") -> None:
    """资源不存在或不可见时抛出 404 错误。"""
    raise not_found(message)


class MockServiceService:
    """MockService CRUD 服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 列表 / 详情

    def list_services(
        self, db: Session, project_id: int, user: User, *,
        keyword: str | None = None, enabled: bool | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> MockServiceListResponse:
        """列出`services`。"""
        get_project_or_404(db, project_id, user)
        page_size = max(1, min(page_size, MAX_PAGE_SIZE))
        q = db.query(MockService).filter(MockService.project_id == project_id)
        if enabled is not None:
            q = q.filter(MockService.enabled.is_(enabled))
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(
                or_(
                    MockService.name.ilike(f"%{kw}%"),
                    MockService.service_key.ilike(f"%{kw}%"),
                )
            )
        total = int(q.count())
        items = (
            q.order_by(MockService.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return MockServiceListResponse(
            items=[service_response(db, s) for s in items],
            total=total, page=page, page_size=page_size,
        )

    def get_service(self, db: Session, service_id: int, user: User):
        """获取服务。"""
        row = self._get_or_404(db, service_id, user)
        return service_response(db, row)

    # ---------------------------------------------------------------- 创建 / 删除

    def create_service(
        self, db: Session, project_id: int, body: MockServiceCreate, *, actor: User,
    ) -> MockServiceCreateResponse:
        """创建服务。"""
        project = require_manage_project(db, project_id, actor)
        key = (body.service_key or "").strip()
        if not re.fullmatch(SERVICE_KEY_PATTERN, key):
            raise conflict(f"service_key 必须匹配 {SERVICE_KEY_PATTERN}")
        name = (body.name or "").strip()
        if not name:
            raise conflict("服务名称不能为空")
        if (
            db.query(MockService)
            .filter(MockService.project_id == project.id, MockService.service_key == key)
            .first()
            is not None
        ):
            raise conflict("同项目下 service_key 已存在")

        # 明文 token：用户传入优先，否则自动生成；只存哈希。
        plaintext = (body.runtime_token or "").strip() or generate_runtime_token()
        token_hash = hash_token(plaintext)

        service = MockService(
            project_id=project.id,
            name=name,
            description=(body.description or "").strip() or None,
            service_key=key,
            base_path=(body.base_path or "").strip() or None,
            enabled=body.enabled,
            public_runtime=body.public_runtime,
            runtime_token_hash=token_hash,
            created_by=actor.id,
        )
        db.add(service)
        db.commit()
        db.refresh(service)
        # 明文 token 仅此一次性返回。
        return MockServiceCreateResponse(service=service_response(db, service), runtime_token=plaintext)

    def delete_service(self, db: Session, service_id: int, *, actor: User) -> None:
        """删除服务。"""
        service = self._get_writable_or_404(db, service_id, actor)
        ref_count = int(
            db.query(TestCaseMock.id).filter(TestCaseMock.mock_service_id == service.id).count()
        )
        if ref_count:
            raise conflict(f"该 Mock 服务正被 {ref_count} 条用例 Mock 依赖引用，请先在用例上移除")
        db.delete(service)
        db.commit()

    # ---------------------------------------------------------------- 更新 + 重置 Token

    def update_service(
        self, db: Session, service_id: int, body: MockServiceUpdate, *, actor: User,
    ):
        """更新服务。"""
        service = self._get_writable_or_404(db, service_id, actor)
        # 乐观锁：revision 不匹配 → 409。
        if body.revision != service.revision:
            raise conflict("该 Mock 服务已被他人修改，请刷新后重试")
        data = body.model_dump(exclude_unset=True)
        if not data:
            return service_response(db, service)

        if (name := data.get("name")) is not None:
            name = name.strip()
            if not name:
                raise conflict("服务名称不能为空")
            service.name = name
        if data.get("description") is not None:
            service.description = data["description"].strip() or None
        if data.get("base_path") is not None:
            service.base_path = data["base_path"].strip() or None
        if data.get("enabled") is not None:
            service.enabled = bool(data["enabled"])
        if data.get("public_runtime") is not None:
            service.public_runtime = bool(data["public_runtime"])
        if "default_scenario_id" in data:
            sid = data["default_scenario_id"]
            service.default_scenario_id = self._validate_default_scenario(db, service, sid)
        service.revision = (service.revision or 0) + 1
        db.commit()
        db.refresh(service)
        return service_response(db, service)

    def reset_token(self, db: Session, service_id: int, *, actor: User) -> MockServiceCreateResponse:
        """重置 Runtime Token：旧 token 立即失效，新明文只返回一次（§五十）。"""
        service = self._get_writable_or_404(db, service_id, actor)
        plaintext = generate_runtime_token()
        service.runtime_token_hash = hash_token(plaintext)
        service.revision = (service.revision or 0) + 1
        db.commit()
        db.refresh(service)
        return MockServiceCreateResponse(service=service_response(db, service), runtime_token=plaintext)

    # ---------------------------------------------------------------- 内部

    def _validate_default_scenario(
        self, db: Session, service: MockService, scenario_id: int | None,
    ) -> int | None:
        """服务级默认场景：软引用，校验归属本项目（不要求属于某个 endpoint）。"""
        if scenario_id is None:
            return None
        from app.features.mock_management.models import MockScenario

        scenario = db.get(MockScenario, scenario_id)
        if scenario is None or scenario.project_id != service.project_id:
            raise not_found(f"Mock 场景 {scenario_id} 不存在或不属于本项目")
        return scenario.id

    def _get_or_404(self, db: Session, service_id: int, user: User) -> MockService:
        """获取或。"""
        row = db.get(MockService, service_id)
        if row is None:
            _raise_not_found()
        get_project_or_404(db, row.project_id, user)
        return row

    def _get_writable_or_404(self, db: Session, service_id: int, actor: User) -> MockService:
        """获取可写或。"""
        row = db.get(MockService, service_id)
        if row is None:
            _raise_not_found()
        require_manage_project(db, resolve_service_project_id(db, service_id), actor)
        return row


__all__ = ["MockServiceService"]
