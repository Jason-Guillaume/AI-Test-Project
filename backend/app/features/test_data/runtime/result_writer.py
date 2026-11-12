"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

import time
from datetime import datetime
from sqlalchemy.orm import Session
from app.core.security.sensitive import SensitiveDataMasker
from app.features.test_data.models.execution import DataExecution, ProviderExecution
from app.features.test_data.providers import CLEANUP_HANDLE_KEY, ProviderResult


def record_provider_result(masker: SensitiveDataMasker, rec: ProviderExecution, result: ProviderResult, started: float) -> None:
    """写入 Provider 执行结果：状态、耗时、脱敏快照、cleanup 句柄。"""
    rec.status = "SUCCESS" if result.success else "FAILED"
    rec.finished_at = datetime.now()
    rec.duration_ms = int((time.perf_counter() - started) * 1000)
    snapshot = masker.mask_body(dict(result.outputs))
    if result.cleanup_handle is not None:
        snapshot = dict(snapshot or {})
        snapshot[CLEANUP_HANDLE_KEY] = result.cleanup_handle
    rec.output_snapshot = snapshot
    rec.error_code = None if result.success else result.error_code
    rec.error_message = None if result.success else (result.error_message or None)


def finish(data_exec: DataExecution, started: float, *, status: str, error_code: str | None=None, error_message: str | None=None) -> None:
    """保存固定数据生成结果并关闭执行记录。"""
    data_exec.status = status
    data_exec.finished_at = datetime.now()
    data_exec.duration_ms = int((time.perf_counter() - started) * 1000)
    data_exec.error_code = error_code
    data_exec.error_message = error_message


def persist(db: Session) -> None:
    """把失败记录落库；commit 失败则回滚，原异常照常上抛。"""
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
