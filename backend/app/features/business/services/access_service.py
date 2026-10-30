"""业务管理服务层共享的可见性 / 可写性校验与实体→项目回溯。

集中放在 feature 内部（services/_access.py），避免 6 个 service 各自重复同一套
「取项目 → 校验 viewer/member」逻辑。不放到 app/shared，是因为这些校验针对业务
实体的层级关系（domain→flow→action→子配置），属本 feature 私有，不跨 feature 复用。

权限口径与 defects / api_catalog 一致：
- 读：对该 project 至少 viewer；不可见与不存在共用 404（隐藏存在性）。
- 写：至少 member；不足 403（写操作语义上不存在「隐藏」，故用 403）。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.models.business_flow import BusinessFlow
from app.core.http.errors import not_found
from app.platform.projects.services.access_service import (
    check_writable,
    get_project_or_404,
    require_writable_project,
)


# ---------------------------------------------------------------- 实体 → 项目回溯
# 业务实体多层级嵌套（flow→project、action→flow→project、binding→action→flow→project）。
# 这里提供按 ID 回溯 project_id 的辅助：找不到实体一律 404，避免上层拿到 project_id
# 后再做可见性校验时把「实体不存在」误判成「无权」。
# 注意：这些回溯函数只解析 project_id，不做可见性校验；可见性由调用方拿到 project_id
# 后再走 get_project_or_404 完成，统一 404 口径。


def resolve_flow_project_id(db: Session, flow_id: int) -> int:
    """按 flow_id 回溯所属 project_id；流程不存在 → 404。"""
    flow = db.get(BusinessFlow, flow_id)
    if flow is None:
        raise not_found("业务流程不存在")
    return flow.project_id


def resolve_action_project_id(db: Session, action_id: int) -> int:
    """按 action_id 回溯所属 project_id（action → flow → project）；任一缺失 → 404。"""
    action = db.get(BusinessAction, action_id)
    if action is None:
        raise not_found("业务动作不存在")
    return resolve_flow_project_id(db, action.flow_id)


def resolve_binding_project_id(db: Session, binding_id: int) -> int:
    """按 binding_id 回溯所属 project_id（binding → action → flow → project）。"""
    binding = db.get(BusinessBinding, binding_id)
    if binding is None:
        raise not_found("业务绑定不存在")
    return resolve_action_project_id(db, binding.action_id)
