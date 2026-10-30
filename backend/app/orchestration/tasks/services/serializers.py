"""任务响应转换。

本模块只把已加载的 ORM 对象转换为稳定 wire 字段，不读取数据库、不写入状态；
Worker 与业务服务可继续通过 TaskService 的兼容方法获得相同响应形状。
"""

from typing import Any

from app.agents.assembly.snapshot import public_agent_snapshot
from app.orchestration.tasks.models import Task, TaskRun


class TaskSerializers:
    """任务与运行的纯响应转换器。"""

    @staticmethod
    def task_response(task: Task, run: TaskRun | None) -> dict[str, Any]:
        """生成稳定任务 DTO，不暴露 ORM 关系或内部配置。"""
        return {
            "id": task.id,
            "project_id": task.project_id,
            "created_by": task.created_by,
            "title": task.title,
            "goal": task.goal,
            "environment_id": task.environment_id,
            "input_case_ids": task.input_case_ids or [],
            "status": task.status,
            "task_mode": task.task_mode,
            "archived": task.archived,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "latest_run": TaskSerializers.run_response(run) if run is not None else None,
        }

    @staticmethod
    def run_response(run: TaskRun) -> dict[str, Any]:
        """保留可审计 Agent 版本信息，并从响应中移除指令和 Skill 正文。"""
        input_snapshot = dict(run.input_snapshot or {})
        projected_agent = public_agent_snapshot(input_snapshot.get("agent_definition"))
        if projected_agent is not None:
            input_snapshot["agent_definition"] = projected_agent
        return {
            "id": run.id,
            "task_id": run.task_id,
            "run_number": run.run_number,
            "status": run.status,
            "stage": run.stage,
            "goal_snapshot": run.goal_snapshot,
            "input_snapshot": input_snapshot,
            "current_plan_version": run.current_plan_version,
            "event_seq": run.event_seq,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "created_at": run.created_at,
        }
