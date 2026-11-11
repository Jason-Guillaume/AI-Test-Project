"""统一执行者有效性检查，供 Worker 收尾复用；不提交事务或刷新调用方待写对象。"""
from datetime import datetime
from sqlalchemy.orm import Session
from app.orchestration.tasks.models import TaskRun, TaskWorkItem, TaskAttempt


def has_live_claim(db: Session, run_id: int, work_id: int, attempt_id: int, owner: str, generation: int) -> bool:
    """锁权威 Run 并读取数据库列；失效租约或非运行尝试不能提交迟到结果。"""
    # 查询列而非刷新 ORM 对象，避免覆盖处理器尚未提交的成功结果或控制状态。
    with db.no_autoflush:
        row = (db.query(TaskRun.lease_owner, TaskRun.lease_expires_at, TaskRun.deadline_at,
                        TaskWorkItem.attempt_count, TaskWorkItem.status,
                        TaskAttempt.owner, TaskAttempt.status, TaskAttempt.deadline_at)
            .join(TaskWorkItem, TaskWorkItem.task_run_id == TaskRun.id)
            .join(TaskAttempt, TaskAttempt.work_item_id == TaskWorkItem.id)
            .filter(TaskRun.id == run_id, TaskWorkItem.id == work_id, TaskAttempt.id == attempt_id)
            .with_for_update(of=TaskRun).first())
    now = datetime.now()
    return bool(row and row[0] == owner and row[1] and row[1] > now
        and (row[2] is None or row[2] > now) and row[3] == generation and row[4] == 'RUNNING'
        and row[5] == owner and row[6] == 'RUNNING' and (row[7] is None or row[7] > now))
