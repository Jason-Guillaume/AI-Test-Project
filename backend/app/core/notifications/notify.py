"""通知写入工具。

集中放置跨模块的通知写入逻辑，避免每个 feature 各自拼收件箱字段。
所有通知都写进同一个 notification 收件箱表，并带 project/organization 作用域，
供个人通知列表与项目作用域筛选共用。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.models.notification import Notification

logger = logging.getLogger(__name__)

# 事件类型到标题的默认映射。
EVENT_TITLES: dict[str, str] = {
    "user.created": "欢迎加入测试开发平台",
    "user.updated": "账号信息已更新",
    "user.password_changed": "密码已修改，请重新登录",
    "organization.member.invited": "你被邀请加入组织",
    "project.member.invited": "你被邀请加入项目",
    "project.owner_changed": "项目负责人已变更",
    "defect.created": "你报告的缺陷已创建",
    "defect.assigned": "有新的缺陷分配给你",
    "defect.status_changed": "你报告的缺陷状态已变更",
    "task.plan_ready": "任务方案待确认",
    "task.completed": "任务已完成",
    "task.completed_with_issues": "任务完成但有问题",
    "task.failed": "任务执行失败",
    "task.waiting_model": "任务等待模型配置恢复",
    "task.reconciliation_required": "任务执行结果待核对",
}

# 事件类型中文说明，供 /notifications/events 目录接口返回。
EVENT_LABELS: dict[str, str] = {
    "user.created": "账号创建",
    "user.updated": "账号信息变更",
    "user.password_changed": "密码修改",
    "organization.member.invited": "组织成员变更",
    "project.member.invited": "项目成员变更",
    "project.owner_changed": "项目负责人变更",
    "defect.created": "缺陷创建",
    "defect.assigned": "缺陷分配",
    "defect.status_changed": "缺陷状态变更",
    "task.plan_ready": "任务方案待确认",
    "task.completed": "任务完成",
    "task.completed_with_issues": "任务完成但有问题",
    "task.failed": "任务执行失败",
    "task.waiting_model": "任务等待模型恢复",
    "task.reconciliation_required": "任务执行结果待核对",
}


def notify(
    db: Session,
    *,
    user_id: int,
    event_type: str,
    actor_id: int | None = None,
    actor_username: str | None = None,
    title: str | None = None,
    body: str | None = None,
    project_id: int | None = None,
    organization_id: int | None = None,
    detail: dict[str, Any] | None = None,
) -> Notification | None:
    """写一条通知；失败时仅记录告警，不影响主数据事务。

    通知属于附加信息，写失败不应让业务操作回滚，因此异常被吞掉并记录日志。
    调用方通常在同一事务内调用，需要 flush 以便拿到自增 ID 后再提交。

    Args:
        user_id: 通知的接收者；收件箱按人隔离。
        event_type: 事件类型，取值见 EVENT_TITLES / EVENT_LABELS，同时用于回查默认标题。
        actor_id / actor_username: 操作人身份，只写入 payload 供前端展示。
        title / body: 展示文案；为空时 title 回退到 EVENT_TITLES，body 回退为「操作人：xxx」。
        project_id / organization_id: 作用域字段，供个人通知列表按项目或组织筛选。
        detail: 附加业务数据，存入 payload.detail 供跳转时读取。

    Returns:
        Notification | None: 写入成功返回该行对象；失败返回 None（主流程不因此回滚）。
    """
    try:
        row = Notification(
            user_id=user_id,
            organization_id=organization_id,
            project_id=project_id,
            event_type=event_type,
            title=title or EVENT_TITLES.get(event_type, "账号信息已更新"),
            body=body or (f"操作人：{actor_username}" if actor_username else None),
            # payload 固定为 {actor, detail} 结构：detail 缺省给空对象而非 None，保证前端取值不炸。
            payload={"actor": actor_id, "detail": detail or {}},
            # 新通知一律未读；已读状态由前端在阅读后回写。
            is_read=False,
        )
        db.add(row)
        db.flush()
        return row
    except Exception:
        logger.warning("通知写入失败，已跳过：%s", event_type)
        return None
