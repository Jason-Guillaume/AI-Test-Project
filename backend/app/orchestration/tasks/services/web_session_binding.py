"""任务内浏览器会话的运行与参与者绑定校验。"""

from sqlalchemy.orm import Session

from app.core.http.errors import not_found
from app.orchestration.tasks.models import Task, TaskAgentInstance, TaskRun


def validate_task_web_session_binding(
    db: Session,
    *,
    project_id: int,
    environment_id: int,
    task_run_id: int,
    task_agent_instance_id: int,
) -> None:
    """确保浏览器绑定到当前项目、Web 编写运行及其 UI Worker。"""
    run = db.get(TaskRun, task_run_id)
    task = db.get(Task, run.task_id) if run else None
    worker = db.get(TaskAgentInstance, task_agent_instance_id)
    if (
        run is None
        or task is None
        or task.project_id != project_id
        or run.input_snapshot.get("target_type") != "WEB_AUTHORING"
        or run.status not in {"QUEUED", "RUNNING", "WAITING_CONFIRMATION", "PAUSED"}
        or worker is None
        or worker.task_run_id != run.id
        or worker.role != "UI_WORKER"
        or run.input_snapshot.get("environment_id") != environment_id
    ):
        raise not_found("任务 Web 工作区不存在")
