"""项目出站目标公开读取契约。

供共享 HTTP 策略协调器按项目和目标四元组查询明确启用的白名单项；本模块不执行网络请求。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.models.project import ProjectOutboundTarget


def find_enabled_outbound_target(
    db: Session,
    project_id: int,
    scheme: str,
    host: str,
    port: int,
) -> ProjectOutboundTarget | None:
    """返回项目中精确匹配且已启用的出站目标；未找到时返回 None。"""
    return (
        db.query(ProjectOutboundTarget)
        .filter(
            ProjectOutboundTarget.project_id == project_id,
            ProjectOutboundTarget.scheme == scheme,
            ProjectOutboundTarget.host == host,
            ProjectOutboundTarget.port == port,
            ProjectOutboundTarget.enabled.is_(True),
        )
        .first()
    )


__all__ = ["find_enabled_outbound_target"]
