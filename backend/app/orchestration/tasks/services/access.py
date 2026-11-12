"""任务领域访问检查。

集中保留任务、运行与项目的读写权限门槛，并通过 core 角色机制校验项目身份。
TaskService 兼容入口和查询、消息等服务都复用这里的唯一实现；不可见资源统一按 404 处理。
"""

from sqlalchemy.orm import Session

from app.core.http.errors import forbidden, not_found
from app.core.models.identity import User
from app.core.models.project import Project
from app.core.security.roles import (
    PROJECT_ROLE_MEMBER,
    PROJECT_ROLE_VIEWER,
    has_project_role,
    project_role_for,
)
from app.orchestration.tasks.models import Task, TaskRun


class TaskAccessService:
    """任务与运行的项目范围访问检查。"""

    @staticmethod
    def get_project_for_read(db: Session, project_id: int, user: User) -> Project:
        """读取项目并按 viewer+ 校验；不可见与不存在统一返回 404。"""
        project = db.get(Project, project_id)
        # 权限判定：跨项目读取统一隐藏存在性，避免通过响应差异探测项目。
        if project is None or not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_VIEWER):
            raise not_found("项目不存在")
        return project

    @staticmethod
    def get_project_for_write(db: Session, project_id: int, user: User) -> Project:
        """读取项目并要求 member+ 写权限；不可见项目仍统一返回 404。"""
        project = TaskAccessService.get_project_for_read(db, project_id, user)
        if not has_project_role(project_role_for(db, project, user), PROJECT_ROLE_MEMBER):
            raise forbidden("需要项目成员权限")
        return project

    @staticmethod
    def get_task_for_read(db: Session, task_id: int, user: User) -> Task:
        """读取任务并复核其所属项目的可见权限。"""
        task = db.get(Task, task_id)
        if task is None:
            raise not_found("任务不存在")
        TaskAccessService.get_project_for_read(db, task.project_id, user)
        return task

    @staticmethod
    def get_run_for_read(db: Session, run_id: int, user: User) -> tuple[TaskRun, Task]:
        """读取运行和任务，并复核所属项目的可见权限。"""
        run = db.get(TaskRun, run_id)
        if run is None:
            raise not_found("任务运行不存在")
        task = TaskAccessService.get_task_for_read(db, run.task_id, user)
        return run, task

    @staticmethod
    def get_run_for_write(
        db: Session, run_id: int, actor: User, *, lock: bool = False,
    ) -> tuple[TaskRun, Task]:
        """读取可写运行；控制命令和消息可要求行锁保持原串行化语义。"""
        query = db.query(TaskRun).filter(TaskRun.id == run_id)
        if lock:
            query = query.with_for_update()
        run = query.first()
        if run is None:
            raise not_found("任务运行不存在")
        task = db.get(Task, run.task_id)
        if task is None:
            raise not_found("任务不存在")
        TaskAccessService.get_project_for_write(db, task.project_id, actor)
        return run, task
