"""业务流程 / 业务动作服务层（编排核心）。

负责 BusinessFlow 与 BusinessAction 的 CRUD、动作重排，以及聚合详情
BusinessFlowDetailResponse 的组装（流程 + 域名 + 有序动作含各自子配置 + 变量引用 + 规则）。

权限：读 viewer+、写 member+、越权与不存在共用 404。service owns commit。
动作属于流程、流程属于域与项目；写动作时经 resolve_flow_project_id 回溯到项目做可写校验。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.features.business.models.business_action import BusinessAction
from app.features.business.models.business_domain import BusinessDomain
from app.features.business.models.business_flow import BusinessFlow
from app.features.business.models.business_precondition import BusinessPrecondition
from app.features.business.models.business_rule import BusinessRule
from app.features.business.models.business_state import BusinessState
from app.features.business.models.business_variable import BusinessVariable
from app.features.business.models.business_variable_ref import BusinessVariableRef
from app.features.business.schemas import (
    BUSINESS_ACTION_TYPES,
    BUSINESS_FLOW_STATUSES,
    BusinessActionCreate,
    BusinessActionDetailResponse,
    BusinessActionReorder,
    BusinessActionResponse,
    BusinessActionUpdate,
    BusinessFlowCreate,
    BusinessFlowDetailResponse,
    BusinessFlowListResponse,
    BusinessFlowResponse,
    BusinessFlowUpdate,
    BusinessPreconditionResponse,
    BusinessRuleResponse,
    BusinessStateResponse,
    BusinessVariableRefResponse,
    BusinessVariableResponse,
)
from app.features.business.services._access import (
    get_project_or_404,
    require_writable_project,
    resolve_flow_project_id,
)
from app.features.business.services.binding_service import _binding_detail
from app.models.identity import User
from app.shared.errors import bad_request, conflict, not_found
from app.shared.notify import notify
from app.shared.pagination import DEFAULT_PAGE_SIZE


def _flow_response(flow: BusinessFlow) -> BusinessFlowResponse:
    return BusinessFlowResponse.model_validate(flow)


def _action_response(action: BusinessAction) -> BusinessActionResponse:
    return BusinessActionResponse.model_validate(action)


def _ensure_unique_flow_name(
    db: Session, domain_id: int, name: str, *, exclude_id: int | None = None
) -> None:
    query = db.query(BusinessFlow).filter(
        BusinessFlow.domain_id == domain_id, BusinessFlow.name == name
    )
    if exclude_id is not None:
        query = query.filter(BusinessFlow.id != exclude_id)
    if query.first() is not None:
        raise conflict("业务流程名称已存在")


def _ensure_unique_action_key(
    db: Session, flow_id: int, action_key: str, *, exclude_id: int | None = None
) -> None:
    query = db.query(BusinessAction).filter(
        BusinessAction.flow_id == flow_id, BusinessAction.action_key == action_key
    )
    if exclude_id is not None:
        query = query.filter(BusinessAction.id != exclude_id)
    if query.first() is not None:
        raise conflict("业务动作 action_key 已存在")


class FlowService:
    """业务流程与动作服务。无状态，路由层复用单例。"""

    # ---------------------------------------------------------------- 流程

    def list_flows(
        self,
        db: Session,
        project_id: int,
        user: User,
        *,
        domain_id: int | None = None,
        status: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> BusinessFlowListResponse:
        get_project_or_404(db, project_id, user)
        query = db.query(BusinessFlow).filter(BusinessFlow.project_id == project_id)
        if domain_id is not None:
            query = query.filter(BusinessFlow.domain_id == domain_id)
        if status:
            if status not in BUSINESS_FLOW_STATUSES:
                raise bad_request("业务流程状态取值非法")
            query = query.filter(BusinessFlow.status == status)
        kw = (keyword or "").strip()
        if kw:
            query = query.filter(
                or_(BusinessFlow.name.ilike(f"%{kw}%"), BusinessFlow.description.ilike(f"%{kw}%"))
            )
        total = int(query.count())
        items = (
            query.order_by(BusinessFlow.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return BusinessFlowListResponse(
            items=[_flow_response(f) for f in items], total=total, page=page, page_size=page_size
        )

    def create_flow(
        self, db: Session, project_id: int, body: BusinessFlowCreate, *, actor: User
    ) -> BusinessFlowResponse:
        project = require_writable_project(db, project_id, actor)
        # domain_id 必须属于本项目（跨资源 → 404）。
        domain = db.get(BusinessDomain, body.domain_id)
        if domain is None or domain.project_id != project.id:
            raise not_found("业务域不存在")
        name = body.name.strip()
        if not name:
            raise bad_request("业务流程名称不能为空")
        _ensure_unique_flow_name(db, body.domain_id, name)
        flow = BusinessFlow(
            project_id=project_id,
            domain_id=body.domain_id,
            name=name,
            description=(body.description or "").strip() or None,
            status=body.status,
            version=1,
        )
        db.add(flow)
        db.flush()
        notify(
            db,
            user_id=actor.id,
            event_type="business.flow.created",
            title=f"你已创建业务流程「{flow.name}」",
            project_id=project_id,
            actor_id=actor.id,
            actor_username=actor.username,
            detail={"flow_id": flow.id, "domain_id": flow.domain_id},
        )
        db.commit()
        db.refresh(flow)
        return _flow_response(flow)

    def get_flow(self, db: Session, flow_id: int, user: User) -> BusinessFlowResponse:
        flow = self._get_flow_or_404(db, flow_id, user)
        return _flow_response(flow)

    def get_flow_detail(self, db: Session, flow_id: int, user: User) -> BusinessFlowDetailResponse:
        """聚合详情：流程 + 域名 + 有序动作（含各自子配置与绑定）+ 变量引用 + 规则。"""
        flow = self._get_flow_or_404(db, flow_id, user)
        domain = db.get(BusinessDomain, flow.domain_id)
        actions = (
            db.query(BusinessAction)
            .filter(BusinessAction.flow_id == flow_id)
            .order_by(BusinessAction.sort.asc(), BusinessAction.id.asc())
            .all()
        )
        action_ids = [a.id for a in actions]

        preconditions = _group_by_action(
            db.query(BusinessPrecondition)
            .filter(BusinessPrecondition.action_id.in_(action_ids))
            .order_by(BusinessPrecondition.sort.asc(), BusinessPrecondition.id.asc())
            .all()
        ) if action_ids else {}
        variables = (
            db.query(BusinessVariable)
            .filter(BusinessVariable.action_id.in_(action_ids))
            .order_by(BusinessVariable.sort.asc(), BusinessVariable.id.asc())
            .all()
        ) if action_ids else []
        states = _group_by_action(
            db.query(BusinessState)
            .filter(BusinessState.action_id.in_(action_ids))
            .order_by(BusinessState.id.asc())
            .all()
        ) if action_ids else {}
        from app.features.business.models.business_binding import BusinessBinding

        bindings = (
            db.query(BusinessBinding)
            .filter(
                BusinessBinding.action_id.in_(action_ids),
                BusinessBinding.binding_type.in_(("API", "WEB")),
            )
            .order_by(BusinessBinding.enabled.asc(), BusinessBinding.is_default.asc(), BusinessBinding.binding_type.asc(), BusinessBinding.id.asc())
            .all()
        ) if action_ids else []
        binding_by_action = {b.action_id: b for b in bindings}

        variable_refs = (
            db.query(BusinessVariableRef)
            .filter(BusinessVariableRef.flow_id == flow_id)
            .order_by(BusinessVariableRef.id.asc())
            .all()
        )
        rules = (
            db.query(BusinessRule)
            .filter(BusinessRule.flow_id == flow_id)
            .order_by(BusinessRule.id.asc())
            .all()
        )

        # 变量按 action 与 direction 分组。
        input_vars: dict[int, list[BusinessVariable]] = defaultdict(list)
        output_vars: dict[int, list[BusinessVariable]] = defaultdict(list)
        for v in variables:
            (output_vars if v.direction == "OUTPUT" else input_vars)[v.action_id].append(v)

        action_details = [
            BusinessActionDetailResponse(
                **_action_response(a).model_dump(),
                preconditions=[BusinessPreconditionResponse.model_validate(p) for p in preconditions.get(a.id, [])],
                input_variables=[BusinessVariableResponse.model_validate(v) for v in input_vars.get(a.id, [])],
                output_variables=[BusinessVariableResponse.model_validate(v) for v in output_vars.get(a.id, [])],
                states=[BusinessStateResponse.model_validate(s) for s in states.get(a.id, [])],
                binding=_binding_detail(db, binding_by_action[a.id]) if a.id in binding_by_action else None,
            )
            for a in actions
        ]
        return BusinessFlowDetailResponse(
            **_flow_response(flow).model_dump(),
            domain_name=domain.name if domain is not None else None,
            actions=action_details,
            variable_refs=[BusinessVariableRefResponse.model_validate(r) for r in variable_refs],
            rules=[BusinessRuleResponse.model_validate(r) for r in rules],
        )

    def update_flow(
        self, db: Session, flow_id: int, body: BusinessFlowUpdate, *, actor: User
    ) -> BusinessFlowResponse:
        flow = self._get_writable_flow_or_404(db, flow_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _flow_response(flow)
        # 乐观锁校验。
        if "revision" in data and data["revision"] != flow.revision:
            raise conflict("业务流程已被其他用户修改，请刷新后重试")
        if "name" in data and data["name"] is not None:
            new_name = data["name"].strip()
            if not new_name:
                raise bad_request("业务流程名称不能为空")
            if new_name != flow.name:
                _ensure_unique_flow_name(db, flow.domain_id, new_name, exclude_id=flow.id)
                flow.name = new_name
        for field in ("description", "status"):
            if field in data and data[field] is not None:
                setattr(flow, field, data[field])
        if "description" in data:
            flow.description = data["description"]
        flow.revision = (flow.revision or 0) + 1
        db.flush()
        db.commit()
        db.refresh(flow)
        return _flow_response(flow)

    def delete_flow(self, db: Session, flow_id: int, *, actor: User) -> None:
        flow = self._get_writable_flow_or_404(db, flow_id, actor)
        # 级联由外键承担：流程删除 → 动作 → 绑定/前置条件/变量/状态/映射 → 变量引用/规则。
        db.delete(flow)
        db.commit()

    # ---------------------------------------------------------------- 动作

    def list_actions(self, db: Session, flow_id: int, user: User) -> list[BusinessActionResponse]:
        self._get_flow_or_404(db, flow_id, user)
        items = (
            db.query(BusinessAction)
            .filter(BusinessAction.flow_id == flow_id)
            .order_by(BusinessAction.sort.asc(), BusinessAction.id.asc())
            .all()
        )
        return [_action_response(a) for a in items]

    def create_action(
        self, db: Session, flow_id: int, body: BusinessActionCreate, *, actor: User
    ) -> BusinessActionResponse:
        project = require_writable_project(db, resolve_flow_project_id(db, flow_id), actor)
        action_key = body.action_key.strip()
        if not action_key:
            raise bad_request("业务动作 action_key 不能为空")
        name = body.name.strip()
        if not name:
            raise bad_request("业务动作名称不能为空")
        _ensure_unique_action_key(db, flow_id, action_key)
        # append 到末尾：sort 未显式给时取当前最大 sort + 1，保证新动作排在最后。
        max_sort = (
            db.query(BusinessAction)
            .filter(BusinessAction.flow_id == flow_id)
            .order_by(BusinessAction.sort.desc())
            .first()
        )
        next_sort = (max_sort.sort if max_sort else 0) + 1 if body.sort == 0 else body.sort
        action = BusinessAction(
            flow_id=flow_id,
            name=name,
            description=(body.description or "").strip() or None,
            action_key=action_key,
            sort=next_sort,
            action_type=body.action_type,
        )
        db.add(action)
        db.flush()
        notify(
            db,
            user_id=actor.id,
            event_type="business.action.created",
            title=f"你已在流程中新增业务动作「{action.name}」",
            project_id=project.id,
            actor_id=actor.id,
            actor_username=actor.username,
            detail={"action_id": action.id, "flow_id": flow_id},
        )
        db.commit()
        db.refresh(action)
        return _action_response(action)

    def update_action(
        self, db: Session, action_id: int, body: BusinessActionUpdate, *, actor: User
    ) -> BusinessActionResponse:
        action = self._get_writable_action_or_404(db, action_id, actor)
        data = body.model_dump(exclude_unset=True)
        if not data:
            return _action_response(action)
        # 乐观锁校验。
        if "revision" in data and data["revision"] != action.revision:
            raise conflict("业务动作已被其他用户修改，请刷新后重试")
        if "action_key" in data and data["action_key"] is not None:
            new_key = data["action_key"].strip()
            if not new_key:
                raise bad_request("业务动作 action_key 不能为空")
            if new_key != action.action_key:
                _ensure_unique_action_key(db, action.flow_id, new_key, exclude_id=action.id)
                action.action_key = new_key
        if "name" in data and data["name"] is not None:
            stripped_name = data["name"].strip()
            if not stripped_name:
                raise bad_request("业务动作名称不能为空")
            action.name = stripped_name
        for field in ("description", "sort", "action_type"):
            if field in data and data[field] is not None:
                if field == "action_type" and data[field] not in BUSINESS_ACTION_TYPES:
                    raise bad_request("业务动作类型取值非法")
                setattr(action, field, data[field])
        if "description" in data:
            action.description = data["description"]
        action.revision = (action.revision or 0) + 1
        db.flush()
        db.commit()
        db.refresh(action)
        return _action_response(action)

    def delete_action(self, db: Session, action_id: int, *, actor: User) -> None:
        action = self._get_writable_action_or_404(db, action_id, actor)
        db.delete(action)
        db.commit()

    def reorder_actions(
        self, db: Session, flow_id: int, body: BusinessActionReorder, *, actor: User
    ) -> list[BusinessActionResponse]:
        """批量重排动作顺序。仅校验流程可写，不要求 items 覆盖全部动作。"""
        require_writable_project(db, resolve_flow_project_id(db, flow_id), actor)
        id_to_sort = {item.action_id: item.sort for item in body.items}
        actions = (
            db.query(BusinessAction)
            .filter(BusinessAction.flow_id == flow_id, BusinessAction.id.in_(id_to_sort.keys()))
            .all()
        )
        for a in actions:
            a.sort = id_to_sort[a.id]
        db.flush()
        db.commit()
        items = (
            db.query(BusinessAction)
            .filter(BusinessAction.flow_id == flow_id)
            .order_by(BusinessAction.sort.asc(), BusinessAction.id.asc())
            .all()
        )
        return [_action_response(a) for a in items]

    # ---------------------------------------------------------------- 取实体

    def _get_flow_or_404(self, db: Session, flow_id: int, user: User) -> BusinessFlow:
        flow = db.get(BusinessFlow, flow_id)
        if flow is None:
            raise not_found("业务流程不存在")
        get_project_or_404(db, flow.project_id, user)
        return flow

    def _get_writable_flow_or_404(
        self, db: Session, flow_id: int, actor: User
    ) -> BusinessFlow:
        flow = db.get(BusinessFlow, flow_id)
        if flow is None:
            raise not_found("业务流程不存在")
        require_writable_project(db, flow.project_id, actor)
        return flow

    def _get_writable_action_or_404(
        self, db: Session, action_id: int, actor: User
    ) -> BusinessAction:
        action = db.get(BusinessAction, action_id)
        if action is None:
            raise not_found("业务动作不存在")
        require_writable_project(db, resolve_flow_project_id(db, action.flow_id), actor)
        return action


def _group_by_action(rows: list) -> dict[int, list]:
    """按 action_id 把行分组，便于在聚合详情里挂到对应动作下。"""
    grouped: dict[int, list] = defaultdict(list)
    for row in rows:
        grouped[row.action_id].append(row)
    return grouped
