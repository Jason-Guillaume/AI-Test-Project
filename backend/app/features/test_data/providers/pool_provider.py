"""EXISTING_POOL Provider（§9.7）：从数据池占用一个已有条目。

行为：
- 池 DISABLED → ``PROVIDER_DISABLED``（区别于耗尽，便于排障时分清是配置还是容量）。
- 没有可用条目 / 占用已满 → ``DATA_POOL_EXHAUSTED``，**不降级去写数据库**。
- 成功 → payload 合并进私有变量，cleanup 句柄是释放租约。
- scope=RUN 且同一 ``test_run_id`` 已持有该池租约时复用，不第二次占用。

payload 以**原值**进入私有变量（运行时要用真值），落快照时才由 data_factory 脱敏。
"""

from __future__ import annotations

from app.features.test_data.models.pool import DataPool, DataPoolItem, DataPoolLease
from app.features.test_data.providers.base import BaseProvider, ProviderContext, ProviderResult, config_of
from app.shared.errors import CODE_PROVIDER_DISABLED, AppError


class PoolProvider(BaseProvider):
    provider_type = "EXISTING_POOL"

    def run(self, ctx: ProviderContext) -> ProviderResult:
        from app.features.test_data.schemas import PoolProviderConfig
        from app.features.test_data.services.pool_service import PoolService

        cfg = self.load_config(config_of(ctx), PoolProviderConfig)
        pool_key = cfg.pool_key.strip()

        pool = ctx.db.query(DataPool).filter(
            DataPool.project_id == ctx.project_id,
            DataPool.pool_key == pool_key,
        ).first()
        if pool is None:
            raise AppError(
                f"数据池 {pool_key} 不存在",
                status_code=404,
                code=CODE_PROVIDER_DISABLED,
            )
        if pool.status != "ACTIVE":
            raise AppError(
                f"数据池 {pool_key} 已停用",
                status_code=400,
                code=CODE_PROVIDER_DISABLED,
            )

        # RUN 作用域复用：同一 test_run 已占的租约不重复占用。
        if ctx.test_run_id is not None:
            reused = self._reuse_run_lease(ctx, pool)
            if reused is not None:
                item_id, lease_id, payload = reused
                return ProviderResult.ok(
                    dict(payload),
                    request_snapshot={"pool_key": pool_key, "reused": True},
                    response_snapshot={"item_id": item_id, "lease_id": lease_id},
                    cleanup_handle=self._lease_handle(item_id, lease_id),
                )

        service = PoolService()
        item_id, lease_id, payload = service.acquire(
            ctx.db,
            project_id=ctx.project_id,
            pool_key=pool_key,
            test_run_id=ctx.test_run_id,
            case_execution_id=ctx.case_execution_id,
        )
        return ProviderResult.ok(
            dict(payload),
            request_snapshot={"pool_key": pool_key},
            response_snapshot={"item_id": item_id, "lease_id": lease_id},
            cleanup_handle=self._lease_handle(item_id, lease_id),
        )

    @staticmethod
    def _lease_handle(item_id: int, lease_id: int) -> dict:
        return {"type": "POOL_LEASE", "item_id": item_id, "lease_id": lease_id}

    @staticmethod
    def _reuse_run_lease(ctx: ProviderContext, pool: DataPool) -> tuple[int, int, dict] | None:
        """同一 test_run 在本池上已有的 ACTIVE 租约 → 复用，返回 (item_id, lease_id, payload)。"""
        lease = ctx.db.query(DataPoolLease).filter(
            DataPoolLease.project_id == ctx.project_id,
            DataPoolLease.test_run_id == ctx.test_run_id,
            DataPoolLease.status == "ACTIVE",
            DataPoolLease.item_id.in_(
                ctx.db.query(DataPoolItem.id).filter(DataPoolItem.pool_id == pool.id)
            ),
        ).order_by(DataPoolLease.id.asc()).first()
        if lease is None:
            return None
        item = ctx.db.get(DataPoolItem, lease.item_id)
        if item is None:
            return None
        return int(item.id), int(lease.id), dict(item.payload_json or {})


__all__ = ["PoolProvider"]
