"""测试数据目录（TestDataAsset）服务层。

- 静态/池派生的既有数据条目登记，供 EXISTING_POOL Provider 与用例变量引用。
- value_json 在**读接口**统一经 SensitiveDataMasker.mask_body 脱敏后返回。
- 被 data_pool.asset_id 引用时不允许删除（409）。

service owns commit。
"""

from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.business.executors.sensitive import SensitiveDataMasker
from app.features.test_data.models.asset import TestDataAsset
from app.features.test_data.models.pool import DataPool
from app.features.test_data.schemas import (
    ASSET_SOURCES,
    ASSET_STATUSES,
    TestDataAssetCreate,
    TestDataAssetListResponse,
    TestDataAssetResponse,
    TestDataAssetUpdate,
)
from app.features.test_data.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_asset_project_id,
)
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found
from app.shared.pagination import DEFAULT_PAGE_SIZE

# 目录的作用域：与 Fixture 的 scope 口径一致（复用常量，不另起一套）。
ASSET_SCOPES = ("CASE", "RUN", "PROJECT", "GLOBAL")


def _mask_value(value: object) -> object:
    """脱敏静态值；非 dict/list 原样返回。"""
    return SensitiveDataMasker.mask_body(value)


def _response(asset: TestDataAsset, db: Session) -> TestDataAssetResponse:
    """响应体：value_json 已脱敏，并附带引用它的池数量。"""
    resp = TestDataAssetResponse.model_validate(asset)
    resp.value_json = _mask_value(asset.value_json)
    resp.referenced_count = int(
        db.query(DataPool.id).filter(DataPool.asset_id == asset.id).count()
    )
    return resp


class AssetService:
    """测试数据目录服务。无状态，路由层复用单例。"""

    def list_assets(
        self, db: Session, project_id: int, user: User, *,
        keyword: str | None = None, entity_type: str | None = None,
        source: str | None = None, status: str | None = None,
        scope: str | None = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> TestDataAssetListResponse:
        """列出`assets`。"""
        get_project_or_404(db, project_id, user)
        q = db.query(TestDataAsset).filter(TestDataAsset.project_id == project_id)
        if entity_type:
            q = q.filter(TestDataAsset.entity_type == entity_type)
        if source:
            if source not in ASSET_SOURCES:
                raise bad_request("数据源取值非法：STATIC/POOL/FIXTURE")
            q = q.filter(TestDataAsset.source == source)
        if status:
            if status not in ASSET_STATUSES:
                raise bad_request("状态取值非法：ACTIVE/DISABLED/EXPIRED")
            q = q.filter(TestDataAsset.status == status)
        if scope:
            if scope not in ASSET_SCOPES:
                raise bad_request("作用域取值非法：CASE/RUN/PROJECT/GLOBAL")
            q = q.filter(TestDataAsset.scope == scope)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(
                or_(TestDataAsset.name.ilike(f"%{kw}%"), TestDataAsset.entity_type.ilike(f"%{kw}%"))
            )
        total = int(q.count())
        items = q.order_by(TestDataAsset.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return TestDataAssetListResponse(
            items=[_response(a, db) for a in items], total=total, page=page, page_size=page_size
        )

    def get_asset(self, db: Session, asset_id: int, user: User) -> TestDataAssetResponse:
        """获取资产。"""
        return _response(self._get_or_404(db, asset_id, user), db)

    def create_asset(
        self, db: Session, project_id: int, body: TestDataAssetCreate, *, actor: User,
    ) -> TestDataAssetResponse:
        """创建资产。"""
        project = require_writable_project(db, project_id, actor)
        name = body.name.strip()
        if not name:
            raise bad_request("数据名称不能为空")
        if not body.entity_type.strip():
            raise bad_request("实体类型不能为空")
        if body.source not in ASSET_SOURCES:
            raise bad_request("数据源取值非法：STATIC/POOL/FIXTURE")
        if body.status not in ASSET_STATUSES:
            raise bad_request("状态取值非法：ACTIVE/DISABLED/EXPIRED")
        if body.scope not in ASSET_SCOPES:
            raise bad_request("作用域取值非法：CASE/RUN/PROJECT/GLOBAL")
        if db.query(TestDataAsset).filter(
            TestDataAsset.project_id == project.id, TestDataAsset.name == name
        ).first() is not None:
            raise conflict("同项目下数据名称已存在")

        asset = TestDataAsset(
            project_id=project.id,
            name=name,
            entity_type=body.entity_type.strip(),
            source=body.source,
            scope=body.scope,
            status=body.status,
            fixture_id=body.fixture_id,
            value_json=body.value_json,
            description=(body.description or "").strip() or None,
            created_by=actor.id,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return _response(asset, db)

    def update_asset(
        self, db: Session, asset_id: int, body: TestDataAssetUpdate, *, actor: User,
    ) -> TestDataAssetResponse:
        """更新资产。"""
        asset = self._get_writable_or_404(db, asset_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _response(asset, db)

        name = data.get("name")
        if name is not None:
            if not name.strip():
                raise bad_request("数据名称不能为空")
            if db.query(TestDataAsset).filter(
                TestDataAsset.project_id == asset.project_id,
                TestDataAsset.name == name.strip(),
                TestDataAsset.id != asset.id,
            ).first() is not None:
                raise conflict("同项目下数据名称已存在")
            asset.name = name.strip()
        if data.get("entity_type") is not None:
            if not str(data["entity_type"]).strip():
                raise bad_request("实体类型不能为空")
            asset.entity_type = str(data["entity_type"]).strip()
        if data.get("source") is not None:
            if data["source"] not in ASSET_SOURCES:
                raise bad_request("数据源取值非法：STATIC/POOL/FIXTURE")
            asset.source = data["source"]
        if data.get("scope") is not None:
            if data["scope"] not in ASSET_SCOPES:
                raise bad_request("作用域取值非法：CASE/RUN/PROJECT/GLOBAL")
            asset.scope = data["scope"]
        if data.get("status") is not None:
            if data["status"] not in ASSET_STATUSES:
                raise bad_request("状态取值非法：ACTIVE/DISABLED/EXPIRED")
            asset.status = data["status"]
        if data.get("fixture_id") is not None:
            asset.fixture_id = data["fixture_id"]
        if data.get("value_json") is not None:
            asset.value_json = data["value_json"]
        if data.get("description") is not None:
            asset.description = data["description"].strip() or None

        db.commit()
        db.refresh(asset)
        return _response(asset, db)

    def delete_asset(self, db: Session, asset_id: int, *, actor: User) -> None:
        """删除资产。"""
        asset = self._get_writable_or_404(db, asset_id, actor)
        ref_count = int(db.query(DataPool.id).filter(DataPool.asset_id == asset.id).count())
        if ref_count:
            raise conflict(f"该数据正被 {ref_count} 个数据池引用，请先移除引用")
        db.delete(asset)
        db.commit()

    def _get_or_404(self, db: Session, asset_id: int, user: User) -> TestDataAsset:
        """获取或。"""
        row = db.get(TestDataAsset, asset_id)
        if row is None:
            raise not_found("测试数据不存在")
        get_project_or_404(db, row.project_id, user)
        return row

    def _get_writable_or_404(self, db: Session, asset_id: int, actor: User) -> TestDataAsset:
        """获取可写或。"""
        row = db.get(TestDataAsset, asset_id)
        if row is None:
            raise not_found("测试数据不存在")
        require_writable_project(db, resolve_asset_project_id(db, asset_id), actor)
        return row


__all__ = ["AssetService"]
