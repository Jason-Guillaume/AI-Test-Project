"""统一任务 HTTP 接口。

路由只负责参数校验、认证依赖和 DTO；权限、事务、状态机与业务引用全部由 TaskService 执行。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.features.tasks.schemas import (
    AvailableTaskAgentResponse,
    TaskCommandCreate,
    TaskCommandResponse,
    TaskCreate,
    TaskEventResponse,
    TaskListResponse,
    TaskMessageCreate,
    TaskMessageResponse,
    TaskPlanResponse,
    TaskResourceRefResponse,
    TaskResponse,
    TaskRunDetailResponse,
    TaskWebAuthoringTurn,
)
from app.features.tasks.services.web_authoring_service import TaskWebAuthoringService
from app.features.web_ui.schemas import PromoteInput
from app.features.tasks.services.task_service import TaskService
from app.models.identity import User
from app.shared.auth import get_current_user
from app.shared.database import get_db

router = APIRouter(tags=["统一任务"])
service = TaskService()
web_authoring_service = TaskWebAuthoringService()


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="创建统一 API 测试任务",
)
def create_task(
    project_id: int,
    body: TaskCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """登记任务和首个持久化运行，长执行由数据库调度器继续处理。"""
    return service.create_task(db, project_id, body, actor=user)


@router.get("/task-runs/{run_id}/web-authoring", summary="读取任务内 Web 编写工作区")
def get_task_web_authoring(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return web_authoring_service.workspace(db, run_id, user)


@router.post("/task-runs/{run_id}/web-authoring/restart", summary="启动或重启任务受控浏览器")
def restart_task_web_authoring(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return web_authoring_service.start_or_restart(db, run_id, user)


@router.post("/task-runs/{run_id}/web-authoring/close", summary="关闭任务受控浏览器")
def close_task_web_authoring(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return web_authoring_service.close_session(db, run_id, user)


@router.post("/task-runs/{run_id}/web-authoring/messages", summary="推进任务内 Web Agent")
def send_task_web_authoring_message(
    run_id: int,
    body: TaskWebAuthoringTurn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return web_authoring_service.turn(db, run_id, body, user)


@router.post("/task-runs/{run_id}/web-authoring/draft", status_code=status.HTTP_201_CREATED, summary="从任务内浏览器生成未确认 Web 草稿")
def promote_task_web_authoring_draft(
    run_id: int,
    body: PromoteInput,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return web_authoring_service.promote(db, run_id, body, user)


@router.get(
    "/projects/{project_id}/available-agents",
    response_model=list[AvailableTaskAgentResponse],
    summary="列出项目可用的任务 Agent",
)
def list_available_agents(
    project_id: int,
    target_type: str = Query("API", pattern="^(API|WEB|SECURITY)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """仅返回当前项目有模型授权且具备完整运行权限的已启用 Agent。"""
    return service.list_available_agents(
        db, project_id, actor=user, target_type=target_type,
    )


@router.get("/tasks", response_model=TaskListResponse, summary="当前用户可见任务")
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: int | None = Query(None, gt=0),
    task_status: str | None = Query(None, alias="status", max_length=32),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """按项目权限分页列出任务及其最新运行。"""
    return service.list_tasks(db, user, page=page, page_size=page_size, project_id=project_id, status=task_status)


@router.get("/tasks/{task_id}", response_model=TaskResponse, summary="任务详情")
def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """读取任务与最新运行，服务层统一检查项目可见性。"""
    return service.get_task(db, task_id, user)


@router.get("/task-runs/{run_id}", response_model=TaskRunDetailResponse, summary="运行与团队详情")
def get_run_detail(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """返回运行、方案、真实参与者实例和子工作项。"""
    return service.get_run_detail(db, run_id, user)


@router.get("/task-runs/{run_id}/messages", response_model=list[TaskMessageResponse], summary="运行内会话")
def list_messages(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    """按运行读取各独立参与者的会话消息。"""
    return service.list_messages(db, run_id, user)


@router.post("/task-runs/{run_id}/messages", response_model=dict, status_code=status.HTTP_202_ACCEPTED, summary="发送任务消息")
def send_message(
    run_id: int,
    body: TaskMessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """投递给主 Agent 的目标或对话，或发给指定 API Worker 的补充要求。"""
    result = service.send_message(db, run_id, body, actor=user)
    return {
        "message": TaskMessageResponse.model_validate(result["message"]),
        "created_run_id": result["created_run_id"],
    }


@router.post("/task-runs/{run_id}/commands", response_model=TaskCommandResponse, summary="任务控制命令")
def create_command(
    run_id: int,
    body: TaskCommandCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskCommandResponse:
    """以幂等键记录并应用计划确认、暂停、恢复、取消或失败项重试。"""
    return TaskCommandResponse.model_validate(service.create_command(db, run_id, body, actor=user))


@router.get("/task-runs/{run_id}/events", response_model=list[TaskEventResponse], summary="续读持久化事件")
def list_events(
    run_id: int,
    after_seq: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    """按运行事件序号增量读取，前端断线后可从游标继续。"""
    return service.list_events(db, run_id, user, after_seq=after_seq, limit=limit)


@router.get("/task-runs/{run_id}/resources", response_model=list[TaskResourceRefResponse], summary="运行资源与产物")
def list_resources(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    """读取输入资产和真实 TestRun / Report 业务产物引用。"""
    return service.list_resources(db, run_id, user)


@router.get("/task-resources", response_model=list[TaskResourceRefResponse], summary="按业务资源反查来源任务")
def find_tasks_for_resource(
    resource_type: str = Query(min_length=1, max_length=40),
    resource_id: str = Query(min_length=1, max_length=64),
    project_id: int | None = Query(None, gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list:
    """让原管理页使用同一套项目权限反查关联任务。"""
    return service.find_tasks_for_resource(
        db, user, resource_type=resource_type, resource_id=resource_id, project_id=project_id,
    )
