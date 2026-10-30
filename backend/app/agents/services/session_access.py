"""领域职责提取；保留原权限、事务和执行顺序。"""

from __future__ import annotations

from sqlalchemy.orm import Session
from app.agents.models.session import AgentSession
from app.platform.projects.services.access_service import get_project_or_404, require_writable_project
from app.core.models.identity import User
from app.core.http.errors import not_found


def create_session(
    db: Session, project_id: int, actor: User, *, title: str | None = None,
    task_run_id: int | None = None, task_agent_instance_id: int | None = None,
) -> AgentSession:
    """建会话。写操作需 project member（不足 403）。"""
    require_writable_project(db, project_id, actor)
    session = AgentSession(
        project_id=project_id, user_id=actor.id, title=title,
        task_run_id=task_run_id, task_agent_instance_id=task_agent_instance_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions(db: Session, project_id: int, user: User) -> list[AgentSession]:
    """列出项目内会话（按更新时间倒序）。viewer+ 可见。"""
    get_project_or_404(db, project_id, user)
    return (
        db.query(AgentSession)
        .filter(AgentSession.project_id == project_id, AgentSession.task_run_id.is_(None))
        .order_by(AgentSession.updated_at.desc(), AgentSession.id.desc())
        .all()
    )


def get_session_or_404(db: Session, session_id: int, user: User) -> AgentSession:
    """取会话并校验项目可见性（viewer+）；不存在 / 不可见统一 404（§33）。"""
    session = db.get(AgentSession, session_id)
    if session is None or session.task_run_id is not None:
        raise not_found("会话不存在")
    get_project_or_404(db, session.project_id, user)
    return session


def get_session_for_write(db: Session, session_id: int, actor: User) -> AgentSession:
    """取会话并校验可写（member+）：发消息 / 删会话用。"""
    session = db.get(AgentSession, session_id)
    if session is None or session.task_run_id is not None:
        raise not_found("会话不存在")
    require_writable_project(db, session.project_id, actor)
    return session


def delete_session(db: Session, session_id: int, actor: User) -> None:
    """删会话（连带消息，agent_message.session_id 外键 ON DELETE CASCADE）。"""
    session = get_session_for_write(db, session_id, actor)
    db.delete(session)
    db.commit()
