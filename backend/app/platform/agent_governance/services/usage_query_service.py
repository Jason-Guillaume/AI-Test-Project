"""Skill 使用统计只读查询。

近期任务是治理页面的跨域 read model，因此在此明确联结任务运行与任务标题；
不把 ORM 聚合逻辑放进 Agent 引用保护服务，也不在任务域增加反向依赖。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.agents.models import AgentDefinition
from app.core.http.errors import not_found
from app.skills.models import SkillDefinition, SkillUsageEvent


def skill_usage(db: Session, skill_id: int) -> dict[str, Any]:
    """汇总 Skill 加载数、去重任务数、Agent 用量和最近十次任务运行。"""
    # 仅用于只读统计的跨域联表；局部导入避免模型注册阶段产生循环依赖。
    from app.orchestration.tasks.models.task import Task, TaskRun

    if db.get(SkillDefinition, skill_id) is None:
        raise not_found("Skill 不存在")

    usage = db.query(SkillUsageEvent).filter(
        SkillUsageEvent.skill_definition_id == skill_id,
    )
    total_loads = usage.count()
    last_used_at = usage.with_entities(func.max(SkillUsageEvent.created_at)).scalar()
    agent_rows = db.query(
        AgentDefinition.id,
        AgentDefinition.name,
        func.count(SkillUsageEvent.id),
    ).join(
        SkillUsageEvent,
        SkillUsageEvent.agent_definition_id == AgentDefinition.id,
    ).filter(
        SkillUsageEvent.skill_definition_id == skill_id,
    ).group_by(
        AgentDefinition.id,
        AgentDefinition.name,
    ).all()
    recent = db.query(SkillUsageEvent, TaskRun, Task).join(
        TaskRun,
        TaskRun.id == SkillUsageEvent.task_run_id,
    ).join(
        Task,
        Task.id == TaskRun.task_id,
    ).filter(
        SkillUsageEvent.skill_definition_id == skill_id,
    ).order_by(
        SkillUsageEvent.created_at.desc(),
    ).limit(10).all()

    return {
        "total_loads": total_loads,
        "task_count": usage.with_entities(
            func.count(func.distinct(SkillUsageEvent.task_run_id)),
        ).scalar() or 0,
        "last_used_at": last_used_at,
        "agents": [
            {"id": row[0], "name": row[1], "loads": row[2]}
            for row in agent_rows
        ],
        "recent_tasks": [
            {
                "task_id": task.id,
                "title": task.title,
                "run_number": run.run_number,
                "used_at": event.created_at,
            }
            for event, run, task in recent
        ],
    }
