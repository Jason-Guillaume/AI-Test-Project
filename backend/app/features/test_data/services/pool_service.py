"""数据池（DataPool / DataPoolItem / DataPoolLease）服务层。

- 池条目 payload_json 在**读接口**统一经 SensitiveDataMasker.mask_body 脱敏。
- 池删除：仍有 ACTIVE 租约时 409；条目删除：状态为 OCCUPIED 时 409。
- acquire / release 是 EXISTING_POOL Provider（Phase B）与生命周期层共用的唯一入口：
  行级锁 + 原子自增占用数，不靠应用层判断。

service owns commit。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy import func as sa_func
from sqlalchemy.orm import Session

from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_data.models.pool import DataPool, DataPoolItem, DataPoolLease
from app.features.test_data.schemas import (
    FIXTURE_SCOPES,
    LEASE_STATUSES,
    POOL_ITEM_STATUSES,
    POOL_STATUSES,
    DataPoolCreate,
    DataPoolItemCreate,
    DataPoolItemResponse,
    DataPoolItemUpdate,
    DataPoolLeaseResponse,
    DataPoolListResponse,
    DataPoolResponse,
    DataPoolUpdate,
    DataPoolItemListResponse,
)
from app.features.test_data.services.access_service import resolve_pool_item_project_id, resolve_pool_project_id
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.models.identity import User
from app.core.http.errors import (
    CODE_DATA_POOL_EXHAUSTED,
    AppError,
    bad_request,
    conflict,
    not_found,
)
from app.core.http.pagination import DEFAULT_PAGE_SIZE


def _mask_value(value: object) -> object:
    """脱敏值。"""
    return SensitiveDataMasker.mask_body(value)


def _pool_response(pool: DataPool, db: Session) -> DataPoolResponse:
    """池响应：条目数 / 可用数 / 活跃租约数（聚合查询）。"""
    resp = DataPoolResponse.model_validate(pool)
    counts = {
        row[0]: row[1]
        for row in db.query(DataPoolItem.status, sa_func.count(DataPoolItem.id))
        .filter(DataPoolItem.pool_id == pool.id)
        .group_by(DataPoolItem.status)
        .all()
    }
    resp.item_count = sum(counts.values())
    resp.available_count = counts.get("AVAILABLE", 0)
    resp.active_lease_count = int(
        db.query(DataPoolLease.id)
        .filter(DataPoolLease.status == "ACTIVE")
        .filter(DataPoolLease.item_id.in_(
            db.query(DataPoolItem.id).filter(DataPoolItem.pool_id == pool.id)
        ))
        .count()
    )
    return resp


def _item_response(item: DataPoolItem) -> DataPoolItemResponse:
    """构造条目响应数据。"""
    resp = DataPoolItemResponse.model_validate(item)
    resp.payload_json = _mask_value(item.payload_json)
    return resp


class PoolService:
    """数据池服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 池 CRUD

    def list_pools(
        self, db: Session, project_id: int, user: User, *,
        keyword: str | None = None, status: str | None = None,
        page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> DataPoolListResponse:
        """列出`pools`。"""
        get_project_or_404(db, project_id, user)
        q = db.query(DataPool).filter(DataPool.project_id == project_id)
        if status:
            if status not in POOL_STATUSES:
                raise bad_request("池状态取值非法：ACTIVE/DISABLED")
            q = q.filter(DataPool.status == status)
        kw = (keyword or "").strip()
        if kw:
            q = q.filter(DataPool.name.ilike(f"%{kw}%") | DataPool.pool_key.ilike(f"%{kw}%"))
        total = int(q.count())
        items = q.order_by(DataPool.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return DataPoolListResponse(
            items=[_pool_response(p, db) for p in items], total=total, page=page, page_size=page_size
        )

    def get_pool(self, db: Session, pool_id: int, user: User) -> DataPoolResponse:
        """获取连接池。"""
        return _pool_response(self._get_pool_or_404(db, pool_id, user), db)

    def create_pool(
        self, db: Session, project_id: int, body: DataPoolCreate, *, actor: User,
    ) -> DataPoolResponse:
        """创建连接池。"""
        project = require_writable_project(db, project_id, actor)
        if body.pool_key.strip().upper() != body.pool_key.strip():
            raise bad_request("pool_key 必须为全大写")
        if body.scope not in FIXTURE_SCOPES:
            raise bad_request("作用域取值非法：CASE/RUN/PROJECT/GLOBAL")
        if body.status not in POOL_STATUSES:
            raise bad_request("池状态取值非法：ACTIVE/DISABLED")
        name = body.name.strip()
        if not name:
            raise bad_request("池名称不能为空")
        if db.query(DataPool).filter(
            DataPool.project_id == project.id, DataPool.pool_key == body.pool_key.strip()
        ).first() is not None:
            raise conflict("同项目下 pool_key 已存在")

        pool = DataPool(
            project_id=project.id,
            asset_id=body.asset_id,
            pool_key=body.pool_key.strip(),
            name=name,
            scope=body.scope,
            max_concurrency=body.max_concurrency,
            lease_ttl_seconds=body.lease_ttl_seconds,
            status=body.status,
        )
        db.add(pool)
        db.commit()
        db.refresh(pool)
        return _pool_response(pool, db)

    def update_pool(
        self, db: Session, pool_id: int, body: DataPoolUpdate, *, actor: User,
    ) -> DataPoolResponse:
        """更新连接池。"""
        pool = self._get_pool_writable_or_404(db, pool_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _pool_response(pool, db)
        name = data.get("name")
        if name is not None:
            if not name.strip():
                raise bad_request("池名称不能为空")
            pool.name = name.strip()
        if data.get("max_concurrency") is not None:
            pool.max_concurrency = data["max_concurrency"]
        if data.get("lease_ttl_seconds") is not None:
            pool.lease_ttl_seconds = data["lease_ttl_seconds"]
        if data.get("status") is not None:
            if data["status"] not in POOL_STATUSES:
                raise bad_request("池状态取值非法：ACTIVE/DISABLED")
            if data["status"] == "DISABLED" and self._active_lease_count(db, pool.id):
                raise conflict("存在活跃租约，无法停用数据池")
            pool.status = data["status"]
        db.commit()
        db.refresh(pool)
        return _pool_response(pool, db)

    def delete_pool(self, db: Session, pool_id: int, *, actor: User) -> None:
        """删除连接池。"""
        pool = self._get_pool_writable_or_404(db, pool_id, actor)
        if self._active_lease_count(db, pool.id):
            raise conflict("数据池存在活跃租约，无法删除")
        db.delete(pool)
        db.commit()

    # ---------------------------------------------------------------- 条目 CRUD

    def list_items(
        self, db: Session, pool_id: int, user: User, *,
        status: str | None = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> DataPoolItemListResponse:
        """列出条目。"""
        pool = self._get_pool_or_404(db, pool_id, user)
        q = db.query(DataPoolItem).filter(DataPoolItem.pool_id == pool.id)
        if status:
            if status not in POOL_ITEM_STATUSES:
                raise bad_request("条目状态取值非法：AVAILABLE/OCCUPIED/EXPIRED/DISABLED")
            q = q.filter(DataPoolItem.status == status)
        total = int(q.count())
        items = q.order_by(DataPoolItem.id).offset((page - 1) * page_size).limit(page_size).all()
        return DataPoolItemListResponse(
            items=[_item_response(i) for i in items], total=total, page=page, page_size=page_size
        )

    def create_item(
        self, db: Session, pool_id: int, body: DataPoolItemCreate, *, actor: User,
    ) -> DataPoolItemResponse:
        """创建条目。"""
        pool = self._get_pool_writable_or_404(db, pool_id, actor)
        if pool.status != "ACTIVE":
            raise conflict("数据池未启用，无法添加条目")
        if body.status not in POOL_ITEM_STATUSES:
            raise bad_request("条目状态取值非法：AVAILABLE/OCCUPIED/EXPIRED/DISABLED")
        if body.status == "OCCUPIED":
            raise bad_request("新条目不能直接置为 OCCUPIED，请通过租约占用")
        item = DataPoolItem(
            pool_id=pool.id,
            status=body.status,
            payload_json=body.payload_json,
            occupied_count=0,
            expires_at=body.expires_at,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        return _item_response(item)

    def update_item(
        self, db: Session, item_id: int, body: DataPoolItemUpdate, *, actor: User,
    ) -> DataPoolItemResponse:
        """更新条目。"""
        item = self._get_item_writable_or_404(db, item_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _item_response(item)
        if data.get("status") is not None:
            if data["status"] not in POOL_ITEM_STATUSES:
                raise bad_request("条目状态取值非法：AVAILABLE/OCCUPIED/EXPIRED/DISABLED")
            if data["status"] == "OCCUPIED" and item.status != "OCCUPIED":
                raise conflict("条目只能通过租约置为 OCCUPIED，请使用手工占用接口")
            item.status = data["status"]
        if data.get("payload_json") is not None:
            item.payload_json = data["payload_json"]
        if data.get("expires_at") is not None:
            item.expires_at = data["expires_at"]
        db.commit()
        db.refresh(item)
        return _item_response(item)

    def delete_item(self, db: Session, item_id: int, *, actor: User) -> None:
        """删除条目。"""
        item = self._get_item_writable_or_404(db, item_id, actor)
        if item.status == "OCCUPIED":
            raise conflict("条目处于 OCCUPIED 状态，无法删除")
        db.delete(item)
        db.commit()

    def release_item(self, db: Session, item_id: int, *, actor: User) -> DataPoolItemResponse:
        """手工释放：清掉条目上的活跃租约并归还。"""
        item = self._get_item_writable_or_404(db, item_id, actor)
        leases = db.query(DataPoolLease).filter(
            DataPoolLease.item_id == item.id, DataPoolLease.status == "ACTIVE"
        ).all()
        now = datetime.now()
        for lease in leases:
            lease.status = "RELEASED"
            lease.released_at = now
        item.status = "AVAILABLE"
        item.occupied_count = 0
        db.commit()
        db.refresh(item)
        return _item_response(item)

    # ---------------------------------------------------------------- 租约

    def list_leases(
        self, db: Session, pool_id: int, user: User, *,
        status: str | None = None, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE,
    ) -> dict:
        """列出`leases`。"""
        pool = self._get_pool_or_404(db, pool_id, user)
        q = db.query(DataPoolLease).filter(
            DataPoolLease.project_id == pool.project_id,
            DataPoolLease.item_id.in_(db.query(DataPoolItem.id).filter(DataPoolItem.pool_id == pool.id)),
        )
        if status:
            if status not in LEASE_STATUSES:
                raise bad_request("租约状态取值非法：ACTIVE/RELEASED/EXPIRED")
            q = q.filter(DataPoolLease.status == status)
        total = int(q.count())
        rows = q.order_by(DataPoolLease.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
        return {
            "items": [DataPoolLeaseResponse.model_validate(r) for r in rows],
            "page": page,
            "page_size": page_size,
            "total": total,
        }

    # ---------------------------------------------------------------- 内部：占用 / 释放

    def acquire(
        self,
        db: Session,
        *,
        project_id: int,
        pool_key: str,
        test_run_id: int | None = None,
        case_execution_id: int | None = None,
    ) -> tuple[int, int, dict]:
        """占用一个条目，返回 (item_id, lease_id, payload)。

        并发安全：候选条目按 id 顺序取行锁，占用数按 max_concurrency 判断；
        没有可用条目时抛 409 DATA_POOL_EXHAUSTED。
        """
        pool = (
            db.query(DataPool)
            .filter(DataPool.project_id == project_id, DataPool.pool_key == pool_key,
                    DataPool.status == "ACTIVE")
            .with_for_update()
            .first()
        )
        if pool is None:
            raise AppError(
                f"数据池 {pool_key} 不存在或未启用", status_code=409, code=CODE_DATA_POOL_EXHAUSTED
            )
        now = datetime.now()
        candidates = (
            db.query(DataPoolItem)
            .filter(
                DataPoolItem.pool_id == pool.id,
                DataPoolItem.status == "AVAILABLE",
                DataPoolItem.occupied_count < pool.max_concurrency,
            )
            .order_by(DataPoolItem.id)
            .with_for_update()
            .all()
        )
        item = None
        for cand in candidates:
            expired = cand.expires_at is not None and cand.expires_at <= now
            if not expired:
                item = cand
                break
            cand.status = "EXPIRED"
            cand.occupied_count = 0
        if item is None:
            db.flush()
            raise AppError(
                f"数据池 {pool_key} 已耗尽，无可用条目",
                status_code=409,
                code=CODE_DATA_POOL_EXHAUSTED,
            )
        item.status = "OCCUPIED"
        item.occupied_count = item.occupied_count + 1
        lease = DataPoolLease(
            item_id=item.id,
            project_id=pool.project_id,
            test_run_id=test_run_id,
            case_execution_id=case_execution_id,
            status="ACTIVE",
            leased_at=now,
            expires_at=now + timedelta(seconds=pool.lease_ttl_seconds),
        )
        db.add(lease)
        db.flush()
        return int(item.id), int(lease.id), dict(item.payload_json or {})

    def release(
        self,
        db: Session,
        *,
        item_id: int,
        lease_id: int,
    ) -> None:
        """归还租约：释放租约行，条目占用数减一。"""
        lease = db.get(DataPoolLease, lease_id)
        item = db.get(DataPoolItem, item_id)
        if lease is None or item is None:
            return
        if lease.status == "ACTIVE":
            lease.status = "RELEASED"
            lease.released_at = datetime.now()
        item.occupied_count = max(0, (item.occupied_count or 0) - 1)
        if item.occupied_count == 0 and item.status == "OCCUPIED":
            item.status = "AVAILABLE"

    # ---------------------------------------------------------------- 内部：查询与权限

    @staticmethod
    def _active_lease_count(db: Session, pool_id: int) -> int:
        """统计启用状态租约数量。"""
        return int(
            db.query(DataPoolLease.id)
            .filter(DataPoolLease.status == "ACTIVE")
            .filter(DataPoolLease.item_id.in_(db.query(DataPoolItem.id).filter(DataPoolItem.pool_id == pool_id)))
            .count()
        )

    def _get_pool_or_404(self, db: Session, pool_id: int, user: User) -> DataPool:
        """获取连接池或。"""
        row = db.get(DataPool, pool_id)
        if row is None:
            raise not_found("数据池不存在")
        get_project_or_404(db, row.project_id, user)
        return row

    def _get_pool_writable_or_404(self, db: Session, pool_id: int, actor: User) -> DataPool:
        """获取连接池可写或。"""
        row = db.get(DataPool, pool_id)
        if row is None:
            raise not_found("数据池不存在")
        require_writable_project(db, resolve_pool_project_id(db, pool_id), actor)
        return row

    def _get_item_or_404(self, db: Session, item_id: int, user: User) -> DataPoolItem:
        """获取条目或。"""
        item = db.get(DataPoolItem, item_id)
        if item is None:
            raise not_found("池条目不存在")
        pool = db.get(DataPool, item.pool_id)
        if pool is None:
            raise not_found("数据池不存在")
        get_project_or_404(db, pool.project_id, user)
        return item

    def _get_item_writable_or_404(self, db: Session, item_id: int, actor: User) -> DataPoolItem:
        """获取条目可写或。"""
        item = db.get(DataPoolItem, item_id)
        if item is None:
            raise not_found("池条目不存在")
        require_writable_project(db, resolve_pool_item_project_id(db, item_id), actor)
        return item


__all__ = ["PoolService"]
