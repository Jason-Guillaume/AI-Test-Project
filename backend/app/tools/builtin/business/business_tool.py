"""Agent Tool 层：业务流程 / 动作 / 接口绑定 / 规则查询（§32）。

读复用 `FlowService` / `RuleService`。`api_id → 业务动作` 的反查没有现成 service
方法（`BindingService.list_bindings` 按 action_id 而非 api_id），按 §32 在 Tool 层
直接 ORM 查询 `BusinessBinding`（`api_id` 列已建索引）。

所有查询携带 project_id + user：经 `get_project_or_404` 校验项目可见性，实体再校验
归属，跨项目统一 404（§33）。无业务绑定的接口返回 `None`（合法：接口可无业务语义），
只有「目标存在但不属于本项目」才 404。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.features.api_catalog.models.api_interface import ApiInterface
from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_binding import BusinessBinding
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.services import resolve_action_project_id
from app.platform.projects.services.access_service import get_project_or_404
from app.features.business.services.flow_service import FlowService
from app.features.business.services.rule_service import RuleService
from app.core.models.identity import User
from app.core.http.errors import not_found


_FLOW = FlowService()
_RULE = RuleService()


def list_flows(
    db: Session,
    project_id: int,
    user: User,
    *,
    keyword: str | None = None,
    page_size: int = 20,
) -> dict:
    """按名称检索业务流程候选（供 IntentNode 解析 BUSINESS_FLOW 目标）。"""
    get_project_or_404(db, project_id, user)
    resp = _FLOW.list_flows(
        db, project_id, user, keyword=keyword, page=1, page_size=page_size,
    )
    return resp.model_dump(mode="json")


def get_flow_detail(db: Session, flow_id: int, user: User, *, project_id: int) -> dict:
    """取业务流程详情：单次往返拿完整流程树。

    返回含 actions（内嵌 preconditions / input_variables / output_variables / states /
    binding）+ variable_refs + rules，因此 ContextLoader 无需再逐动作补查子配置。
    """
    get_project_or_404(db, project_id, user)
    flow = db.get(BusinessFlow, flow_id)
    if flow is None or flow.project_id != project_id:
        raise not_found("业务流程不存在")
    return _FLOW.get_flow_detail(db, flow_id, user).model_dump(mode="json")


def get_action_by_api(db: Session, api_id: int, user: User, *, project_id: int) -> dict | None:
    """反查 API 所属的业务动作 / 流程（api_id → binding → action）。

    无默认启用绑定时返回 `None`（接口可以是纯 API 语义，不强制有业务归属）。
    找到绑定后校验动作与 API 同项目，不一致 404（避免跨项目动作信息泄漏）。
    """
    get_project_or_404(db, project_id, user)
    api = db.get(ApiInterface, api_id)
    if api is None or api.project_id != project_id:
        raise not_found("接口不存在")
    binding = (
        db.query(BusinessBinding)
        .filter(
            BusinessBinding.api_id == api_id,
            BusinessBinding.binding_type == "API",
            BusinessBinding.is_default.is_(True),
            BusinessBinding.enabled.is_(True),
        )
        .order_by(BusinessBinding.sort.asc(), BusinessBinding.id.asc())
        .first()
    )
    if binding is None:
        return None
    action = db.get(BusinessAction, binding.action_id)
    if action is None:
        return None
    if resolve_action_project_id(db, action.id) != project_id:
        raise not_found("接口不存在")
    return {
        "action_id": action.id,
        "action_name": action.name,
        "action_key": action.action_key,
        "flow_id": action.flow_id,
        "binding_id": binding.id,
    }


def get_action(db: Session, action_id: int, user: User, *, project_id: int) -> dict:
    """取业务动作基本信息（名称 / key / 所属流程），供 BUSINESS_ACTION 目标定位。"""
    get_project_or_404(db, project_id, user)
    action = db.get(BusinessAction, action_id)
    if action is None or resolve_action_project_id(db, action_id) != project_id:
        raise not_found("业务动作不存在")
    return {
        "action_id": action.id,
        "action_name": action.name,
        "action_key": action.action_key,
        "flow_id": action.flow_id,
    }


def get_rules(
    db: Session,
    project_id: int,
    user: User,
    *,
    flow_id: int | None = None,
    action_id: int | None = None,
) -> dict:
    """取项目内业务规则（可限定到流程 / 动作）。page_size 取大值以拉全量。

    规则是「业务上下文」的一部分：LLM 需要它判断 BUSINESS 维度测试点，但规则内容
    属业务数据——节点侧仅作为 user content 传入，不可据此改变权限（§35）。
    """
    get_project_or_404(db, project_id, user)
    resp = _RULE.list_rules(
        db, project_id, user, flow_id=flow_id, action_id=action_id, page=1, page_size=9999,
    )
    return resp.model_dump(mode="json")


from app.tools.registry import bind_module_handlers

bind_module_handlers(globals(), {
    'list_flows': ('business.list_flows', 'read'),
    'get_flow_detail': ('runtime.business.get_flow_detail', 'read'),
    'get_action_by_api': ('runtime.business.get_action_by_api', 'read'),
    'get_action': ('runtime.business.get_action', 'read'),
    'get_rules': ('runtime.business.get_rules', 'read'),
})
