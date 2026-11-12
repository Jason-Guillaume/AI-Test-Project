"""扫描过程事件写入（§二十一「SecurityScanEvent」）。

三个写入方（job_service 的创建/取消、worker 的领任务与收尾、orchestrator 的阶段推进）
都要往同一张表写事件，seq 分配如果各写一遍就会出现同一个 seq 被两个独立 session
算出来：worker 线程和 HTTP 请求可以在同一毫秒里给同一个任务取「当前最大 seq」。

做法：
- 数据库上加 (job_id, seq) 唯一索引，重号在存储层就不可能发生；
- 这里统一写入并处理冲突：唯一冲突说明有并发写入方抢了号，回滚到保存点后重读
  最大 seq 再写一次。用 SAVEPOINT 而不是 session.rollback()，否则会把调用方
  还没提交的其他改动（比如刚 add 的任务行）一起丢掉。

事件是审计记录，不是日志替代品：payload 由调用方在传入前完成脱敏。
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.features.security_testing.zap.models.job import SecurityScanEvent

logger = logging.getLogger(__name__)

#: seq 冲突时的重试次数。同一个任务的并发写入方只有 worker 与 HTTP 两个来源，
#: 连续三次都撞上几乎不可能，超了就当作真异常抛出去，不静默吞掉。
_MAX_SEQ_ATTEMPTS = 3
MESSAGE_MAX_LENGTH = 500


def next_seq(db: Session, job_id: int) -> int:
    """算出该任务下一个事件序号（任务内从 1 递增）。"""
    last = (
        db.query(SecurityScanEvent.seq)
        .filter(SecurityScanEvent.job_id == job_id)
        .order_by(SecurityScanEvent.seq.desc())
        .first()
    )
    return (int(last[0]) + 1) if last is not None else 1


def add_event(
    db: Session,
    *,
    job_id: int,
    project_id: int,
    event_type: str,
    stage: str,
    message: str,
    payload: dict | None = None,
) -> SecurityScanEvent:
    """写一条过程事件，只 add + flush，提交由调用方负责。

    (job_id, seq) 冲突时在保存点内回滚并重试，保证时间线序号唯一且不丢调用方
    尚未提交的改动。
    """
    text = (message or "")[:MESSAGE_MAX_LENGTH]
    for attempt in range(_MAX_SEQ_ATTEMPTS):
        event = SecurityScanEvent(
            job_id=job_id,
            project_id=project_id,
            seq=next_seq(db, job_id),
            event_type=event_type,
            stage=stage,
            message=text,
            payload_json=payload,
        )
        db.add(event)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            logger.warning(
                "扫描事件序号并发冲突，重新分配 seq（job_id=%s，第 %d 次重试）",
                job_id, attempt + 1,
            )
            if attempt == _MAX_SEQ_ATTEMPTS - 1:
                raise
            continue
        return event
    raise RuntimeError("扫描事件序号分配失败：并发冲突重试次数用尽")
